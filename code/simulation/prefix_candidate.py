"""PF2: bounded feedback only under an unchanged full robust prefix plan."""
from pathlib import Path
import numpy as np
from feedback_base import Candidate as FeedbackBase,JLCR,PROJECT,SIM
HERE=Path(__file__).resolve().parent

class Candidate(FeedbackBase):
    def __init__(self,*a,variant='PF2',**k):
        self.pf_enabled=variant=='PF2'
        self.pf_filter=False
        super().__init__(*a,variant='F2' if self.pf_enabled else 'off',**k)

    def observe(self,i):
        obs,mask,ids=super().observe(i)
        if self.pf_filter:
            c=self.c;ph=self.phase(self.t)
            erx=c['packet_bits']*(c['elec_j_per_bit']+c['aggregate_j_per_bit'])
            for k in np.flatnonzero(mask[:-1]):
                j=int(ids[k])
                if j==self.n:continue
                nxt=int(self.reference_next[ph][j])
                fwd=self.tx_energy(j,nxt)+(self.control_cost(j,nxt)[0] if nxt<self.n else 0.)
                need=self.control_cost(i,j)[1]+erx+fwd
                if self.cached_battery[j]<c['reserve_j']+need or self.cached_quota[j]<need:
                    mask[k]=False;self.dev['pf_cached_transaction_filtered']+=1
        return obs,mask,ids

    def extra_actions(self,i,chset):
        if not self.pf_enabled or i not in chset:return
        if self.fdc_active[i] or self.listen_scale[i]<1-1e-12:
            self.dev['pf_not_full_prefix']+=1
            return
        self.dev['pf_full_prefix_gate']+=1
        self.pf_filter=True
        try:return super().extra_actions(i,chset)
        finally:self.pf_filter=False

    def metrics(self):
        m=super().metrics();m['development_variant']='PF2' if self.pf_enabled else 'off'
        return m
