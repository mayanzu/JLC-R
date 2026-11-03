"""Replay saved network delivery states on observed strawberry-farm measurements.

Uses recorded soil moisture and valve state as observations. It does not
simulate irrigation, infer crop-water demand, or change any network run.
"""
from collections import defaultdict
from pathlib import Path
import argparse
import csv
import hashlib
import io
import json
import statistics
import zipfile

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
INPUTS = [HERE/'raw/D_moisture.txt', HERE/'raw/D_valve.txt', HERE/'raw/D_flowmeter.txt',
          HERE/'raw/dataset_metadata.json', HERE/'download_receipt.json',
          PROJECT/'code/experiments/rc2_confirmation/raw/rc2_formal_raw.zip',
          PROJECT/'code/experiments/rc2_confirmation/results/confirmation_480.csv',
          Path(__file__).resolve()]
SOURCE = PROJECT/'code/experiments/rc2_confirmation/raw/rc2_formal_raw.zip'
CASE_FILE = PROJECT/'code/experiments/rc2_confirmation/results/confirmation_480.csv'
WINDOW_STARTS = ['2022-07-13T00:00:00Z','2022-07-27T00:00:00Z',
                 '2022-08-10T00:00:00Z','2022-08-24T00:00:00Z']
ROUNDS = 1344
NODES = 100


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path,payload):
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


def write_csv(path,rows):
    with path.open('w',encoding='utf8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def freeze():
    path=HERE/'protocol.json'
    if path.exists():raise FileExistsError(path)
    receipt=json.loads((HERE/'download_receipt.json').read_text(encoding='utf8'))
    for e in receipt['files']:
        assert sha(HERE/'raw'/e['name'])==e['sha256']
    p={'study':'Strawberry field moisture and valve-operation observational replay',
       'source_doi':'10.17632/cjb4vy4mzj.3','source_licence':'CC BY 4.0',
       'windows_utc':WINDOW_STARTS,'window_selection':'Four consecutive nonoverlapping 14-day windows beginning at the first full UTC midnight after the available series begins, selected from timestamps before outcomes were computed.',
       'rounds_per_window':ROUNDS,'round_minutes':15,'simulated_sources':NODES,
       'field_truth':'At each round, latest observed soil moisture not older than 30 minutes and latest valve command not older than 10 minutes; no interpolation. Exclude rounds missing either ground-truth observation.',
       'delivered_value':'Read field moisture available at each simulated delivery birth; it is usable when the delivered birth is at most four rounds old and the field measurement at that birth is not older than 30 minutes.',
       'pairing':'Same four 2022 strawberry-farm windows paired by elapsed round with each of 480 previously saved network runs. Field and simulated weather are not contemporaneous or colocated, and a single field series is replicated to all sources.',
       'endpoints':['overall usable fraction on truth-valid source-rounds','usable fraction during observed open-valve source-rounds','absolute soil-moisture error conditional on a usable state, overall and during valve opening'],
       'interpretation':'Descriptive retrospective open-loop data availability and reconstruction, not closed-loop control, irrigation need, crop damage, field testing of JLC-R, or independent farm replication.',
       'analysis':'40 method-by-condition/supply cells and four windows; 12 existing paired network seeds; descriptive summaries only; no hypothesis test or new independent seeds.',
       'source_sha256':{p.relative_to(PROJECT).as_posix():sha(p) for p in INPUTS}}
    write_json(path,p);print(json.dumps({'status':'FROZEN','protocol_sha256':sha(path)},indent=2))


def verify_protocol():
    p=json.loads((HERE/'protocol.json').read_text(encoding='utf8'))
    for rel,digest in p['source_sha256'].items():assert sha(PROJECT/rel)==digest,rel


def field_frames():
    moisture=pd.read_csv(HERE/'raw/D_moisture.txt')
    valve=pd.read_csv(HERE/'raw/D_valve.txt')
    for frame in (moisture,valve):
        frame['time_stamp']=pd.to_datetime(frame['time_stamp'],format='%d-%b-%Y %H:%M:%S',utc=True,errors='raise')
        frame.sort_values('time_stamp',inplace=True)
        assert frame.time_stamp.is_unique
    assert moisture.moisture.between(0,100).all() and valve.relay.isin([0,1]).all()
    field=[]
    for w,start in enumerate(WINDOW_STARTS):
        times=pd.date_range(start,periods=ROUNDS,freq='15min')
        table=pd.DataFrame({'time':times})
        table=pd.merge_asof(table,moisture.rename(columns={'time_stamp':'moisture_time'}),left_on='time',
                            right_on='moisture_time',direction='backward',tolerance=pd.Timedelta(minutes=30))
        table=pd.merge_asof(table,valve.rename(columns={'time_stamp':'valve_time'}),left_on='time',
                            right_on='valve_time',direction='backward',tolerance=pd.Timedelta(minutes=10))
        value=table.moisture.to_numpy(float);state=table.relay.to_numpy(float)
        valid=np.isfinite(value)&np.isfinite(state)
        assert valid.any() and ((state[valid]==0)|(state[valid]==1)).all()
        field.append({'moisture':value,'valve':state,'valid':valid,'table':table})
    return field


def score(latest,field):
    assert latest.shape==(ROUNDS,NODES)
    t=np.arange(ROUNDS)[:,None]
    value=field['moisture'];valid=field['valid']
    assert ((latest>=-1)&(latest<=t)).all()
    usable=(latest>=0)&(t-latest+1<=4)
    birth=np.maximum(latest,0)
    reported=value[birth]
    usable &= np.isfinite(reported)
    eligible=np.broadcast_to(valid[:,None],latest.shape)
    usable &= eligible
    open_mask=np.broadcast_to((valid & (field['valve']==1))[:,None],latest.shape)
    n_valid=int(eligible.sum());n_open=int(open_mask.sum());n_usable=int(usable.sum());n_open_usable=int((usable&open_mask).sum())
    if not n_valid or not n_open:raise ValueError('Missing valid or open-valve source-rounds')
    error=np.abs(reported-value[:,None])
    return {'truth_valid_rounds':int(valid.sum()),'open_valve_valid_rounds':int((valid & (field['valve']==1)).sum()),
            'usable_pct':100*n_usable/n_valid,'unavailable_pct':100*(n_valid-n_usable)/n_valid,
            'usable_during_open_pct':100*n_open_usable/n_open,
            'unavailable_during_open_pct':100*(n_open-n_open_usable)/n_open,
            'mae_moisture_pp_given_usable':float(error[usable].mean()) if n_usable else None,
            'mae_moisture_pp_during_open_given_usable':float(error[usable&open_mask].mean()) if n_open_usable else None,
            'usable_source_rounds':n_usable,'open_valve_usable_source_rounds':n_open_usable}


def run():
    verify_protocol();out=HERE/'results';out.mkdir(exist_ok=False)
    field=field_frames();field_rows=[]
    for w,f in enumerate(field):
        for i,row in f['table'].iterrows():
            field_rows.append({'window':w,'round':i,'time_utc':row['time'].isoformat(),
                'moisture_pct':float(row['moisture']) if pd.notna(row['moisture']) else '',
                'moisture_observed_utc':row['moisture_time'].isoformat() if pd.notna(row['moisture_time']) else '',
                'valve_open':int(row['relay']) if pd.notna(row['relay']) else '',
                'valve_observed_utc':row['valve_time'].isoformat() if pd.notna(row['valve_time']) else '',
                'truth_valid':int(f['valid'][i])})
    write_csv(out/'field_windows_5376.csv',field_rows)
    with CASE_FILE.open(encoding='utf8',newline='') as stream:cases=list(csv.DictReader(stream))
    assert len(cases)==480
    results=[]
    with zipfile.ZipFile(SOURCE) as archive:
        for case in cases:
            branch='new' if case['origin']=='new_execution' else 'reused'
            name=f"{branch}/case_{int(case['case_index']):04d}/arrays.npz"
            content=archive.read(name)
            with np.load(io.BytesIO(content)) as data:latest=data['latest']
            for window,f in enumerate(field):
                results.append({**{k:case[k] for k in ('case_index','method','condition','supply','seed','origin')},
                                'window':window,'arrays_sha256':hashlib.sha256(content).hexdigest(),**score(latest,f)})
    assert len(results)==1920
    write_csv(out/'seed_window_metrics_1920.csv',results)
    fields=['usable_pct','unavailable_pct','usable_during_open_pct','unavailable_during_open_pct',
            'mae_moisture_pp_given_usable','mae_moisture_pp_during_open_given_usable']
    grouped=defaultdict(list)
    for r in results:grouped[(r['method'],r['condition'],r['supply'])].append(r)
    summaries=[]
    for (method,condition,supply),group in sorted(grouped.items()):
        assert len(group)==48
        summaries.append({'method':method,'condition':condition,'supply':supply,'n_seeds':12,'field_windows':4,
                          **{k:statistics.mean(r[k] for r in group if r[k] is not None) for k in fields}})
    write_csv(out/'condition_summary_40.csv',summaries)
    grouped=defaultdict(list)
    for r in results:grouped[(r['method'],r['seed'])].append(r)
    seed_summary=[]
    for (method,seed),group in sorted(grouped.items()):
        assert len(group)==32
        seed_summary.append({'method':method,'seed':seed,'network_conditions':8,'field_windows':4,
                             **{k:statistics.mean(r[k] for r in group if r[k] is not None) for k in fields}})
    write_csv(out/'equal_condition_seed_summary_60.csv',seed_summary)
    overall=[]
    for method in sorted({r['method'] for r in seed_summary}):
        group=[r for r in seed_summary if r['method']==method];assert len(group)==12
        overall.append({'method':method,'network_seeds':12,'field_windows':4,
                        **{k:statistics.mean(r[k] for r in group) for k in fields}})
    write_csv(out/'equal_condition_summary_5.csv',overall)
    write_json(out/'replay_receipt.json',{'status':'PASS','field_windows':4,'field_window_rows':len(field_rows),
       'network_cases':480,'method_condition_seed_window_records':len(results),'network_simulations_started':0,
       'protocol_sha256':sha(HERE/'protocol.json'),'field_weather_matching':'Illustrative elapsed-time pairing; not colocated or contemporaneous.',
       'independent_farms':1,'new_network_seeds':0})
    print(json.dumps({'status':'PASS','records':len(results),'output':str(out),'network_simulations_started':0},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--mode',choices=['freeze','run'],required=True)
    args=parser.parse_args();freeze() if args.mode=='freeze' else run()
