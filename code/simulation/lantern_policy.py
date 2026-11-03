"""LANTERN Algorithms 1--2 / Eqs. (2),(4),(5): decision-kernel reimplementation.

Source: Taghizadeh et al., IEEE TNSM 21(6), 2024,
10.1109/TNSM.2024.3450011, author-uploaded manuscript.
This is NOT an admitted whole-network baseline. The host must implement paid
RPL DIO exchange, dynamic DODAG maintenance, radio execution and the 10-second
causal energy meter. No JLC-R module is imported or used here.
"""
from dataclasses import dataclass
import math
import random


@dataclass(frozen=True)
class DIO:
    sender: int
    rank: float
    battery_minus_minimum: float
    eema: float
    max_q: float
    measured_until_s: float
    root: bool = False


class LanternPolicy:
    def __init__(self, node, *, capacity_j, maximum_reward,
                 alpha=0.5, epsilon=0.2, gamma=0.8, seed=0):
        # MaximumReward is a required explicit input: its numerical value is
        # not established by the accessed manuscript excerpts.
        values=(capacity_j, maximum_reward, alpha, epsilon, gamma)
        if not all(math.isfinite(x) for x in values):
            raise ValueError('nonfinite parameter')
        if maximum_reward <= 0 or capacity_j <= 0:
            raise ValueError('invalid energy/reward parameter')
        if not (0 < alpha <= 1 and 0 <= epsilon <= 1 and 0 <= gamma < 1):
            raise ValueError('invalid learning parameter')
        self.node=node; self.maximum_reward=maximum_reward
        self.minimum_battery=0.1*capacity_j
        self.turn_on_battery=0.2*capacity_j
        self.enabled=True
        self.alpha=alpha; self.epsilon=epsilon; self.gamma=gamma
        self.rng=random.Random(seed); self.q={}; self.eema=0.0
        self.harvest_component=0.0;self.consumption_component=0.0
        self.intervals=0; self.measured_until_s=0.0

    def update_power_state(self,battery_j):
        """Source Sec.V/TableII: 10% off / 20% on battery hysteresis.

        This policy gate does not spend energy. The shared host must still
        charge sleep/off energy and prevent unaffordable physical actions.
        """
        if not math.isfinite(battery_j) or battery_j<0:
            raise ValueError('invalid battery')
        if self.enabled and battery_j<=self.minimum_battery:self.enabled=False
        elif not self.enabled and battery_j>=self.turn_on_battery:self.enabled=True
        return self.enabled

    def meter(self, harvested_j, consumed_j, *, until_s):
        """Alg.1: accept completed 10-second intervals, never future energy."""
        if not all(math.isfinite(x) for x in (harvested_j,consumed_j,until_s)):
            raise ValueError('nonfinite energy meter')
        if harvested_j < 0 or consumed_j < 0:
            raise ValueError('negative measured energy')
        if abs(until_s-self.measured_until_s-10.0)>1e-9:
            raise ValueError('LANTERN requires a completed 10-second interval')
        delta=harvested_j-consumed_j
        self.eema=(0.5*self.eema if self.intervals else 0.0)+delta
        # Diagnostic decomposition only; not read by routing decisions.
        self.harvest_component=(.5*self.harvest_component if self.intervals else 0.)+harvested_j
        self.consumption_component=(.5*self.consumption_component if self.intervals else 0.)+consumed_j
        self.intervals+=1; self.measured_until_s=until_s
        return self.eema

    def receive(self, dio, *, now_s, own_rank):
        """Alg.2 Q update after receipt of a causally available paid DIO.

        Rank filtering is the host RPL contract, not a JLC reference route.
        The minus sign follows Eq.(4) and Alg.2 line24; line9's parenthetic
        plus-sign comment is inconsistent with those two source statements.
        """
        if not self.enabled:return False
        vals=(dio.rank,dio.battery_minus_minimum,dio.eema,dio.max_q,
              dio.measured_until_s,now_s)
        if not all(math.isfinite(x) for x in vals):
            raise ValueError('nonfinite DIO')
        if dio.measured_until_s>now_s:
            raise ValueError('future DIO rejected')
        if dio.sender==self.node or dio.rank>=own_rank:
            return False
        reward=self.maximum_reward if dio.root else dio.battery_minus_minimum+dio.eema
        old=self.q.get(dio.sender,0.0)
        self.q[dio.sender]=(1-self.alpha)*old+self.alpha*(reward+self.gamma*dio.max_q)
        return True

    def select_parent(self, eligible_senders):
        """Epsilon-greedy selection over the current dynamic RPL parent set."""
        if not self.enabled:return None
        ids=sorted(set(eligible_senders)&self.q.keys())
        if not ids:return None
        if self.rng.random()<=self.epsilon:return self.rng.choice(ids)
        return max(ids,key=lambda i:(self.q[i],-i))

    def advertisement(self, battery_j, rank):
        if not math.isfinite(battery_j) or battery_j<0:
            raise ValueError('invalid battery')
        return DIO(self.node,rank,battery_j-self.minimum_battery,self.eema,
                   max(self.q.values(),default=0.0),self.measured_until_s)
