"""Source-aware admission and matched controls over the packet-funded core.

Only receiver-local queues and successful-hop histories enter decisions.
Existing packet holds are never revoked or spent by another packet.
"""
from collections import Counter

import numpy as np

from packet_funded import PacketFundedJLCR


class SourceProtectedJLCR(PacketFundedJLCR):
    def __init__(self, *args, source_protection='admission', **kwargs):
        if source_protection not in ('off', 'priority', 'admission', 'joint', 'headroom'):
            raise ValueError('Unknown source protection mode')
        self.source_protection = source_protection
        self.protection_counts = Counter()
        super().__init__(*args, **kwargs)
        self.protected_attempt_round = np.full(self.n, -1, dtype=int)

    def _protected_packet(self, node):
        if self.protected_attempt_round[node] == self.t:
            return None
        cutoff = self.t - self.c['deadline_rounds'] + 1
        held_sources = {p.source for p in self.queues[node]
                        if self.holds.get(p.sequence, (-1, 0))[0] == node}
        eligible = [p for p in self.queues[node]
                    if not p.finalized and p.birth >= cutoff and p.source not in held_sources
                    and (self.source_protection == 'headroom'
                         or self.local_forwarded_birth[node, p.source] < cutoff)
                    and (p.last_try_round != self.t
                         or p.round_tries < self.c['max_link_attempts'])]
        if not eligible:
            return None
        if self.source_protection == 'headroom':
            return max(eligible, key=lambda p: (p.birth, -p.source, -p.sequence))
        return max(eligible, key=lambda p: (-self.local_forwarded_birth[node, p.source],
                                           p.birth, -p.source, -p.sequence))

    def _protected_cost(self, node):
        choices = self.neighbors.get(node, []) if node in self.ch else [int(self.parent[node])]
        costs = [self.tx_energy(node, int(peer))
                 + (self.control_cost(node, int(peer))[0] if peer < self.n else 0.)
                 for peer in choices]
        return max(costs) if costs else float('inf')

    def _guard_exchange(self, sender, receiver, packet):
        if self.source_protection not in ('admission', 'joint', 'headroom'):
            return super()._guard_exchange(sender, receiver, packet)
        waiting = self._protected_packet(receiver)
        if waiting is None or waiting.source == packet.source:
            return super()._guard_exchange(sender, receiver, packet)
        reserve = self._protected_cost(receiver)
        if not np.isfinite(reserve):
            return super()._guard_exchange(sender, receiver, packet)
        si, rj = self.control_cost(sender, receiver)
        rx = self.c['packet_bits'] * (self.c['elec_j_per_bit'] + self.c['aggregate_j_per_bit'])
        nxt = int(self.reference_next[self.phase(self.t)][receiver])
        forward = self.tx_energy(receiver, nxt)
        if nxt < self.n:
            forward += self.control_cost(receiver, nxt)[0]
        free_slots = self.slots_left[receiver] - self.forward_slot_holds[receiver]
        # A rejected request pays only the sender fee. Receiver response fees
        # cannot drain the protected opportunity through repeated denials.
        if self.available(receiver) < rj + rx + forward + reserve or free_slots < 3:
            fresh = self.last_message[receiver] == self.t
            if fresh and (self.cached_off[receiver] or self.cached_quota[receiver] < rx):
                self.block(packet, sender, receiver, 'known_receiver_unavailable')
                return False, 0.
            if self.available(sender, packet) < self.tx_energy(sender, receiver) + si:
                self.block(packet, sender, receiver, 'sender_credit')
                return False, 0.
            self.use_slot(sender, packet)
            self.fee_control(sender, si, packet)
            self.denied += 1
            self.protection_counts['paid_source_opportunity_denials'] += 1
            self.block(packet, sender, receiver, 'source_opportunity')
            return False, 0.
        result = super()._guard_exchange(sender, receiver, packet)
        if result[0]:
            self.protection_counts['admissions_preserving_source_opportunity'] += 1
        return result

    def choose_packet(self, node):
        if self.source_protection not in ('priority', 'joint'):
            return super().choose_packet(node)
        packet = self._protected_packet(node)
        if (packet is None or self.slots_left[node] - self.forward_slot_holds[node] < 1
                or self.available(node) < self._protected_cost(node)):
            return super().choose_packet(node)
        queue = self.queues[node]
        index = next(i for i, queued in enumerate(queue) if queued.sequence == packet.sequence)
        queue.rotate(-index)
        selected = queue.popleft()
        queue.rotate(index)
        queue.appendleft(selected)
        return selected

    def attempt(self, sender, receiver, packet):
        if self.source_protection not in ('priority', 'joint'):
            return super().attempt(sender, receiver, packet)
        waiting = self._protected_packet(sender)
        protected = waiting is not None and waiting.sequence == packet.sequence
        if protected and self.source_protection in ('priority', 'joint'):
            self.protected_attempt_round[sender] = self.t
            self.protection_counts['protected_attempts'] += 1
        result = super().attempt(sender, receiver, packet)
        if protected and self.source_protection in ('priority', 'joint') and result[0]:
            self.protection_counts['protected_successful_hops'] += 1
        return result

    def metrics(self):
        row = super().metrics()
        row.update(source_protection=self.source_protection,
                   source_protection_counts=dict(self.protection_counts),
                   source_protection_scope='Local source-opportunity admission; no end-to-end service guarantee')
        return row
