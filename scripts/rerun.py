"""Explicit opt-in reproduction of locked cases into a new external directory."""
from pathlib import Path
import csv,json,sys,traceback
import numpy as np
from analysis_core import ROOT

sys.path.insert(0,str(ROOT/'code/simulation'))
from current_io import load_config,build_scenario
from validation_model import StreamingBank
from jlc_r import JLCR
from eadcm_host import EADCMCommonHost
from lantern_host import LanternCommonHost
from v6_model import HYBSimulator
from v63_model import RelayRepairHYB

def encode(x):
    if isinstance(x,np.generic):return x.item()
    if isinstance(x,np.ndarray):return x.tolist()
    raise TypeError(type(x).__name__)
def dump(path,x):path.write_text(json.dumps(x,indent=2,default=encode),encoding='utf8')
def csvout(path,items):
    if not items:return
    with path.open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(items[0]));w.writeheader();w.writerows(items)
def construct(method,c,sc):
    bank=StreamingBank(sc)
    if method=='JLC-R-RC2':return JLCR(c,sc,bank)
    if method=='EADCM-CE':return EADCMCommonHost(c,sc,bank,forecast_days=5,target_fraction=.2)
    if method=='LANTERN-CE':return LanternCommonHost(c,sc,bank,maximum_reward=32.,trickle_redundancy=1,data_header_bits=64,uniform_listen_s=.56)
    if method=='Base-hybrid':return HYBSimulator(c,sc,bank)
    if method=='Pre-recovery-JLC-R':return RelayRepairHYB(c,sc,bank,v63_mechanism='relay_repair')
    raise ValueError(method)
def run_case(case,protocol,out):
    folder=out/f"case_{case['index']:04d}";folder.mkdir(exist_ok=False)
    dump(folder/'case.json',case);latest=[];battery=[];parents=[];ranks=[]
    try:
        condition=next(c for c in protocol['conditions'] if c['name']==case['condition'])
        c=load_config(condition);sc=build_scenario(c,case['seed'],protocol['days'],case['supply'],condition)
        s=construct(case['method'],c,sc);dump(folder/'effective_config.json',s.c)
        for _ in range(sc.rounds):
            s.round();latest.append(s.latest.copy());battery.append(s.battery.copy())
            if case['method']=='LANTERN-CE':parents.append(s.parent.copy());ranks.append(s.rank.copy())
        # Finalize outstanding status codes before serializing the terminal
        # array, matching the original formal execution order.
        m=s.metrics()
        l=np.asarray(latest);b=np.asarray(battery)
        extra=dict(parents=np.asarray(parents),ranks=np.asarray(ranks)) if parents else {}
        np.savez_compressed(folder/'arrays.npz',latest=l,battery=b,sample_status=s.sample_status,**extra)
        csvout(folder/'node_ledgers.csv',s.node_rows())
        for attr,name in [('cadence_plans','cadence_plans.csv'),('activation_rows','intentional_sleep.csv'),
                          ('planning_rows','planning.csv'),('activity_rows','activity.csv'),
                          ('control_rows','control_frames.csv'),('meter_rows','DIO_meters.csv')]:
            if hasattr(s,attr):csvout(folder/name,getattr(s,attr))
        cov=((l>=0)&(np.arange(sc.rounds)[:,None]-l+1<=4)).mean(axis=0)*100
        ages=np.where(l>=0,np.arange(sc.rounds)[:,None]-l+1,np.arange(sc.rounds)[:,None]+1)
        metrics=dict(coverage_pct=cov.mean(),source_coverage_p5_pct=np.quantile(cov,.05),
            source_coverage_jain=cov.sum()**2/(100*(cov**2).sum()) if cov.any() else 0.,aoi_mean_minutes=ages.mean()*15)
        for k,v in metrics.items():assert abs(m[k]-v)<1e-8,k
        assert np.isfinite(b).all() and b.min()>=-1e-12 and b.max()<=4+1e-12
        assert m['max_node_energy_error_j']<=1e-8 and m['max_energy_balance_error_j']<=1e-6 and m['timing_misses']==0
        outcomes=m.get('outcomes',m)
        assert sum(outcomes.get(k,0) for k in ['delivered','expired','overflow','outstanding','unsensed','routing_drop'])==sc.rounds*c['nodes']
        assert np.count_nonzero(s.sample_status)==sc.rounds*c['nodes']
        dump(folder/'record.json',dict(case=case,metrics=m,rounds=sc.rounds,run_kind='explicit_reexecution'))
        dump(folder/'validation.json',dict(status='PASS',metrics_recomputed=list(metrics),data_and_energy_checked=True))
    except BaseException as exc:
        if latest:np.savez_compressed(folder/'partial_arrays.npz',latest=latest,battery=battery)
        dump(folder/'failure.json',dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc()))
        raise
def run(protocol,out,indices=None,dry_run=False):
    cases=protocol['cases']
    if indices is not None:
        wanted=set(indices);cases=[c for c in cases if c['index'] in wanted]
        assert len(cases)==len(wanted),'Unknown or duplicate requested case index'
    plan=dict(study='confirmation',cases=len(cases),rounds_per_case=protocol['days']*96,
        original_network_seeds=True,new_formal_claim=False,output=str(out))
    if dry_run:return dict(**plan,dry_run=True,simulations_started=0)
    out=Path(out).resolve();assert not out.is_relative_to(ROOT.resolve()),'Output must be outside the frozen package'
    out.mkdir(parents=True,exist_ok=False);dump(out/'run_plan.json',plan)
    completed=[]
    for case in cases:
        run_case(case,protocol,out);completed.append(case['index'])
        print(f"Completed {len(completed)}/{len(cases)}: case {case['index']}",flush=True)
    dump(out/'completed.json',dict(status='COMPLETE',cases=completed,formal_claim=False))
    return dict(**plan,dry_run=False,simulations_started=len(completed))
