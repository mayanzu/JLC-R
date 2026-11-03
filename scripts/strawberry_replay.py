"""Recompute the strawberry-field replay from packaged original data and masks."""
from collections import defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path
import bisect
import csv
import math
import statistics
import numpy as np
from analysis_core import ROOT,rows

RAW=ROOT/'data/strawberry'
SUPPLEMENT=ROOT/'results/rc2_supplement'
STARTS=['2022-07-13T00:00:00+00:00','2022-07-27T00:00:00+00:00',
        '2022-08-10T00:00:00+00:00','2022-08-24T00:00:00+00:00']
FIELDS=['usable_pct','unavailable_pct','usable_during_open_pct','unavailable_during_open_pct',
        'mae_moisture_pp_given_usable','mae_moisture_pp_during_open_given_usable']


def _write(path,data):
    with path.open('w',encoding='utf8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)


def _raw(name,field):
    data=rows(RAW/name)
    out=[]
    for r in data:
        timestamp=datetime.strptime(r['time_stamp'],'%d-%b-%Y %H:%M:%S').replace(tzinfo=timezone.utc)
        out.append((timestamp,float(r[field])))
    out.sort()
    assert len({r[0] for r in out})==len(out)
    return out


def field_frames():
    moisture=_raw('D_moisture.txt','moisture');valve=_raw('D_valve.txt','relay')
    assert all(0<=v<=100 for _,v in moisture) and all(v in (0,1) for _,v in valve)
    mt=[r[0] for r in moisture];vt=[r[0] for r in valve]
    archives=rows(SUPPLEMENT/'field_windows_5376.csv');assert len(archives)==5376
    fields=[];out=[]
    for w,start in enumerate(STARTS):
        begin=datetime.fromisoformat(start);values=[];states=[];valid=[]
        for t in range(1344):
            when=begin+timedelta(minutes=15*t)
            a=bisect.bisect_right(mt,when)-1;b=bisect.bisect_right(vt,when)-1
            m=moisture[a] if a>=0 and (when-mt[a]).total_seconds()<=1800 else None
            v=valve[b] if b>=0 and (when-vt[b]).total_seconds()<=600 else None
            r={'window':w,'round':t,'time_utc':when.isoformat(),
               'moisture_pct':m[1] if m else '', 'moisture_observed_utc':m[0].isoformat() if m else '',
               'valve_open':int(v[1]) if v else '', 'valve_observed_utc':v[0].isoformat() if v else '',
               'truth_valid':int(bool(m and v))}
            archived=archives[w*1344+t]
            assert all(str(r[k])==archived[k] for k in r), (w,t,r,archived)
            out.append(r);values.append(m[1] if m else float('nan'))
            states.append(v[1] if v else float('nan'));valid.append(bool(m and v))
        fields.append((np.asarray(values),np.asarray(states),np.asarray(valid)))
    return fields,out


def score(code,field):
    assert code.shape==(1344,100) and ((code>=0)&(code<=4)).all()
    value,state,valid=field;t=np.arange(1344)[:,None]
    fresh=(code>0);birth=np.where(fresh,t-code.astype(int)+1,0)
    assert ((birth>=0)&(birth<=t)).all()
    report=value[birth]
    eligible=np.broadcast_to(valid[:,None],fresh.shape)
    usable=fresh & np.isfinite(report) & eligible
    opening=np.broadcast_to((valid & (state==1))[:,None],fresh.shape)
    n_valid=int(eligible.sum());n_open=int(opening.sum());n_usable=int(usable.sum());n_uopen=int((usable&opening).sum())
    assert n_valid>0 and n_open>0 and n_usable>0 and n_uopen>0
    err=np.abs(report-value[:,None])
    return {'truth_valid_rounds':int(valid.sum()),'open_valve_valid_rounds':int((valid&(state==1)).sum()),
      'usable_pct':100*n_usable/n_valid,'unavailable_pct':100*(n_valid-n_usable)/n_valid,
      'usable_during_open_pct':100*n_uopen/n_open,'unavailable_during_open_pct':100*(n_open-n_uopen)/n_open,
      'mae_moisture_pp_given_usable':float(err[usable].mean()),
      'mae_moisture_pp_during_open_given_usable':float(err[usable&opening].mean()),
      'usable_source_rounds':n_usable,'open_valve_usable_source_rounds':n_uopen}


def recompute(output=None):
    fields,field_rows=field_frames()
    cases=sorted(rows(ROOT/'results/confirmation_480.csv'),key=lambda r:int(r['case_index']))
    archived=rows(SUPPLEMENT/'strawberry_seed_window_metrics_1920.csv')
    assert len(cases)==480 and len(archived)==1920
    with np.load(SUPPLEMENT/'delivery_fresh_age_480.npz') as data:
        ages=data['age'];indices=data['case_index'];hashes=data['source_arrays_sha256']
    assert ages.shape==(480,1344,100) and np.array_equal(indices,np.arange(480))
    result=[];cell=defaultdict(list);seed=defaultdict(list)
    for i,case in enumerate(cases):
        assert int(case['case_index'])==i
        assert abs(100*(ages[i]>0).mean()-float(case['coverage_pct']))<1e-8
        for w,field in enumerate(fields):
            a=archived[i*4+w]
            assert all(case[k]==a[k] for k in ('case_index','method','condition','supply','seed','origin'))
            assert int(a['window'])==w and str(hashes[i])==a['arrays_sha256']
            computed=score(ages[i],field)
            assert all(math.isclose(float(a[k]),v,rel_tol=0,abs_tol=1e-8) for k,v in computed.items()),(i,w)
            r={**{k:case[k] for k in ('case_index','method','condition','supply','seed','origin')},
               'window':w,'arrays_sha256':str(hashes[i]),**computed}
            result.append(r);cell[(r['method'],r['condition'],r['supply'])].append(r)
            seed[(r['method'],r['seed'])].append(r)
    assert len(result)==1920 and len(cell)==40 and len(seed)==60
    cells=[]
    for (method,condition,supply),group in sorted(cell.items()):
        assert len(group)==48
        cells.append({'method':method,'condition':condition,'supply':supply,'n_seeds':12,'field_windows':4,
                      **{k:statistics.mean(r[k] for r in group) for k in FIELDS}})
    seeds=[]
    for (method,network_seed),group in sorted(seed.items()):
        assert len(group)==32
        seeds.append({'method':method,'seed':network_seed,'network_conditions':8,'field_windows':4,
                      **{k:statistics.mean(r[k] for r in group) for k in FIELDS}})
    totals=[]
    for method in sorted({r['method'] for r in seeds}):
        group=[r for r in seeds if r['method']==method];assert len(group)==12
        totals.append({'method':method,'network_seeds':12,'field_windows':4,
                       **{k:statistics.mean(r[k] for r in group) for k in FIELDS}})
    for filename,computed in [('strawberry_condition_summary_40.csv',cells),
                              ('strawberry_equal_condition_seed_summary_60.csv',seeds),
                              ('strawberry_equal_condition_summary_5.csv',totals)]:
        previous=rows(SUPPLEMENT/filename);assert len(previous)==len(computed)
        for a,b in zip(previous,computed):
            assert all(math.isclose(float(a[k]),b[k],rel_tol=0,abs_tol=1e-8) for k in FIELDS),filename
    if output is not None:
        output=Path(output)
        for name,table in [('strawberry_field_windows_5376.csv',field_rows),
                           ('strawberry_seed_window_metrics_1920.csv',result),
                           ('strawberry_condition_summary_40.csv',cells),
                           ('strawberry_equal_condition_seed_summary_60.csv',seeds),
                           ('strawberry_equal_condition_summary_5.csv',totals)]:_write(output/name,table)
    return {'status':'PASS','field_windows':4,'field_rows':len(field_rows),'case_window_records':len(result),
            'independent_farms':1,'simulations_started':0,
            'scope':'Open-loop elapsed-time pairing of one field record and existing simulated delivery traces; no field test of the network or irrigation controller.'}


if __name__=='__main__':
    import json
    print(json.dumps(recompute(),indent=2))
