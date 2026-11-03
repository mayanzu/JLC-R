"""Independently check field time alignment and stratified replay metrics."""
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
import bisect
import csv
import hashlib
import io
import json
import statistics
import zipfile
import numpy as np

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[2]
ARCHIVE=PROJECT/'code/experiments/rc2_confirmation/raw/rc2_formal_raw.zip'
FIELDS=['usable_pct','unavailable_pct','usable_during_open_pct','unavailable_during_open_pct',
        'mae_moisture_pp_given_usable','mae_moisture_pp_during_open_given_usable']


def rows(path):
    with path.open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))


def stamp(raw):
    return datetime.strptime(raw,'%d-%b-%Y %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()


def original(name,value):
    rr=rows(HERE/'raw'/name)
    return sorted((stamp(r['time_stamp']),float(r[value])) for r in rr)


def check_field():
    moisture=original('D_moisture.txt','moisture');valve=original('D_valve.txt','relay')
    mt=[x[0] for x in moisture];vt=[x[0] for x in valve]
    field=rows(HERE/'results/field_windows_5376.csv');assert len(field)==5376
    segments=[]
    for w in range(4):
        rr=[r for r in field if int(r['window'])==w];assert len(rr)==1344
        assert [int(r['round']) for r in rr]==list(range(1344))
        for r in rr:
            t=datetime.fromisoformat(r['time_utc']).timestamp()
            a=bisect.bisect_right(mt,t)-1;b=bisect.bisect_right(vt,t)-1
            m=moisture[a][1] if a>=0 and t-mt[a]<=1800 else None
            v=valve[b][1] if b>=0 and t-vt[b]<=600 else None
            assert (r['moisture_pct']=='' and m is None) or abs(float(r['moisture_pct'])-m)<1e-10
            assert (r['valve_open']=='' and v is None) or int(r['valve_open'])==v
            assert int(r['truth_valid'])==int(m is not None and v is not None)
        segments.append(rr)
    return segments


def check_case(latest,rr):
    # Independent round-by-round counting rather than the original matrix expression.
    values=[float(r['moisture_pct']) if r['moisture_pct'] else float('nan') for r in rr]
    denom=opened=usable=usable_open=0;err=err_open=0.
    for t,r in enumerate(rr):
        if not int(r['truth_valid']):continue
        is_open=int(r['valve_open'])==1
        denom+=100;opened+=100*is_open
        for birth in latest[t]:
            birth=int(birth)
            if birth<0 or t-birth+1>4 or not np.isfinite(values[birth]):continue
            delta=abs(values[birth]-values[t]);usable+=1;err+=delta
            if is_open:usable_open+=1;err_open+=delta
    assert denom>0 and opened>0 and usable>0 and usable_open>0
    return {'usable_pct':100*usable/denom,'unavailable_pct':100*(denom-usable)/denom,
            'usable_during_open_pct':100*usable_open/opened,
            'unavailable_during_open_pct':100*(opened-usable_open)/opened,
            'mae_moisture_pp_given_usable':err/usable,
            'mae_moisture_pp_during_open_given_usable':err_open/usable_open}


def main():
    segments=check_field()
    records=rows(HERE/'results/seed_window_metrics_1920.csv');assert len(records)==1920
    grouped=defaultdict(list)
    for r in records:grouped[(r['method'],r['condition'],r['supply'],r['seed'])].append(r)
    assert len(grouped)==480 and all(len(g)==4 for g in grouped.values())
    # One lowest seed in every method x condition/supply cell; all 4 field windows.
    selected=[]
    for method,condition,supply in sorted({k[:3] for k in grouped}):
        candidates=[k for k in grouped if k[:3]==(method,condition,supply)]
        selected.append(min(candidates,key=lambda k:int(k[3])))
    assert len(selected)==40
    checks=0
    with zipfile.ZipFile(ARCHIVE) as archive:
        for key in selected:
            group=grouped[key];r=group[0];branch='new' if r['origin']=='new_execution' else 'reused'
            name=f"{branch}/case_{int(r['case_index']):04d}/arrays.npz"
            content=archive.read(name)
            assert hashlib.sha256(content).hexdigest()==r['arrays_sha256']
            with np.load(io.BytesIO(content)) as data:latest=data['latest']
            for item in group:
                w=int(item['window']);values=check_case(latest,segments[w])
                for k in FIELDS:
                    assert abs(float(item[k])-values[k])<1e-8,(key,w,k,item[k],values[k])
                    checks+=1
    grouped_cells=defaultdict(list)
    for r in records:grouped_cells[(r['method'],r['condition'],r['supply'])].append(r)
    summaries=rows(HERE/'results/condition_summary_40.csv');assert len(summaries)==40
    for row in summaries:
        group=grouped_cells[(row['method'],row['condition'],row['supply'])];assert len(group)==48
        for k in FIELDS:assert abs(float(row[k])-statistics.mean(float(r[k]) for r in group))<1e-9
    receipt={'status':'PASS','field_timestamps_checked':5376,'stratified_network_cases':40,
             'case_window_checks':160,'endpoint_checks':checks,'condition_summaries_checked':40,
             'simulations_started':0,'independent_weather_farms':1}
    (HERE/'results/independent_audit.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf8')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
