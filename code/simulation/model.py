"""Result-informed operating-regime redesign; common newest-first controls."""
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
from validation_model import ValidationSimulator, StreamingBank, ScenarioV2, DEFAULTS

CASES = {'REFERENCE': (4, 4000), 'LONG': (24, 4000),
         'DATA': (4, 32000), 'TARGET': (24, 32000)}
POLICIES = ['JLC-R-FIXED', 'POINT', 'POINT-D050', 'LISTEN', 'LPL-MATCH', 'BENO(0.4)']
SEEDS = [1101, 1202]
SUPPLIES = [1., .7]


def configuration(base, case):
    epoch, payload = CASES[case]
    c = dict(base)
    c.update(period_rounds=epoch, packet_bits=payload,
             control_j_per_node_period=base['control_j_per_node_period']*
                 epoch/base['period_rounds'])
    return c


class ModelSimulator(ValidationSimulator):
    def __init__(self, c, sc, bank, policy):
        if policy not in POLICIES:
            raise ValueError(policy)
        self.model_policy = policy
        mapped = {'JLC-R-FIXED': 'JOINT-NEWEST', 'POINT': 'JOINT-NEWEST',
                  'POINT-D050': 'JOINT-NEWEST', 'LISTEN': 'LISTEN',
                  'LPL-MATCH': 'LPL-MATCH', 'BENO(0.4)': 'BATTERY-ENO-0.4'}[policy]
        super().__init__(c, sc, bank, mapped)
        if policy.startswith('POINT'):
            self.prediction_mode = 'P'
        self.method = self.variant = policy

    def install_plan(self):
        super().install_plan()
        if self.model_policy == 'POINT-D050':
            removed = .5*self.extra
            self.extra -= removed
            self.issued_credit -= float(removed.sum())
            self.cmax -= removed
            self.credit -= removed

    def choose_packet(self, i):
        queue = self.queues[i]
        committed = ([p for p in queue if self.holds.get(p.sequence, (-1, 0))[0] == i]
                     if self.priority else [])
        selected = max(committed or queue, key=lambda p: (p.birth, -p.sequence))
        index = next(k for k, p in enumerate(queue) if p.sequence == selected.sequence)
        queue.rotate(-index); queue.popleft(); queue.rotate(index); queue.appendleft(selected)
        return selected

    def metrics(self):
        row = super().metrics()
        issued = row['issued_extra_credit_j']
        used = issued-row['unused_extra_credit_j']
        row.update(method=self.model_policy, used_extra_credit_j=used,
            extra_credit_utilization_pct=100*used/issued if issued else 0.,
            communication_energy_fraction_pct=100*row['comm_consumed_j']/row['consumed_j'],
            operational_epoch_rounds=self.c['period_rounds'], logical_bits=self.c['packet_bits'])
        return row
