"""Lexicographic joint listening/credit model, motivated by the slack-credit screen."""
import numpy as np
from model import ModelSimulator, StreamingBank, ScenarioV2, DEFAULTS, configuration
from diagnostic import battery_path
from service_model import radio_capacity

JOINT_POLICIES = ['JLC-R', 'POINT-JL', 'JLC-R-FIXED', 'POINT', 'LPL-MATCH', 'BENO(0.4)']


class JointSimulator(ModelSimulator):
    def __init__(self, c, sc, bank, policy):
        self.joint_label = policy
        self.joint_listening = policy in {'JLC-R', 'POINT-JL'}
        base_policy = {'JLC-R': 'JLC-R-FIXED', 'POINT-JL': 'POINT'}.get(policy, policy)
        super().__init__(c, sc, bank, base_policy)
        self.reference_listening = [p.copy() for p in self.listen_profiles]
        self.listen_scale = np.ones(self.n)
        self.scale_sum = 0.
        self.scale_count = 0
        self.joint_floor_failures = 0

    def coefficients(self, t):
        c = self.c
        fixed = (c['sleep_w']*c['round_seconds'] + c['radio_idle_w']*c['sync_listen_s'] +
                 c['radio_idle_w']*c.get('sync_extra_listen_s', 0.) +
                 c['sense_j_per_bit']*c['packet_bits'] +
                 c['control_j_per_node_period']/c['period_rounds'])
        varying = np.empty((self.n, c['forecast_rounds']))
        for h in range(c['forecast_rounds']):
            ph = self.phase(t+h)
            varying[:, h] = c['radio_idle_w']*(self.reference_listening[ph]-c['sync_listen_s'])
            if h >= c['period_rounds']:
                varying[:, h] += .65*(self.phase_structures[ph][2]+self.grant_profiles[ph])
        ph = self.phase(t)
        demand = self.phase_structures[ph][2]+self.grant_profiles[ph]
        return fixed, varying, demand

    def base_profile(self, t, low=None):
        if not self.joint_listening or not hasattr(self, 'reference_listening'):
            return super().base_profile(t, low)
        fixed, varying, _ = self.coefficients(t)
        return fixed+self.listen_scale[:, None]*varying

    def install_plan(self):
        if self.joint_listening:
            c = self.c
            no_floor = bool(c.get('no_reference_floor', False))
            point, risk, _, _ = self.bank.entries[self.t]
            scenarios = point[None] if self.prediction_mode == 'P' else risk
            fixed, varying, demand = self.coefficients(self.t)
            # x >= T_L * a * reference_load, so this is the least expensive
            # communication plan for each candidate listening fraction a.
            # The floor-free diagnostic variant maximizes a against the
            # listening cost alone, with no reference communication plan.
            full = varying.copy()
            if not no_floor:
                full[:, :c['period_rounds']] += demand[:, None]
            lo = np.zeros(self.n)
            hi = (np.ones(self.n) if no_floor else
                  np.minimum(1., c['battery_j']/np.maximum(c['period_rounds']*demand, 1e-30)))
            minimum, _, _ = battery_path(self.battery, c['battery_j'], scenarios,
                fixed+hi[:, None]*full, c['reserve_j'])
            lo = np.where((minimum >= -1e-10).all(axis=0), hi, lo)
            for _ in range(15):
                mid = (lo+hi)/2
                minimum, _, _ = battery_path(self.battery, c['battery_j'], scenarios,
                    fixed+mid[:, None]*full, c['reserve_j'])
                good = (minimum >= -1e-10).all(axis=0)
                lo = np.where(good, mid, lo)
                hi = np.where(good, hi, mid)
            self.listen_scale = lo
            self.listen_profiles = [c['sync_listen_s']+lo*(p-c['sync_listen_s'])
                                    for p in self.reference_listening]
            self.actual_profiles = [p.copy() for p in self.listen_profiles]
            self.runtime_cap_profiles = [radio_capacity(p, c) for p in self.listen_profiles]
            self.scale_sum += float(lo.sum())
            self.scale_count += self.n
        super().install_plan()
        if self.joint_listening:
            floor = self.c['period_rounds']*self.listen_scale*demand
            # The second lexicographic stage uses the original scalar solver.
            # Both lower bounds have finite bisection precision.
            bad = self.extra + self.c['battery_j']/2**15+1e-9 < floor
            if no_floor:
                bad = np.zeros_like(bad, dtype=bool)
            self.joint_floor_failures += int(bad.sum())
            if bad.any():
                raise AssertionError('Joint plan lost its feasible communication floor')

    def metrics(self):
        row = super().metrics()
        row.update(method=self.joint_label,
            mean_listen_fraction=self.scale_sum/self.scale_count if self.scale_count else 1.,
            joint_floor_violations=self.joint_floor_failures)
        return row
