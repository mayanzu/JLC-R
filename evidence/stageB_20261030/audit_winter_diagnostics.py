"""Post hoc, record-based winter diagnostic; never runs or changes simulations.

Compare the frozen controller and the q=8 candidate over their paired 24 seeds
and three winter cells.  Event counters are opportunities/actions, not unique
packets or causal attributions.  All intervals are descriptive and unadjusted.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open('w', encoding='utf8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    stage, out = args.stage.resolve(), args.output.resolve()
    if out.exists():
        raise SystemExit('Refusing to overwrite existing diagnostic')
    # A local research workspace stores runs directly under stage; the
    # submission archive places the same records under case_records/.
    record_root = stage if (stage / 'confirmation').exists() else stage / 'case_records'
    parent = json.loads((stage / 'protocol_predefined.json').read_text(encoding='utf8'))
    proposal = json.loads((stage / 'q8_protocol.json').read_text(encoding='utf8'))
    assert proposal['parent_protocol_sha256'] == digest(stage / 'protocol_predefined.json')
    for path in (record_root / 'confirmation/completion.json',
                 record_root / 'q8_confirmation/completion.json',
                 stage / 'analysis_complete/receipt.json', stage / 'q8_analysis_complete/receipt.json'):
        status = json.loads(path.read_text(encoding='utf8'))['status']
        assert status in ('COMPLETE', 'PASS'), (str(path), status)
    seeds = parent['seeds']
    cells = [(name, float(scale)) for name, scale in proposal['conditions']]
    assert len(set(seeds)) == 24 and len(set(cells)) == 3
    choices = {
        'JLC-R': ('confirmation', [dict(c, days=parent['days']) for c in parent['cases']
                                   if c['method'] == 'JLC-R']),
        'q8': ('q8_confirmation', proposal['cases']),
    }
    records: dict[tuple, dict] = {}
    for label, (folder, cases) in choices.items():
        for case in cases:
            cell = case['condition'], float(case['supply'])
            if cell not in cells:
                continue
            key = label, cell[0], cell[1], int(case['seed'])
            assert key not in records and case['seed'] in seeds
            path = record_root / folder / f"case_{case['index']:06d}"
            assert json.loads((path / 'validation.json').read_text(encoding='utf8'))['status'] == 'PASS'
            record = json.loads((path / 'record.json').read_text(encoding='utf8'))
            assert all(record['case'][k] == case[k] for k in
                       ('index', 'seed', 'condition', 'supply', 'method', 'days'))
            m = record['metrics']
            demand = int(record['rounds']) * int(m['nodes'])
            assert sum(int(m[k]) for k in ('delivered', 'expired', 'overflow', 'outstanding', 'unsensed')) == demand
            assert int(m['generated']) == demand - int(m['unsensed'])
            assert int(m['generated']) > 0
            records[key] = {
                'unsensed_demand_pct': 100.0 * m['unsensed'] / demand,
                'expired_generated_pct': 100.0 * m['expired'] / m['generated'],
                'delivered_demand_pct': 100.0 * m['delivered'] / demand,
                'queue_p95_packets': float(m['queue_p95']),
                'queue_p99_packets': float(m['queue_p99']),
                'listen_capacity_events': int(m['slot_capacity_events']),
                'forward_reserve_events': int(m['reserve_events']),
                'nonlink_stops': int(m['stopped_nonlink']),
                'control_j': float(m['control_j']),
                'communication_j': float(m['comm_consumed_j']),
                'total_consumed_j': float(m['consumed_j']),
            }
    assert len(records) == 2 * len(cells) * len(seeds)
    per_run = []
    for (method, condition, supply, seed), values in sorted(records.items()):
        per_run.append({'method': method, 'condition': condition, 'supply': supply,
                        'seed': seed, **values})
    result = []
    fields = list(next(iter(records.values())))
    selections = [('equal_three_cells', cells)] + [(f'{c}/{s}', [(c, s)]) for c, s in cells]
    for group, selected in selections:
        for field in fields:
            left = np.array([np.mean([records[('JLC-R', c, s, seed)][field]
                                      for c, s in selected]) for seed in seeds])
            right = np.array([np.mean([records[('q8', c, s, seed)][field]
                                       for c, s in selected]) for seed in seeds])
            d = right - left
            half = student_t.ppf(.975, len(seeds) - 1) * d.std(ddof=1) / math.sqrt(len(seeds))
            result.append({'group': group, 'field': field, 'n_seeds': len(seeds),
                           'jlcr_mean': float(left.mean()), 'q8_mean': float(right.mean()),
                           'q8_minus_jlcr': float(d.mean()),
                           'nominal_ci95_low': float(d.mean()-half),
                           'nominal_ci95_high': float(d.mean()+half)})
    out.mkdir(parents=True)
    write_csv(out / 'paired_run_metrics.csv', per_run)
    write_csv(out / 'winter_diagnostic.csv', result)
    receipt = {
        'status': 'PASS', 'network_seeds': len(seeds), 'conditions': cells,
        'records_per_method': len(cells) * len(seeds),
        'classification': 'post hoc descriptive diagnostic; no multiplicity-adjusted decision',
        'caveats': [
            'Expiry includes packets at sources and relays and is not a localized congestion measure.',
            'Event counts can involve the same packet repeatedly and are not unique packet failures.',
            'Listen-capacity, forward-reserve and nonlink-stop counters have different definitions; do not sum them.',
            'These aggregates do not identify downstream causality, time-varying capacity or the path of an individual packet.',
            'q=8 uses the existing control mechanism; control_j is all model-accounted control energy, not new message overhead.',
            'Intervals are nominal paired-t intervals, not adjusted for the many exploratory endpoints.',
        ],
        'parent_protocol_sha256': digest(stage / 'protocol_predefined.json'),
        'q8_protocol_sha256': digest(stage / 'q8_protocol.json'),
        'script_sha256': digest(Path(__file__)),
        'outputs': {p.name: digest(p) for p in sorted(out.iterdir())},
    }
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
