"""Experimental topology-weighted source competition; public JLCR unchanged."""
import numpy as np

from packet_funded import PacketFundedJLCR
from source_protection import SourceProtectedJLCR


class TopologyWeightedJLCR(SourceProtectedJLCR):
    def __init__(self,*args,**kwargs):
        if 'source_protection' in kwargs:
            raise ValueError('This experimental class fixes its admission policy')
        super().__init__(*args,source_protection='admission',**kwargs)
        distance=np.linalg.norm(self.sc.pos-self.sc.sink,axis=1)
        self.origin_hops=np.maximum(1,np.ceil(distance/self.c['range_m']).astype(int))

    def source_debt(self,node,source):
        cutoff=self.t-self.c['deadline_rounds']+1
        return max(0,int(cutoff-self.local_forwarded_birth[node,source]))*int(self.origin_hops[source])

    def _held_sources(self,node):
        return {p.source for p in self.queues[node] if self.holds.get(p.sequence,(-1,0))[0]==node}

    def _protected_packet(self,node):
        if self.protected_attempt_round[node]==self.t:return None
        cutoff=self.t-self.c['deadline_rounds']+1
        held=self._held_sources(node)
        eligible=[p for p in self.queues[node] if not p.finalized and p.birth>=cutoff
            and p.source not in held and self.local_forwarded_birth[node,p.source]<cutoff
            and (p.last_try_round!=self.t or p.round_tries<self.c['max_link_attempts'])]
        return max(eligible,key=lambda p:(self.source_debt(node,p.source),p.birth,-p.source,-p.sequence)) if eligible else None

    def _guard_exchange(self,sender,receiver,packet):
        waiting=self._protected_packet(receiver)
        if (waiting is not None and waiting.source!=packet.source
                and packet.source not in self._held_sources(receiver)
                and self.source_debt(receiver,packet.source)>self.source_debt(receiver,waiting.source)):
            # The incoming source wins the one-source local priority comparison.
            # Its original onward hold represents that source's opportunity.
            # All packet-funding, transit and live physical checks still bind.
            self.protection_counts['higher_debt_incoming_source_selected']+=1
            return PacketFundedJLCR._guard_exchange(self,sender,receiver,packet)
        return super()._guard_exchange(sender,receiver,packet)

    def metrics(self):
        result=super().metrics()
        result['source_protection']='topology_weighted_development'
        result['source_protection_scope']='Experimental geometric-hop-weighted local forwarding debt; no global spatial guarantee'
        return result
