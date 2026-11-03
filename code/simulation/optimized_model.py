"""Slot-valued planning and local source-update scheduling for JLC-R.

Physical service, telemetry, admission, quotas and resource holds are inherited
unchanged. No sink freshness state is consulted by the new scheduling rule.
"""
import numpy as np

from diagnostic import battery_path
from joint_model import JointSimulator
from model import ModelSimulator
from service_model import radio_capacity


OPTIMIZED_POLICIES = ['JLC-R-SLOT', 'JLC-R-AGE', 'JLC-R-SA']


class OptimizedSimulator(JointSimulator):
    def __init__(self, c, sc, bank, policy='JLC-R-SA'):
        if policy not in OPTIMIZED_POLICIES:
            raise ValueError(policy)
        super().__init__(c, sc, bank, 'JLC-R')
        self.optimized_label = policy
        self.slot_planning = policy in {'JLC-R-SLOT', 'JLC-R-SA'}
        self.age_scheduling = policy in {'JLC-R-AGE', 'JLC-R-SA'}
        self.local_forwarded_birth = np.full((self.n, self.n), -1, dtype=int)
        self.reference_slots = np.asarray([radio_capacity(p, self.c)
                                          for p in self.reference_listening])
        self.plan_profiles = None
        self.planned_floor = np.zeros(self.n)

    def slot_plan(self, t, scale):
        """Exact paid slot cost at each known future role, including its floor.

        The forecast and future-demand coefficient remain those of JLC-R.
        Only the continuous radio allocation is replaced by attainable slots.
        """
        c = self.c
        phases = np.array([self.phase(t+h) for h in range(c['forecast_rounds'])])
        slots = np.floor(self.reference_slots*scale[None, :]+1e-9).astype(int)
        ratios = slots/np.maximum(self.reference_slots, 1)
        fixed, _, _ = self.coefficients(t)
        costs = np.full((self.n, c['forecast_rounds']), fixed)
        for h, ph in enumerate(phases):
            costs[:, h] += c['radio_idle_w']*c['guard_listen_s']*slots[ph]
            if h >= c['period_rounds']:
                demand = self.phase_structures[ph][2]+self.grant_profiles[ph]
                costs[:, h] += .65*demand*ratios[ph]
        ph = self.phase(t)
        demand = self.phase_structures[ph][2]+self.grant_profiles[ph]
        floor = c['period_rounds']*demand*ratios[ph]
        return costs, floor, slots, ratios

    def base_profile(self, t, low=None):
        if getattr(self, 'slot_planning', False) and self.plan_profiles is not None:
            return self.slot_plan(t, self.listen_scale)[0]
        return super().base_profile(t, low)

    def install_plan(self):
        if not self.slot_planning:
            return super().install_plan()
        c = self.c
        point, risk, _, _ = self.bank.entries[self.t]
        paths = risk

        def feasible(scale):
            costs, floor, _, _ = self.slot_plan(self.t, scale)
            costs[:, :c['period_rounds']] += floor[:, None]/c['period_rounds']
            margin, _, _ = battery_path(self.battery, c['battery_j'], paths,
                                        costs, c['reserve_j'])
            return ((margin >= -1e-10).all(axis=0) &
                    (floor <= c['battery_j']+1e-10))

        lo = np.zeros(self.n)
        hi = np.ones(self.n)
        lo = np.where(feasible(hi), hi, lo)
        for _ in range(15):
            mid = (lo+hi)/2
            good = feasible(mid)
            lo = np.where(good, mid, lo)
            hi = np.where(good, hi, mid)
        self.listen_scale = lo
        _, floor, slots, ratios = self.slot_plan(self.t, lo)
        self.planned_floor = floor
        self.plan_profiles = c['sync_listen_s']+c['guard_listen_s']*slots
        self.listen_profiles = [p.copy() for p in self.plan_profiles]
        self.actual_profiles = [p.copy() for p in self.plan_profiles]
        self.runtime_cap_profiles = [s.copy() for s in slots]
        self.scale_sum += float(ratios[self.phase(self.t)].sum())
        self.scale_count += self.n
        # Same second-stage prefix-credit solver and exogenous role install.
        ModelSimulator.install_plan(self)
        bad = self.extra+c['battery_j']/2**15+1e-9 < floor
        self.joint_floor_failures += int(bad.sum())
        if bad.any():
            raise AssertionError('Slot plan lost its communication floor')

    def choose_packet(self, i):
        if not self.age_scheduling:
            return super().choose_packet(i)
        queue = self.queues[i]
        committed = [p for p in queue if self.holds.get(p.sequence, (-1, 0))[0] == i]
        cutoff = self.t-self.c['deadline_rounds']+1

        def priority(p):
            previous = self.local_forwarded_birth[i, p.source]
            # A sender's own successful-hop history, not sink delivery state.
            uncovered = previous < cutoff and p.birth >= cutoff
            gain = p.birth-max(previous, cutoff-1)
            return uncovered, gain, p.birth, -p.sequence

        selected = max(committed or queue, key=priority)
        index = next(k for k, p in enumerate(queue) if p.sequence == selected.sequence)
        queue.rotate(-index)
        queue.popleft()
        queue.rotate(index)
        queue.appendleft(selected)
        return selected

    def attempt(self, i, j, packet):
        result = super().attempt(i, j, packet)
        if result[0]:
            self.local_forwarded_birth[i, packet.source] = max(
                self.local_forwarded_birth[i, packet.source], packet.birth)
        return result

    def metrics(self):
        row = super().metrics()
        row.update(method=self.optimized_label, slot_planning=int(self.slot_planning),
                   local_age_scheduling=int(self.age_scheduling))
        return row
