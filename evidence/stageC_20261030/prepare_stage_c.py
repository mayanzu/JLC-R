"""Pre-register the Stage C protocol before any confirmation run."""
from pathlib import Path
import datetime, hashlib, json

HERE = Path(__file__).resolve().parent
STAGE_B = HERE.parent / 'stageB_20261030'

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    parent = json.loads((STAGE_B / 'protocol_predefined.json').read_text(encoding='utf8'))
    seeds = parent['seeds']
    conditions = parent['conditions']
    supplies = parent['supplies']
    assert len(seeds) == 24 and sorted(supplies) == [0.7, 1.0]
    cells = [(c['name'], s) for c in conditions for s in supplies]
    methods_e1 = ['JLC-R', 'SIMPLE-MATCHED-PLANNER', 'POINT-PLANNER']
    cases = []
    def add(method, condition, supply, seed, days, deadline=4):
        cases.append({'index': len(cases) + 1, 'seed': seed, 'condition': condition,
                      'supply': supply, 'method': method, 'days': days,
                      'deadline_rounds': deadline})
    e1 = []
    for seed in seeds:
        for condition, supply in cells:
            for method in methods_e1:
                add(method, condition, supply, seed, 14)
                e1.append(cases[-1])
    e3 = []
    for seed in seeds:
        for condition in [c['name'] for c in conditions]:
            for deadline in (2, 8):
                for method in ('JLC-R', 'SIMPLE-MATCHED-PLANNER'):
                    add(method, condition, 1.0, seed, 14, deadline=deadline)
                    e3.append(cases[-1])
    protocol = {
        'study': 'Stage C: matched planner controls (review E1) and freshness-window sensitivity (review E3)',
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'parent_protocol_sha256': sha(STAGE_B / 'protocol_predefined.json'),
        'frozen_source_sha256': parent['frozen_source_sha256'],
        'pairing_source': '../stageB_20261030/compact_evidence_complete/run_metrics.csv',
        'days': 14,
        'seeds': seeds,
        'conditions': conditions,
        'supplies': supplies,
        'method_definitions': {
            'JLC-R': 'frozen RC2 controller unchanged; fresh replication arm serving as reproduction check and planner-timing baseline',
            'SIMPLE-MATCHED-PLANNER': 'stage-1 budget replaced by a one-shot proportional rule on the point forecast: scale_i=clip(((battery_i-reserve)/horizon_days+point_day_i)/(full_slot_obligation_i),0,1); no bisection, no scenario stress; slot quantisation, credit-floor formula, stage-2 prefix-credit solver, cadence, queue, holds, Guard and recovery unchanged; floor shortfalls counted not repaired, and for this arm only the FDC re-plan floor assertion (which fires after its state updates) is downgraded to a counter',
            'POINT-PLANNER': 'identical to JLC-R except every planning-time scenario risk path is replaced by the point path (bank view proxy); isolates scenario robustness',
        },
        'e1': {'methods': methods_e1, 'cells': cells, 'days': 14,
               'n_cases': len(e1), 'cases': e1},
        'e3': {'deadline_rounds': [2, 8], 'methods': ['JLC-R', 'SIMPLE-MATCHED-PLANNER'],
               'weather_cells': [c['name'] for c in conditions], 'supply': 1.0,
               'override': 'sim.c[deadline_rounds] set after construction; period_rounds and cadence untouched',
               'n_cases': len(e3), 'cases': e3},
        'planned_statistics': [
            'reproduction check: stage C JLC-R vs stage B JLC-R per (seed,cell) metric equality',
            'paired deltas SMP/PP minus JLC-R on coverage_pct, source_coverage_p5_pct, demand_delivery_pct, sample_completion_pct, consumed_j',
            'equal-condition means (unweighted mean of the 8 cell means) and per-cell means',
            'seed-level paired t intervals (nominal, descriptive) and the same deltas against NO-JOINT-PADC from stage B',
            'planner wall time per call and per run by arm',
            'floor shortfall counts under SIMPLE-MATCHED-PLANNER',
            'E3: coverage and Source P5 by D in {2,4,8} x method x weather cell at supply 1.0 (D=4 from stage B and stage C e1)',
        ],
        'pilot': {
            'seeds': [60503, 60705],
            'excluded_from_confirmation': True,
            'cases': [
                {'index': 1, 'seed': 60503, 'condition': 'SYNTHETIC_G20', 'supply': 1.0,
                 'method': 'JLC-R', 'days': 2, 'deadline_rounds': 4, 'pilot': True},
                {'index': 2, 'seed': 60503, 'condition': 'SYNTHETIC_G20', 'supply': 1.0,
                 'method': 'SIMPLE-MATCHED-PLANNER', 'days': 2, 'deadline_rounds': 4, 'pilot': True},
                {'index': 3, 'seed': 60503, 'condition': 'SYNTHETIC_G20', 'supply': 1.0,
                 'method': 'POINT-PLANNER', 'days': 2, 'deadline_rounds': 4, 'pilot': True},
                {'index': 4, 'seed': 60705, 'condition': 'SYNTHETIC_G20', 'supply': 1.0,
                 'method': 'JLC-R', 'days': 2, 'deadline_rounds': 2, 'pilot': True},
                {'index': 5, 'seed': 60705, 'condition': 'SYNTHETIC_G20', 'supply': 0.7,
                 'method': 'SIMPLE-MATCHED-PLANNER', 'days': 2, 'deadline_rounds': 8, 'pilot': True},
                {'index': 6, 'seed': 60503, 'condition': 'SYNTHETIC_G20', 'supply': 1.0,
                 'method': 'SIMPLE-MATCHED-PLANNER', 'days': 14, 'deadline_rounds': 4, 'pilot': True},
            ],
            'locked_reference_case': 'added at run time from 算法最小复现包 confirmation_480.csv (14-day JLC-R, exact array comparison)',
            'intent': 'exercise switches, the D-override path and timing probes; not select methods or seeds',
        },
        'failure_rule': 'any failed case stops the confirmation phase and is retained as failure.json; no silent replacement',
        'exploratory_status': 'Stage B evaluation seeds are reused for paired descriptive comparisons; not a blind hold-out; intervals nominal',
    }
    (HERE / 'protocol_predefined.json').write_text(
        json.dumps(protocol, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'cases_e1': len(e1), 'cases_e3': len(e3),
                      'protocol_sha256': sha(HERE / 'protocol_predefined.json')}, indent=2))

if __name__ == '__main__':
    main()
