"""Replay nine frozen outcomes with observational packet counters only."""
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import hashlib
import json
import sys

H = Path(__file__).resolve().parent
sys.path.insert(0, str(H))
import run_stage_b as base


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PacketTrace(base.JLCR):
    def __init__(self, *args):
        self.trace_holder = {}
        self.trace_ever_held = set()
        self.trace_terminal = Counter()
        self.trace_expired_reason = Counter()
        self.trace_blocks = defaultdict(lambda: [0, 0., 0., 0.])
        super().__init__(*args)

    def block(self, packet, i, j, reason):
        # Values describe the local sender at an event; events are not independent packets.
        role = 'source' if i == packet.source else 'relay'
        bucket = self.trace_blocks[(role, str(reason))]
        bucket[0] += 1
        bucket[1] += float(self.battery[i])
        bucket[2] += float(self.quota[i])
        bucket[3] += float(self.slots_left[i])
        return super().block(packet, i, j, reason)

    def attempt(self, i, j, packet):
        result = super().attempt(i, j, packet)
        if result[0] and j < self.n and not packet.finalized:
            self.trace_holder[packet.sequence] = int(j)
            if packet.sequence in self.holds:
                self.trace_ever_held.add(packet.sequence)
        return result

    def finalize(self, packet, status):
        holder = self.trace_holder.pop(packet.sequence, int(packet.source))
        role = 'source' if holder == packet.source else 'relay'
        held = packet.sequence in self.trace_ever_held
        self.trace_ever_held.discard(packet.sequence)
        self.trace_terminal[(status, role, 'ever-held' if held else 'no-observed-hold')] += 1
        if status == 'expired':
            self.trace_expired_reason[(role, str(packet.last_reason))] += 1
        return super().finalize(packet, status)

    def metrics(self):
        m = super().metrics()
        terminal = [{'status': k[0], 'last_holder': k[1], 'hold_history': k[2], 'packets': v}
                    for k, v in sorted(self.trace_terminal.items())]
        reasons = [{'last_holder': k[0], 'last_reason': k[1], 'packets': v}
                   for k, v in sorted(self.trace_expired_reason.items())]
        blocks = [{'sender_role': k[0], 'reason': k[1], 'events': int(v[0]),
                   'sender_battery_sum_j': v[1], 'sender_quota_sum_j': v[2], 'sender_guard_sum': v[3]}
                  for k, v in sorted(self.trace_blocks.items())]
        assert sum(row['packets'] for row in terminal if row['status'] == 'expired') == m['expired']
        assert sum(row['packets'] for row in terminal if row['status'] == 'delivered') == m['delivered']
        assert sum(row['packets'] for row in reasons) == m['expired']
        m['observational_trace'] = {'terminal': terminal, 'expired_last_reason': reasons, 'block_events': blocks}
        return m


def construct(method, config, scenario):
    if method != 'TRACE-DIAG':
        raise ValueError(method)
    return PacketTrace(config, scenario, base.StreamingBank(scenario))


def worker(job):
    case, protocol, folder = job
    case = dict(case)
    ref = H / 'confirmation' / f"case_{case['reference_index']:06d}"
    for name, expected in case['reference_sha256'].items():
        assert sha(ref / name) == expected, (case['index'], name)
    original = json.loads((ref / 'record.json').read_text(encoding='utf8'))['metrics']
    case['reference_arrays'] = str(ref / 'arrays.npz')
    case['reference_expected'] = {k: original[k] for k in
                                  ('coverage_pct', 'source_coverage_p5_pct', 'demand_delivery_pct', 'consumed_j')}
    base.construct = construct
    result = base.run_case((case, protocol, folder))
    if sha(Path(folder) / 'node_ledgers.csv') != case['reference_sha256']['node_ledgers.csv']:
        raise AssertionError('Instrumentation altered a node ledger')
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=2)
    args = ap.parse_args()
    plan = json.loads((H / 'packet_trace_protocol.json').read_text(encoding='utf8'))
    lock = json.loads((H / 'packet_trace_lock.json').read_text(encoding='utf8'))
    assert lock['protocol_sha256'] == sha(H / 'packet_trace_protocol.json')
    assert lock['runner_sha256'] == sha(Path(__file__))
    assert lock['base_runner_sha256'] == sha(H / 'run_stage_b.py')
    parent = json.loads((H / 'protocol_predefined.json').read_text(encoding='utf8'))
    assert plan['parent_protocol_sha256'] == sha(H / 'protocol_predefined.json')
    for rel, expected in parent['frozen_source_sha256'].items():
        assert sha(base.PACKAGE / rel) == expected, rel
    # base.submit calls base.run_case directly, so use the same disciplined
    # bounded executor but with the observational worker.
    from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
    out = H / 'packet_trace_replays'
    out.mkdir(exist_ok=False)
    base.dump(out / 'run_plan.json', {'cases': len(plan['cases']), 'workers': args.workers,
                                      'protocol_sha256': sha(H / 'packet_trace_protocol.json'),
                                      'runner_sha256': sha(Path(__file__)),
                                      'not_independent_outcomes': True})
    pending = iter(plan['cases']); done = []; failure = None
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        def launch():
            try:
                case = next(pending)
            except StopIteration:
                return
            target = out / f"case_{case['index']:06d}"
            futures[pool.submit(worker, (case, parent, str(target)))] = case
        for _ in range(args.workers):
            launch()
        while futures:
            ready, _ = wait(futures, return_when=FIRST_COMPLETED)
            for fut in ready:
                case = futures.pop(fut)
                try:
                    result = fut.result(); done.append(result)
                    print(json.dumps({'completed': len(done), 'total': len(plan['cases']), **result}), flush=True)
                except Exception as exc:
                    failure = {'case': case, 'exception': repr(exc)}
                    print(json.dumps({'FAILED': failure}), flush=True)
                if failure is None:
                    launch()
    base.dump(out / 'completion.json', {'status': 'FAIL' if failure else 'COMPLETE',
                                        'completed': done, 'planned_cases': len(plan['cases']),
                                        'failure': failure})
    if failure:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
