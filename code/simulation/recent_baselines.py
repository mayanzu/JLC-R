"""Recent duty-control rules in the common, charged multihop executor.

These are explicitly adapted control laws, not reproductions of complete MAC
stacks. See RECENT_BASELINES_SPEC.md for sources and the mapping contract.
"""
import numpy as np

from joint_model import JointSimulator
from service_model import radio_capacity


def heno_duty(remaining_fraction, energy_neutral):
    """HENO-MAC (2024), Table I and Eq. (6), fractions rather than percent.

    The discontinuity at 10% is in the published table; do not smooth it.
    """
    r = np.asarray(remaining_fraction, dtype=float)
    return np.where(np.asarray(energy_neutral) | (r >= .5), 1.,
                    np.where(r >= .1, (r - .1) / .9, .05))


def padc_duty(expected_fraction, predicted_energy, full_activity_energy):
    """PADC-MAC (2023), Table 3 and Eq. (5), normalized percent units.

    In addition to the 50% branch, prediction enables full duty only when
    expected storage is at least 30% AND predicted energy covers full activity.
    """
    r = np.asarray(expected_fraction, dtype=float)
    full = (r >= .5) | ((r >= .3) &
                        (np.asarray(predicted_energy) >= full_activity_energy))
    return np.where(full, 1., np.where(r >= .1, r/.9, .05))


class DutyControlSimulator(JointSimulator):
    """Share routing, newest/committed priority, grants and all physical costs.

    Only the listening decision and the communication-permission rule change.
    Nonbinding credit lets these controls use every physically affordable
    transaction, without importing JLC-R's prefix solver into their decisions.
    """
    def __init__(self, c, sc, bank, policy='HENO-DC'):
        if policy not in ['HENO-DC', 'PADC-DC']:
            raise ValueError(policy)
        super().__init__(c, sc, bank, 'JLC-R-FIXED')
        self.duty_policy = policy
        self.duty_sum = 0.
        self.duty_count = 0

    def install_plan(self):
        c = self.c
        # Completed metered interval only. Current-round harvest is unavailable.
        end = self.sc.warm + self.t
        past_rate = self.sc.observed[end-c['period_rounds']:end].mean(axis=0)
        ph = self.phase(self.t)
        full_base = (c['sleep_w']*c['round_seconds'] +
                     c['radio_idle_w']*(self.reference_listening[ph] +
                                            c.get('sync_extra_listen_s', 0.)) +
                     c['sense_j_per_bit']*c['packet_bits'] +
                     c['control_j_per_node_period']/c['period_rounds'])
        full_demand = self.phase_structures[ph][2] + self.grant_profiles[ph]
        point, _, self.rho, self.pred.multiplier = self.bank.entries[self.t]
        if self.duty_policy == 'HENO-DC':
            duty = heno_duty(self.battery/c['battery_j'],
                             past_rate >= full_base + full_demand)
        else:
            predicted = point[:, :c['period_rounds']].sum(axis=1)
            duty = padc_duty((self.battery + predicted)/c['battery_j'],
                             predicted, c['period_rounds']*(full_base + full_demand))
        self.listen_scale = duty
        self.listen_profiles = [c['sync_listen_s'] + duty*(p-c['sync_listen_s'])
                                for p in self.reference_listening]
        self.actual_profiles = [p.copy() for p in self.listen_profiles]
        self.runtime_cap_profiles = [radio_capacity(p, c) for p in self.listen_profiles]
        self._base_profiles.clear()
        # Same exogenous role/candidate installation, without a prefix solver.
        heads = self.phase_heads[ph]
        parent, rank, load = self.phase_structures[ph]
        changed = (np.zeros(self.n, bool) if self.last_parent is None else
                   parent != self.last_parent)
        self.reclusters += int(changed.any())
        self.changed += int(changed.sum())
        self.ch, self.parent, self.rank, self.expected_load = heads, parent, rank, load
        self.last_parent = parent.copy()
        self.extra = np.full(self.n, c['period_rounds']*c['battery_j'])
        self.issued_credit += float(self.extra.sum())
        self.periods += 1
        base = self.base_profile(self.t)[:, :c['period_rounds']].sum(axis=1)
        self.cmax = base + self.extra
        self.credit = self.cmax.copy()
        self.actual_period[:] = 0
        self.period_comm[:] = 0
        self.neighbors = {}
        for i in heads:
            vertices = np.r_[heads, self.n]
            eligible = vertices[self.adj[i, vertices] & (rank[vertices] < rank[i]-1e-9)]
            self.neighbors[int(i)] = np.sort(eligible)[:c['candidates']]
        self.duty_sum += float(duty.sum())
        self.duty_count += self.n

    def metrics(self):
        row = super().metrics()
        row.update(method=self.duty_policy,
                   mean_listen_fraction=self.duty_sum/self.duty_count,
                   permission_rule='nonbinding; physical battery/reserve/holds bind')
        return row
