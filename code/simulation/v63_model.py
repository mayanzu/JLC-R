"""V6.3 Relay-Repair Hybrid Controller (RelayRepairHYB) and PADC-AGE diagnostic control.

Addresses the two winter multi-hop relay bottlenecks identified in Stage A:
1. Transit Protection Admission (M-B, addressing C): prevents 1-hop cluster members
   from exhausting the last transit guard slot and credit on a cluster head (CH)
   that serves upstream CHs.
2. Uncovered Staleness Tie-Breaking (M-A, addressing P): breaks same-round uncovered
   packet priority ties by oldest local forwarded birth (-previous) instead of node ID
   (-sequence), preventing starvation of higher-indexed peripheral sources while
   preserving remaining-lifetime gain priority in benign conditions.
3. Cluster-Head Period Demand Recognition (addressing P/C at period boundary):
   recognizes that active CHs (i in chset) receive member/relay traffic across the
   4-round period even before round-t sensing occurs.

When v63_mechanism == "off", RelayRepairHYB is byte-for-byte identical to HYB60
(HYBSimulator).
"""
from __future__ import annotations

import numpy as np

from v4_diagnostics import DiagnosticPADCAge
from v6_model import HYBSimulator

VALID_MECHANISMS = ("off", "relay_repair", "B", "A", "C")


class RelayRepairMixin:
    """Shared local relay-repair methods for HYB and PADC-AGE diagnostic control."""

    def _init_v63(self, v63_mechanism: str | None = None) -> None:
        mech = v63_mechanism if v63_mechanism is not None else self.c.get("v63_mechanism", "relay_repair")
        if mech not in VALID_MECHANISMS:
            raise ValueError(f"Unsupported v63_mechanism: {mech!r}")
        self.v63_mechanism = mech
        self.transit_reserve = np.zeros(self.n, dtype=int)
        self.transit_unit_j = np.zeros(self.n, dtype=float)
        self.transit_protect_denials = 0
        self.mc_allowance_grants = 0

    def _update_transit_protection(self) -> None:
        ph = self.phase(self.t)
        chset = set(self.ch.tolist())
        counts = np.zeros(self.n, dtype=int)
        max_rj = np.zeros(self.n, dtype=float)
        for i in self.ch:
            ii = int(i)
            for j in self.neighbors.get(ii, []):
                jj = int(j)
                if jj < self.n:
                    counts[jj] += 1
                    max_rj[jj] = max(max_rj[jj], self.control_cost(ii, jj)[1])
        self.transit_reserve = np.minimum(1, counts)
        erx = self.c["packet_bits"] * (self.c["elec_j_per_bit"] + self.c["aggregate_j_per_bit"])
        for j in range(self.n):
            if j in chset and self.transit_reserve[j] > 0:
                nxt = int(self.reference_next[ph][j])
                fwd = self.tx_energy(j, nxt)
                if nxt < self.n:
                    fwd += self.control_cost(j, nxt)[0]
                self.transit_unit_j[j] = max_rj[j] + erx + fwd
            else:
                self.transit_unit_j[j] = 0.0

    def _apply_mc_recovery_allowance(self) -> None:
        c = self.c
        period = c["period_rounds"]
        ch_mask = np.zeros(self.n, dtype=bool)
        ch_mask[self.ch] = True
        prefix_mode = ~getattr(self, "fdc_active", np.zeros(self.n, dtype=bool))
        has_hold = (self.forward_slot_holds > 0) | (self.forward_holds > 1e-12)
        healthy = (self.battery / c["battery_j"]) >= 0.5
        grant = ch_mask & prefix_mode & has_hold & healthy
        if not grant.any():
            return
        self.mc_allowance_grants += int(grant.sum())
        base_new = self.base_profile(self.t)
        new_extra = self.extra.copy()
        new_extra[grant] = np.maximum(new_extra[grant], period * c["battery_j"])
        self.issued_credit += float((new_extra - self.extra).sum())
        self.extra = new_extra
        self.cmax = base_new[:, :period].sum(axis=1) + self.extra
        self.credit = self.cmax.copy()

    def _priority_tuple(self, i: int, p, cutoff: int):
        previous = self.local_forwarded_birth[i, p.source]
        uncovered = previous < cutoff and p.birth >= cutoff
        gain = p.birth - max(previous, cutoff - 1)
        if self.v63_mechanism in ("relay_repair", "B", "A"):
            return (uncovered, gain, -previous, p.birth, -p.sequence)
        return (uncovered, gain, p.birth, -p.sequence)


class RelayRepairHYB(RelayRepairMixin, HYBSimulator):
    """Final JLC-R (V6.3) hybrid controller with multi-hop relay protection and tie-breaking."""

    def __init__(self, c, sc, bank, v63_mechanism: str | None = None):
        super().__init__(c, sc, bank)
        self._init_v63(v63_mechanism)

    def _select(self, genuine, duty):
        if self.v63_mechanism == "off" or not self.hyb_enabled:
            return super()._select(genuine, duty)
        c = self.c
        enter_thr = float(c.get("hyb_thin_scale", 0.60))
        exit_thr = float(c.get("hyb_exit_scale", 0.70))
        cutoff = self.t - c["deadline_rounds"] + 1
        if self.v63_mechanism in ("relay_repair", "B", "A"):
            ph = self.phase(self.t)
            ch_mask = np.zeros(self.n, dtype=bool)
            ch_mask[self.ch] = True
            uncov = np.array([self._uncovered_fresh(i, cutoff) for i in range(self.n)], dtype=bool)
            # A CH requires >= 2 guard slots (1 RX + 1 forward-hold) to relay any multi-hop packet
            ch_relay_starved = ch_mask & (self.runtime_cap_profiles[ph] < 2)
            demand = uncov | ch_relay_starved
        else:
            demand = np.array([self._uncovered_fresh(i, cutoff) for i in range(self.n)], dtype=bool)
        thin = self.listen_scale < enter_thr
        stay = self.hyb_latched & (self.listen_scale < exit_thr)
        use = demand & (genuine | thin | stay)
        self.hyb_latched = use.copy()
        self.hyb_thin_added_periods += int((use & ~genuine).sum())
        return use

    def install_plan(self):
        super().install_plan()
        if self.v63_mechanism == "off":
            return
        if self.v63_mechanism in ("relay_repair", "B"):
            self._update_transit_protection()
        elif self.v63_mechanism == "C":
            self._apply_mc_recovery_allowance()

    def request_grant(self, i, j, packet):
        if self.v63_mechanism not in ("relay_repair", "B"):
            return super().request_grant(i, j, packet)
        c = self.c
        etx = self.tx_energy(i, j)
        fresh = self.last_message[j] == self.t
        erx = c["packet_bits"] * (c["elec_j_per_bit"] + c["aggregate_j_per_bit"])
        if fresh and (self.cached_off[j] or self.cached_quota[j] < erx):
            self.block(packet, i, j, "known_receiver_unavailable")
            return False, 0.0
        si, rj = self.control_cost(i, j)
        if self.available(i, packet) < etx + si:
            self.block(packet, i, j, "sender_credit")
            return False, 0.0
        self.use_slot(i, packet)
        self.fee_control(i, si, packet)
        if self.off[j] or self.available(j) < rj or self.slots_left[j] - self.forward_slot_holds[j] <= 0:
            self.denied += 1
            self.block(packet, i, j, "grant_denied")
            return False, 0.0
        nxt = int(self.reference_next[self.phase(self.t)][j])
        forward = self.tx_energy(j, nxt)
        if nxt < self.n:
            forward += self.control_cost(j, nxt)[0]
        chset = set(self.ch.tolist())
        if i not in chset and j in chset:
            protect = int(self.transit_reserve[j])
            if (
                self.slots_left[j] - self.forward_slot_holds[j] - 1 < protect
                or self.available(j) - rj - (erx + forward) < protect * self.transit_unit_j[j]
            ):
                self.denied += 1
                self.transit_protect_denials += 1
                self.block(packet, i, j, "transit_protect")
                return False, 0.0
        self.use_slot(j)
        self.fee_control(j, rj)
        if self.available(j) < erx + forward or self.slots_left[j] - self.forward_slot_holds[j] < 1:
            self.denied += 1
            self.block(packet, i, j, "forward_reserve")
            return False, 0.0
        self.granted += 1
        return True, forward

    def read_only_packet(self, i):
        if self.v63_mechanism == "off":
            return super().read_only_packet(i)
        queue = self.queues[i]
        committed = [p for p in queue if self.holds.get(p.sequence, (-1, 0))[0] == i]
        cutoff = self.t - self.c["deadline_rounds"] + 1
        return max(committed or queue, key=lambda p: self._priority_tuple(i, p, cutoff))

    def choose_packet(self, i):
        if self.v63_mechanism == "off":
            return super().choose_packet(i)
        queue = self.queues[i]
        committed = [p for p in queue if self.holds.get(p.sequence, (-1, 0))[0] == i]
        cutoff = self.t - self.c["deadline_rounds"] + 1
        selected = max(committed or queue, key=lambda p: self._priority_tuple(i, p, cutoff))
        index = next(k for k, p in enumerate(queue) if p.sequence == selected.sequence)
        queue.rotate(-index)
        queue.popleft()
        queue.rotate(index)
        queue.appendleft(selected)
        return selected

    def metrics(self):
        row = super().metrics()
        if self.v63_mechanism != "off":
            row.update(
                v63_mechanism=self.v63_mechanism,
                transit_protect_denials=int(self.transit_protect_denials),
                mc_allowance_grants=int(self.mc_allowance_grants),
            )
        return row


class RelayRepairPADCAge(RelayRepairMixin, DiagnosticPADCAge):
    """PADC-AGE with the V6.3 relay-repair mechanism for Stage C/D diagnostic control."""

    def __init__(self, c, sc, bank, v63_mechanism: str | None = "relay_repair"):
        super().__init__(c, sc, bank)
        self._init_v63(v63_mechanism)

    def install_plan(self):
        super().install_plan()
        if self.v63_mechanism in ("relay_repair", "B"):
            self._update_transit_protection()

    def request_grant(self, i, j, packet):
        if self.v63_mechanism not in ("relay_repair", "B"):
            return super().request_grant(i, j, packet)
        c = self.c
        etx = self.tx_energy(i, j)
        fresh = self.last_message[j] == self.t
        erx = c["packet_bits"] * (c["elec_j_per_bit"] + c["aggregate_j_per_bit"])
        if fresh and (self.cached_off[j] or self.cached_quota[j] < erx):
            self.block(packet, i, j, "known_receiver_unavailable")
            return False, 0.0
        si, rj = self.control_cost(i, j)
        if self.available(i, packet) < etx + si:
            self.block(packet, i, j, "sender_credit")
            return False, 0.0
        self.use_slot(i, packet)
        self.fee_control(i, si, packet)
        if self.off[j] or self.available(j) < rj or self.slots_left[j] - self.forward_slot_holds[j] <= 0:
            self.denied += 1
            self.block(packet, i, j, "grant_denied")
            return False, 0.0
        nxt = int(self.reference_next[self.phase(self.t)][j])
        forward = self.tx_energy(j, nxt)
        if nxt < self.n:
            forward += self.control_cost(j, nxt)[0]
        chset = set(self.ch.tolist())
        if i not in chset and j in chset:
            protect = int(self.transit_reserve[j])
            if (
                self.slots_left[j] - self.forward_slot_holds[j] - 1 < protect
                or self.available(j) - rj - (erx + forward) < protect * self.transit_unit_j[j]
            ):
                self.denied += 1
                self.transit_protect_denials += 1
                self.block(packet, i, j, "transit_protect")
                return False, 0.0
        self.use_slot(j)
        self.fee_control(j, rj)
        if self.available(j) < erx + forward or self.slots_left[j] - self.forward_slot_holds[j] < 1:
            self.denied += 1
            self.block(packet, i, j, "forward_reserve")
            return False, 0.0
        self.granted += 1
        return True, forward

    def read_only_packet(self, i):
        if self.v63_mechanism == "off":
            return super().read_only_packet(i)
        queue = self.queues[i]
        committed = [p for p in queue if self.holds.get(p.sequence, (-1, 0))[0] == i]
        cutoff = self.t - self.c["deadline_rounds"] + 1
        return max(committed or queue, key=lambda p: self._priority_tuple(i, p, cutoff))

    def choose_packet(self, i):
        if self.v63_mechanism == "off":
            return super().choose_packet(i)
        queue = self.queues[i]
        committed = [p for p in queue if self.holds.get(p.sequence, (-1, 0))[0] == i]
        cutoff = self.t - self.c["deadline_rounds"] + 1
        selected = max(committed or queue, key=lambda p: self._priority_tuple(i, p, cutoff))
        index = next(k for k, p in enumerate(queue) if p.sequence == selected.sequence)
        queue.rotate(-index)
        queue.popleft()
        queue.rotate(index)
        queue.appendleft(selected)
        return selected

    def metrics(self):
        row = super().metrics()
        row.update(
            method="PADC-AGE+V63" if self.v63_mechanism != "off" else "PADC-AGE",
            v63_mechanism=self.v63_mechanism,
            transit_protect_denials=int(self.transit_protect_denials),
        )
        return row
