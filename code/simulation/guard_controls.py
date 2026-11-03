"""Local complete-transit guard reservation; original energy and fees preserved."""
import sys
from collections import Counter
from pathlib import Path
HERE=Path(__file__).resolve().parent;PROJECT=HERE.parents[1];SIM=PROJECT/'code/simulation'
sys.path.insert(0,str(SIM))
from v63_model import RelayRepairHYB as JLCR
from prefix_candidate import Candidate as PF2

class FullTransitGuard:
    def __init__(self,*a,full_guard=True,**k):
        self.gr4_enabled=full_guard;self.gr4_counts=Counter()
        super().__init__(*a,**k)
    def request_grant(self,i,j,packet):
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
            full_guard_bad=protect>0 and free<2+2*protect
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
        m=super().metrics();m['complete_transit_guard_counts']=dict(self.gr4_counts);return m

class JGuard(FullTransitGuard,JLCR):pass
class PGuard(FullTransitGuard,PF2):pass

def make(c,sc,bank,variant):
    if variant=='JG4':return JGuard(c,sc,bank,v63_mechanism='relay_repair')
    if variant=='PG4':return PGuard(c,sc,bank,variant='PF2',v63_mechanism='relay_repair')
    raise ValueError(variant)
