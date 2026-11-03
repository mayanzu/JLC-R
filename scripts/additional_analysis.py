"""Read-only verification and saved-data reproduction for supplementary analyses."""
from __future__ import annotations

import csv
import itertools
import math
import statistics
from pathlib import Path

import numpy as np
from scipy import stats

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'results/rc2_supplement'


def rows(name):
    with (DATA/name).open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))


def interval(values):
    v=np.asarray(values,float);n=len(v);mean=float(v.mean());sd=float(v.std(ddof=1))
    h=float(stats.t.ppf(.975,n-1)*sd/math.sqrt(n))
    return mean,mean-h,mean+h,sd


def holm(p):
    order=np.argsort(p,kind='stable');out=np.empty(len(p));last=0.
    for rank,i in enumerate(order):
        last=max(last,(len(p)-rank)*p[i]);out[i]=min(1.,last)
    return out


def verify_factorial():
    data=rows('factorial_seed_records_768.csv');archive=rows('factorial_primary_holm14.csv')
    values={(r['condition'],float(r['supply']),int(r['seed']),r['bits']):r for r in data}
    assert len(data)==len(values)==768
    cells=sorted({(x[0],x[1]) for x in values});seeds=sorted({x[2] for x in values})
    assert len(cells)==8 and len(seeds)==12
    bits=[f'{i:03b}' for i in range(8)]
    design=[]
    for b in bits:
        a,g,r=[2*int(v)-1 for v in b]
        design.append([1,a,g,r,a*g,a*r,g*r,a*g*r])
    design=np.asarray(design,float)
    assert np.array_equal(design.T@design,8*np.eye(8))
    contrasts=['A','G','R','AG','AR','GR','AGR'];scale=np.asarray([2,2,2,4,4,4,8])
    tests=[];flips=np.asarray(list(itertools.product((-1.,1.),repeat=12)))
    for metric in ('coverage_pct','source_coverage_p5_pct'):
        estimates=[]
        for seed in seeds:
            blocks=[]
            for condition,supply in cells:
                y=np.asarray([float(values[(condition,supply,seed,b)][metric]) for b in bits])
                blocks.append((design.T@y/8)[1:]*scale)
            estimates.append(np.asarray(blocks).mean(axis=0))
        estimates=np.asarray(estimates)
        for i,contrast in enumerate(contrasts):
            v=estimates[:,i];mean,lo,hi,sd=interval(v)
            p=1. if sd==0 else float(2*stats.t.sf(abs(mean/(sd/math.sqrt(12))),11))
            flip=float(np.mean(np.abs((flips@v)/12)>=abs(mean)-1e-12))
            tests.append({'endpoint':metric,'contrast':contrast,'mean':mean,'ci95_low':lo,'ci95_high':hi,
                          'p_two_sided':p,'p_sign_flip':flip})
    adjusted=holm([x['p_two_sided'] for x in tests]);flipadj=holm([x['p_sign_flip'] for x in tests])
    for r,a,b in zip(tests,adjusted,flipadj):r.update(p_holm14=float(a),p_signflip_holm14=float(b))
    assert len(archive)==len(tests)==14
    for expected in tests:
        matches=[r for r in archive if r['endpoint']==expected['endpoint'] and r['contrast']==expected['contrast']]
        assert len(matches)==1
        for k in ('mean','ci95_low','ci95_high','p_two_sided','p_sign_flip','p_holm14','p_signflip_holm14'):
            assert math.isclose(float(matches[0][k]),expected[k],rel_tol=1e-8,abs_tol=1e-10),(expected['contrast'],k)
    assert sum(r['origin']=='new_component_execution' for r in data)==576
    assert sum(r['origin']=='reused_formal_endpoint' for r in data)==192
    return 14


def verify_padc():
    data=rows('paired_seed_records_96.csv');archive=rows('equal_weight_effects.csv')
    assert len(data)==96
    seeds=sorted({int(r['seed']) for r in data});assert len(seeds)==12
    metrics=['coverage_pct','source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes',
             'sample_completion_pct','fixed_demand_packet_delivery_pct','actual_energy_j']
    for metric in metrics:
        d=[]
        for seed in seeds:
            subset=[r for r in data if int(r['seed'])==seed];assert len(subset)==8
            d.append(statistics.mean(float(r['difference_'+metric]) for r in subset))
        mean,lo,hi,_=interval(d)
        match=next(r for r in archive if r['metric']==metric)
        for key,value in [('difference_rc2_minus_padc',mean),('nominal_ci95_low',lo),('nominal_ci95_high',hi)]:
            assert math.isclose(float(match[key]),value,rel_tol=1e-9,abs_tol=1e-9),(metric,key)
    return 7


def verify_temperature():
    truth=rows('temperature_15m_1344.csv');data=rows('seed_task_metrics_144.csv')
    archive=rows('condition_task_summary.csv')
    assert len(truth)==1344 and all(r['quality_valid']=='1' for r in truth)
    assert sum(float(r['air_temperature_c'])<=0 for r in truth)==701
    assert len(data)==144 and len({(r['method'],r['supply'],r['seed']) for r in data})==144
    for a in archive:
        values=[float(r[a['metric']]) for r in data if r['method']==a['method'] and r['supply']==a['supply']
                and r[a['metric']]!='']
        assert len(values)==int(a['n_seeds'])==12
        mean,lo,hi,_=interval(values)
        for key,value in [('mean',mean),('nominal_ci95_low',lo),('nominal_ci95_high',hi)]:
            assert math.isclose(float(a[key]),value,rel_tol=1e-9,abs_tol=1e-9),(a['method'],a['metric'],key)
    for r in data:
        parts=sum(float(r[k]) for k in ['cold_detected_pct','cold_false_safe_pct','cold_unavailable_pct'])
        assert abs(parts-100)<1e-9
    return len(archive)


def verify():
    return {'status':'PASS','factorial_records':768,'factorial_holm14_tests_recomputed':verify_factorial(),
            'padc_paired_records':96,'padc_summary_effects_recomputed':verify_padc(),
            'temperature_replay_records':144,'temperature_summaries_recomputed':verify_temperature(),
            'temperature_weather_trajectories':1,'simulations_started':0,
            'scope':'Saved summaries and supplementary statistics; raw arrays remain in the research archive.'}


if __name__=='__main__':
    import json
    print(json.dumps(verify(),indent=2))
