"""Independent validation adapters; all physical transaction kernels unchanged."""
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
from extension_model import ExtensionSimulator, StreamingBank, ScenarioV2, DEFAULTS
from review_model import ReviewSimulator
from service_model import radio_capacity

SEEDS = [60101 + 101*k for k in range(12)]
SUPPLIES = [1., .7]
CASES = {'BASE': {}, 'CLOUD7': {'test_forced_cloud_days': list(range(3, 10))},
         'PAYLOAD2': {'packet_bits': 8000}}
POLICIES = ['ADMIT-FIFO', 'LOCK-FIFO', 'PRIORITY-ONLY', 'JOINT',
            'JOINT-NEWEST', 'POINT', 'LISTEN', 'LPL-MATCH', 'BATTERY-ENO-0.4']


class ValidationSimulator(ExtensionSimulator):
    def __init__(self, c, sc, bank, policy='JOINT'):
        if policy not in POLICIES:
            raise ValueError(policy)
        self.validation_policy = policy
        base = policy if policy in ('LISTEN', 'LPL-MATCH') else 'JOINT'
        super().__init__(dict(c), sc, bank, base)
        self.variant = policy
        self.method = policy
        self.keep_lock = policy not in ('ADMIT-FIFO', 'PRIORITY-ONLY')
        self.priority = policy not in ('ADMIT-FIFO', 'LOCK-FIFO', 'LISTEN', 'LPL-MATCH')
        self.prediction_mode = 'P' if policy == 'POINT' else 'U'

    def install_plan(self):
        if self.validation_policy.startswith('BATTERY-ENO'):
            # Invoke the existing feedback planner, then restore the fast
            # routing label. Only diagnostic profiles need refreshing.
            saved = self.policy
            self.policy = self.validation_policy
            try:
                ReviewSimulator.install_plan(self)
            finally:
                self.policy = saved
            phase = self.phase(self.t)
            self.actual_profiles[phase] = self.listen_profiles[phase].copy()
            self.runtime_cap_profiles[phase] = radio_capacity(self.listen_profiles[phase], self.c)
        else:
            super().install_plan()

    def choose_packet(self, i):
        if self.validation_policy not in ('PRIORITY-ONLY', 'JOINT-NEWEST'):
            return super().choose_packet(i)
        queue = self.queues[i]
        committed = [p for p in queue if self.holds.get(p.sequence, (-1, 0))[0] == i or
                     (self.validation_policy == 'PRIORITY-ONLY' and p.sequence in self.admitted)]
        candidates = committed or queue
        selected = (max(candidates, key=lambda p: (p.birth, -p.sequence))
                    if self.validation_policy == 'JOINT-NEWEST' else candidates[0])
        index = next(k for k, p in enumerate(queue) if p.sequence == selected.sequence)
        queue.rotate(-index)
        queue.popleft()
        queue.rotate(index)
        queue.appendleft(selected)
        return selected


def configuration(base, case):
    return dict(base, **CASES[case])
