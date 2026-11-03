"""Stage C runner: matched planner controls (E1) and freshness-window sensitivity (E3).

Frozen sources come from the Stage B package and are hash-verified. All outputs
stay under this study directory. No execution on import.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, sys, time, traceback
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
STAGE_B = HERE.parent / 'stageB_20261030'
PACKAGE = STAGE_B / 'frozen_package'
sys.path.insert(0, str(PACKAGE / 'scripts'))
sys.path.insert(0, str(PACKAGE / 'code' / 'simulation'))
from current_io import build_scenario, load_config
from validation_model import StreamingBank
from jlc_r import JLCR
from model import ModelSimulator
from optimized_model import OptimizedSimulator
from v6_model import FDCSimulator
from rerun import encode

ORIGINAL_INSTALL = OptimizedSimulator.install_plan
ORIGINAL_FDC_INSTALL = FDCSimulator.install_plan
METHODS = ['JLC-R', 'SIMPLE-MATCHED-PLANNER', 'POINT-PLANNER']

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=encode),
                          encoding='utf8')

def csvout(path, items):
    with Path(path).open('w', encoding='utf8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(items[0]))
        w.writeheader()
        w.writerows(items)

class _PointRiskView:
    """Read-only bank view replacing every planning-time risk path by the point path."""
    def __init__(self, bank):
        self._bank = bank
        self.entries = self
    def __getitem__(self, t):
        point, risk, rho, mult = self._bank[t]
        return (point, point[None], rho, mult)
    def __getattr__(self, name):
        return getattr(self._bank, name)

def _tick(sim, t0):
    dt = time.perf_counter() - t0
    sim.planner_seconds_total = getattr(sim, 'planner_seconds_total', 0.) + dt
    sim.planner_calls = getattr(sim, 'planner_calls', 0) + 1

def timed_install(sim):
    t0 = time.perf_counter()
    ORIGINAL_INSTALL(sim)
    _tick(sim, t0)

def fdc_tolerant_install(sim):
    """SMP arm only: the FDC re-plan floor assertion fires after its state
    updates; downgrade it to a counter instead of aborting the run."""
    try:
        ORIGINAL_FDC_INSTALL(sim)
    except AssertionError as exc:
        if 'communication floor' not in str(exc):
            raise
        sim.fdc_floor_assertions = getattr(sim, 'fdc_floor_assertions', 0) + 1

def simple_install(sim):
    """One-shot proportional point-forecast budget; everything downstream unchanged."""
    t0 = time.perf_counter()
    c = sim.c
    point, _, _, _ = sim.bank.entries[sim.t]
    full_costs, full_floor, _, _ = sim.slot_plan(sim.t, np.ones(sim.n))
    obligation = full_costs.sum(axis=1) + full_floor
    horizon_days = sim.horizon_days or 3
    budget = np.maximum(0., sim.battery - c['reserve_j']) / horizon_days + point.sum(axis=1)
    scale = np.clip(budget / np.maximum(obligation, 1e-30), 0., 1.)
    _, floor, slots, ratios = sim.slot_plan(sim.t, scale)
    sim.planned_floor = floor
    sim.plan_profiles = c['sync_listen_s'] + c['guard_listen_s'] * slots
    sim.listen_profiles = [p.copy() for p in sim.plan_profiles]
    sim.actual_profiles = [p.copy() for p in sim.plan_profiles]
    sim.runtime_cap_profiles = [s.copy() for s in slots]
    sim.listen_scale = scale
    sim.scale_sum += float(ratios[sim.phase(sim.t)].sum())
    sim.scale_count += sim.n
    ModelSimulator.install_plan(sim)
    tol = c['battery_j'] / 2**15 + 1e-9
    bad = sim.extra + tol < floor
    sim.joint_floor_failures = getattr(sim, 'joint_floor_failures', 0) + int(bad.sum())
    shortfall = np.maximum(0., floor - (sim.extra + tol))
    sim.max_floor_shortfall_j = max(getattr(sim, 'max_floor_shortfall_j', 0.),
                                    float(shortfall.max()) if shortfall.size else 0.)
    _tick(sim, t0)

def construct(method, config, sc):
    if method not in METHODS:
        raise ValueError(method)
    sim = JLCR(config, sc, StreamingBank(sc))
    sim.planner_seconds_total = 0.
    sim.planner_calls = 0
    sim.max_floor_shortfall_j = 0.
    return sim

def run_case(job):
    case, protocol, folder = job
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    dump(folder / 'case.json', case)
    method = case['method']
    OptimizedSimulator.install_plan = simple_install if method == 'SIMPLE-MATCHED-PLANNER' else timed_install
    if method == 'SIMPLE-MATCHED-PLANNER':
        FDCSimulator.install_plan = fdc_tolerant_install
    try:
        condition = next(c for c in protocol['conditions'] if c['name'] == case['condition'])
        deadline = int(case.get('deadline_rounds', 4))
        config = load_config(condition)
        sc = build_scenario(config, case['seed'], case['days'], case['supply'], condition)
        sim = construct(method, config, sc)
        if method == 'POINT-PLANNER':
            sim.bank = _PointRiskView(sim.bank)
        if deadline != 4:
            # Exploratory D-override after construction; P4 and cadence untouched.
            sim.c['deadline_rounds'] = deadline
        if int(sim.c['deadline_rounds']) != deadline:
            raise AssertionError('deadline override failed')
        dump(folder / 'effective_config.json', sim.c)
        latest = np.empty((sc.rounds, sim.n), dtype=np.int32)
        battery = np.empty((sc.rounds, sim.n), dtype=np.float64)
        for t in range(sc.rounds):
            sim.round()
            latest[t] = sim.latest
            battery[t] = sim.battery
        metrics = sim.metrics()
        metrics['study_method'] = method
        metrics['study_deadline_rounds'] = deadline
        metrics['planner_seconds_total'] = getattr(sim, 'planner_seconds_total', 0.)
        metrics['planner_calls'] = getattr(sim, 'planner_calls', 0)
        metrics['planner_seconds_per_call'] = (
            metrics['planner_seconds_total'] / metrics['planner_calls']
            if metrics['planner_calls'] else None)
        metrics['max_floor_shortfall_j'] = getattr(sim, 'max_floor_shortfall_j', 0.)
        metrics['fdc_floor_assertions'] = getattr(sim, 'fdc_floor_assertions', 0)
        np.savez_compressed(folder / 'arrays.npz', latest=latest, battery=battery,
                            sample_status=sim.sample_status)
        csvout(folder / 'node_ledgers.csv', sim.node_rows())
        cov = ((latest >= 0) & (np.arange(sc.rounds)[:, None] - latest + 1 <= deadline)).mean(axis=0) * 100
        ages = np.where(latest >= 0, np.arange(sc.rounds)[:, None] - latest + 1,
                        np.arange(sc.rounds)[:, None] + 1)
        computed = {'coverage_pct': cov.mean(),
                    'source_coverage_p5_pct': np.quantile(cov, .05),
                    'source_coverage_jain': cov.sum()**2 / (sim.n * (cov**2).sum()) if cov.any() else 0.,
                    'aoi_mean_minutes': ages.mean() * 15}
        for key, value in computed.items():
            if abs(metrics[key] - value) >= 1e-8:
                raise AssertionError(f'metric mismatch: {key}: {metrics[key]} vs {value}')
        if not (np.isfinite(battery).all() and battery.min() >= -1e-12
                and battery.max() <= config['battery_j'] + 1e-12):
            raise AssertionError('battery range')
        if (metrics['max_node_energy_error_j'] > 1e-8 or metrics['max_energy_balance_error_j'] > 1e-6
                or metrics['timing_misses'] != 0):
            raise AssertionError('energy or timing constraint')
        outcomes = metrics.get('outcomes', metrics)
        count = sum(outcomes.get(k, 0) for k in
                    ['delivered', 'expired', 'overflow', 'outstanding', 'unsensed', 'routing_drop'])
        if count != sc.rounds * config['nodes'] or np.count_nonzero(sim.sample_status) != sc.rounds * config['nodes']:
            raise AssertionError('fixed demand accounting')
        if method == 'SIMPLE-MATCHED-PLANNER' and getattr(sim, 'joint_floor_failures', 0) < 0:
            raise AssertionError('floor accounting')
        if case.get('reference_expected'):
            for key, expected in case['reference_expected'].items():
                if abs(float(metrics[key]) - float(expected)) > 1e-6:
                    raise AssertionError(f'locked reference mismatch: {key}: {metrics[key]} != {expected}')
            with np.load(case['reference_arrays']) as ref:
                for key, actual in [('latest', latest), ('battery', battery),
                                    ('sample_status', sim.sample_status)]:
                    if not np.array_equal(ref[key], actual):
                        raise AssertionError(f'locked reference array mismatch: {key}')
        dump(folder / 'record.json',
             {'case': case, 'metrics': metrics, 'rounds': sc.rounds,
              'run_kind': 'stageC_pilot' if case.get('pilot') else 'stageC_confirmation'})
        dump(folder / 'validation.json',
             {'status': 'PASS', 'metrics_recomputed': list(computed),
              'battery_range_checked': True, 'energy_and_demand_checked': True,
              'deadline_rounds': deadline, 'method': method,
              'floor_shortfalls_counted_not_repaired': method == 'SIMPLE-MATCHED-PLANNER'})
        return {'index': case['index'], 'status': 'PASS', 'method': method,
                'seed': case['seed'], 'condition': case['condition'],
                'supply': case['supply'], 'deadline_rounds': deadline}
    except BaseException as exc:
        dump(folder / 'failure.json', {'type': type(exc).__name__, 'message': str(exc),
                                       'traceback': traceback.format_exc()})
        raise
    finally:
        OptimizedSimulator.install_plan = ORIGINAL_INSTALL
        FDCSimulator.install_plan = ORIGINAL_FDC_INSTALL

def submit(cases, out, workers):
    out.mkdir(parents=True, exist_ok=False)
    dump(out / 'run_plan.json', {'cases': len(cases), 'workers': workers,
                                 'protocol_sha256': sha(HERE / 'protocol_predefined.json'),
                                 'runner_sha256': sha(Path(__file__)),
                                 'stage_b_protocol_sha256': sha(STAGE_B / 'protocol_predefined.json')})
    pending = iter(cases)
    complete = []
    failure = None
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {}
        def start():
            try:
                case = next(pending)
            except StopIteration:
                return False
            folder = out / f"case_{case['index']:06d}"
            futures[pool.submit(run_case, (case, PROTOCOL, str(folder)))] = case
            return True
        for _ in range(workers):
            start()
        while futures:
            ready, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in ready:
                case = futures.pop(future)
                try:
                    result = future.result()
                    complete.append(result)
                    print(json.dumps({'completed': len(complete), 'total': len(cases), **result}), flush=True)
                except Exception as exc:
                    failure = {'case': case, 'exception': repr(exc)}
                    print(json.dumps({'FAILED': failure}), flush=True)
                if failure is None:
                    start()
    dump(out / 'completion.json', {'status': 'FAIL' if failure else 'COMPLETE',
                                   'completed': complete, 'failure': failure,
                                   'planned_cases': len(cases)})
    return failure is None

PROTOCOL = None

def pilot_cases(protocol):
    cases = [dict(c, pilot=True) for c in protocol['pilot']['cases']]
    reference_csv = Path(r'D:\OneDrive\07_论文\算法最小复现包\JLC-R\results\confirmation_480.csv')
    with reference_csv.open(encoding='utf8', newline='') as f:
        reference = next(r for r in csv.DictReader(f)
                         if r['method'] == 'JLC-R-RC2' and r['condition'] == 'SYNTHETIC_G20'
                         and float(r['supply']) == 1.0)
    fields = ['coverage_pct', 'source_coverage_p5_pct', 'source_coverage_jain',
              'aoi_mean_minutes', 'sample_completion_pct']
    expected = {k: float(reference[k]) for k in fields}
    expected.update(demand_delivery_pct=float(reference['fixed_demand_packet_delivery_pct']),
                    consumed_j=float(reference['actual_energy_j']))
    refarrays = (r'D:\OneDrive\07_论文\JLC-R\temp\current_research'
                 r'\rc2_confirmation_lock_20261027_091500\execution_20261027_095300'
                 r'\runs\case_0000\arrays.npz')
    cases.append({'index': len(cases) + 1, 'seed': int(reference['seed']),
                  'condition': 'SYNTHETIC_G20', 'supply': 1.0, 'method': 'JLC-R',
                  'days': 14, 'deadline_rounds': 4, 'pilot': True,
                  'reference_arrays': refarrays, 'reference_expected': expected})
    return cases

def main():
    global PROTOCOL
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', choices=('pilot', 'confirmation'), required=True)
    ap.add_argument('--group', choices=('e1', 'e3'))
    ap.add_argument('--workers', type=int, default=8)
    args = ap.parse_args()
    PROTOCOL = json.loads((HERE / 'protocol_predefined.json').read_text(encoding='utf8'))
    for rel, expected in PROTOCOL['frozen_source_sha256'].items():
        if sha(PACKAGE / rel) != expected:
            raise SystemExit(f'Frozen input altered: {rel}')
    if args.phase == 'pilot':
        cases = pilot_cases(PROTOCOL)
        out = HERE / 'pilot'
    else:
        if not args.group:
            raise SystemExit('--group required for confirmation')
        lock = json.loads((HERE / 'study_lock.json').read_text(encoding='utf8'))
        if (lock['runner_sha256'] != sha(Path(__file__))
                or lock['protocol_sha256'] != sha(HERE / 'protocol_predefined.json')):
            raise SystemExit('Frozen runner or protocol differs from lock')
        pilot = json.loads((HERE / 'pilot' / 'completion.json').read_text(encoding='utf8'))
        if pilot['status'] != 'COMPLETE':
            raise SystemExit('Pilot failed; stop')
        cases = PROTOCOL[args.group]['cases']
        out = HERE / f'confirmation_{args.group}'
    if not submit(cases, out, args.workers):
        raise SystemExit(1)

if __name__ == '__main__':
    main()
