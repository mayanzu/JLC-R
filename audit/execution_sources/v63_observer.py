"""Read-only hop-fate attribution observer for V6.3 Stage A.

Instruments HYB60 (HYBSimulator) and PADC-AGE (DiagnosticPADCAge) without
altering any RNG draw, control decision, packet queue order, or energy ledger.
"""
from __future__ import annotations

from collections import Counter
import numpy as np

from v6_model import HYBSimulator
from v4_diagnostics import DiagnosticPADCAge

CATEGORIES = ("S", "L", "C", "Q", "P", "O")


class HopFateMixin:
    """Zero-side-effect observer recording far-source relay hop losses by category."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.far_source = (
            np.hypot(
                self.sc.pos[:, 0] - self.sc.sink[0],
                self.sc.pos[:, 1] - self.sc.sink[1],
            )
            >= 200.0
        )
        self.fate_counts: Counter[str] = Counter({k: 0 for k in CATEGORIES})
        self.source_fate_counts: dict[int, Counter[str]] = {
            int(s): Counter({k: 0 for k in CATEGORIES}) for s in range(self.n)
        }
        self.terminal_fates: Counter[str] = Counter()
        self.member_rx_used = np.zeros(self.n, dtype=int)
        self.member_energy_used = np.zeros(self.n, dtype=float)
        self._holder_of: dict[int, int] = {}
        self._entry_round: dict[int, int] = {}
        self._attempted_at_holder: set[tuple[int, int]] = set()
        self._holder_activity: Counter[tuple[int, int]] = Counter()
        self._chset: set[int] = set()

    def _record_relay_loss(self, source: int, cat: str) -> None:
        cat_key = cat if cat in CATEGORIES else "O"
        self.fate_counts[cat_key] += 1
        self.source_fate_counts[int(source)][cat_key] += 1

    def round(self):
        self.member_rx_used[:] = 0
        self.member_energy_used[:] = 0.0
        return super().round()

    def route(self, i, chset):
        self._chset = set(chset)
        for p in self.queues[i]:
            if self._holder_of.get(p.sequence) != i:
                self._holder_of[p.sequence] = int(i)
                self._entry_round[p.sequence] = int(self.t)
        return super().route(i, chset)

    def request_grant(self, i, j, packet):
        c = self.c
        etx = self.tx_energy(i, j)
        erx = c["packet_bits"] * (c["elec_j_per_bit"] + c["aggregate_j_per_bit"])
        si, rj = self.control_cost(i, j)
        nxt = int(self.reference_next[self.phase(self.t)][j])
        forward = self.tx_energy(j, nxt)
        if nxt < self.n:
            forward += self.control_cost(j, nxt)[0]

        hold_i = (
            self.holds.get(packet.sequence, (-1, 0.0))[1]
            if self.holds.get(packet.sequence, (-1, 0.0))[0] == i
            else 0.0
        )
        pre_free_i = self.battery[i] - c["reserve_j"] - (self.forward_holds[i] - hold_i)
        pre_avail_j = self.available(j)
        pre_free_j = self.battery[j] - c["reserve_j"] - self.forward_holds[j]
        pre_slots_j = int(self.slots_left[j] - self.forward_slot_holds[j])
        pre_mem_slots_j = int(self.member_rx_used[j])
        pre_mem_e_j = float(self.member_energy_used[j])

        ok, fwd = super().request_grant(i, j, packet)
        if not ok and i != packet.source and self.far_source[packet.source]:
            reason = packet.last_reason
            cat = "O"
            if reason == "sender_credit":
                if pre_free_i >= etx + si and self.quota[i] < pre_free_i:
                    cat = "Q"
                else:
                    cat = "S"
            elif reason in ("grant_denied", "forward_reserve", "known_receiver_unavailable"):
                need_j = (
                    rj
                    if reason == "grant_denied"
                    else (rj + erx + forward if reason != "known_receiver_unavailable" else erx)
                )
                need_slots = (
                    1 if reason == "grant_denied" else (2 if reason == "forward_reserve" else 0)
                )
                if not self.off[j] and (
                    (pre_slots_j < need_slots and pre_slots_j + pre_mem_slots_j >= need_slots)
                    or (pre_avail_j < need_j and pre_avail_j + pre_mem_e_j >= need_j)
                ):
                    cat = "C"
                elif not self.off[j] and pre_free_j >= need_j and self.quota[j] < pre_free_j:
                    cat = "Q"
                elif self.off[j]:
                    cat = "S"
            self._record_relay_loss(packet.source, cat)
        return ok, fwd

    def attempt(self, i, j, packet):
        if i != packet.source:
            self._attempted_at_holder.add((packet.sequence, int(i)))
        self._holder_activity[(int(i), int(self.t))] += 1

        c = self.c
        etx = self.tx_energy(i, j)
        hold_i = (
            self.holds.get(packet.sequence, (-1, 0.0))[1]
            if self.holds.get(packet.sequence, (-1, 0.0))[0] == i
            else 0.0
        )
        pre_free_i = self.battery[i] - c["reserve_j"] - (self.forward_holds[i] - hold_i)
        pre_slots_i = int(
            self.slots_left[i] - self.forward_slot_holds[i] + int(packet.sequence in self.hold_slots)
        )

        ok, why = super().attempt(i, j, packet)
        if ok and j < self.n and i not in self._chset:
            erx = c["packet_bits"] * (c["elec_j_per_bit"] + c["aggregate_j_per_bit"])
            _, rj = self.control_cost(i, j)
            nxt = int(self.reference_next[self.phase(self.t)][j])
            fwd = self.tx_energy(j, nxt) + (self.control_cost(j, nxt)[0] if nxt < self.n else 0.0)
            self.member_rx_used[j] += 2
            self.member_energy_used[j] += rj + erx + fwd
        elif ok and j < self.n:
            self._holder_of[packet.sequence] = int(j)
            self._entry_round[packet.sequence] = int(self.t)
        elif not ok and i != packet.source and self.far_source[packet.source]:
            if why == "grant_denied":
                pass
            elif why == "sender_credit":
                cat = "Q" if (pre_free_i >= etx and self.quota[i] < pre_free_i) else "S"
                self._record_relay_loss(packet.source, cat)
            elif why == "sender_energy":
                self._record_relay_loss(packet.source, "S")
            elif why == "listen_capacity":
                cat = "C" if (pre_slots_i <= 0 and self.member_rx_used[i] > 0) else "O"
                self._record_relay_loss(packet.source, cat)
            elif why == "link_loss" and packet.round_tries >= c["max_link_attempts"]:
                self._record_relay_loss(packet.source, "L")
            elif why != "link_loss":
                self._record_relay_loss(packet.source, "O")
        return ok, why

    def finalize(self, packet, status):
        holder = self._holder_of.get(packet.sequence, int(packet.source))
        if status == "delivered":
            self.terminal_fates["DELIVERED"] += 1
        elif status == "expired":
            if holder == packet.source:
                self.terminal_fates["EXPIRED_AT_SOURCE"] += 1
            else:
                self.terminal_fates["EXPIRED_AT_RELAY"] += 1
                if self.far_source[packet.source] and (packet.sequence, holder) not in self._attempted_at_holder:
                    t0 = self._entry_round.get(packet.sequence, int(packet.birth))
                    other = sum(self._holder_activity[(holder, tt)] for tt in range(t0, int(self.t) + 1))
                    self._record_relay_loss(packet.source, "P" if other > 0 else "O")
        else:
            self.terminal_fates["RETAINED_AT_END"] += 1
        return super().finalize(packet, status)


class ObservedHYBSimulator(HopFateMixin, HYBSimulator):
    """HYB60 simulator instrumented with read-only hop-fate attribution."""


class ObservedPADCAge(HopFateMixin, DiagnosticPADCAge):
    """PADC-AGE simulator instrumented with read-only hop-fate attribution."""
