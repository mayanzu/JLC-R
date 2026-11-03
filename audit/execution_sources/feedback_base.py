"""Development candidates. Frozen kernel and physical parameters are unchanged."""
import sys
from collections import Counter
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[2]
SIM=PROJECT/'code/simulation'
sys.path.insert(0,str(SIM))
from jlc_r import JLCR
from diagnostic import battery_path, budget_caps


class Candidate(JLCR):
    def __init__(self,*args,variant='off',**kwargs):
        self.dev_variant=variant
        self.dev=Counter()
        self.cap_t=-1
        self.cap_cost=None
        self.cap_min_margin=float('inf')
        self.cap_max_floor_deficit=0.
        self.actions=0
        self.failed_pairs=set()
        self.failed_receivers=set()
        self.last_action=None
        self.last_block=None
        super().__init__(*args,**kwargs)

    def base_profile(self,t,low=None):
        base=super().base_profile(t,low)
        if getattr(self,'cap_t',-1)==t:
            base=base.copy()
            base[:,:self.c['period_rounds']]+=self.cap_cost[:,None]
        return base

    def install_plan(self):
        super().install_plan()
        if self.dev_variant not in ('C','CF2'):
            return
        c=self.c;p=c['period_rounds'];ph=self.phase(self.t)
        old=np.asarray(self.runtime_cap_profiles[ph]).copy()
        ref=self.reference_slots[ph]
        eligible=(~self.fdc_active)&(old<ref)
        if not eligible.any():return
        base=super().base_profile(self.t).copy()
        _,paths,_,_=self.bank.entries[self.t]
        demand=self.phase_structures[ph][2]+self.grant_profiles[ph]
        w=c['radio_idle_w']*c['guard_listen_s']
        def feasible(k):
            floor=p*demand*k/np.maximum(ref,1)
            cost=base.copy()
            cost[:,:p]+=(w*(k-old)+floor/p)[:,None]
            m,_,_=battery_path(self.battery,c['battery_j'],paths,cost,c['reserve_j'])
            return (m>=-1e-10).all(axis=0)&(floor<=c['battery_j']+1e-10)
        lo=old.copy();hi=np.where(eligible,ref+1,old+1)
        while (hi-lo>1).any():
            active=(hi-lo>1)&eligible
            mid=(hi+lo)//2
            good=feasible(mid)&active
            lo=np.where(good,mid,lo)
            hi=np.where(active&~good,mid,hi)
        added=lo-old
        changed=added>0
        if not changed.any():return
        assert not (changed&self.fdc_active).any()
        newbase=base.copy();delta=w*added
        newbase[:,:p]+=delta[:,None]
        floor=p*demand*lo/np.maximum(ref,1)
        cap,_,_,_,_=budget_caps(self.battery,c['battery_j'],c['reserve_j'],paths,newbase,p,'PREFIX')
        newextra=self.extra.copy()
        # Exact feasible floor can lie just above the finite scalar bisection.
        newextra[changed]=np.maximum(cap[changed],floor[changed])
        certcost=newbase.copy();certcost[:,:p]+=newextra[:,None]/p
        margin,_,_=battery_path(self.battery,c['battery_j'],paths,certcost,c['reserve_j'])
        cert=float(margin[:,changed].min())
        assert cert>=-1e-10,(self.t,cert)
        self.cap_min_margin=min(self.cap_min_margin,cert)
        self.cap_max_floor_deficit=max(self.cap_max_floor_deficit,float(np.maximum(floor[changed]-newextra[changed],0).max()))
        self.dev['cap_node_periods']+=int(changed.sum())
        self.dev['cap_guard_node_rounds']+=int(added.sum())*p
        self.dev['cap_credit_change_j']+=float((newextra-self.extra).sum())
        self.issued_credit+=float((newextra-self.extra).sum())
        self.extra=newextra
        self.cap_t=self.t;self.cap_cost=delta
        self.cmax=newbase[:,:p].sum(axis=1)+newextra
        self.credit=self.cmax.copy()
        self.planned_floor[changed]=floor[changed]
        newlisten=c['sync_listen_s']+c['guard_listen_s']*lo
        self.plan_profiles[ph]=newlisten.copy()
        self.listen_profiles[ph]=newlisten.copy()
        self.actual_profiles[ph]=newlisten.copy()
        self.runtime_cap_profiles[ph]=lo.copy()
        self.scale_sum+=float((added/np.maximum(ref,1)).sum())

    def choose_packet(self,i):
        self.actions+=1
        return super().choose_packet(i)

    def block(self,packet,i,j,reason):
        self.last_block=(int(j),reason)
        return super().block(packet,i,j,reason)

    def attempt(self,i,j,packet):
        result=super().attempt(i,j,packet)
        self.last_action=result
        if not result[0]:
            self.failed_pairs.add((packet.sequence,int(j)))
            # Endpoint-local paid denial is independent of which queued packet
            # is next. Sender credit and link failures are NOT peer denials.
            if j<self.n and packet.last_reason in ('grant_denied','forward_reserve','transit_protect'):
                self.failed_receivers.add(int(j))
                self.dev['receiver_denial_feedback']+=1
        return result

    def extra_actions(self,i,chset):
        # Only cache values, own resources and received denial feedback are used.
        for _ in range(2):
            if self.actions>=self.c['max_ch_actions_round'] or self.off[i] or not self.queues[i]:break
            q=list(self.queues[i])
            held=[p for p in q if self.holds.get(p.sequence,(-1,0))[0]==i]
            pool=held or q
            if i in chset:
                _,mask,ids=self.observe(i)
                choices=[int(ids[k]) for k in np.flatnonzero(mask[:-1])]
            else:choices=[int(self.parent[i])]
            choices=[j for j in choices if j not in self.failed_receivers]
            cutoff=self.t-self.c['deadline_rounds']+1
            selected=None
            for packet in sorted(pool,key=lambda x:self._priority_tuple(i,x,cutoff),reverse=True):
                if packet.finalized or self.t-packet.birth>=self.c['deadline_rounds']:continue
                if packet.last_try_round==self.t and packet.round_tries>=self.c['max_link_attempts']:continue
                if self.slots_left[i]-self.forward_slot_holds[i]+int(packet.sequence in self.hold_slots)<=0:continue
                allowed=[j for j in choices if (packet.sequence,j) not in self.failed_pairs and
                    self.available(i,packet)>=self.tx_energy(i,j)+(self.control_cost(i,j)[0] if j<self.n else 0.)]
                if not allowed:continue
                def score(j):
                    return 1/self.prob[i,j]+self.rank[j]+(0 if j==self.n else .04*self.cached_queue[j]+.15/(self.cached_battery[j]+.15))
                selected=packet,min(allowed,key=score)
                break
            if selected is None:break
            packet,j=selected;self.actions+=1
            self.dev['extra_attempts']+=1
            ok,why=self.attempt(i,j,packet)
            if ok:
                self.queues[i].remove(packet)
                self.dev['extra_successful_hops']+=1
            else:self.dev['extra_'+why]+=1

    def route(self,i,chset):
        self.actions=0;self.failed_pairs=set();self.failed_receivers=set()
        self.last_action=None;self.last_block=None
        super().route(i,chset)
        if self.dev_variant not in ('F2','CF2') or not self.queues[i] or self.off[i]:return
        if self.actions>=self.c['max_ch_actions_round']:return
        no_choice=self.last_block is not None and self.last_block[0]==-1
        if no_choice or self.last_action is None or self.last_action[0] or self.last_action[1]!='link_loss':
            self.extra_actions(i,chset)

    def metrics(self):
        m=super().metrics()
        m.update(development_variant=self.dev_variant,dev_counts=dict(self.dev),
            cap_min_prefix_margin_j=self.cap_min_margin if np.isfinite(self.cap_min_margin) else None,
            cap_max_floor_deficit_j=self.cap_max_floor_deficit)
        return m
