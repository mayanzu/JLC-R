"""Replay measured Bondville temperature through saved network deliveries.

An illustrative single-station air-temperature task, not crop frost truth,
sensor field deployment, or an independent simulation. No raw input is edited.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import statistics
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
RC2 = PROJECT / 'code/experiments/rc2_confirmation'
WEATHER = PROJECT / 'code/results/strengthening_weather/T3'
OLD = PROJECT / 'temp/current_research/jlcr_rgp_confirmation_retry_20261026_155216'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, data):
    with path.open('w', encoding='utf8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8')


def freeze():
    path = HERE / 'protocol.json'
    if path.exists():
        raise FileExistsError(path)
    quality = read(WEATHER / 'quality.json')
    assert quality['station'] == 'Bondville_IL' and quality['utc_offset_hours'] == -6
    assert quality['warmup_days'] == 2 and quality['scored_days'] == 14
    source = {}
    for info in quality['source_files']:
        p = WEATHER / 'raw' / info['file']
        assert sha(p) == info['sha256']
        source[info['file']] = {'sha256': info['sha256'], 'url': info['url']}
    protocol = {
        'purpose': 'Illustrative temperature signal reconstruction at the sink under the existing T3/Bondville network traces',
        'status': 'Exploratory replay specified after the principal simulation results; not an agronomic validation or new independent weather experiment',
        'location': 'Bondville SURFRAD meteorological tower in an agricultural region; 10 m air-temperature instrument',
        'station_source': 'https://gml.noaa.gov/grad/surfrad/bondvill.html',
        'measurement_source': 'https://gml.noaa.gov/grad/surfrad/overview.html',
        'format_source': 'https://github.com/pvlib/pvlib-python/blob/main/pvlib/iotools/surfrad.py',
        'temperature': 'daily files: column 39 in degrees Celsius and QC flag column 40, one-minute average; accept flag 0 and -80 < T < 65 C only',
        'alignment': 'Original T3 local standard time (UTC-6); score from local 2024-01-03 00:00 for 1344 15-minute rounds. Take the valid one-minute measurement timestamped at the start of each round.',
        'synthetic_mapping': 'Each simulated source samples the same single measured station signal; no spatial variation, crop-canopy temperature, sensing noise or radio/packet changes are inferred.',
        'decision': 'Illustrative 0 C station-air threshold, not a crop or frost-damage threshold. A sink observation is usable only when its delivered birth is nonnegative, at most four simulation rounds old, and the birth-time station sample has valid QC.',
        'metrics': 'On truth-valid source-rounds: unavailable fraction and mean absolute reconstruction error conditional on usable. On truth-valid station-air <=0 C source-rounds: percentage usable and alarmed, usable and not alarmed, or unavailable. Unavailable is not silently labelled safe.',
        'units': 'One aggregate per paired network seed; 12 previously used seeds per method and supply. One weather time series repeated across sources is not 100 independent fields.',
        'methods': 'All five original methods plus the separately verified historical PADC-AGE adaptation; evaluate T3 at both existing supply levels.',
        'weather_file_sha256': source,
        'weather_quality_sha256': sha(WEATHER/'quality.json'),
        'rc2_summary_sha256': sha(RC2/'results/confirmation_480.csv'),
        'old_inventory_sha256': sha(OLD/'execution_inventory.json'),
        'script_sha256': sha(HERE/'replay.py'),
        'sampling': 'This is a postprocessing replay of fixed existing packet times; decisions do not use station temperature, no sample or network rerun is implied.'}
    write_json(path, protocol)
    print(json.dumps({'protocol_sha256': sha(path), 'status': 'FROZEN'}), flush=True)


def truth_values(protocol):
    data = {}
    for name, info in protocol['weather_file_sha256'].items():
        p = WEATHER/'raw'/name
        assert sha(p) == info['sha256']
        with p.open(encoding='utf8') as f:
            next(f); next(f)
            for line in f:
                x = line.split()
                if len(x) < 48:
                    raise ValueError(f'Unexpected SURFRAD row in {name}')
                key = dt.datetime(int(x[0]), int(x[2]), int(x[3]), int(x[4]), int(x[5]))
                value, flag = float(x[38]), int(x[39])
                if key in data:
                    raise ValueError(f'Duplicate station timestamp {key}')
                data[key] = value if flag == 0 and -80 < value < 65 else np.nan
    start_local = dt.datetime(2024,1,3,0,0)
    temp, trace = [], []
    for i in range(1344):
        local = start_local + dt.timedelta(minutes=15*i)
        utc = local + dt.timedelta(hours=6)
        if utc not in data:
            raise ValueError(f'Missing station timestamp {utc}')
        v = data[utc]
        temp.append(v)
        trace.append({'round': i, 'local_standard_time': local.isoformat(), 'utc': utc.isoformat()+'Z',
                      'air_temperature_c': '' if not np.isfinite(v) else float(v),
                      'quality_valid': int(np.isfinite(v))})
    return np.asarray(temp, dtype=float), trace


def evaluate(latest, truth):
    if latest.shape != (1344,100):
        raise ValueError('Unexpected latest-delivery shape')
    t = np.arange(1344)[:,None]
    if np.any(latest > t):
        raise ValueError('A delivery references a future sample')
    truth_valid = np.isfinite(truth)[:,None]
    truth_matrix = np.broadcast_to(truth[:,None], latest.shape)
    birth_valid = (latest >= 0) & (latest <= t)
    safe_idx = np.maximum(latest, 0)
    reported = truth[safe_idx]
    usable = truth_valid & birth_valid & ((t-latest+1) <= 4) & np.isfinite(reported)
    valid_den = int(np.broadcast_to(truth_valid, latest.shape).sum())
    cold = truth_valid & (truth_matrix <= 0)
    cold_den = int(cold.sum())
    assert valid_den and cold_den
    errors = np.abs(reported[usable] - truth_matrix[usable])
    good_alarm = cold & usable & (reported <= 0)
    wrong_safe = cold & usable & (reported > 0)
    unknown = cold & ~usable
    assert int(good_alarm.sum()+wrong_safe.sum()+unknown.sum()) == cold_den
    warm = truth_valid & (truth_matrix > 0)
    warm_usable = warm & usable
    return {
        'unavailable_pct': float(100*(np.broadcast_to(truth_valid,latest.shape) & ~usable).sum()/valid_den),
        'mae_c_given_usable': float(errors.mean()) if len(errors) else None,
        'cold_detected_pct': float(100*good_alarm.sum()/cold_den),
        'cold_false_safe_pct': float(100*wrong_safe.sum()/cold_den),
        'cold_unavailable_pct': float(100*unknown.sum()/cold_den),
        'warm_false_alarm_pct_given_usable': float(100*(warm_usable & (reported <= 0)).sum()/warm_usable.sum()) if warm_usable.any() else None,
        'truth_valid_source_rounds': valid_den,
        'truth_cold_source_rounds': cold_den,
        'usable_source_rounds': int(usable.sum()),
    }


def run():
    p = read(HERE/'protocol.json')
    assert p['script_sha256'] == sha(HERE/'replay.py')
    assert p['weather_quality_sha256'] == sha(WEATHER/'quality.json')
    assert p['rc2_summary_sha256'] == sha(RC2/'results/confirmation_480.csv')
    assert p['old_inventory_sha256'] == sha(OLD/'execution_inventory.json')
    out = HERE/'output'
    out.mkdir(exist_ok=False)
    truth, trace = truth_values(p)
    write_csv(out/'temperature_15m_1344.csv', trace)
    data = [r for r in rows(RC2/'results/confirmation_480.csv') if r['condition']=='T3_G20']
    assert len(data) == 120
    result = []
    with zipfile.ZipFile(RC2/'raw/rc2_formal_raw.zip') as z:
        for r in data:
            branch = 'new' if r['origin']=='new_execution' else 'reused'
            file = f"{branch}/case_{int(r['case_index']):04d}/arrays.npz"
            archive = np.load(io.BytesIO(z.read(file)))
            row = {'method': r['method'], 'supply': float(r['supply']), 'seed': int(r['seed']),
                   'source_case': r['case_index'], 'origin': r['origin'], **evaluate(archive['latest'],truth)}
            result.append(row)
    inventory = read(OLD/'execution_inventory.json')
    matches = [x for x in inventory if x['case']['method']=='PADC-AGE' and x['case']['condition']=='T3_G20']
    assert len(matches)==24
    for x in matches:
        folder=OLD/'runs'/f"case_{x['index']:04d}"
        assert sha(folder/'arrays.npz') == x['arrays_sha256']
        archive=np.load(folder/'arrays.npz')
        row={'method':'PADC-AGE','supply':float(x['case']['supply']),'seed':int(x['case']['seed']),
             'source_case':x['index'],'origin':'historical_padc',**evaluate(archive['latest'],truth)}
        result.append(row)
    assert len(result)==144
    write_csv(out/'seed_task_metrics_144.csv',result)
    summary=[]
    metrics=['unavailable_pct','mae_c_given_usable','cold_detected_pct','cold_false_safe_pct',
             'cold_unavailable_pct','warm_false_alarm_pct_given_usable']
    for method,supply in sorted({(x['method'],x['supply']) for x in result}):
        subset=[x for x in result if x['method']==method and x['supply']==supply]
        assert len(subset)==12
        for metric in metrics:
            values=[x[metric] for x in subset if x[metric] is not None]
            if not values:
                continue
            n=len(values)
            mean=statistics.mean(values)
            half=stats.t.ppf(.975,n-1)*statistics.stdev(values)/math.sqrt(n) if n>1 else None
            summary.append({'method':method,'supply':supply,'metric':metric,'n_seeds':n,'mean':mean,
                            'nominal_ci95_low':None if half is None else mean-half,
                            'nominal_ci95_high':None if half is None else mean+half})
    write_csv(out/'condition_task_summary.csv',summary)
    valid=np.isfinite(truth)
    meta={'status':'PASS','protocol_sha256':sha(HERE/'protocol.json'),'runs':144,
          'valid_station_rounds':int(valid.sum()),'invalid_station_rounds':int((~valid).sum()),
          'station_cold_rounds':int((valid & (truth<=0)).sum()),
          'n_weather_trajectories':1,'n_network_seeds_per_method_supply':12,
          'simulations_started':0,'outputs_sha256':{x.name:sha(x) for x in out.glob('*.csv')}}
    write_json(out/'audit.json',meta)
    print(json.dumps(meta,ensure_ascii=False,indent=2),flush=True)


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['freeze','run'])
    args=parser.parse_args()
    freeze() if args.mode=='freeze' else run()
