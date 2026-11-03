"""Selector, adapter and observable-audit layer on the common service model."""
from __future__ import annotations
from collections import Counter, deque
import numpy as np
from service_model import ServiceSimulator, ScenarioV2, ForecastBank, DEFAULTS, daylight
from revision_model import ENOAdapter


class ReviewSimulator(ServiceSimulator):
    def __init__(self, c, sc, bank, policy='JOINT', discount=1., event_writer=None):
        super().__init__(c, sc, bank, 'LISTEN' if policy == 'LISTEN' else 'JOINT')
        self.policy = policy
        self.method = policy
        self.discount = discount
        self.prediction_mode = 'P' if policy.startswith('POINT') else 'U'
        self.keep_lock = policy not in ('ADMIT-FIFO', 'PRIORITY-ONLY')
        self.priority = policy not in ('ADMIT-FIFO', 'LOCK-FIFO', 'LISTEN')
        self.event_writer = event_writer
        self.event_id = 0
        self.admitted = set()
        self.stats = Counter()
        self.by_role = {r: Counter() for r in ('member', 'CH')}
        self.node_base = np.zeros(self.n)
        self.node_data = np.zeros(self.n)
        self.node_control = np.zeros(self.n)
        self.node_harvest = np.zeros(self.n)
        self.node_spill = np.zeros(self.n)
        self.initial_node_battery = self.battery.copy()
        self.source_age_sum = np.zeros(self.n)
        self.source_fresh = np.zeros(self.n, int)
        self.last_delivery_round = np.full(self.n, -1, int)
        self.longest_gap = np.zeros(self.n, int)
        self.max_node_error = 0.
        self._start_quota = np.zeros(self.n)
        if event_writer:
            self.emit('initial', battery=self.battery.tolist(), reserve=c['reserve_j'],
                      capacity=c['battery_j'])

    def emit(self, kind, **values):
        if self.event_writer:
            self.event_writer(dict(id=self.event_id, round=self.t, event=kind, **values))
            self.event_id += 1

    def install_plan(self):
        if self.policy.startswith('BATTERY-ENO'):
            ENOAdapter.install_plan(self)
            target = float(self.policy.rsplit('-', 1)[1])*self.c['battery_j']
            c = self.c
            end = self.sc.warm+self.t
            rate = self.sc.observed[end-c['day_rounds']:end].mean(axis=0)
            listen = self.listen_profiles[self.phase(self.t)]
            base = (c['sleep_w']*c['round_seconds']+c['radio_idle_w']*listen+
                    c['sense_j_per_bit']*c['packet_bits']+
                    c['control_j_per_node_period']/c['period_rounds'])
            previous = self.extra.copy()
            desired = c['period_rounds']*(rate-base)+(self.battery-target)
            cap = np.maximum(0., self.battery-c['reserve_j']-c['period_rounds']*base)
            self.extra = np.minimum(np.maximum(0., desired), cap)
            self.issued_credit += float((self.extra-previous).sum())
            self.cmax = c['period_rounds']*base+self.extra
            self.credit = self.cmax.copy()
            self.method = self.policy
        else:
            super().install_plan()
            if self.policy == 'POINT-DISCOUNT':
                difference = self.extra*(1-self.discount)
                self.extra *= self.discount
                self.issued_credit -= float(difference.sum())
                self.cmax -= difference
                self.credit -= difference

    def spend(self, i, energy, category='comm'):
        before = float(self.battery[i])
        super().spend(i, energy, category)
        ledger = self.node_data if category == 'comm' else self.node_control if category == 'control' else self.node_base
        ledger[i] += energy
        self.emit('debit', node=int(i), amount=float(energy), category=category,
                  before=before, after=float(self.battery[i]))

    def block(self, packet, i, j, reason):
        super().block(packet, i, j, reason)
        role = 'CH' if i in self.ch else 'member'
        self.by_role[role]['block_'+reason] += 1

    def release_hold(self, packet):
        if packet.sequence in self.holds:
            self.stats['hold_releases'] += 1
        super().release_hold(packet)

    def use_slot(self, i, packet=None):
        super().use_slot(i, packet)

    def state(self, i):
        return dict(node=int(i), battery=float(self.battery[i]), quota=float(self.quota[i]),
                    slots=int(self.slots_left[i]), used=int(self.slots_used[i]),
                    energy_holds=[[int(k), float(v[1])] for k,v in self.holds.items() if v[0] == i],
                    slot_holds=[int(k) for k in self.hold_slots if self.holds[k][0] == i])

    def attempt(self, i, j, packet):
        held_before = self.holds.get(packet.sequence)
        held_slot_before = packet.sequence in self.hold_slots
        latest_before = self.latest[packet.source]
        used_before = self.slots_used[i]
        result = super().attempt(i, j, packet)
        ok, why = result
        if held_before and held_before[0] == i:
            self.stats['held_packet_actions'] += 1
            if self.slots_used[i] > used_before:
                self.stats['held_packet_paid_actions'] += 1
                if held_slot_before:
                    self.stats['held_slot_used'] += 1
            if ok:
                self.stats['held_packet_hop_successes'] += 1
        if ok and j < self.n and not packet.finalized and self.reserve_enabled:
            self.stats['hold_created'] += 1
            self.admitted.add(packet.sequence)
            if not self.keep_lock:
                super().release_hold(packet)
        if ok and j == self.n and self.latest[packet.source] > latest_before:
            source = packet.source
            self.longest_gap[source] = max(self.longest_gap[source], self.t-self.last_delivery_round[source])
            self.last_delivery_round[source] = self.t
        if self.event_writer:
            nodes = [i] if j == self.n else [i,j]
            self.emit('transaction', sender=int(i), receiver=int(j), sequence=packet.sequence,
                      ok=bool(ok), reason=why, states=[self.state(k) for k in nodes])
        return result

    def choose_packet(self, i):
        q = self.queues[i]
        candidates = list(q)
        if self.priority:
            admitted = [p for p in candidates if
                        self.holds.get(p.sequence, (-1,0))[0] == i or
                        (self.policy == 'PRIORITY-ONLY' and p.sequence in self.admitted)]
            if admitted:
                candidates = admitted
        if self.policy == 'JOINT-EDF':
            selected = min(candidates, key=lambda p:(p.birth,p.sequence))
        elif self.policy == 'JOINT-NEWEST':
            selected = max(candidates, key=lambda p:(p.birth,-p.sequence))
        else:
            selected = candidates[0]
        index = next(k for k,p in enumerate(q) if p.sequence == selected.sequence)
        q.rotate(-index); selected = q.popleft(); q.rotate(index); q.appendleft(selected)
        return selected

    def route(self, i, chset):
        if not hasattr(self, '_routed_round') or self._routed_round != self.t:
            self._routed_round = self.t
            self._start_quota = self.quota.copy()
            self._start_battery = self.battery.copy()
            self.admitted.clear()
            self.emit('round_ready', states=[self.state(k) for k in range(self.n)])
        if self.off[i]:
            if self.queues[i]:
                self.block(self.queues[i][0], i, -1, 'sender_energy')
            return
        c = self.c
        fallback = self.policy == 'JOINT-FALLBACK'
        for _ in range(c['max_ch_actions_round']):
            if not self.queues[i]:
                break
            packet = self.choose_packet(i)
            if i not in chset:
                choices = [int(self.parent[i])]
            else:
                _, mask, ids = self.observe(i)
                for k in np.flatnonzero(mask[:-1]):
                    j = int(ids[k])
                    cost = self.tx_energy(i,j)
                    if fallback and self.reserve_enabled and j < self.n:
                        cost += self.control_cost(i,j)[0]
                    if self.available(i, packet) < cost:
                        mask[k] = False
                choices = []
                while mask[:-1].any():
                    a = self.greedy(i,mask,ids)
                    choices.append(int(ids[a])); mask[a] = False
                    if not fallback:
                        break
                if not choices:
                    self.block(packet,i,-1,self.no_action_reason(i)); break
            ok = False; why = 'no_route'
            for j in choices:
                # Recheck after a previous denial's irreversible fee and slot.
                cost = self.tx_energy(i,j)+(self.control_cost(i,j)[0]
                       if self.reserve_enabled and j < self.n else 0.)
                if fallback and self.available(i,packet) < cost:
                    continue
                ok, why = self.attempt(i,j,packet)
                if ok or why == 'link_loss' or not fallback:
                    break
                self.stats['alternative_candidates_tried'] += 1
            if ok:
                self.queues[i].popleft()
            elif why != 'link_loss' or packet.round_tries >= c['max_link_attempts']:
                self.stats['stopped_nonlink'] += 1
                break
        else:
            if self.queues[i]:
                self.block(self.queues[i][0],i,-1,'action_limit')

    def round(self):
        self.stats['holds_released_at_boundary'] += len(self.holds)
        self.stats['slots_released_at_boundary'] += len(self.hold_slots)
        b0 = self.battery.copy()
        spent0 = self.node_base+self.node_data+self.node_control
        previous_latest = self.latest.copy()
        super().round()
        t = self.t-1
        h = self.sc.harvest[self.sc.warm+t]
        spent = self.node_base+self.node_data+self.node_control-spent0
        preharvest = b0-spent
        spill = np.maximum(0.,preharvest+h-self.c['battery_j'])
        self.node_harvest += h; self.node_spill += spill
        for i in range(self.n):
            if self.event_writer:
                self.emit('harvest', node=i, amount=float(h[i]), spill=float(spill[i]),
                          after=float(self.battery[i]))
        error = self.initial_node_battery+self.node_harvest-self.node_spill-self.node_base-self.node_data-self.node_control-self.battery
        self.max_node_error = max(self.max_node_error, float(np.abs(error).max()))
        if self.max_node_error > 1e-8:
            raise AssertionError('node energy conservation')
        ages = np.where(self.latest >= 0,t-self.latest+1,t+1)
        self.source_age_sum += ages*self.c['round_seconds']/60
        self.source_fresh += ((self.latest >= 0)&(ages <= self.c['deadline_rounds']))
        for role, mask in [('CH',np.isin(np.arange(self.n),self.ch)),
                           ('member',~np.isin(np.arange(self.n),self.ch))]:
            issued = float(self._start_quota[mask].sum())
            remaining = float(np.maximum(self.quota[mask],0).sum())
            self.by_role[role]['issued_j'] += issued
            self.by_role[role]['used_j'] += issued-remaining
            self.by_role[role]['node_rounds'] += int(mask.sum())
            self.by_role[role]['zero_quota'] += int((self._start_quota[mask] == 0).sum())
        if daylight(t,self.c['day_rounds']) == 0:
            chset = set(self.ch.tolist())
            choices = [self.neighbors[i] if i in chset else [int(self.parent[i])]
                       for i in range(self.n)]
            minimum_tx = np.array([min((self.tx_energy(i,int(j))+
                (self.control_cost(i,int(j))[0] if self.reserve_enabled and j < self.n else 0.)
                for j in choices[i]), default=np.inf) for i in range(self.n)])
            self.stats['night_online_no_sender_budget'] += int((~self.off &
                ((self._start_quota < minimum_tx)|(self._start_battery-self.c['reserve_j'] < minimum_tx))).sum())
            self.stats['night_node_rounds'] += self.n
        self.stats['unconsumed_slots'] += int(np.maximum(self.slots_left,0).sum())

    def node_rows(self):
        return [dict(node=i, initial_j=float(self.initial_node_battery[i]),
                     harvest_j=float(self.node_harvest[i]),spill_j=float(self.node_spill[i]),
                     base_j=float(self.node_base[i]),data_j=float(self.node_data[i]),
                     control_j=float(self.node_control[i]),final_j=float(self.battery[i]),
                     mean_aoi_minutes=float(self.source_age_sum[i]/self.sc.rounds),
                     coverage_pct=float(100*self.source_fresh[i]/self.sc.rounds),
                     never_delivered=int(self.last_delivery_round[i] < 0),
                     longest_no_update_minutes=float(max(self.longest_gap[i],self.sc.rounds-1-self.last_delivery_round[i])*self.c['round_seconds']/60),
                     x_m=float(self.sc.pos[i,0]),y_m=float(self.sc.pos[i,1])) for i in range(self.n)]

    def metrics(self):
        m = super().metrics()
        m['method'] = self.policy
        m['max_node_energy_error_j'] = self.max_node_error
        m['holds_at_horizon'] = len(self.holds)
        m.update({k:self.stats[k] for k in [
            'hold_created','held_slot_used','held_packet_actions','held_packet_paid_actions',
            'held_packet_hop_successes','holds_released_at_boundary','slots_released_at_boundary',
            'alternative_candidates_tried','stopped_nonlink','unconsumed_slots',
            'night_online_no_sender_budget','night_node_rounds']})
        nodes = self.node_rows()
        m['never_delivered_pct'] = float(100*np.mean([x['never_delivered'] for x in nodes]))
        m['source_aoi_p95_minutes'] = float(np.quantile([x['mean_aoi_minutes'] for x in nodes],.95))
        m['longest_gap_p95_minutes'] = float(np.quantile([x['longest_no_update_minutes'] for x in nodes],.95))
        return m
