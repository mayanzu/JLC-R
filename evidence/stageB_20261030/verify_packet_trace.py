"""Read-only check of archived observational trace counts, without simulation."""
from pathlib import Path
from collections import defaultdict
import argparse
import csv
import hashlib
import json
import math

H = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    with path.open(encoding='utf8', newline='') as stream:
        return list(csv.DictReader(stream))


def close(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=H)
    ap.add_argument('--record-root', type=Path)
    args = ap.parse_args()
    root = args.root.resolve()
    records = (args.record_root or root/'case_records').resolve()
    plan = json.loads((root/'packet_trace_protocol.json').read_text(encoding='utf8'))
    receipt = json.loads((root/'packet_trace_analysis/receipt.json').read_text(encoding='utf8'))
    assert receipt['status'] == 'PASS' and receipt['cases'] == len(plan['cases']) == 9
    for name, value in receipt['outputs'].items():
        assert sha(root/'packet_trace_analysis'/name) == value
    portable = json.loads((root/'packet_trace_analysis/portable_trace_counts.json').read_text(encoding='utf8'))
    cases = {int(r['index']): r for r in read(root/'packet_trace_analysis/case_counts.csv')}
    compact = {int(r['index']): r for r in read(root/'compact_evidence_complete/run_metrics.csv')
               if r['study'] == 'confirmation'}
    assert len(portable) == len(cases) == 9
    for item in portable:
        meta, trace = item['case'], item['trace']
        row = cases[int(meta['index'])]
        index = int(meta['reference_index'])
        folder = records/'confirmation'/f'case_{index:06d}'
        for filename in ('record.json', 'node_ledgers.csv'):
            assert sha(folder/filename) == item['reference_sha256'][filename]
        assert compact[index]['npz_sha256'] == item['reference_sha256']['arrays.npz']
        reference = json.loads((folder/'record.json').read_text(encoding='utf8'))
        for key in ('seed', 'condition', 'supply'):
            assert str(reference['case'][key]) == str(meta[key])
        for key in ('generated', 'expired', 'delivered'):
            assert int(reference['metrics'][key]) == int(item[key]) == int(row[key])
        def count(status, holder=None, held=None):
            return sum(e['packets'] for e in trace['terminal'] if e['status'] == status and
                       (holder is None or e['last_holder'] == holder) and
                       (held is None or e['hold_history'] == held))
        for field, val in [('expired_at_source', count('expired', 'source')),
                           ('expired_at_relay', count('expired', 'relay')),
                           ('delivered_ever_held', count('delivered', held='ever-held')),
                           ('expired_ever_held', count('expired', held='ever-held'))]:
            assert int(row[field]) == val
        assert count('expired') == int(row['expired']) and count('delivered') == int(row['delivered'])
        assert sum(e['packets'] for e in trace['expired_last_reason']) == int(row['expired'])
        assert item['unmodified_replay_record_sha256'] == row['replay_record_sha256']
    grouped = defaultdict(list)
    for row in cases.values():
        grouped[(row['condition'], float(row['supply']))].append(row)
    for row in read(root/'packet_trace_analysis/condition_summary.csv'):
        group = grouped[(row['condition'], float(row['supply']))]
        assert len(group) == int(row['network_seeds']) == 3
        expired = sum(int(r['expired']) for r in group)
        delivered = sum(int(r['delivered']) for r in group)
        assert expired == int(row['expired_packets_pooled'])
        assert delivered == int(row['delivered_packets_pooled'])
        assert close(100*sum(int(r['expired_at_source']) for r in group)/expired,
                     row['expired_source_pct_pooled'])
        assert close(100*sum(int(r['expired_at_relay']) for r in group)/expired,
                     row['expired_relay_pct_pooled'])
        assert close(100*sum(int(r['delivered_ever_held']) for r in group)/delivered,
                     row['delivered_ever_held_pct_pooled'])
    print(json.dumps({'status': 'PASS', 'cases': 9, 'simulations_started': 0,
                      'limitation': 'full replay arrays are external; equality was checked before export'}, indent=2))


if __name__ == '__main__':
    main()
