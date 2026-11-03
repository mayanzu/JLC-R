"""Locked-plan analysis; refuses incomplete matrices. No simulation or tuning."""
import argparse,csv,itertools,json,math
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
from scipy import stats
from rc2_runtime import HERE,PROJECT,read,sha

FIELDS=['coverage_pct','source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes']
def holm(values):
    p=np.asarray(values,float);assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
    order=np.argsort(p,kind='stable');out=np.empty(len(p));running=0.
    for rank,i in enumerate(order):running=max(running,(len(p)-rank)*p[i]);out[i]=min(1.,running)
    return out.tolist()
def paired(d):
    d=np.asarray(d,float);assert d.shape==(12,) and np.isfinite(d).all()
    mean=float(d.mean());sd=float(d.std(ddof=1));undefined=sd==0.
    if undefined:t=None;p=1.;lo=hi=None
    else:
        se=sd/math.sqrt(12);t=mean/se;p=float(2*stats.t.sf(abs(t),11));half=float(stats.t.ppf(.975,11)*se);lo=mean-half;hi=mean+half
    flips=np.asarray(list(itertools.product([-1.,1.],repeat=12)))
    perm=(flips@d)/12
    sp=float(np.count_nonzero(np.abs(perm)>=abs(mean)-1e-12)/4096)
    return dict(n=12,df=11,mean_difference=mean,sd_difference=sd,t=t,p=p,ci95_low=lo,ci95_high=hi,
        undefined_t_variance=undefined,sign_flip_p=sp,sign_flip_patterns=4096)
def csvout(p,rows):
    with p.open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execution',required=True);a=parser.parse_args()
    root=Path(a.execution).resolve();assert root.parent==HERE.resolve()
    p=read(HERE/'protocol.json');assert read(root/'execution_lock.json')['protocol_sha256']==sha(HERE/'protocol.json')
    completion=read(root/'completed.json');assert completion['status']=='COMPLETE' and not completion['failed'] and len(completion['completed'])==288
    if (HERE/'analysis_implementation_lock.json').exists():
        lock=read(HERE/'analysis_implementation_lock.json');assert lock['protocol_sha256']==sha(HERE/'protocol.json') and lock['analyze_sha256']==sha(Path(__file__))
    reuse={(r['method'],r['condition'],r['supply'],r['seed']):r for r in read(HERE/'reuse_inventory.json')}
    matrix={};inventory=[]
    for case in p['cases']:
        key=tuple(case[k] for k in ['method','condition','supply','seed'])
        if case['execution']=='reuse':
            r=reuse[key];d=PROJECT/r['directory']
            for name,h in r['files'].items():assert sha(d/name)==h
        else:d=root/'runs'/f"case_{case['index']:04d}"
        assert read(d/'validation.json')['status']=='PASS' and not (d/'failure.json').exists()
        r=read(d/'record.json');matrix[key]={f:float(r['metrics'][f]) for f in FIELDS}
        inventory.append(dict(index=case['index'],record=(d/'record.json').relative_to(PROJECT).as_posix(),sha256=sha(d/'record.json')))
    assert len(matrix)==480
    cells=[(c['name'],s) for c in p['conditions'] for s in p['supplies']];seeds=p['seeds']
    def vector(method,field,cell=None):
        return np.asarray([np.mean([matrix[(method,cn,sp,seed)][field] for cn,sp in (cells if cell is None else [cell])]) for seed in seeds])
    primary=[];heterogeneity=[];fair_age=[];primary_flip=[]
    for control in p['methods'][1:]:
        for field in FIELDS:
            for cell in [None,*cells]:
                delta=vector(p['methods'][0],field,cell)-vector(control,field,cell)
                if field=='aoi_mean_minutes':delta=-delta
                r=dict(control=control,endpoint=field,cell='equal_weight_8cell' if cell is None else f'{cell[0]}/{cell[1]}',
                    positive_means='RC2 improvement; AoI=control minus RC2, other metrics=RC2 minus control',**paired(delta))
                if field in FIELDS[:2] and cell is None:primary.append(r)
                elif field in FIELDS[:2]:heterogeneity.append(r)
                else:fair_age.append(r)
    assert (len(primary),len(heterogeneity),len(fair_age))==(8,64,72)
    for rr,name in [(primary,'Holm8_primary'),(heterogeneity,'Holm64_secondary'),(fair_age,'Holm72_secondary')]:
        adj=holm([r['p'] for r in rr])
        for r,value in zip(rr,adj):r.update(family=name,adjusted_p=value,reject_05=value<.05)
    for r,ap in zip(primary,holm([r['sign_flip_p'] for r in primary])):
        primary_flip.append(dict(control=r['control'],endpoint=r['endpoint'],n=12,patterns=4096,p=r['sign_flip_p'],adjusted_p=ap,
            family='Holm8_sign_flip_sensitivity',replaces_primary_decision=False))
    out=HERE/('analysis_'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d_%H%M%S'));out.mkdir(exist_ok=False)
    csvout(out/'seed_metrics_480.csv',[dict(method=k[0],condition=k[1],supply=k[2],seed=k[3],
        all_source_coverage_zero=v['coverage_pct']==0.,**v) for k,v in matrix.items()])
    for name,rows in [('primary_holm8.csv',primary),('cell_primary_endpoints_holm64.csv',heterogeneity),('fairness_age_holm72.csv',fair_age),('sign_flip_holm8.csv',primary_flip)]:csvout(out/name,rows)
    (out/'input_inventory.json').write_text(json.dumps(inventory,indent=2),encoding='utf8')
    (out/'reporting_boundaries.md').write_text('All five methods and eight cells retained. n=12 network seeds, not96 cells or100 nodes. Intervals are nominal95%, not simultaneous. Reused controls make this a staged comparison; seeds were already used. Secondary tests and sign-flip sensitivity cannot rescue failed primary claims. No algorithm or parameter selection from these results.\n',encoding='utf8')
    print(out)
if __name__=='__main__':main()
