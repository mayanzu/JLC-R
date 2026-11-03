"""Exact conditional freshness ceiling from saved RC2 comparison trajectories.

This is retrospective analysis, not a network simulation or a deployable policy.
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

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
STUDY = PROJECT / 'code/experiments/rc2_confirmation'
ARCHIVE = STUDY / 'raw/rc2_formal_raw.zip'
RECORDS = STUDY / 'results/confirmation_480.csv'
INPUTS = [ARCHIVE, RECORDS, PROJECT / 'code/simulation/diagnostic.py',
          PROJECT / 'code/simulation/cadence.py', PROJECT / 'code/simulation/eadcm_host.py',
          PROJECT / 'code/simulation/lantern_host.py', Path(__file__).resolve()]
THRESHOLD = 4


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def dump(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')


def read_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def write_rows(path, rows):
    assert rows
    with path.open('w', encoding='utf8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def freeze():
    path = HERE / 'protocol.json'
    if path.exists():
        raise FileExistsError(path)
    protocol = {
        'study': 'Conditional observed-sampling, instantaneous-delivery freshness ceiling',
        'scope': 'Descriptive retrospective decomposition of existing 480 formal trajectories. No simulation, new seeds, parameter changes, hypothesis tests or causal treatment effects.',
        'sample_status': {'delivered': 1, 'expired': 2, 'overflow': 3, 'outstanding': 4,
                          'unsensed': 5, 'routing_drop': 6},
        'threshold_rounds': THRESHOLD,
        'initial_condition': 'No prior sensed or delivered sample before round zero.',
        'oracle': 'For each observed sensing trajectory, every sensed sample is delivered instantaneously with no extra energy, link, queue, capacity, or contention constraints. It is not an implementable or energy-matched policy.',
        'components': ['actual fresh source-rounds', 'observed-sample-fresh but not delivered-fresh source-rounds',
                       'source-rounds without a sample within the freshness window'],
        'aggregation': 'Each run is one network-seed/condition/method record; equal-condition summaries average eight cells within each seed, then average 12 seeds.',
        'source_sha256': {str(p.relative_to(PROJECT).as_posix()): sha(p) for p in INPUTS},
    }
    dump(path, protocol)
    print(json.dumps({'status': 'FROZEN', 'protocol_sha256': sha(path)}, indent=2))


def verify_protocol():
    protocol = json.loads((HERE / 'protocol.json').read_text(encoding='utf8'))
    for rel, expected in protocol['source_sha256'].items():
        assert sha(PROJECT / rel) == expected, rel


def summarize_one(latest, status):
    rounds, nodes = latest.shape
    assert status.shape == (rounds * nodes,)
    assert np.isin(status, np.arange(1, 7)).all()
    t = np.arange(rounds)[:, None]
    sensed = status.reshape(rounds, nodes) != 5
    ideal_birth = np.maximum.accumulate(np.where(sensed, t, -1), axis=0)
    assert ((latest >= -1) & (latest <= t)).all()
    assert (latest <= ideal_birth).all(), 'A delivery cannot predate its observed sample'
    source_idx = np.broadcast_to(np.arange(nodes), latest.shape)
    observed_delivery = latest >= 0
    sequence = latest[observed_delivery] * nodes + source_idx[observed_delivery]
    assert (status[sequence] == 1).all(), 'Every delivered birth must have delivered terminal status'
    actual_fresh = observed_delivery & ((t - latest + 1) <= THRESHOLD)
    ideal_fresh = (ideal_birth >= 0) & ((t - ideal_birth + 1) <= THRESHOLD)
    assert not (actual_fresh & ~ideal_fresh).any()
    actual_source = 100 * actual_fresh.mean(axis=0)
    ideal_source = 100 * ideal_fresh.mean(axis=0)
    assert (actual_source <= ideal_source + 1e-12).all()
    actual_age = np.where(observed_delivery, t - latest + 1, t + 1)
    ideal_age = np.where(ideal_birth >= 0, t - ideal_birth + 1, t + 1)
    assert (ideal_age <= actual_age).all()
    return {
        'coverage_pct': 100 * float(actual_fresh.mean()),
        'conditional_ceiling_pct': 100 * float(ideal_fresh.mean()),
        'delivery_freshness_deficit_pct': 100 * float((ideal_fresh & ~actual_fresh).mean()),
        'no_fresh_sample_pct': 100 * float((~ideal_fresh).mean()),
        'source_p5_pct': float(np.quantile(actual_source, 0.05)),
        'source_p5_ceiling_pct': float(np.quantile(ideal_source, 0.05)),
        'aoi_mean_minutes': 15 * float(actual_age.mean()),
        'conditional_aoi_floor_minutes': 15 * float(ideal_age.mean()),
        'sample_completion_pct': 100 * float(sensed.mean()),
    }


def run():
    verify_protocol()
    out = HERE / 'results'
    out.mkdir(exist_ok=False)
    cases = read_rows(RECORDS)
    assert len(cases) == 480
    records = []
    with zipfile.ZipFile(ARCHIVE) as archive:
        for case in cases:
            branch = 'new' if case['origin'] == 'new_execution' else 'reused'
            name = f"{branch}/case_{int(case['case_index']):04d}/arrays.npz"
            content = archive.read(name)
            with np.load(io.BytesIO(content)) as data:
                latest, status = data['latest'], data['sample_status']
            assert latest.shape == (1344, 100)
            v = summarize_one(latest, status)
            for old, new in [('coverage_pct', 'coverage_pct'), ('source_coverage_p5_pct', 'source_p5_pct'),
                             ('aoi_mean_minutes', 'aoi_mean_minutes'), ('sample_completion_pct', 'sample_completion_pct')]:
                assert abs(float(case[old]) - v[new]) < 1e-8, (name, old, case[old], v[new])
            assert abs(v['coverage_pct'] + v['delivery_freshness_deficit_pct'] + v['no_fresh_sample_pct'] - 100) < 1e-10
            records.append({**{key: case[key] for key in ('case_index', 'method', 'condition', 'supply', 'seed', 'origin')},
                            'arrays_sha256': hashlib.sha256(content).hexdigest(), **v})
    write_rows(out / 'seed_decomposition_480.csv', records)
    fields = list(v)
    cells = defaultdict(list)
    per_seed = defaultdict(list)
    for row in records:
        cells[(row['method'], row['condition'], row['supply'])].append(row)
        per_seed[(row['method'], row['seed'])].append(row)
    assert len(cells) == 40 and len(per_seed) == 60
    cell_rows = []
    for (method, condition, supply), rr in sorted(cells.items()):
        assert len(rr) == 12
        cell_rows.append({'method': method, 'condition': condition, 'supply': supply, 'n_seeds': len(rr),
                          **{key: statistics.mean(r[key] for r in rr) for key in fields}})
    write_rows(out / 'condition_means_40.csv', cell_rows)
    seed_rows = []
    for (method, seed), rr in sorted(per_seed.items()):
        assert len(rr) == 8
        seed_rows.append({'method': method, 'seed': seed, 'condition_count': len(rr),
                          **{key: statistics.mean(r[key] for r in rr) for key in fields}})
    write_rows(out / 'equal_condition_seed_means_60.csv', seed_rows)
    methods = sorted({r['method'] for r in seed_rows})
    totals = []
    for method in methods:
        rr = [r for r in seed_rows if r['method'] == method]
        assert len(rr) == 12
        totals.append({'method': method, 'n_network_seeds': len(rr),
                       **{key: statistics.mean(r[key] for r in rr) for key in fields}})
    write_rows(out / 'equal_condition_means_5.csv', totals)
    dump(out / 'analysis_receipt.json', {
        'status': 'PASS', 'logical_cases': len(records), 'conditions_by_method': len(cells),
        'equal_condition_seed_rows': len(seed_rows), 'source_round_checks': 480 * 1344 * 100,
        'protocol_sha256': sha(HERE / 'protocol.json'), 'simulations_started': 0,
        'interpretation': 'Exact descriptive relaxation conditional on each method\'s realized sensing, not an achievable performance bound at common energy or a causal decomposition.'})
    print(json.dumps({'status': 'PASS', 'cases': len(records), 'output': str(out), 'simulations_started': 0}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=['freeze', 'run'])
    args = parser.parse_args()
    freeze() if args.mode == 'freeze' else run()
