"""Isolated RC2-component factorial adapter and deterministic execution.

This script only writes below this study directory and never edits the locked
controller, its V63 parent, original records, configuration, or weather data.
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import csv
import hashlib
import io
import itertools
import json
import os
import sys
import time
import traceback
import zipfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
SIM = PROJECT / 'code' / 'simulation'
FORMAL = PROJECT / 'code/experiments/rc2_confirmation'
sys.path.insert(0, str(SIM))

from cadence import ReserveCadenceCandidate
from current_io import load_config, build_scenario
from validation_model import StreamingBank


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def clean(value):
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write_json(path, data):
    path.write_text(json.dumps(clean(data), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


class FactorialController(ReserveCadenceCandidate):
    """Only the three additions are switched; V63 relay repair stays on."""

    def __init__(self, c, sc, bank, activity, guard, recovery):
        super().__init__(c, sc, bank,
                         horizon_days=3 if activity else None,
                         trigger_mode='reference' if guard else 'none',
                         v63_mechanism='relay_repair')
        if not recovery:
            # Both the route gate and the PF2 callback are disabled; the
            # original resource, cache and local packet selectors are retained.
            self.dev_variant = 'off'
            self.pf_enabled = False


def freeze():
    target = HERE / 'protocol.json'
    if target.exists():
        raise FileExistsError('The protocol is already frozen')
    original = read(FORMAL / 'configs/formal_protocol_original.json')
    identity = read(PROJECT / 'code/CURRENT_ALGORITHM.json')
    files = {str(p.relative_to(PROJECT).as_posix()): sha(p)
             for p in sorted(SIM.glob('*.py'))}
    paths = [SIM / 'config.json', FORMAL / 'configs/formal_protocol_original.json',
             FORMAL / 'results/confirmation_480.csv', FORMAL / 'raw/rc2_formal_raw.zip',
             PROJECT / 'code/CURRENT_ALGORITHM.json']
    paths += [PROJECT / x['weather_file'] for x in original['conditions'] if x.get('weather_file')]
    for path in paths:
        files[path.relative_to(PROJECT).as_posix()] = sha(path)
    for rel, digest in {**identity['kernel_module_sha256'], **identity['new_implementation_sha256']}.items():
        if sha(PROJECT / rel) != digest:
            raise RuntimeError(f'Locked source changed: {rel}')
    protocol = {
        'study': 'RC2 additions: activity cadence, demand guard, bounded recovery',
        'status': 'analysis design frozen before component executions; exploratory with previously used network seeds',
        'factors': {
            'A': {'off': 'horizon_days=None', 'on': 'horizon_days=3'},
            'G': {'off': 'trigger_mode=none', 'on': 'trigger_mode=reference'},
            'R': {'off': 'PF2 recovery route and callback disabled', 'on': 'PF2 recovery enabled'},
        },
        'retained_in_every_group': 'Frozen RelayRepairHYB and relay_repair mechanism, all physical parameters, demand and causal information',
        'conditions': original['conditions'], 'supplies': original['supplies'],
        'seeds': original['seeds'], 'days': original['days'],
        'logical_factorial_records': 8 * len(original['conditions']) * len(original['supplies']) * len(original['seeds']),
        'endpoint_reuse': 'Only after full-trajectory and terminal-status equality tests in all eight condition/supply cells; original results retain their identity.',
        'primary_endpoints': ['coverage_pct', 'source_coverage_p5_pct'],
        'primary_estimands': ['A', 'G', 'R', 'AG', 'AR', 'GR', 'AGR'],
        'inference': 'Within each network seed average the eight fixed condition/supply cells; paired t df=11, two-sided nominal 95% CI, Holm correction across 14 factor-by-endpoint tests. Previously used seeds: exploratory, not a fresh blind confirmation.',
        'secondary': ['111 minus 100 at the same activity rule', 'sample completion', 'fixed-demand delivery', 'energy', 'Jain', 'AoI', 'longest unfresh gap'],
        'seed_exclusions': 'None; stop inferential analysis if any case fails or is missing.',
        'randomness': 'Original keyed randomness; same environmental inputs, different control decisions may consume different link keys.',
        'frozen_files_sha256': files,
        'adapter_sha256': sha(HERE / 'factorial.py'),
    }
    write_json(target, protocol)
    print(json.dumps({'protocol': str(target), 'sha256': sha(target), 'records': protocol['logical_factorial_records']}), flush=True)


def verify_freeze(protocol):
    if sha(HERE / 'factorial.py') != protocol['adapter_sha256']:
        raise RuntimeError('Adapter source changed after protocol lock')
    for rel, expected in protocol['frozen_files_sha256'].items():
        if sha(PROJECT / rel) != expected:
            raise RuntimeError(f'Frozen dependency changed: {rel}')


def case_name(condition, supply, seed, bits):
    return f"{condition}_s{str(supply).replace('.', 'p')}_{seed}_{bits}"


def longest_gap(latest):
    nrounds, n = latest.shape
    current = np.zeros(n, dtype=np.int64)
    longest = np.zeros(n, dtype=np.int64)
    for t in range(nrounds):
        fresh = (latest[t] >= 0) & ((t - latest[t] + 1) <= 4)
        current = np.where(fresh, 0, current + 1)
        longest = np.maximum(longest, current)
    return float(np.quantile(longest, 0.95) * .25), float((longest > 16).mean() * 100)


def raw_reference(condition, supply, seed, bits):
    method = {'000': 'Pre-recovery-JLC-R', '111': 'JLC-R-RC2'}[bits]
    with (FORMAL / 'results/confirmation_480.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = [r for r in csv.DictReader(f) if r['method'] == method and r['condition'] == condition
                and float(r['supply']) == supply and int(r['seed']) == seed]
    if len(rows) != 1:
        raise RuntimeError('Expected one frozen endpoint record')
    original = rows[0]
    branch = 'new' if original['origin'] == 'new_execution' else 'reused'
    name = f"{branch}/case_{int(original['case_index']):04d}/arrays.npz"
    with zipfile.ZipFile(FORMAL / 'raw/rc2_formal_raw.zip') as z:
        archive = np.load(io.BytesIO(z.read(name)))
        arrays = {key: archive[key] for key in ('latest', 'battery', 'sample_status')}
    return original, arrays, name


def run_one(task):
    protocol = read(HERE / 'protocol.json')
    condition = next(c for c in protocol['conditions'] if c['name'] == task['condition'])
    bits = task['bits']
    out = HERE / task['output'] / case_name(task['condition'], task['supply'], task['seed'], bits)
    out.mkdir(parents=True, exist_ok=False)
    started = time.time()
    try:
        c = load_config(condition)
        sc = build_scenario(c, task['seed'], protocol['days'], task['supply'], condition)
        sim = FactorialController(c, sc, StreamingBank(sc), *(v == '1' for v in bits))
        latest, battery = [], []
        for _ in range(sc.rounds):
            sim.round()
            latest.append(sim.latest.copy())
            battery.append(sim.battery.copy())
        metrics = sim.metrics()  # Finalizes outstanding sample states.
        latest = np.asarray(latest)
        battery = np.asarray(battery)
        status = np.asarray(sim.sample_status)
        time_index = np.arange(sc.rounds)[:, None]
        coverage = ((latest >= 0) & (time_index - latest + 1 <= 4)).mean(axis=0) * 100
        age = np.where(latest >= 0, time_index - latest + 1, time_index + 1)
        recomputed = {
            'coverage_pct': float(coverage.mean()),
            'source_coverage_p5_pct': float(np.quantile(coverage, .05)),
            'source_coverage_jain': float(coverage.sum() ** 2 / (100 * (coverage ** 2).sum())) if coverage.any() else 0.,
            'aoi_mean_minutes': float(age.mean() * 15),
        }
        for key, value in recomputed.items():
            if abs(float(metrics[key]) - value) > 1e-8:
                raise AssertionError(f'Independent metric mismatch: {key}')
        if not (np.isfinite(battery).all() and battery.min() >= -1e-12 and battery.max() <= c['battery_j'] + 1e-12):
            raise AssertionError('Battery out of bounds')
        if metrics['max_node_energy_error_j'] > 1e-8 or metrics['max_energy_balance_error_j'] > 1e-6:
            raise AssertionError('Energy accounting mismatch')
        if metrics['timing_misses'] or metrics['max_hold_violation_j'] > 1e-8 or metrics['max_slot_violation'] > 1e-8:
            raise AssertionError('Timing or reservation violation')
        if np.count_nonzero(status) != sc.rounds * 100:
            raise AssertionError('Unfinalized sample state')
        total = sum(int(metrics.get(k, 0)) for k in ('delivered', 'expired', 'overflow', 'outstanding', 'unsensed', 'routing_drop'))
        if total != sc.rounds * 100:
            raise AssertionError(f'Demand conservation mismatch: {total}')
        gap_p95, gap_over4 = longest_gap(latest)
        # The published comparison defines actual energy as the sum of the
        # per-node base/data/control ledgers, not the simulator's separately
        # accumulated global consumed_j counter. The two agree to roundoff.
        actual_energy = sum(row[k] for row in sim.node_rows() for k in ('base_j', 'data_j', 'control_j'))
        outcome = dict(**recomputed, sample_completion_pct=float(metrics['sample_completion_pct']),
                       fixed_demand_packet_delivery_pct=100 * int(metrics['delivered']) / (sc.rounds * 100),
                       actual_energy_j=float(actual_energy), longest_unfresh_p95_h=gap_p95,
                       sources_gap_over4h_pct=gap_over4)
        record = {'task': task, 'outcomes': outcome, 'metrics': metrics,
                  'protocol_sha256': sha(HERE / 'protocol.json'),
                  'runtime_seconds': time.time() - started}
        if task['endpoint_reference']:
            original, arrays, name = raw_reference(task['condition'], task['supply'], task['seed'], bits)
            comparisons = {'latest': bool(np.array_equal(latest, arrays['latest'])),
                           'battery': bool(np.array_equal(battery, arrays['battery'])),
                           'sample_status': bool(np.array_equal(status, arrays['sample_status']))}
            for key, value in outcome.items():
                if key in original and original[key] != '':
                    comparisons[key] = bool(abs(float(original[key]) - value) <= 1e-8)
            record['endpoint_reference'] = {'source': name, 'comparisons': comparisons}
            if not all(comparisons.values()):
                raise AssertionError(f'Endpoint mismatch: {comparisons}')
        np.savez_compressed(out / 'arrays.npz', latest=latest, battery=battery, sample_status=status)
        write_json(out / 'record.json', record)
        write_json(out / 'validation.json', {'status': 'PASS', 'demand': total,
                                            'metrics_recomputed': list(recomputed),
                                            'endpoint_comparison': record.get('endpoint_reference')})
        return {'case': out.name, 'seconds': round(time.time() - started, 2), 'status': 'PASS'}
    except BaseException as exc:
        write_json(out / 'failure.json', {'task': task, 'exception': repr(exc), 'traceback': traceback.format_exc()})
        raise


def tasks(mode, protocol):
    bits = ('000', '111') if mode == 'endpoints' else tuple(f'{i:03b}' for i in range(1, 7))
    seeds = protocol['seeds'][:1] if mode == 'endpoints' else protocol['seeds']
    for condition, supply, seed, factor in itertools.product(protocol['conditions'], protocol['supplies'], seeds, bits):
        yield {'condition': condition['name'], 'supply': supply, 'seed': seed, 'bits': factor,
               'output': mode, 'endpoint_reference': mode == 'endpoints'}


def execute(mode, workers):
    protocol = read(HERE / 'protocol.json')
    verify_freeze(protocol)
    target = HERE / mode
    target.mkdir(exist_ok=False)
    jobs = list(tasks(mode, protocol))
    print(json.dumps({'event': 'start', 'mode': mode, 'cases': len(jobs), 'workers': workers}), flush=True)
    complete, failures = [], []
    with futures.ProcessPoolExecutor(max_workers=workers) as executor:
        active = {executor.submit(run_one, job): job for job in jobs}
        for result in futures.as_completed(active):
            job = active[result]
            try:
                complete.append(result.result())
            except BaseException as exc:
                failures.append({'task': job, 'error': repr(exc)})
                print(json.dumps({'event': 'failure', 'done': len(complete), 'failures': failures[-1]}), flush=True)
            if len(complete) % 12 == 0 and len(complete):
                print(json.dumps({'event': 'progress', 'done': len(complete), 'failures': len(failures), 'total': len(jobs)}), flush=True)
    verify_freeze(protocol)
    summary = {'status': 'PASS' if len(complete) == len(jobs) and not failures else 'FAIL',
               'planned': len(jobs), 'completed': len(complete), 'failures': failures,
               'protocol_sha256': sha(HERE / 'protocol.json'), 'results': complete}
    write_json(target / 'summary.json', summary)
    print(json.dumps({'event': 'finish', 'mode': mode, 'status': summary['status'],
                      'completed': len(complete), 'failures': len(failures)}), flush=True)
    if failures:
        raise SystemExit(1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['freeze', 'endpoints', 'intermediates'])
    p.add_argument('--workers', type=int, default=4)
    a = p.parse_args()
    if a.mode == 'freeze':
        freeze()
    else:
        if not 1 <= a.workers <= 8:
            p.error('workers must be between 1 and 8')
        execute(a.mode, a.workers)


if __name__ == '__main__':
    main()
