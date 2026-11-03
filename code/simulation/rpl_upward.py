"""Relevant RFC6550 upward operation with the complete LANTERN OF.

MOP0 intentionally has no downward DAO. This is not an IPv6-stack conformance
claim. All neighbor state is learned from delivered DIOs, never global ranks.
"""
from dataclasses import dataclass
from collections import Counter
import math,struct
from lantern_policy import LanternPolicy,DIO

INF=65535;MIN_HOP=256;ROOT_RANK=256
def increment(v):return (v+1)&(255 if v>=128 else 127)
def compare(a,b):
    if a==b:return 0
    if a>=128>b:return -1 if 256+b-a<=16 else 1
    if b>=128>a:return 1 if 256+a-b<=16 else -1
    if a<128 and b<128:
        if 0<(a-b)%128<=16:return 1
        if 0<(b-a)%128<=16:return -1
        return None
    if abs(a-b)>16:return None
    return 1 if a>b else -1

@dataclass(frozen=True)
class Advertisement:
    sender:int
    version:int
    rank:int
    battery_margin:float
    eema:float
    max_q:float
    sequence:int=0
    def wire(self,k=10):
        header=struct.pack('!HHI',self.sender,1,self.sequence)
        base=struct.pack('!BBHBBBB16s',0,self.version,self.rank,0x80,0,0,0,(1).to_bytes(16,'big'))
        config=bytes([4,14])+struct.pack('!BBBBHHHBBH',0,8,12,k,1792,256,0xffff,0,30,60)
        return header+base+config+struct.pack('!ddd',self.battery_margin,self.eema,self.max_q)
    @classmethod
    def decode(cls,payload):
        if len(payload)!=72:raise ValueError('bad DIO length')
        sender,kind,sequence=struct.unpack('!HHI',payload[:8])
        instance,version,rank,flags,dtsn,r1,r2,dodag=struct.unpack('!BBHBBBB16s',payload[8:32])
        if kind!=1 or instance!=0 or flags!=0x80 or dodag!=(1).to_bytes(16,'big') or payload[32:34]!=bytes([4,14]):
            raise ValueError('ineligible instance/DODAG/configuration')
        margin,eema,q=struct.unpack('!ddd',payload[48:72])
        if not all(math.isfinite(x) for x in [margin,eema,q]):raise ValueError('nonfinite DIO')
        return cls(sender,version,rank,margin,eema,q,sequence)

class UpwardRPL:
    def __init__(self,node,*,root,capacity_j,maximum_reward,seed,ttl_s=4045.728):
        self.node=node;self.root=root;self.version=240 if node==root else None
        self.rank=ROOT_RANK if node==root else INF;self.lowest=self.rank
        self.parent=None;self.neighbors={};self.ttl=ttl_s;self.counts=Counter()
        self.poison_pending=False;self.repair_release=0.;self.parent_changes=[]
        self.policy=LanternPolicy(node,capacity_j=capacity_j,maximum_reward=maximum_reward,seed=seed)
    def detach(self,now):
        if self.rank!=INF or self.parent is not None:
            self.counts['local_repairs']+=1;self.poison_pending=self.version is not None
        self.rank=INF;self.parent=None;self.repair_release=now
    def _expire(self,now):
        expired=[j for j,(a,at) in self.neighbors.items() if now-at>self.ttl]
        for j in expired:self.neighbors.pop(j);self.policy.q.pop(j,None);self.counts['expired_neighbors']+=1
    def eligible(self,now):
        self._expire(now)
        if self.poison_pending or now<self.repair_release:return []
        return [j for j,(a,at) in self.neighbors.items() if a.version==self.version and a.rank<self.rank and a.rank<INF]
    def select(self,now,*,explore=True):
        if self.node==self.root:return None
        candidates=self.eligible(now)
        if not candidates:
            self.detach(now);return None
        if explore:p=self.policy.select_parent(candidates)
        elif self.parent in candidates:p=self.parent
        else:p=max(candidates,key=lambda j:(self.policy.q.get(j,0.),-j))
        if p is None:return None
        rank=self.neighbors[p][0].rank+MIN_HOP
        if rank>=INF or (self.lowest<INF and rank>self.lowest+1792):
            self.detach(now);self.counts['rank_increase_limit']+=1;return None
        old=self.parent;self.parent=p;self.rank=rank;self.lowest=min(self.lowest,rank)
        if old!=p:self.counts['parent_changes']+=1;self.parent_changes.append((now,old,p))
        return p
    def receive(self,a,now):
        if a.sender==self.node or self.node==self.root:return 'ignored'
        relation=1 if self.version is None else compare(a.version,self.version)
        if relation is None or relation<0:return 'stale_version'
        joined=relation>0
        if joined:
            self.version=a.version;self.neighbors.clear();self.policy.q.clear();self.rank=INF;self.lowest=INF
            self.parent=None;self.poison_pending=False;self.repair_release=now;self.counts['versions_joined']+=1
        if a.rank>=INF:
            self.neighbors.pop(a.sender,None);self.policy.q.pop(a.sender,None)
            self.counts['poison_received']+=1
            if self.parent==a.sender:
                self.parent=None
                if not self.eligible(now):self.detach(now)
                else:self.select(now,explore=False)
            return 'poison'
        self.neighbors[a.sender]=(a,now)
        if self.rank==INF and not self.poison_pending and now>=self.repair_release:
            proposed=a.rank+MIN_HOP
            if proposed<INF and (self.lowest==INF or proposed<=self.lowest+1792):
                self.rank=proposed;self.lowest=min(self.lowest,proposed)
        if a.rank<self.rank and not self.poison_pending:
            self.policy.receive(DIO(a.sender,a.rank,a.battery_margin,a.eema,a.max_q,math.floor(now/10)*10,a.sender==self.root),
                                now_s=now,own_rank=self.rank)
            self.counts['Q_updates']+=1;self.select(now)
        return 'joined' if joined else 'consistent'
    def mark_reachable(self,j,now):
        # A paid successful unicast/ACK is positive link confirmation. It
        # refreshes liveness only, never the cached battery/EEMA/Q metrics.
        if j in self.neighbors:
            a,last_contact=self.neighbors[j]
            self.neighbors[j]=(a,max(last_contact,now))
            self.counts['data_reachability_refreshes']+=1
    def failed_neighbor(self,j,now):
        self.neighbors.pop(j,None);self.policy.q.pop(j,None);self.counts['NUD_removed']+=1
        if self.parent==j:
            self.parent=None
            if not self.eligible(now):self.detach(now)
            else:self.select(now,explore=False)
    def poison_sent(self,now):
        self.poison_pending=False;self.repair_release=now+4.096;self.counts['poison_sent']+=1
    def advertisement(self,battery,eema,sequence,now):
        valid=self.eligible(now) if self.rank<INF else []
        maximum=max((self.policy.q.get(j,0.) for j in valid),default=0.)
        return Advertisement(self.node,self.version if self.version is not None else 240,
            self.rank,battery-self.policy.minimum_battery,eema,maximum,sequence)
    def check_local(self,now):
        valid=self.eligible(now)
        if self.parent is not None:
            assert self.parent in valid
            assert self.neighbors[self.parent][0].rank<self.rank
        if self.rank<INF and self.lowest<INF:assert self.rank<=self.lowest+1792

def rank_error(packet,sender_rank,receiver_rank):
    # RFC6550 Sec11.2.2.2 permits one rank inconsistency, drops the second.
    # Equal ranks cannot be an upward parent either, so handle conservatively.
    if sender_rank<=receiver_rank:
        if getattr(packet,'rpl_rank_error',False):return 'drop'
        packet.rpl_rank_error=True;return 'marked'
    return 'consistent'
