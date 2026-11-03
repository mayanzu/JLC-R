"""Independently audit a completed nine-case observational replay; no new simulation."""
from collections import defaultdict
from pathlib import Path
import csv
import hashlib
import json

import numpy as np

H = Path(__file__).resolve().parent
OUT = H / 'packet_trace_analysis'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, rows):
    with path.open('w', encoding='utf8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def main():
    if OUT.exists():
        raise SystemExit('Refusing to overwrite a completed trace analysis')
    plan = json.loads((H / 'packet_trace_protocol.json').read_text(encoding='utf8'))
    lock = json.loads((H / 'packet_trace_lock.json').read_text(encoding='utf8'))
    assert lock['protocol_sha256'] == sha(H / 'packet_trace_protocol.json')
    assert lock['runner_sha256'] == sha(H / 'run_packet_trace.py')
    done = json.loads((H / 'packet_trace_replays/completion.json').read_text(encoding='utf8'))
    assert done['status'] == 'COMPLETE' and done['planned_cases'] == len(plan['cases']) == 9
    assert {c['index'] for c in done['completed']} == {c['index'] for c in plan['cases']}
    rows = []
    clean = []
    for c in plan['cases']:
        replay = H / 'packet_trace_replays' / f"case_{c['index']:06d}"
        original = H / 'confirmation' / f"case_{c['reference_index']:06d}"
        for name, expected in c['reference_sha256'].items():
            assert sha(original / name) == expected, (c['index'], name)
        assert sha(replay / 'node_ledgers.csv') == sha(original / 'node_ledgers.csv')
        assert json.loads((replay/'validation.json').read_text(encoding='utf8'))['status'] == 'PASS'
        with np.load(replay/'arrays.npz') as a, np.load(original/'arrays.npz') as b:
            for name in ('latest', 'battery', 'sample_status'):
                assert np.array_equal(a[name], b[name]), (c['index'], name)
        r = json.loads((replay/'record.json').read_text(encoding='utf8'))
        ref = json.loads((original/'record.json').read_text(encoding='utf8'))
        m, original_m = r['metrics'], ref['metrics']
        for field in ('coverage_pct', 'source_coverage_p5_pct', 'demand_delivery_pct', 'consumed_j',
                      'generated', 'expired', 'delivered'):
            assert float(m[field]) == float(original_m[field]), (c['index'], field)
        trace = m['observational_trace']
        terminal = trace['terminal']
        def count(status, holder=None, held=None):
            return sum(t['packets'] for t in terminal if t['status'] == status and
                       (holder is None or t['last_holder'] == holder) and
                       (held is None or t['hold_history'] == held))
        assert count('expired') == m['expired'] and count('delivered') == m['delivered']
        assert sum(q['packets'] for q in trace['expired_last_reason']) == m['expired']
        row = {'index': c['index'], 'seed': c['seed'], 'condition': c['condition'], 'supply': c['supply'],
               'reference_index': c['reference_index'], 'generated': m['generated'], 'expired': m['expired'],
               'expired_at_source': count('expired', 'source'), 'expired_at_relay': count('expired', 'relay'),
               'delivered': m['delivered'], 'delivered_ever_held': count('delivered', held='ever-held'),
               'expired_ever_held': count('expired', held='ever-held'),
               'reference_array_sha256': c['reference_sha256']['arrays.npz'],
               'replay_array_sha256': sha(replay/'arrays.npz'), 'replay_record_sha256': sha(replay/'record.json')}
        assert row['expired_at_source'] + row['expired_at_relay'] == row['expired']
        rows.append(row)
        clean.append({'case': {k: c[k] for k in ('index', 'seed', 'condition', 'supply', 'reference_index')},
                      'reference_sha256': c['reference_sha256'], 'trace': trace,
                      'generated': m['generated'], 'expired': m['expired'], 'delivered': m['delivered'],
                      'unmodified_replay_record_sha256': row['replay_record_sha256']})
    groups = defaultdict(list)
    for r in rows:
        groups[(r['condition'], float(r['supply']))].append(r)
    summary = []
    for (condition, supply), group in sorted(groups.items()):
        assert len(group) == 3
        source = sum(r['expired_at_source'] for r in group)
        relay = sum(r['expired_at_relay'] for r in group)
        expired = source + relay
        delivered = sum(r['delivered'] for r in group)
        summary.append({'condition': condition, 'supply': supply, 'network_seeds': len(group),
                        'expired_packets_pooled': expired, 'expired_source_pct_pooled': 100*source/expired,
                        'expired_relay_pct_pooled': 100*relay/expired,
                        'delivered_packets_pooled': delivered,
                        'delivered_ever_held_pct_pooled': 100*sum(r['delivered_ever_held'] for r in group)/delivered})
    OUT.mkdir()
    write(OUT/'case_counts.csv', rows)
    write(OUT/'condition_summary.csv', summary)
    (OUT/'portable_trace_counts.json').write_text(json.dumps(clean, indent=2) + '\n', encoding='utf8')
    receipt = {'status': 'PASS', 'cases': len(rows), 'seeds_per_cell': 3,
               'validation': 'latest, battery and sample-status arrays exactly matched; node-ledger bytes identical',
               'sampling': 'same first three parent seeds crossed with three selected winter cells',
               'interpretation': 'post hoc diagnostic replays of existing cases; terminal holder and hold history are observational, not causal',
               'limitations': 'Only nine cases; no downstream-aware intervention; raw arrays retained outside supplement.',
               'analysis_sha256': sha(Path(__file__)),
               'outputs': {p.name: sha(p) for p in OUT.iterdir()}}
    (OUT/'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
