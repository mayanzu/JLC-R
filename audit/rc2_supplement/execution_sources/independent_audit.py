"""Independently audit all saved factorial arrays and effect-coded contrasts."""
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import t

HERE=Path(__file__).resolve().parent
out=HERE/'analysis'


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def rows(p):
    with p.open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))


def read(p):
    return json.loads(p.read_text(encoding='utf8'))


def main():
    sources=[];checked=0;max_energy_roundoff=0.;max_node=0.;max_global=0.
    for folder in sorted((HERE/'intermediates').iterdir()):
        if not folder.is_dir():continue
        record=read(folder/'record.json');valid=read(folder/'validation.json')
        assert valid['status']=='PASS'
        m=record['metrics'];observed=record['outcomes'];arr=np.load(folder/'arrays.npz')
        latest=arr['latest'];battery=arr['battery'];sample=arr['sample_status']
        assert latest.shape==battery.shape==(1344,100) and sample.shape==(134400,)
        tvec=np.arange(1344)[:,None]
        assert np.all(latest>=-1) and np.all(latest<=tvec)
        cov=((latest>=0)&(tvec-latest+1<=4)).mean(axis=0)*100
        age=np.where(latest>=0,tvec-latest+1,tvec+1).mean()*15
        jain=cov.sum()**2/(100*(cov**2).sum()) if cov.any() else 0.
        for name,value in [('coverage_pct',cov.mean()),('source_coverage_p5_pct',np.quantile(cov,.05)),
                           ('source_coverage_jain',jain),('aoi_mean_minutes',age)]:
            assert abs(float(observed[name])-value)<1e-8,(folder.name,name)
        assert np.isfinite(battery).all() and battery.min()>=-1e-12 and battery.max()<=4+1e-12
        assert np.count_nonzero(sample)==134400
        assert sum(int(m.get(x,0)) for x in ('delivered','expired','overflow','outstanding','unsensed','routing_drop'))==134400
        assert abs(float(observed['fixed_demand_packet_delivery_pct'])-100*int(m['delivered'])/134400)<1e-8
        assert abs(float(observed['sample_completion_pct'])-100*(134400-int(m['unsensed']))/134400)<1e-8
        node=float(m['max_node_energy_error_j']);glob=float(m['max_energy_balance_error_j'])
        assert node<=1e-8 and glob<=1e-6 and m['timing_misses']==0
        assert m['max_hold_violation_j']<=1e-8 and m['max_slot_violation']<=1e-8
        energy_diff=abs(float(observed['actual_energy_j'])-float(m['consumed_j']))
        assert energy_diff<=1e-6
        max_energy_roundoff=max(max_energy_roundoff,energy_diff);max_node=max(max_node,node);max_global=max(max_global,glob)
        for name in ('record.json','arrays.npz','validation.json'):
            p=folder/name;sources.append((p.relative_to(HERE).as_posix(),sha(p)))
        checked+=1
    assert checked==576
    data=rows(out/'factorial_seed_records_768.csv');effects=rows(out/'factorial_primary_holm14.csv')
    lookup={(r['condition'],float(r['supply']),int(r['seed']),r['bits']):r for r in data}
    assert len(lookup)==768
    seeds=sorted({k[2] for k in lookup});cells=sorted({(k[0],k[1]) for k in lookup})
    assert len(seeds)==12 and len(cells)==8
    bits=[f'{x:03b}' for x in range(8)]
    x=np.asarray([[1,2*int(b[0])-1,2*int(b[1])-1,2*int(b[2])-1,
                  (2*int(b[0])-1)*(2*int(b[1])-1),
                  (2*int(b[0])-1)*(2*int(b[2])-1),
                  (2*int(b[1])-1)*(2*int(b[2])-1),
                  math.prod(2*int(i)-1 for i in b)] for b in bits],float)
    assert np.array_equal(x.T@x,8*np.eye(8))
    factors=['A','G','R','AG','AR','GR','AGR'];mult=[2,2,2,4,4,4,8]
    comparisons=0
    for endpoint in ('coverage_pct','source_coverage_p5_pct'):
        seed_effects=[]
        for seed in seeds:
            cell_effects=[]
            for condition,supply in cells:
                y=np.asarray([float(lookup[(condition,supply,seed,b)][endpoint]) for b in bits])
                beta=(x.T@y)/8
                factor=beta[1:]*np.asarray(mult)
                assert abs((y[-1]-y[0])-(factor[0]+factor[1]+factor[2]+factor[6]/4))<1e-10
                cell_effects.append(factor)
            seed_effects.append(np.asarray(cell_effects).mean(axis=0))
        seed_effects=np.asarray(seed_effects)
        for i,factor in enumerate(factors):
            result=next(r for r in effects if r['endpoint']==endpoint and r['contrast']==factor)
            z=seed_effects[:,i];mean=float(z.mean());sd=float(z.std(ddof=1))
            half=float(t.ppf(.975,11)*sd/math.sqrt(12))
            assert abs(mean-float(result['mean']))<1e-10
            assert abs(mean-half-float(result['ci95_low']))<1e-10
            assert abs(mean+half-float(result['ci95_high']))<1e-10
            comparisons+=1
    manifest=out/'raw_checksums.sha256'
    manifest.write_text(''.join(f'{digest}  {name}\n' for name,digest in sources),encoding='utf8')
    result={'status':'PASS','new_cases_checked':checked,'raw_files_hashed':len(sources),
            'endpoint_tests':16,'independent_factorial_contrasts_checked':comparisons,
            'max_energy_accumulator_difference_j':max_energy_roundoff,
            'max_recorded_node_energy_error_j':max_node,'max_recorded_global_energy_error_j':max_global,
            'scope':'Arrays, saved scalar ledger maxima and outcomes checked; individual node ledgers were not saved for the 576 new component executions.',
            'simulations_started':0,'checksums_sha256':sha(manifest)}
    (out/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
