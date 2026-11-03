"""Causal receiver reservation and role-based listening, with finite radio slots.

All variants use the same abstract sequential MAC and the same exogenous data.
Guard listening is distinct from data airtime (whose energy is packet-based).
"""
from __future__ import annotations
from collections import Counter, deque
import numpy as np
from diagnostic import DiagnosticSimulator, ScenarioV2, ForecastBank, Sample, daylight, BITS

DEFAULTS = dict(sync_listen_s=.020, guard_listen_s=.010,
                slot_safety_factor=1.25, control_frame_bits=64,
                bitrate_bps=250000., slot_guard_floor_s=.010)
MODES = {'FIXED': (False, False), 'RESERVE': (True, False),
         'LISTEN': (False, True), 'JOINT': (True, True)}
NEW_REASONS = ['listen_capacity', 'known_receiver_unavailable',
               'grant_denied', 'forward_reserve']
NEW_BITS = {r: 1 << (len(BITS) + i) for i, r in enumerate(NEW_REASONS)}


def radio_capacity(listen_s, c):
    """Each data attempt consumes one guard slot at each participating radio."""
    return np.maximum(0, np.floor((np.asarray(listen_s)-c['sync_listen_s']) /
                                 c['guard_listen_s'] + 1e-9)).astype(int)


class ServiceSimulator(DiagnosticSimulator):
    def __init__(self, c, sc, bank, mode):
        cfg = dict(c); cfg.update({k: c.get(k, v) for k, v in DEFAULTS.items()})
        if mode not in MODES:
            raise ValueError('unknown service mode')
        if cfg['guard_listen_s'] < cfg['slot_guard_floor_s']:
            raise ValueError('guard shorter than registered minimum')
        if cfg['sync_listen_s'] <= 0 or cfg['slot_safety_factor'] < 1:
            raise ValueError('invalid timing parameters')
        super().__init__(cfg, sc, bank, 'U_PREFIX')
        self.mode = mode; self.reserve_enabled, self.listen_enabled = MODES[mode]
        self.method = mode
        self.listen_profiles = []; self.grant_profiles = []; self.reference_next = []
        self.anticipated_slots = []
        for heads, struct in zip(self.phase_heads, self.phase_structures):
            listen, grant, nxt, slots = self.reference_profile(heads, struct)
            self.listen_profiles.append(listen); self.grant_profiles.append(grant)
            self.reference_next.append(nxt); self.anticipated_slots.append(slots)
        self.slots_left = np.zeros(self.n, int); self.slots_used = np.zeros(self.n, int)
        self.forward_holds = np.zeros(self.n)
        self.forward_slot_holds = np.zeros(self.n, int)
        self.holds = {}  # source sample id -> (receiving owner, reserved next-hop energy)
        self.hold_slots = set()
        self.grant_energy = 0.; self.granted = 0; self.denied = 0
        self.guard_energy = 0.; self.slot_sum = 0; self.slot_used_sum = 0
        self.max_hold_violation = 0.; self.max_slot_violation = 0

    def control_cost(self, i, j):
        fraction = self.c['control_frame_bits'] / self.c['packet_bits']
        rx = self.c['control_frame_bits'] * self.c['elec_j_per_bit']
        # Request + response, including the original packet radio overhead.
        return self.tx_energy(i, j) * fraction + rx, self.tx_energy(j, i) * fraction + rx

    def reference_profile(self, heads, struct):
        """Offered one-sample/node demand; uses topology, never future arrivals."""
        parent, rank, _ = struct; n = self.n
        counts = np.ones(n); slots = np.zeros(n); grant = np.zeros(n)
        nxt = parent.copy(); is_head = np.zeros(n, bool); is_head[heads] = True
        order = list(np.flatnonzero(~is_head)) + list(heads[np.argsort(-rank[heads])])
        vertices = np.r_[heads, n]
        for i in order:
            i = int(i)
            if is_head[i]:
                eligible = vertices[self.adj[i, vertices] & (rank[vertices] < rank[i]-1e-9)]
                j = int(min(eligible, key=lambda j: 1/self.prob[i, j]+rank[j]))
                nxt[i] = j
            else:
                j = int(parent[i])
            attempts = counts[i] / self.prob[i, j]
            slots[i] += attempts
            a, b = self.control_cost(i, j); grant[i] += attempts*a
            if j < n:
                slots[j] += attempts; counts[j] += counts[i]; grant[j] += attempts*b
        fixed = np.full(n, self.c['cm_listen_s']); fixed[heads] = self.c['ch_listen_s']
        if self.listen_enabled:
            target = np.ceil(self.c['slot_safety_factor']*slots).astype(int)
            listen = np.minimum(fixed, self.c['sync_listen_s']+target*self.c['guard_listen_s'])
        else:
            listen = fixed
        if not self.reserve_enabled:
            grant[:] = 0
        return listen, grant, nxt, slots

    def base_profile(self, t, low=None):
        c = self.c; period = c['period_rounds']
        base = np.empty((self.n, c['forecast_rounds']))
        for k in range(c['forecast_rounds']):
            ph = self.phase(t+k)
            base[:, k] = (c['sleep_w']*c['round_seconds'] +
                          c['radio_idle_w']*self.listen_profiles[ph] +
                          c['radio_idle_w']*c.get('sync_extra_listen_s', 0.) +
                          c['sense_j_per_bit']*c['packet_bits'] +
                          c['control_j_per_node_period']/period)
            if k >= period:
                base[:, k] += .65*(self.phase_structures[ph][2]+self.grant_profiles[ph])
        return base

    def block(self, packet, i, j, reason):
        super().block(packet, i, j, reason)
        packet.history |= NEW_BITS.get(reason, 0)

    def finalize(self, packet, status):
        super().finalize(packet, status)
        for reason, bit in NEW_BITS.items():
            if packet.history & bit:
                self.block_history[reason] += 1

    def release_hold(self, packet):
        hold = self.holds.pop(packet.sequence, None)
        if hold is not None:
            i, amount = hold; self.forward_holds[i] -= amount
            if packet.sequence in self.hold_slots:
                self.hold_slots.remove(packet.sequence)
                self.forward_slot_holds[i] -= 1
            if abs(self.forward_holds[i]) < 1e-12:
                self.forward_holds[i] = 0

    def available(self, i, packet=None):
        own = self.holds.get(packet.sequence, (-1, 0)) if packet else (-1, 0)
        adjustment = own[1] if own[0] == i else 0.
        held = self.forward_holds[i] - adjustment
        return min(self.quota[i], self.battery[i]-self.c['reserve_j'])-held

    def fee_control(self, i, amount, packet=None):
        self.debit(i, amount, 'control')
        # Handshakes use forwarding quota; they are debited once physically.
        self.quota[i] -= amount
        self.grant_energy += amount
        if packet is not None and packet.sequence in self.holds:
            owner, held = self.holds[packet.sequence]
            if owner == i:
                used = min(held, amount)
                self.holds[packet.sequence] = (owner, held-used)
                self.forward_holds[i] -= used

    def request_grant(self, i, j, packet):
        """An atomic charged exchange with receiver-local admission control."""
        c = self.c; etx = self.tx_energy(i, j)
        # A fresh unavailable announcement permits local WAIT, not a free peek.
        fresh = self.last_message[j] == self.t
        erx = c['packet_bits']*(c['elec_j_per_bit']+c['aggregate_j_per_bit'])
        if fresh and (self.cached_off[j] or self.cached_quota[j] < erx):
            self.block(packet, i, j, 'known_receiver_unavailable'); return False, 0.
        si, rj = self.control_cost(i, j)
        if self.available(i, packet) < etx+si:
            self.block(packet, i, j, 'sender_credit'); return False, 0.
        self.use_slot(i, packet)
        self.fee_control(i, si, packet)
        # Local receiver checks are communicated via the paid grant/denial.
        if self.off[j] or self.available(j) < rj or self.slots_left[j]-self.forward_slot_holds[j] <= 0:
            self.denied += 1; self.block(packet, i, j, 'grant_denied'); return False, 0.
        self.use_slot(j)
        self.fee_control(j, rj)
        nxt = int(self.reference_next[self.phase(self.t)][j])
        forward = self.tx_energy(j, nxt)
        if nxt < self.n: forward += self.control_cost(j, nxt)[0]
        if self.available(j) < erx+forward or self.slots_left[j]-self.forward_slot_holds[j] < 1:
            self.denied += 1; self.block(packet, i, j, 'forward_reserve'); return False, 0.
        self.granted += 1
        return True, forward

    def use_slot(self, i, packet=None):
        if packet is not None and packet.sequence in self.hold_slots:
            self.hold_slots.remove(packet.sequence)
            self.forward_slot_holds[i] -= 1
        if self.slots_left[i]-self.forward_slot_holds[i] <= 0:
            raise AssertionError('slot promised to another sample')
        self.slots_left[i] -= 1; self.slots_used[i] += 1

    def attempt(self, i, j, packet):
        c = self.c; etx = self.tx_energy(i, j)
        if self.battery[i] < etx+c['reserve_j']:
            self.block(packet, i, j, 'sender_energy'); return False, 'sender_energy'
        if self.available(i, packet) < etx:
            self.block(packet, i, j, 'sender_credit'); return False, 'sender_credit'
        own_slot = int(packet.sequence in self.hold_slots)
        if self.slots_left[i]-self.forward_slot_holds[i]+own_slot <= 0:
            self.block(packet, i, j, 'listen_capacity'); return False, 'listen_capacity'
        forward = 0.
        exchanged = self.reserve_enabled and j < self.n
        if exchanged:
            ok, forward = self.request_grant(i, j, packet)
            if not ok:
                return False, 'grant_denied'
        self.release_hold(packet)
        if not exchanged: self.use_slot(i)
        # In unscheduled-grant groups an exhausted receiver is discovered after TX.
        if j < self.n and not exchanged and self.slots_left[j] <= 0:
            self.debit(i, etx, 'comm'); self.block(packet, i, j, 'listen_capacity')
            return False, 'listen_capacity'
        ok, why = super().attempt(i, j, packet)
        if j < self.n and not exchanged and why not in ['receiver_off', 'receiver_energy', 'receiver_credit']:
            # A data slot is occupied even on a failed decoded packet.
            self.use_slot(j)
        if ok and j < self.n and self.reserve_enabled and not packet.finalized:
            self.holds[packet.sequence] = (j, forward); self.forward_holds[j] += forward
            self.hold_slots.add(packet.sequence)
            self.forward_slot_holds[j] += 1
            self.max_hold_violation = max(self.max_hold_violation,
                max(0., self.forward_holds[j]-min(self.quota[j], self.battery[j]-c['reserve_j'])))
            if self.max_hold_violation > 1e-8:
                raise AssertionError('overbooked receiver forwarding reserve')
            if self.forward_slot_holds[j] > self.slots_left[j]:
                raise AssertionError('overbooked receiver forwarding slots')
        return ok, why

    def route(self, i, chset):
        c = self.c
        if self.off[i]:
            if self.queues[i]: self.block(self.queues[i][0], i, -1, 'sender_energy')
            return
        for _ in range(c['max_ch_actions_round']):
            if not self.queues[i]: break
            if self.reserve_enabled:
                # Serve admitted obligations before unreserved local traffic.
                for index, queued in enumerate(self.queues[i]):
                    if self.holds.get(queued.sequence, (-1, 0))[0] == i:
                        self.queues[i].rotate(-index)
                        selected = self.queues[i].popleft()
                        self.queues[i].rotate(index)
                        self.queues[i].appendleft(selected)
                        break
            packet = self.queues[i][0]
            if i not in chset:
                j = int(self.parent[i])
            else:
                _, mask, ids = self.observe(i)
                for k in np.flatnonzero(mask[:-1]):
                    if self.available(i, packet) < self.tx_energy(i, int(ids[k])):
                        mask[k] = False
                a = self.greedy(i, mask, ids)
                if a == c['candidates']:
                    self.block(packet, i, -1, self.no_action_reason(i)); break
                j = int(ids[a])
            ok, why = self.attempt(i, j, packet)
            if ok: self.queues[i].popleft()
            elif why != 'link_loss' or packet.round_tries >= c['max_link_attempts']: break
        else:
            if self.queues[i]: self.block(self.queues[i][0], i, -1, 'action_limit')

    def round(self):
        c = self.c; n = self.n
        if self.t % c['period_rounds'] == 0: self.install_plan()
        self.quota = self.extra / c['period_rounds']
        self.round_comm[:] = 0; self.round_base[:] = 0; self.round_control[:] = 0
        self.holds.clear(); self.hold_slots.clear(); self.forward_holds[:] = 0; self.forward_slot_holds[:] = 0
        # Optional current-round resource planning, before capacity, fees and telemetry.
        # Existing controllers have no hook and retain their exact execution path.
        if hasattr(self, 'prepare_extra_round_resources'):
            self.prepare_extra_round_resources()
        listen = self.listen_profiles[self.phase(self.t)]
        capacity = radio_capacity(listen, c)
        self.slots_left = capacity.copy(); self.slots_used[:] = 0
        chset = set(self.ch.tolist())
        for i in range(n):
            alive = deque()
            for packet in self.queues[i]:
                if self.t-packet.birth >= c['deadline_rounds']:
                    self.expired += 1; self.finalize(packet, 'expired')
                else: alive.append(packet)
            self.queues[i] = alive
            if c.get('joint_sync_execution', False):
                self.prepare_sync_activity(i, listen[i])
                continue
            basal = c['sleep_w']*c['round_seconds']+c['radio_idle_w']*(listen[i]+c.get('sync_extra_listen_s',0.))
            sense = c['sense_j_per_bit']*c['packet_bits']
            control = c['control_j_per_node_period']/c['period_rounds']
            required = basal+sense+control
            if self.off[i] and self.battery[i] >= max(c['recovery_j'], required): self.off[i] = False
            if not self.off[i] and self.battery[i] >= required:
                self.debit(i, basal+sense, 'base'); self.debit(i, control, 'control')
                self.guard_energy += c['radio_idle_w']*listen[i]
                self.generated += 1; packet = Sample(i, self.t, self.t*n+i)
                if len(self.queues[i]) < c['max_queue']: self.queues[i].append(packet)
                else:
                    self.overflow += 1; packet.last_reason = 'queue_overflow'; self.finalize(packet, 'overflow')
                self.cached_battery[i] = self.battery[i]; self.cached_quota[i] = self.quota[i]
                self.cached_queue[i] = len(self.queues[i]); self.cached_off[i] = False; self.last_message[i] = self.t
            else:
                self.off[i] = True; self.unsensed += 1; self.outcomes['unsensed'] += 1
                self.sample_status[self.t*n+i] = 5
                self.debit(i, min(self.battery[i], c['off_w']*c['round_seconds']), 'base')
                self.slots_left[i] = 0
        self.demand += n; self.off_rounds += int(self.off.sum())
        stale = (self.last_message < 0) | (self.t-self.last_message > 1)
        self.cached_off[stale] = True
        if daylight(self.t, c['day_rounds']) == 0:
            self.night_off += int(self.off.sum()); self.night_total += n
        for i in range(n):
            if i not in chset: self.route(i, chset)
        for i in self.ch[np.argsort(-self.rank[self.ch])]: self.route(int(i), chset)
        violation = np.maximum(self.forward_holds-np.maximum(0., np.minimum(self.quota, self.battery-c['reserve_j'])), 0.)
        self.max_hold_violation = max(self.max_hold_violation, float(violation.max()))
        if self.max_hold_violation > 1e-8 or (self.forward_slot_holds > self.slots_left).any():
            raise AssertionError('remaining grant obligations overbooked')
        # Conservative sequential envelope: includes both endpoints' data airtime.
        envelope = float(listen[~self.off].sum()+self.slots_used.sum()*c['packet_bits']/c['bitrate_bps'])
        if envelope > c['round_seconds']: raise AssertionError('macro round too short for slots')
        self.slot_sum += int(capacity[~self.off].sum()); self.slot_used_sum += int(self.slots_used.sum())
        self.max_slot_violation = max(self.max_slot_violation, int(np.maximum(self.slots_used-capacity, 0).max()))
        if self.max_slot_violation: raise AssertionError('radio slot capacity exceeded')
        self.unused_credit += float(np.maximum(self.quota, 0).sum())
        harvest = self.sc.harvest[self.sc.warm+self.t]
        spilled = np.maximum(self.battery+harvest-c['battery_j'], 0)
        self.battery = np.minimum(c['battery_j'], self.battery+harvest)
        self.harvested += float(harvest.sum()); self.spilled += float(spilled.sum())
        error = self.initial_sum+self.harvested-self.consumed-self.spilled-self.battery.sum()
        if abs(error) > 1e-6: raise AssertionError('energy conservation')
        ages = np.where(self.latest >= 0, self.t-self.latest+1, self.t+1)
        self.logs.append(dict(round=self.t, day=self.t/c['day_rounds'],
            coverage=float(np.mean((self.latest >= 0) & (ages <= c['deadline_rounds']))),
            aoi_minutes=float(ages.mean()*c['round_seconds']/60), battery_mean_j=float(self.battery.mean()),
            off_fraction=float(self.off.mean()), queue_mean=float(np.mean([len(q) for q in self.queues])),
            solar_mean_j=float(harvest.mean()), rho=self.rho, energy_balance_error_j=float(error),
            slots_available=int(capacity[~self.off].sum()), slots_used=int(self.slots_used.sum()),
            grant_energy_j=self.grant_energy, granted=self.granted, denied=self.denied))
        self.t += 1

    def metrics(self):
        m = super().metrics()
        m.update(grant_energy_j=self.grant_energy, granted=self.granted, denied=self.denied,
                 guard_energy_j=self.guard_energy, slots_available=self.slot_sum, slots_used=self.slot_used_sum,
                 max_hold_violation_j=self.max_hold_violation, max_slot_violation=self.max_slot_violation,
                 slot_capacity_events=self.reasons['listen_capacity'],
                 reserve_events=self.reasons['forward_reserve'],
                 known_unavailable_events=self.reasons['known_receiver_unavailable'])
        return m
