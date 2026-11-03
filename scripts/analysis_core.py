"""Recompute the locked paired analyses from the archived seed records."""
from pathlib import Path
import csv,itertools,math
import numpy as np
from scipy import stats

ROOT=Path(__file__).resolve().parents[1]
FIELDS=['coverage_pct','source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes']
FLIPS=np.asarray(list(itertools.product([-1.,1.],repeat=12)))
def rows(p):
    with p.open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))
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
        se=sd/math.sqrt(12);t=mean/se;p=float(2*stats.t.sf(abs(t),11))
        half=float(stats.t.ppf(.975,11)*se);lo=mean-half;hi=mean+half
    perm=(FLIPS@d)/12
    sp=float(np.count_nonzero(np.abs(perm)>=abs(mean)-1e-12)/4096)
    return dict(n=12,df=11,mean_difference=mean,sd_difference=sd,t=t,p=p,ci95_low=lo,ci95_high=hi,
        undefined_t_variance=undefined,sign_flip_p=sp,sign_flip_patterns=4096)
def recompute(protocol):
    data=rows(ROOT/'results/confirmation_480.csv')
    matrix={(r['method'],r['condition'],float(r['supply']),int(r['seed'])):r for r in data}
    assert len(data)==len(matrix)==480
    cells=[(c['name'],s) for c in protocol['conditions'] for s in protocol['supplies']]
    seeds=protocol['seeds'];methods=protocol['methods']
    def vector(method,field,cell=None):
        return np.asarray([np.mean([float(matrix[(method,cn,sp,seed)][field]) for cn,sp in (cells if cell is None else [cell])]) for seed in seeds])
    primary=[];heterogeneity=[];fair_age=[];primary_flip=[]
    for control in methods[1:]:
        for field in FIELDS:
            for cell in [None,*cells]:
                delta=vector(methods[0],field,cell)-vector(control,field,cell)
                if field=='aoi_mean_minutes':delta=-delta
                r=dict(control=control,endpoint=field,cell='equal_weight_8cell' if cell is None else f'{cell[0]}/{cell[1]}',
                    positive_means='RC2 improvement; AoI=control minus RC2, other metrics=RC2 minus control',**paired(delta))
                if field in FIELDS[:2] and cell is None:primary.append(r)
                elif field in FIELDS[:2]:heterogeneity.append(r)
                else:fair_age.append(r)
    assert (len(primary),len(heterogeneity),len(fair_age))==(8,64,72)
    for rr,name in [(primary,'Holm8_primary'),(heterogeneity,'Holm64_secondary'),(fair_age,'Holm72_secondary')]:
        for r,value in zip(rr,holm([r['p'] for r in rr])):r.update(family=name,adjusted_p=value,reject_05=value<.05)
    for r,ap in zip(primary,holm([r['sign_flip_p'] for r in primary])):
        primary_flip.append(dict(control=r['control'],endpoint=r['endpoint'],n=12,patterns=4096,p=r['sign_flip_p'],adjusted_p=ap,
            family='Holm8_sign_flip_sensitivity',replaces_primary_decision=False))
    return {'primary_holm8.csv':primary,'cell_primary_endpoints_holm64.csv':heterogeneity,
            'fairness_age_holm72.csv':fair_age,'sign_flip_holm8.csv':primary_flip}
def check_archived(generated):
    checked=0
    for name,current in generated.items():
        saved=rows(ROOT/'results/statistics'/name);assert len(saved)==len(current),(name,len(saved),len(current))
        for i,(a,b) in enumerate(zip(current,saved)):
            assert set(a)==set(b),(name,i)
            for k,v in a.items():
                text=b[k]
                if v is None:assert text=='',(name,i,k,text)
                elif isinstance(v,(float,int)) and not isinstance(v,bool):
                    assert math.isclose(float(v),float(text),rel_tol=1e-9,abs_tol=1e-11),(name,i,k,v,text)
                else:assert str(v)==text,(name,i,k,v,text)
            checked+=1
    return checked
def write_outputs(out,generated):
    for name,rr in generated.items():
        with (out/name).open('w',encoding='utf8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rr[0]));w.writeheader();w.writerows(rr)
