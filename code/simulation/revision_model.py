"""Revision-only diagnostics and ENO paradigm adapter; frozen sources untouched."""
from __future__ import annotations
from collections import Counter
import numpy as np
from service_model import ServiceSimulator
from diagnostic import battery_path, daylight


class RevisionSimulator(ServiceSimulator):
    """Default behavior is identical to ServiceSimulator; record role feasibility."""
    def __init__(self, c, sc, bank, mode='JOINT'):
        super().__init__(c, sc, bank, mode)
        self.role_plan = Counter()

    def base_profile(self, t, low=None):
        if self.c.get('future_relay_fraction', .65) == .65:
            return super().base_profile(t, low)
        c = self.c
        base = np.empty((self.n, c['forecast_rounds']))
        for k in range(c['forecast_rounds']):
            ph = self.phase(t+k)
            base[:, k] = (c['sleep_w']*c['round_seconds'] +
                          c['radio_idle_w']*self.listen_profiles[ph] +
                          c['sense_j_per_bit']*c['packet_bits'] +
                          c['control_j_per_node_period']/c['period_rounds'])
            if k >= c['period_rounds']:
                base[:, k] += c['future_relay_fraction']*(
                    self.phase_structures[ph][2]+self.grant_profiles[ph])
        return base

    def install_plan(self):
        super().install_plan()
        point, risk, _, _ = self.bank.entries[self.t]
        chosen = point[None, :, :] if self.prediction_mode == 'P' else risk
        minimum, _, _ = battery_path(self.battery, self.c['battery_j'], chosen,
                                    self.base_profile(self.t), self.c['reserve_j'])
        bad = ~(minimum >= -1e-10).all(axis=0)
        is_ch = np.zeros(self.n, bool); is_ch[self.ch] = True
        period = 'stress' if self.t//self.c['day_rounds'] in [5, 6, 7] else 'remaining'
        for role, mask in [('CH', is_ch), ('member', ~is_ch)]:
            for window in ['all', period]:
                self.role_plan[role, window, 'total'] += int(mask.sum())
                self.role_plan[role, window, 'infeasible'] += int((bad & mask).sum())
        # Feasible credits below the bisection resolution may also be zero;
        # count infeasibility from the explicit x=0 path, never from extra==0.
        assert int(bad.sum()) <= self.n


class ENOAdapter(ServiceSimulator):
    """Past-day mean-rate proportional duty control, no prefix budget or grants.

    This is an explicitly specified paradigm adapter, not a reproduction of
    Kansal et al., PADC-MAC or HENO-MAC. No parameter is fit to validation.
    """
    def __init__(self, c, sc, bank):
        super().__init__(c, sc, bank, 'FIXED')
        self.method = 'ENO-ADAPT'

    def install_plan(self):
        c = self.c; t = self.t; ph = self.phase(t)
        self.ch = self.phase_heads[ph]
        parent, self.rank, self.expected_load = self.phase_structures[ph]
        self.parent = parent
        changed = np.zeros(self.n, bool) if self.last_parent is None else parent != self.last_parent
        self.reclusters += int(changed.any()); self.changed += int(changed.sum())
        self.last_parent = parent.copy()
        # Only completed, metered observations; warm-up provides a full day.
        end = self.sc.warm+t
        mean_rate = self.sc.observed[end-c['day_rounds']:end].mean(axis=0)
        fixed = np.full(self.n, c['cm_listen_s']); fixed[self.ch] = c['ch_listen_s']
        sync_base = (c['sleep_w']*c['round_seconds'] +
                     c['sense_j_per_bit']*c['packet_bits'] +
                     c['control_j_per_node_period']/c['period_rounds'] +
                     c['radio_idle_w']*c['sync_listen_s'])
        discretionary = c['radio_idle_w']*(fixed-c['sync_listen_s']) + self.expected_load
        duty = np.clip((mean_rate-sync_base)/discretionary, 0., 1.)
        listen = c['sync_listen_s'] + duty*(fixed-c['sync_listen_s'])
        self.listen_profiles[ph] = listen
        base = sync_base+c['radio_idle_w']*(listen-c['sync_listen_s'])
        rate_credit = np.maximum(0., mean_rate-base)
        # Current battery caps the whole upcoming credit period, without any
        # multi-step forecast, prefix feasibility or future harvested energy.
        battery_credit = np.maximum(0., self.battery-c['reserve_j']-c['period_rounds']*base)
        self.extra = np.minimum(c['period_rounds']*rate_credit, battery_credit)
        self.issued_credit += float(self.extra.sum()); self.periods += 1
        self.cmax = c['period_rounds']*base+self.extra
        self.credit = self.cmax.copy(); self.actual_period[:] = 0; self.period_comm[:] = 0
        self.neighbors = {}
        for i in self.ch:
            candidates = np.r_[self.ch, self.n]
            self.neighbors[int(i)] = np.sort(candidates[
                self.adj[i, candidates] & (self.rank[candidates] < self.rank[i]-1e-9)])[:c['candidates']]
        self.rho = 1.; self.pred.multiplier = self.bank.entries[t][3]

