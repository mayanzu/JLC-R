"""PADC's unmodified duty rule with the candidate's local-age selector.

This stronger matched control tests whether slot-valued planning adds value
beyond donating the new scheduler to the best recent winter-coverage control.
"""
import numpy as np

from recent_baselines import DutyControlSimulator
from optimized_model import OptimizedSimulator


class MatchedAgeDutySimulator(DutyControlSimulator):
    def __init__(self, c, sc, bank):
        super().__init__(c, sc, bank, 'PADC-DC')
        self.age_scheduling = True
        self.local_forwarded_birth = np.full((self.n, self.n), -1, dtype=int)

    choose_packet = OptimizedSimulator.choose_packet

    def attempt(self, i, j, packet):
        result = super().attempt(i, j, packet)
        if result[0]:
            self.local_forwarded_birth[i, packet.source] = max(
                self.local_forwarded_birth[i, packet.source], packet.birth)
        return result

    def metrics(self):
        row = super().metrics()
        row.update(method='PADC-AGE', local_age_scheduling=1)
        return row
