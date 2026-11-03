"""Audit and compare existing RC2 and historical PADC-AGE seed records.

This is an exploratory cross-stage reanalysis, not a new simulation or an
independent confirmation. It creates files only in a new local output folder.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
OLD = PROJECT / 'temp/current_research/jlcr_rgp_confirmation_retry_20261026_155216'
RC2 = PROJECT / 'code/experiments/rc2_confirmation'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf8'))


def csv_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    with path.open('w', encoding='utf8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf8')


def ci(values):
    x = np.asarray(values, dtype=float)
    mean = float(x.mean())
    sd = float(x.std(ddof=1))
    half = float(stats.t.ppf(.975, len(x)-1) * sd / math.sqrt(len(x)))
    return mean, mean-half, mean+half


def main():
    out = HERE / 'output'
    out.mkdir(exist_ok=False)
    old_protocol = load(OLD / 'protocol.json')
    old_inventory = {r['index']: r for r in load(OLD / 'execution_inventory.json')}
    rc2 = [r for r in csv_rows(RC2 / 'results/confirmation_480.csv') if r['method'] == 'JLC-R-RC2']
    oldcases = [(i, c) for i, c in enumerate(old_protocol['cases']) if c['method'] == 'PADC-AGE']
    assert len(oldcases) == len(rc2) == 96
    lookup = {(r['condition'], float(r['supply']), int(r['seed'])): r for r in rc2}
    assert len(lookup) == 96
    results = []
    with zipfile.ZipFile(RC2 / 'raw/rc2_formal_raw.zip') as archive:
        for index, case in oldcases:
            key = (case['condition'], float(case['supply']), int(case['seed']))
            r = lookup[key]
            folder = OLD / 'runs' / f'case_{index:04d}'
            inv = old_inventory[index]
            assert inv['case'] == case
            assert sha(folder / 'record.json') == inv['record_sha256']
            assert sha(folder / 'arrays.npz') == inv['arrays_sha256']
            assert sha(folder / 'node_ledgers.csv') == inv['node_ledger_sha256']
            old = load(folder / 'record.json')
            old_config = load(folder / 'effective_config.json')
            rc2_folder = f"new/case_{int(r['case_index']):04d}/"
            new = json.loads(archive.read(rc2_folder + 'record.json'))
            new_config = json.loads(archive.read(rc2_folder + 'effective_config.json'))
            assert old['case'] == case
            assert old['input_signature'] == new['input_signature'], key
            assert old['forecast_signature'] == new['forecast_signature'], key
            assert old_config == new_config, key
            assert old['rounds'] == new['rounds'] == 1344
            m = old['metrics']
            arr = np.load(folder / 'arrays.npz')
            latest = arr['latest']
            assert latest.shape == (1344, 100)
            t = np.arange(1344)[:, None]
            source_cov = ((latest >= 0) & (t - latest + 1 <= 4)).mean(axis=0) * 100
            source_age = np.where(latest >= 0, t - latest + 1, t + 1).mean() * 15
            jain = source_cov.sum()**2 / (100 * (source_cov**2).sum()) if source_cov.any() else 0.
            assert np.isclose(source_cov.mean(), m['coverage_pct'], atol=1e-8, rtol=0)
            assert np.isclose(np.quantile(source_cov, .05), m['source_coverage_p5_pct'], atol=1e-8, rtol=0)
            assert np.isclose(jain, m['source_coverage_jain'], atol=1e-8, rtol=0)
            assert np.isclose(source_age, m['aoi_mean_minutes'], atol=1e-8, rtol=0)
            ledger = csv_rows(folder / 'node_ledgers.csv')
            assert len(ledger) == 100
            energy = sum(float(row[k]) for row in ledger for k in ('base_j', 'data_j', 'control_j'))
            assert abs(energy - float(m['consumed_j'])) < 1e-6
            total = sum(int(m.get(k, 0)) for k in ('delivered','expired','overflow','outstanding','unsensed','routing_drop'))
            assert total == 134400
            assert m['max_node_energy_error_j'] <= 1e-8 and m['max_energy_balance_error_j'] <= 1e-6
            assert m['max_hold_violation_j'] <= 1e-8 and m['max_slot_violation'] <= 1e-8
            measured = {
                'coverage_pct': float(source_cov.mean()),
                'source_coverage_p5_pct': float(np.quantile(source_cov,.05)),
                'source_coverage_jain': float(jain),
                'aoi_mean_minutes': float(source_age),
                'sample_completion_pct': 100*(134400-int(m['unsensed']))/134400,
                'fixed_demand_packet_delivery_pct': 100*int(m['delivered'])/134400,
                'actual_energy_j': energy,
            }
            row = {'condition': key[0], 'supply': key[1], 'seed': key[2],
                   'padc_old_case_index': index, 'rc2_case_index': int(r['case_index']),
                   'padc_record_sha256': inv['record_sha256'], 'padc_arrays_sha256': inv['arrays_sha256'],
                   'rc2_record_sha256': r['source_record_sha256']}
            for metric, value in measured.items():
                row['padc_' + metric] = value
                row['rc2_' + metric] = float(r[metric])
                row['difference_' + metric] = float(r[metric]) - value
            results.append(row)
    assert len(results) == 96
    metrics = ['coverage_pct','source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes',
               'sample_completion_pct','fixed_demand_packet_delivery_pct','actual_energy_j']
    groups = defaultdict(list)
    for row in results:
        groups[row['seed']].append(row)
    assert len(groups) == 12 and all(len(v) == 8 for v in groups.values())
    equal = []
    for metric in metrics:
        diffs = [statistics.mean(row['difference_'+metric] for row in groups[s]) for s in sorted(groups)]
        mean, low, high = ci(diffs)
        equal.append({'metric': metric, 'n_seeds': 12, 'difference_rc2_minus_padc': mean,
                      'nominal_ci95_low': low, 'nominal_ci95_high': high,
                      'positive_seeds': sum(v > 0 for v in diffs), 'negative_seeds': sum(v < 0 for v in diffs)})
    cells = []
    for condition, supply in sorted({(r['condition'], r['supply']) for r in results}):
        block = [r for r in results if r['condition']==condition and r['supply']==supply]
        assert len(block) == 12
        for metric in metrics:
            mean, low, high = ci([r['difference_'+metric] for r in block])
            cells.append({'condition': condition, 'supply': supply, 'metric': metric, 'n_seeds': 12,
                          'difference_rc2_minus_padc': mean, 'nominal_ci95_low': low, 'nominal_ci95_high': high})
    write_csv(out / 'paired_seed_records_96.csv', results)
    write_csv(out / 'equal_weight_effects.csv', equal)
    write_csv(out / 'condition_effects.csv', cells)
    manifest = {'status': 'PASS', 'pairs': 96, 'network_seeds': 12, 'weather_supply_cells': 8,
                'scope': 'Exploratory cross-stage contrast; PADC-AGE is an adapted local-age heuristic, not MAoIG. No new independent seeds and no simulations.',
                'verified_each_pair': ['old record/array/ledger SHA256', 'input and forecast signatures',
                                       'effective configuration', 'coverage, source P5, Jain and age from arrays',
                                       'node energy ledger and demand conservation'],
                'analysis_script_sha256': sha(HERE / 'audit_pair.py'),
                'old_protocol_sha256': sha(OLD / 'protocol.json'),
                'old_inventory_sha256': sha(OLD / 'execution_inventory.json'),
                'rc2_summary_sha256': sha(RC2 / 'results/confirmation_480.csv'),
                'outputs_sha256': {p.name: sha(p) for p in out.glob('*.csv')},
                'simulations_started': 0}
    write_json(out / 'audit.json', manifest)
    print(json.dumps({'status': manifest['status'], 'pairs': 96, 'effects': equal}, indent=2), flush=True)


if __name__ == '__main__':
    main()
