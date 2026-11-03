"""Stage B paired experiment. All outputs go to this study, never to frozen sources."""
from __future__ import annotations
import argparse, csv, hashlib, json, os, sys, traceback
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
PACKAGE = HERE / 'frozen_package'
sys.path.insert(0, str(PACKAGE / 'scripts'))
sys.path.insert(0, str(PACKAGE / 'code' / 'simulation'))
from current_io import build_scenario, load_config
from validation_model import StreamingBank
from jlc_r import JLCR
from rerun import construct, encode

FLOOR_OFF = {'NO-FLOOR', 'NO-FLOOR-NO-HOLD'}
HOLD_OFF = {'NO-HOLD', 'NO-FLOOR-NO-HOLD'}
class FactorVariant(JLCR):
    def __init__(self, c, sc, bank, method):
        self.stage_b_hold_off = method in HOLD_OFF
        super().__init__(c, sc, bank)
        self.keep_lock = not self.stage_b_hold_off
        if not self.reserve_enabled:
            raise AssertionError('Handshake/receiver admission must remain enabled')
    def attempt(self, i, j, packet):
        result = super().attempt(i, j, packet)
        if self.stage_b_hold_off:
            if self.holds or self.hold_slots or np.any(self.forward_holds) or np.any(self.forward_slot_holds):
                raise AssertionError('No-hold condition retained a persistent obligation')
        return result

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=encode), encoding='utf8')
def csvout(path, items):
    with path.open('w', encoding='utf8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(items[0]))
        w.writeheader()
        w.writerows(items)
def run_case(job):
    case, protocol, folder = job
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    dump(folder / 'case.json', case)
    try:
        condition = next(c for c in protocol['conditions'] if c['name'] == case['condition'])
        extra = {'no_reference_floor': True} if case['method'] in FLOOR_OFF else {}
        config = load_config(condition, extra=extra)
        sc = build_scenario(config, case['seed'], case['days'], case['supply'], condition)
        if case['method'] in ('JLC-R', *FLOOR_OFF, *HOLD_OFF):
            sim = FactorVariant(config, sc, StreamingBank(sc), case['method'])
            if bool(sim.c.get('no_reference_floor', False)) != (case['method'] in FLOOR_OFF):
                raise AssertionError('Floor switch mismatch')
            if sim.keep_lock != (case['method'] not in HOLD_OFF):
                raise AssertionError('Hold switch mismatch')
        else:
            sim = construct(case['method'], config, sc)
        dump(folder / 'effective_config.json', sim.c)
        latest = np.empty((sc.rounds, sim.n), dtype=np.int32)
        battery = np.empty((sc.rounds, sim.n), dtype=np.float64)
        for t in range(sc.rounds):
            sim.round()
            latest[t] = sim.latest
            battery[t] = sim.battery
        metrics = sim.metrics()
        np.savez_compressed(folder / 'arrays.npz', latest=latest, battery=battery,
                            sample_status=sim.sample_status)
        csvout(folder / 'node_ledgers.csv', sim.node_rows())
        cov = ((latest >= 0) & (np.arange(sc.rounds)[:, None] - latest + 1 <= 4)).mean(axis=0) * 100
        ages = np.where(latest >= 0, np.arange(sc.rounds)[:, None] - latest + 1,
                        np.arange(sc.rounds)[:, None] + 1)
        computed = {'coverage_pct': cov.mean(),
                    'source_coverage_p5_pct': np.quantile(cov, .05),
                    'source_coverage_jain': cov.sum()**2/(sim.n*(cov**2).sum()) if cov.any() else 0.,
                    'aoi_mean_minutes': ages.mean()*15}
        for key, value in computed.items():
            if abs(metrics[key] - value) >= 1e-8:
                raise AssertionError(f'metric mismatch: {key}')
        if not (np.isfinite(battery).all() and battery.min() >= -1e-12 and battery.max() <= config['battery_j']+1e-12):
            raise AssertionError('battery range')
        if metrics['max_node_energy_error_j'] > 1e-8 or metrics['max_energy_balance_error_j'] > 1e-6 or metrics['timing_misses'] != 0:
            raise AssertionError('energy or timing constraint')
        outcomes = metrics.get('outcomes', metrics)
        count = sum(outcomes.get(k,0) for k in ['delivered','expired','overflow','outstanding','unsensed','routing_drop'])
        if count != sc.rounds * config['nodes'] or np.count_nonzero(sim.sample_status) != sc.rounds * config['nodes']:
            raise AssertionError('fixed demand accounting')
        if case['method'] in HOLD_OFF:
            if metrics['held_packet_actions'] != 0 or metrics['held_slot_used'] != 0:
                raise AssertionError('hold actions unexpectedly observed')
            if metrics['grant_energy_j'] <= 0:
                raise AssertionError('paid handshakes unexpectedly absent')
        if case.get('reference_expected'):
            for key, expected in case['reference_expected'].items():
                if abs(float(metrics[key]) - float(expected)) > 1e-6:
                    raise AssertionError(f'locked reference mismatch: {key}: {metrics[key]} != {expected}')
            with np.load(case['reference_arrays']) as ref:
                for key, actual in [('latest', latest), ('battery', battery), ('sample_status', sim.sample_status)]:
                    if not np.array_equal(ref[key], actual):
                        raise AssertionError(f'locked reference array mismatch: {key}')
        dump(folder / 'record.json', {'case': case, 'metrics': metrics, 'rounds': sc.rounds,
                                      'run_kind': 'stageB_pilot' if case.get('pilot') else 'stageB_confirmation'})
        dump(folder / 'validation.json', {'status':'PASS', 'metrics_recomputed':list(computed),
                                          'battery_range_checked':True, 'energy_and_demand_checked':True,
                                          'paid_handshake_enabled':case['method'] in ('JLC-R', *FLOOR_OFF, *HOLD_OFF),
                                          'held_resource_absent_after_transactions':case['method'] in HOLD_OFF})
        return {'index':case['index'], 'status':'PASS', 'method':case['method'],
                'seed':case['seed'], 'condition':case['condition']}
    except BaseException as exc:
        dump(folder / 'failure.json', {'type':type(exc).__name__, 'message':str(exc),
                                        'traceback':traceback.format_exc()})
        raise

def submit(cases, protocol, out, workers):
    out.mkdir(parents=True, exist_ok=False)
    dump(out / 'run_plan.json', {'cases': len(cases), 'workers': workers,
                                  'protocol_sha256':sha(HERE/'protocol_predefined.json'),
                                  'runner_sha256':sha(Path(__file__)),
                                  'no_silent_failure_or_replacement':True})
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
            futures[pool.submit(run_case, (case, protocol, str(folder)))] = case
            return True
        for _ in range(workers): start()
        while futures:
            ready, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in ready:
                case = futures.pop(future)
                try:
                    result = future.result()
                    complete.append(result)
                    print(json.dumps({'completed':len(complete), 'total':len(cases), **result}), flush=True)
                except Exception as exc:
                    failure = {'case':case, 'exception':repr(exc)}
                    print(json.dumps({'FAILED':failure}), flush=True)
                if failure is None:
                    start()
        dump(out / 'completion.json', {'status':'FAIL' if failure else 'COMPLETE',
                                       'completed':complete, 'failure':failure,
                                       'planned_cases':len(cases)})
    return failure is None

def pilot_cases(protocol):
    conditions = [c for c in protocol['conditions'] if c['name']=='SYNTHETIC_G20']
    assert len(conditions)==1
    pilot = []
    for seed in protocol['pilot']['seeds']:
        for method in protocol['methods']:
            pilot.append({'index':len(pilot)+1,'seed':seed,'condition':'SYNTHETIC_G20',
                          'supply':1.0,'method':method,'days':2,'pilot':True})
    original = Path(r'D:\OneDrive\07_论文\算法最小复现包\JLC-R\results\confirmation_480.csv')
    with original.open(encoding='utf8', newline='') as f:
        reference = next(r for r in csv.DictReader(f) if r['method']=='JLC-R-RC2' and
                         r['condition']=='SYNTHETIC_G20' and float(r['supply'])==1.0)
    fields=['coverage_pct','source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes',
            'sample_completion_pct']
    expected = {k:float(reference[k]) for k in fields}
    expected.update(demand_delivery_pct=float(reference['fixed_demand_packet_delivery_pct']),
                    consumed_j=float(reference['actual_energy_j']))
    refarrays = r'D:\OneDrive\07_论文\JLC-R\temp\current_research\rc2_confirmation_lock_20261027_091500\execution_20261027_095300\runs\case_0000\arrays.npz'
    pilot.append({'index':len(pilot)+1,'seed':int(reference['seed']), 'condition':'SYNTHETIC_G20',
                  'supply':1.0,'method':'JLC-R','days':14,'pilot':True,
                  'reference_arrays':refarrays, 'reference_expected':expected})
    return pilot

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', choices=('pilot','confirmation'), required=True)
    ap.add_argument('--workers', type=int, default=4)
    args = ap.parse_args()
    protocol = json.loads((HERE/'protocol_predefined.json').read_text(encoding='utf8'))
    for rel, expected in protocol['frozen_source_sha256'].items():
        if sha(PACKAGE/rel) != expected:
            raise SystemExit(f'Frozen input altered: {rel}')
    if args.phase=='pilot':
        cases = pilot_cases(protocol)
        out = HERE/'pilot'
    else:
        lock = json.loads((HERE/'study_lock.json').read_text(encoding='utf8'))
        if lock['runner_sha256'] != sha(Path(__file__)) or lock['protocol_sha256'] != sha(HERE/'protocol_predefined.json'):
            raise SystemExit('Frozen runner or protocol differs from lock')
        if not (HERE/'pilot'/'completion.json').exists():
            raise SystemExit('Pilot must complete first')
        if json.loads((HERE/'pilot'/'completion.json').read_text(encoding='utf8'))['status']!='COMPLETE':
            raise SystemExit('Pilot failure; stop')
        cases = [dict(c, days=protocol['days']) for c in protocol['cases']]
        out = HERE/'confirmation'
    if not submit(cases, protocol, out, args.workers):
        raise SystemExit(1)
if __name__ == '__main__':
    main()
