"""Demand-triggered complete guard protection; existing causal information only."""
from pathlib import Path
from collections import Counter
from guard_controls import PGuard,JLCR,PROJECT,SIM
from dependencies import reference_upstreams,cached_ready
HERE=Path(__file__).resolve().parent

class Candidate(PGuard):
    def __init__(self,*a,trigger_mode='heard',**k):
        self.tg_mode=trigger_mode;self.tg_receipts={};self.tg_counts=Counter()
        super().__init__(*a,variant='PF2',**k)
    def trigger(self,j):
        if self.tg_mode=='always':return True
        if self.tg_mode=='none':return False
        refs=reference_upstreams(self,j)
        reference_ready=any(cached_ready(self,u,j) for u in refs)
        history_ready=False
        if self.tg_mode=='heard':
            epoch=self.t//self.c['period_rounds'];heads=set(map(int,self.ch))
            history_ready=any(receiver==j and heard_epoch==epoch and u in heads and
                j in self.neighbors.get(u,[]) and cached_ready(self,u,j)
                for (u,receiver),heard_epoch in self.tg_receipts.items())
        if reference_ready:self.tg_counts['reference_ready_requests']+=1
        elif history_ready:self.tg_counts['history_only_ready_requests']+=1
        else:self.tg_counts['inactive_requests']+=1
        return reference_ready or history_ready
    def request_grant(self,i,j,packet):
        before=int(self.slots_used[j]);result=self._guard_exchange(i,j,packet)
        if i in self.ch and j in self.ch and self.slots_used[j]>before:
            self.tg_receipts[int(i),int(j)]=self.t//self.c['period_rounds']
            self.tg_counts['paid_upstream_responses']+=1
        return result
    def _guard_exchange(self,i,j,packet):
        if not self.gr4_enabled or self.v63_mechanism not in ('relay_repair','B'):
            return super().request_grant(i,j,packet)
        c=self.c;etx=self.tx_energy(i,j)
        fresh=self.last_message[j]==self.t
        erx=c['packet_bits']*(c['elec_j_per_bit']+c['aggregate_j_per_bit'])
        if fresh and (self.cached_off[j] or self.cached_quota[j]<erx):
            self.block(packet,i,j,'known_receiver_unavailable');return False,0.
        si,rj=self.control_cost(i,j)
        if self.available(i,packet)<etx+si:
            self.block(packet,i,j,'sender_credit');return False,0.
        self.use_slot(i,packet);self.fee_control(i,si,packet)
        if self.off[j] or self.available(j)<rj or self.slots_left[j]-self.forward_slot_holds[j]<=0:
            self.denied+=1;self.block(packet,i,j,'grant_denied');return False,0.
        nxt=int(self.reference_next[self.phase(self.t)][j])
        forward=self.tx_energy(j,nxt)
        if nxt<self.n:forward+=self.control_cost(j,nxt)[0]
        chset=set(self.ch.tolist())
        if i not in chset and j in chset:
            protect=int(self.transit_reserve[j])
            free=self.slots_left[j]-self.forward_slot_holds[j]
            original_guard_bad=free-1<protect
            energy_bad=self.available(j)-rj-(erx+forward)<protect*self.transit_unit_j[j]
            full_guard_bad=protect>0 and self.trigger(j) and free<2+2*protect
            if protect:self.gr4_counts['protected_member_requests']+=1
            if original_guard_bad or energy_bad or full_guard_bad:
                if full_guard_bad and not original_guard_bad and not energy_bad:
                    self.gr4_counts['additional_slot_only_denials']+=1
                self.denied+=1;self.transit_protect_denials+=1
                self.block(packet,i,j,'transit_protect');return False,0.
        self.use_slot(j);self.fee_control(j,rj)
        if self.available(j)<erx+forward or self.slots_left[j]-self.forward_slot_holds[j]<1:
            self.denied+=1;self.block(packet,i,j,'forward_reserve');return False,0.
        self.granted+=1;return True,forward
    def metrics(self):
        m=super().metrics();m['trigger_guard_counts']=dict(self.tg_counts)
        m['development_variant']={'reference':'RGP','heard':'HGP','always':'PG4','none':'PF2'}[self.tg_mode]
        return m

def make(c,sc,bank,variant):
    if variant=='JLC':return JLCR(c,sc,bank,v63_mechanism='relay_repair')
    mode={'RGP':'reference','HGP':'heard','PG4':'always','PF2':'none'}[variant]
    return Candidate(c,sc,bank,trigger_mode=mode,v63_mechanism='relay_repair')
