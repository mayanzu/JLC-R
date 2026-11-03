"""Equivalent JOINT/LISTEN routing without unused DRL feature construction.

The baseline receiver cache and greedy scores do not change within a node's
turn. Cache candidate scores once, but repeat sender and hold affordability
checks on every action. Physical transactions still use the original attempt.
"""
from followup_model import FollowupSimulator

class FastFollowupSimulator(FollowupSimulator):
    def choose_packet(self,i):
        if self.policy not in ('LISTEN','JOINT'):return super().choose_packet(i)
        queue=self.queues[i]
        if self.priority:
            for index,packet in enumerate(queue):
                if self.holds.get(packet.sequence,(-1,0))[0]==i:
                    if index:
                        queue.rotate(-index);selected=queue.popleft();queue.rotate(index);queue.appendleft(selected)
                    break
        return queue[0]

    def route(self,i,chset):
        if self.policy not in ('LISTEN','JOINT'):return super().route(i,chset)
        if not hasattr(self,'_routed_round') or self._routed_round!=self.t:
            self._routed_round=self.t;self._start_quota=self.quota.copy()
            self._start_battery=self.battery.copy();self.admitted.clear()
            self.emit('round_ready',states=[self.state(k) for k in range(self.n)])
        if self.off[i]:
            if self.queues[i]:self.block(self.queues[i][0],i,-1,'sender_energy')
            return
        c=self.c;candidates=[]
        if i in chset:
            erx=c['packet_bits']*(c['elec_j_per_bit']+c['aggregate_j_per_bit'])
            for j in self.neighbors[i]:
                j=int(j)
                if j<self.n and (self.cached_off[j] or self.cached_battery[j]<erx+c['reserve_j'] or self.cached_quota[j]<erx):continue
                tail=0 if j==self.n else .04*self.cached_queue[j]+.15/(self.cached_battery[j]+.15)
                score=1/self.prob[i,j]+self.rank[j]+tail
                candidates.append((score,j,self.tx_energy(i,j)))
            candidates.sort(key=lambda item:item[0])
        for _ in range(c['max_ch_actions_round']):
            if not self.queues[i]:break
            packet=self.choose_packet(i)
            if i not in chset:j=int(self.parent[i])
            else:
                available=self.available(i,packet)
                j=next((receiver for _,receiver,cost in candidates if self.battery[i]>=cost+c['reserve_j'] and self.quota[i]>=cost and available>=cost),None)
                if j is None:self.block(packet,i,-1,self.no_action_reason(i));break
            ok,why=self.attempt(i,j,packet)
            if ok:self.queues[i].popleft()
            elif why!='link_loss' or packet.round_tries>=c['max_link_attempts']:
                self.stats['stopped_nonlink']+=1;break
        else:
            if self.queues[i]:self.block(self.queues[i][0],i,-1,'action_limit')
