"""One authorized external case. No import-time simulations; never overwrites."""
import csv,json,sys,time,traceback
from pathlib import Path
import numpy as np
from rc2_runtime import HERE,PROJECT,read,sha,verify_sources,make,load_config,build_scenario,signature

def encode(x):
    if isinstance(x,np.generic):return x.item()
    if isinstance(x,np.ndarray):return x.tolist()
    raise TypeError(type(x).__name__)
def dump(p,x):p.write_text(json.dumps(x,indent=2,default=encode),encoding='utf8')
def csvout(p,rows):
    if not rows:return
    with p.open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def require_authorization():
    a=read(HERE/'authorization.json')
    assert a.get('authorized') is True and a['protocol_sha256']==sha(HERE/'protocol.json')
    assert a['new_simulations']==288 and a['reused_internal_records']==192
    return a

def execute(index,run_directory):
    require_authorization();p=read(HERE/'protocol.json');verify_sources(p);case=p['cases'][index]
    assert case['index']==index and case['execution']=='new_execution'
    parent=Path(run_directory).resolve();assert parent.parent==HERE.resolve() and parent.name.startswith('execution_')
    out=parent/'runs'/f'case_{index:04d}';out.mkdir(parents=True,exist_ok=False)
    manifest=dict(case=case,protocol_sha256=sha(HERE/'protocol.json'),source_sha256=p['source_sha256'],execution_source_sha256=p['execution_source_sha256'])
    dump(out/'manifest.json',manifest);started=time.time()
    latest=[];battery=[];parents=[];ranks=[]
    try:
        cond=next(x for x in p['conditions'] if x['name']==case['condition']);c=load_config(cond)
        sc=build_scenario(c,case['seed'],p['days'],case['supply'],cond);s=make(case['method'],c,sc)
        sig=signature(sc,s)
        pair=next(x for x in read(HERE/'paired_initialization_audit.json') if (x['condition'],x['supply'],x['seed'])==(case['condition'],case['supply'],case['seed']))
        assert sig==pair['input_signature'] and s.c==read(HERE/'effective_configs.json')[case['condition']]
        dump(out/'effective_config.json',s.c)
        for _ in range(sc.rounds):
            s.round();latest.append(s.latest.copy());battery.append(s.battery.copy())
            if case['method']=='LANTERN-CE':parents.append(s.parent.copy());ranks.append(s.rank.copy())
        m=s.metrics();l=np.asarray(latest);b=np.asarray(battery)
        extra=dict(parents=np.asarray(parents),ranks=np.asarray(ranks)) if parents else {}
        np.savez_compressed(out/'arrays.npz',latest=l,battery=b,sample_status=s.sample_status,**extra)
        csvout(out/'node_ledgers.csv',s.node_rows())
        for attr,name in [('control_rows','control_frames.csv'),('meter_rows','DIO_meters.csv'),('planning_rows','planning.csv'),('activity_rows','activity.csv'),('cadence_plans','cadence_plans.csv'),('activation_rows','intentional_sleep.csv')]:
            if hasattr(s,attr):csvout(out/name,getattr(s,attr))
        r=dict(**manifest,metrics=m,input_signature=sig,rounds=sc.rounds,runtime_seconds=time.time()-started,
            forecast_signature=s.bank.signature.hexdigest() if getattr(s,'bank',None) else None)
        dump(out/'record.json',r)
        cov=((l>=0)&(np.arange(sc.rounds)[:,None]-l+1<=4)).mean(axis=0)*100
        age=np.where(l>=0,np.arange(sc.rounds)[:,None]-l+1,np.arange(sc.rounds)[:,None]+1)
        recomputed=dict(coverage_pct=cov.mean(),source_coverage_p5_pct=np.quantile(cov,.05),
            source_coverage_jain=cov.sum()**2/(100*(cov**2).sum()) if cov.any() else 0.,aoi_mean_minutes=age.mean()*15)
        for k,v in recomputed.items():assert abs(m[k]-v)<1e-8,k
        assert np.isfinite(b).all() and b.min()>=-1e-12 and b.max()<=4+1e-12
        assert m['max_node_energy_error_j']<=1e-8 and m['max_energy_balance_error_j']<=1e-6 and m['timing_misses']==0
        for key in ['max_hold_violation_j','max_slot_violation']:
            if key in m:assert m[key]<1e-8,key
        assert np.count_nonzero(s.sample_status)==sc.rounds*100
        assert sum(m.get('outcomes',m).get(k,0) for k in ['delivered','expired','overflow','outstanding','unsensed','routing_drop'])==sc.rounds*100
        for row in getattr(s,'meter_rows',[]):assert row['rates_observed_until_s']<=row['round']*900
        verify_sources(p)
        dump(out/'validation.json',dict(status='PASS',metrics_recomputed=list(recomputed),shared_input_signature_verified=True))
        return dict(index=index,method=case['method'],runtime_seconds=r['runtime_seconds'],status='PASS')
    except BaseException as exc:
        np.savez_compressed(out/'partial_arrays.npz',latest=latest,battery=battery)
        dump(out/'failure.json',dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc()))
        raise
if __name__=='__main__':print(json.dumps(execute(int(sys.argv[1]),sys.argv[2])))
