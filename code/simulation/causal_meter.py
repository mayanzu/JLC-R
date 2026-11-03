"""Previous-completed900s-rate input estimates for original10s EEMA.

Only the information interface is adapted. No physical energy is redistributed
or credited. Both harvested and consumed energy use the same causal lag.
"""
import numpy as np
class CausalRateMeter:
    def __init__(self,n):
        self.eema=np.zeros(n);self.harvest_component=np.zeros(n);self.consumption_component=np.zeros(n)
        self.h10=np.zeros(n);self.c10=np.zeros(n);self.until=0.;self.rates_observed_until=0.
    def advance(self,until_s):
        if until_s<self.until-1e-9:raise ValueError('noncausal meter clock')
        count=int((until_s-self.until+1e-9)//10)
        if count:
            a=.5**count;gain=2*(1-a)
            self.harvest_component=a*self.harvest_component+gain*self.h10
            self.consumption_component=a*self.consumption_component+gain*self.c10
            self.eema=self.harvest_component-self.consumption_component
            self.until+=10*count
        return self.eema
    def commit(self,completed_until_s,harvest_j,consumed_j):
        if abs(completed_until_s-self.rates_observed_until-900)>1e-9:raise ValueError('need next completed900s ledger')
        if self.until<completed_until_s-1e-9:raise ValueError('advance old rates to boundary before replacing')
        h=np.asarray(harvest_j,float);c=np.asarray(consumed_j,float)
        if not np.isfinite(h).all() or not np.isfinite(c).all() or h.min()<0 or c.min()<-1e-10:raise ValueError('invalid ledger')
        self.h10=h/90;self.c10=np.maximum(c,0)/90;self.rates_observed_until=completed_until_s
