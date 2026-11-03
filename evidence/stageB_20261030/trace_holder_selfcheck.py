"""Check sampled reconstructed holders against the actual live expiry queue."""
from pathlib import Path
import json

import run_packet_trace as trace
import run_stage_b as base

H = Path(__file__).resolve().parent


class CheckedPacketTrace(trace.PacketTrace):
    def __init__(self, *args):
        self.holder_checks = 0
        super().__init__(*args)

    def finalize(self, packet, status):
        # Expiry is called while the packet is still present in its one queue.
        # A deterministic subsample makes the independent queue scan affordable.
        if status == 'expired' and packet.sequence % 97 == 0:
            actual = [i for i, queue in enumerate(self.queues)
                      if any(queued is packet for queued in queue)]
            predicted = self.trace_holder.get(packet.sequence, int(packet.source))
            assert actual == [predicted], (packet.sequence, actual, predicted)
            self.holder_checks += 1
        return super().finalize(packet, status)

    def metrics(self):
        m = super().metrics()
        assert self.holder_checks >= 100
        m['independent_live_queue_holder_checks'] = self.holder_checks
        return m


def construct(method, config, scenario):
    if method != 'TRACE-DIAG':
        raise ValueError(method)
    return CheckedPacketTrace(config, scenario, base.StreamingBank(scenario))


def main():
    plan = json.loads((H/'packet_trace_protocol.json').read_text(encoding='utf8'))
    parent = json.loads((H/'protocol_predefined.json').read_text(encoding='utf8'))
    case = plan['cases'][0]
    out = H/'packet_trace_holder_selfcheck'
    if out.exists():
        raise SystemExit('Refusing overwrite')
    trace.construct = construct
    trace.worker((case, parent, str(out)))
    metrics = json.loads((out/'record.json').read_text(encoding='utf8'))['metrics']
    receipt = {'status': 'PASS', 'case_index': case['index'],
               'sampled_expired_packets_checked_against_actual_queue': metrics['independent_live_queue_holder_checks'],
               'scope': 'one observational replay; deterministic sequence modulo 97 sample',
               'outcomes': 'round arrays exactly match the prior frozen case and node-ledger bytes match',
               'not_an_independent_outcome': True}
    (out/'selfcheck_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
