"""Post-completion paired analysis; refuses partial matrices and independently rechecks raw arrays."""
from pathlib import Path
import csv,hashlib,json,math,sys
import numpy as np
from scipy import stats
import scipy
H=Path(__file__).resolve().parent
P=json.loads((H/'protocol_predefined.json').read_text(encoding='utf8'))
X=json.loads((H/'extra_comparators_predefined.json').read_text(encoding='utf8'))
OUT=H/'analysis_complete'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def check_lock(file, fields):
    lock=json.loads((H/file).read_text(encoding='utf8'))
    for key,path in fields.items():
        assert lock[key]==sha(H/path),(file,key)
def load_complete(folder, cases):
    completion=json.loads((H/folder/'completion.json').read_text(encoding='utf8'))
    assert completion['status']=='COMPLETE' and completion['planned_cases']==len(cases)
    ids=[r['index'] for r in completion['completed']]
    assert len(ids)==len(set(ids))==len(cases) and set(ids)=={c['index'] for c in cases}
    records={}
    for case in cases:
        d=H/folder/f"case_{case['index']:06d}"
        assert not (d/'failure.json').exists()
        v=json.loads((d/'validation.json').read_text(encoding='utf8'))
        assert v['status']=='PASS'
        rec=json.loads((d/'record.json').read_text(encoding='utf8'))
        assert all(rec['case'][k]==case[k] for k in ('index','seed','condition','supply','method','days'))
        m=rec['metrics']
        if 'max_hold_violation_j' in m:assert float(m['max_hold_violation_j'])<=1e-8
        if 'max_slot_violation' in m:assert float(m['max_slot_violation'])<=1e-8
        if case['method'] in ('NO-JOINT-PADC','SIMPLE-PADC-CADENCE'):
            assert m['floor_enabled']==0 and m['planning_mode']=='independent_padc_nonbinding_permission'
            assert 0<=float(m['mean_listen_fraction'])<=1
        with np.load(d/'arrays.npz') as a:
            latest=a['latest'];battery=a['battery'];status=a['sample_status']
            assert latest.shape==battery.shape==(case['days']*96,100)
            assert np.isfinite(battery).all() and battery.min()>=-1e-12 and battery.max()<=4+1e-12
            assert np.count_nonzero(status)==case['days']*96*100
            t=np.arange(latest.shape[0])[:,None]
            cv=((latest>=0)&(t-latest+1<=4)).mean(axis=0)*100
            age=np.where(latest>=0,t-latest+1,t+1)
            vals={'coverage_pct':float(cv.mean()),'source_coverage_p5_pct':float(np.quantile(cv,.05)),
                  'source_coverage_jain':float(cv.sum()**2/(100*(cv**2).sum())) if cv.any() else 0.,
                  'aoi_mean_minutes':float(age.mean()*15)}
            assert all(abs(vals[k]-float(m[k]))<1e-8 for k in vals)
        with (d/'node_ledgers.csv').open(encoding='utf8',newline='') as f:nodes=list(csv.DictReader(f))
        assert len(nodes)==100 and len({int(r['node']) for r in nodes})==100
        err=max(abs(float(r['initial_j'])+float(r['harvest_j'])-float(r['spill_j'])-
                    float(r['base_j'])-float(r['data_j'])-float(r['control_j'])-
                    float(r['final_j'])) for r in nodes)
        assert err<=1e-8
        consumed=sum(float(r[k]) for r in nodes for k in ('base_j','data_j','control_j'))
        # The common-host controls omit aggregate consumption/delivery fields:
        # derive them from the saved node ledgers and demand outcomes instead.
        if 'consumed_j' in m:
            assert abs(consumed-float(m['consumed_j']))<1e-6
        else:
            m['consumed_j']=consumed
        outcomes=m.get('outcomes',m)
        delivered=int(outcomes['delivered'])
        delivered_pct=100.0*delivered/(case['days']*96*100)
        if 'demand_delivery_pct' in m:
            assert abs(delivered_pct-float(m['demand_delivery_pct']))<1e-8
        else:
            m['demand_delivery_pct']=delivered_pct
        key=(case['method'],case['condition'],float(case['supply']),int(case['seed']))
        assert key not in records
        records[key]=m
    return records
def average(matrix,method,seed,field,cells):
    vals=[float(matrix[(method,condition,float(supply),seed)][field]) for condition,supply in cells]
    return float(np.mean(vals))
def paired(v):
    v=np.asarray(v,float);n=len(v);assert n==24 and np.isfinite(v).all()
    mean=float(v.mean());sd=float(v.std(ddof=1));se=sd/math.sqrt(n)
    if sd==0:
        return dict(n=n,mean_difference=mean,sd_difference=sd,ci95_low=None,ci95_high=None,
                    t=None,df=n-1,p=None)
    t=mean/se;half=float(stats.t.ppf(.975,n-1)*se)
    return dict(n=n,mean_difference=mean,sd_difference=sd,ci95_low=mean-half,ci95_high=mean+half,
                t=t,df=n-1,p=float(2*stats.t.sf(abs(t),n-1)))
def write(name,rows):
    with (OUT/name).open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def main():
    if OUT.exists():raise SystemExit('Refusing to overwrite completed analysis')
    required=['confirmation/completion.json','extra_confirmation/completion.json','new_weather_confirmation/completion.json']
    if any(not (H/p).exists() for p in required):
        raise SystemExit('WAIT: all three predefined experiment matrices must complete before any analysis')
    check_lock('study_lock.json',{'protocol_sha256':'protocol_predefined.json','runner_sha256':'run_stage_b.py'})
    check_lock('extra_study_lock.json',{'protocol_sha256':'extra_comparators_predefined.json',
                                      'runner_sha256':'run_extra_comparators.py','base_runner_sha256':'run_stage_b.py'})
    check_lock('weather_study_lock.json',{'parent_protocol_sha256':'protocol_predefined.json',
                                         'runner_sha256':'run_new_weather.py','base_runner_sha256':'run_stage_b.py',
                                         'processed_weather_sha256':'new_weather/ghi_15min_loader.csv',
                                         'provenance_sha256':'new_weather/provenance.json'})
    maincases=[dict(c,days=P['days']) for c in P['cases']]
    weathercases=[]
    spec=P['new_weather_prespecified']
    for seed in spec['seeds']:
        for supply in spec['supplies']:
            for method in spec['methods']:
                weathercases.append({'index':len(weathercases)+1,'seed':seed,'condition':'NOAA_SEPT2024_G20',
                                     'supply':supply,'method':method,'days':14})
    print('Validating complete primary arrays and ledgers',flush=True)
    main=load_complete('confirmation',maincases)
    print('Validating complete additional-comparator arrays and ledgers',flush=True)
    extra=load_complete('extra_confirmation',X['cases'])
    print('Validating complete unseen-weather arrays and ledgers',flush=True)
    weather=load_complete('new_weather_confirmation',weathercases)
    cells=[(c['name'],s) for c in P['conditions'] for s in P['supplies']]
    seeds=P['seeds'];field='source_coverage_p5_pct'
    primary=[]
    for cmp in ['NO-FLOOR','NO-HOLD']:
        delta=[average(main,'JLC-R',seed,field,cells)-average(main,cmp,seed,field,cells) for seed in seeds]
        primary.append({'contrast':'JLC-R minus '+cmp,'endpoint':field,**paired(delta)})
    ps=[r['p'] for r in primary]
    if all(p is not None for p in ps):
        order=sorted(range(2),key=lambda i:ps[i]);running=0.;adjusted=[None,None]
        for rank,i in enumerate(order):
            running=max(running,(2-rank)*ps[i]);adjusted[i]=min(1.,running)
        for row,a in zip(primary,adjusted):row.update(holm2_adjusted_p=a,reject_05=a<.05)
    else:
        for row in primary:row.update(holm2_adjusted_p=None,reject_05=None)
    summaries=[]
    allmatrix={**main,**extra}
    for endpoint in ['coverage_pct','source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes']:
        for cmp in ['NO-FLOOR-NO-HOLD','EADCM-CE','LANTERN-CE',*X['methods']]:
            d=[average(allmatrix,'JLC-R',seed,endpoint,cells)-average(allmatrix,cmp,seed,endpoint,cells) for seed in seeds]
            result=paired(d)
            summaries.append({'comparison':'JLC-R minus '+cmp,'endpoint':endpoint,
                              'n':result['n'],'mean_difference':result['mean_difference'],
                              'ci95_low':result['ci95_low'],'ci95_high':result['ci95_high'],
                              'interpretation':'exploratory; nominal interval; no multiplicity decision'})
    d=[]
    for seed in seeds:
        f=lambda method:average(main,method,seed,field,cells)
        d.append((f('JLC-R')-f('NO-FLOOR'))-(f('NO-HOLD')-f('NO-FLOOR-NO-HOLD')))
    effect=paired(d)
    interaction=[{'contrast':'(full - no floor) - (no hold - neither)','endpoint':field,
                  'n':effect['n'],'mean_difference':effect['mean_difference'],'ci95_low':effect['ci95_low'],
                  'ci95_high':effect['ci95_high'],'interpretation':'exploratory; nominal interval'}]
    weathercells=[('NOAA_SEPT2024_G20',s) for s in spec['supplies']]
    wrows=[]
    for endpoint in ['coverage_pct','source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes']:
        d=[average(weather,'JLC-R',seed,endpoint,weathercells)-average(weather,'EADCM-CE',seed,endpoint,weathercells) for seed in seeds]
        r=paired(d)
        wrows.append({'comparison':'JLC-R minus EADCM-CE','endpoint':endpoint,'n':r['n'],
                      'mean_difference':r['mean_difference'],'ci95_low':r['ci95_low'],'ci95_high':r['ci95_high'],
                      'interpretation':'exploratory; one shared weather trajectory; nominal interval'})
    OUT.mkdir()
    write('primary_holm2.csv',primary);write('exploratory_comparisons.csv',summaries)
    write('exploratory_interaction.csv',interaction);write('new_weather_exploratory.csv',wrows)
    receipt={'status':'COMPLETE','unit':'network seed','seed_count':24,'original_weather_supply_cells':len(cells),
             'validated_main':len(main),'validated_additional':len(extra),'validated_new_weather':len(weather),
             'independent_audit':'each saved latest/battery/status array and each node energy ledger independently rechecked',
             'primary_family':'two two-sided paired-t tests of equal-cell-average source P5, Holm-2',
             'uncertainty':'individual nominal 95% paired-t intervals; not multiplicity adjusted',
             'weather_scope':'conditional on one added measured trajectory, not independent weather-site replication',
             'scipy_version':scipy.__version__,'numpy_version':np.__version__,
             'protocol_sha256':sha(H/'protocol_predefined.json'),
             'analysis_sha256':sha(Path(__file__)),
             'outputs':{p.name:sha(p) for p in OUT.iterdir()}}
    (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
    print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
