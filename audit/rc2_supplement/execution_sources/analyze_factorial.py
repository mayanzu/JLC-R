"""Analyze the frozen RC2 factorial after every planned execution passes."""
from __future__ import annotations

import csv
import itertools
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[2]
RC2=PROJECT/'code/experiments/rc2_confirmation/results'


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def write(path,data):
    with path.open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)


def contrast(values, factor):
    positions={'A':0,'G':1,'R':2}
    axes=[positions[c] for c in factor]
    # Main effects average four backgrounds, two-way interactions average two;
    # the three-way interaction is the full third difference.
    denominator=2**(3-len(axes))
    return sum(math.prod(1 if int(bits[i]) else -1 for i in axes)*values[bits]
               for bits in values)/denominator


def summary(x):
    x=np.asarray(x,dtype=float)
    assert len(x)==12 and np.isfinite(x).all()
    mean=float(x.mean()); sd=float(x.std(ddof=1))
    half=float(stats.t.ppf(.975,11)*sd/math.sqrt(12))
    if sd == 0:
        tstat=None; p=1.0
    else:
        tstat=float(mean/(sd/math.sqrt(12)));p=float(2*stats.t.sf(abs(tstat),11))
    signs=np.asarray(list(itertools.product((-1.,1.),repeat=12)))
    sign_means=(signs*x).mean(axis=1)
    flip=float(np.mean(np.abs(sign_means)>=abs(mean)-1e-12))
    return {'n_network_seeds':12,'mean':mean,'ci95_low':mean-half,'ci95_high':mean+half,
            't_stat':tstat,'df':11,'p_two_sided':p,'p_sign_flip':flip,
            'positive_seeds':int((x>0).sum()),'negative_seeds':int((x<0).sum()),'zero_seeds':int((x==0).sum())}


def holm(ps):
    order=sorted(range(len(ps)),key=ps.__getitem__);result=[0.]*len(ps);last=0.
    for rank,index in enumerate(order):
        last=max(last,min(1.,(len(ps)-rank)*ps[index]));result[index]=last
    return result


def main():
    protocol=read(HERE/'protocol.json')
    endpoint=read(HERE/'endpoints/summary.json')
    intermediate=read(HERE/'intermediates/summary.json')
    assert endpoint['status']=='PASS' and endpoint['completed']==16
    assert intermediate['status']=='PASS' and intermediate['completed']==576
    gap={(r['method'],r['condition'],float(r['supply']),int(r['seed'])):r
         for r in rows(RC2/'monitoring_gaps_480.csv')}
    raw=[]
    for r in rows(RC2/'confirmation_480.csv'):
        if r['method'] not in ('JLC-R-RC2','Pre-recovery-JLC-R'):
            continue
        bits='111' if r['method']=='JLC-R-RC2' else '000'
        g=gap[(r['method'],r['condition'],float(r['supply']),int(r['seed']))]
        data={'condition':r['condition'],'supply':float(r['supply']),'seed':int(r['seed']),
              'bits':bits,'origin':'reused_formal_endpoint','source_case_index':r['case_index']}
        for metric in ('coverage_pct','source_coverage_p5_pct','source_coverage_jain',
                       'aoi_mean_minutes','sample_completion_pct','fixed_demand_packet_delivery_pct','actual_energy_j'):
            data[metric]=float(r[metric])
        data['longest_unfresh_p95_h']=float(g['longest_observed_unfresh_p95_h'])
        data['sources_gap_over4h_pct']=float(g['sources_with_observed_gap_over4h_pct'])
        raw.append(data)
    for folder in sorted((HERE/'intermediates').iterdir()):
        if not folder.is_dir():continue
        record=read(folder/'record.json');validation=read(folder/'validation.json')
        assert validation['status']=='PASS'
        task=record['task']
        assert task['bits'] not in ('000','111')
        data={'condition':task['condition'],'supply':float(task['supply']),'seed':int(task['seed']),
              'bits':task['bits'],'origin':'new_component_execution','source_case_index':''}
        data.update(record['outcomes'])
        raw.append(data)
    assert len(raw)==768
    key=lambda r:(r['condition'],r['supply'],r['seed'],r['bits'])
    assert len({key(r) for r in raw})==768
    expected={(c['name'],float(s),int(seed),f'{b:03b}')
              for c in protocol['conditions'] for s in protocol['supplies']
              for seed in protocol['seeds'] for b in range(8)}
    assert {key(r) for r in raw}==expected
    lookup={key(r):r for r in raw}
    seeds=protocol['seeds'];cells=[(c['name'],float(s)) for c in protocol['conditions'] for s in protocol['supplies']]
    factors=['A','G','R','AG','AR','GR','AGR']
    primary=[]
    for metric in protocol['primary_endpoints']:
        for factor in factors:
            per_seed=[]
            for seed in seeds:
                cell_effects=[]
                for condition,supply in cells:
                    values={f'{b:03b}':lookup[(condition,supply,seed,f'{b:03b}')][metric] for b in range(8)}
                    cell_effects.append(contrast(values,factor))
                per_seed.append(statistics.mean(cell_effects))
            primary.append({'endpoint':metric,'contrast':factor,**summary(per_seed)})
    adj=holm([r['p_two_sided'] for r in primary]);flips=holm([r['p_sign_flip'] for r in primary])
    for item,p,pflip in zip(primary,adj,flips):item.update(p_holm14=p,p_signflip_holm14=pflip)
    secondary=[]
    metrics=['coverage_pct','source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes',
             'sample_completion_pct','fixed_demand_packet_delivery_pct','actual_energy_j',
             'longest_unfresh_p95_h','sources_gap_over4h_pct']
    pairs=[('111','000'),('100','000'),('111','100'),('111','011'),('111','101'),('111','110')]
    for a,b in pairs:
        for metric in metrics:
            per_seed=[statistics.mean(lookup[(c,s,seed,a)][metric]-lookup[(c,s,seed,b)][metric]
                                      for c,s in cells) for seed in seeds]
            result=summary(per_seed)
            for field in ('t_stat','p_two_sided','p_sign_flip'):result.pop(field)
            secondary.append({'contrast':a+' minus '+b,'endpoint':metric,**result})
    cell=[]
    for condition,supply in cells:
        for metric in protocol['primary_endpoints']:
            for factor in factors:
                values=[]
                for seed in seeds:
                    row={f'{b:03b}':lookup[(condition,supply,seed,f'{b:03b}')][metric] for b in range(8)}
                    values.append(contrast(row,factor))
                r=summary(values)
                for field in ('t_stat','p_two_sided','p_sign_flip'):r.pop(field)
                cell.append({'condition':condition,'supply':supply,'endpoint':metric,'contrast':factor,**r})
    out=HERE/'analysis';out.mkdir(exist_ok=False)
    write(out/'factorial_seed_records_768.csv',sorted(raw,key=key))
    write(out/'factorial_primary_holm14.csv',primary)
    write(out/'factorial_secondary_contrasts.csv',secondary)
    write(out/'factorial_condition_contrasts.csv',cell)
    (out/'analysis_manifest.json').write_text(json.dumps({
        'status':'PASS','logical_records':768,'new_runs':576,'endpoint_records_reused':192,
        'endpoint_trajectory_checks':16,'network_seeds':12,'conditions':8,
        'primary_family':'14 factor-by-endpoint contrasts; Holm-14; nominal, not simultaneous, 95% paired t intervals',
        'sensitivity':'4096 exact sign flips on seed-level contrasts, separate Holm-14; symmetry under null',
        'secondary':'Descriptive nominal intervals; no multiple-comparison claim',
        'scope':'previously used seeds, fixed weather inputs, no new physical or MAC validation',
        'simulations_started':0},indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':'PASS','records':768,'primary':primary},indent=2),flush=True)


if __name__=='__main__':main()
