"""Orthogonal mechanism probes layered on the common execution model."""
from __future__ import annotations
from collections import Counter
import numpy as np
from fast_execution import FastFollowupSimulator
from followup_model import StreamingBank,ScenarioV2,DEFAULTS
from diagnostic import battery_path
from service_model import ServiceSimulator,radio_capacity


def scalar_supremum(initial,capacity,reserve,harvest,base,period,tol=1e-10):
    """Independent min-of-affine battery construction, no bisection.

    Slopes are k/period, k=0..period. Saturation adds a zero-slope branch.
    Every preharvest prefix constrains every affine branch; hence the minimum
    positive-slope crossing is the exact real-arithmetic relaxed supremum.
    """
    m,n,h=harvest.shape
    intercept=np.full((period+1,m,n),np.inf)
    intercept[0]=np.broadcast_to(initial,(m,n))
    upper=np.full((m,n),capacity);viable=np.ones((m,n),bool)
    slopes=np.arange(period+1)/period
    for k in range(h):
        margin=intercept-base[None,None,:,k]-reserve
        coeff=slopes+(1/period if k<period else 0)
        for branch,weight in enumerate(coeff):
            if weight:
                upper=np.minimum(upper,(margin[branch]+tol)/weight)
            else:viable &= margin[branch]>=-tol
        # x=0 must satisfy the intersection, including positive-slope branches.
        viable &= np.min(margin,axis=0)>=-tol
        intercept += harvest[None,:,:,k]-base[None,None,:,k]
        if k<period:intercept[1:]=intercept[:-1].copy();intercept[0]=np.inf
        intercept[0]=np.minimum(intercept[0],capacity)
    good=viable.all(axis=0)
    return np.where(good,np.maximum(0,np.minimum(capacity,upper.min(axis=0))),0),good


class ExtensionSimulator(FastFollowupSimulator):
    def __init__(self,c,sc,bank,variant='JOINT'):
        self.variant=variant
        self.fixed_listen=variant=='FIXED'
        self.audit_gaps=[];self.plan_audit=[]
        self.envelopes=[];self.queue_observations=[];self.failure_cost=[]
        self.probe=Counter();self.deadline_fresh={d:0 for d in [2,4,8,16]}
        base_policy='LISTEN' if variant in ['FIXED','LISTEN','LPL-MATCH','LISTEN-CONSTANT','LISTEN-SHUFFLE'] else 'JOINT'
        super().__init__(c,sc,bank,base_policy)
        if variant=='POINT':self.prediction_mode='P'
        if variant=='LPL-MATCH':
            sums={role:[] for role in ['member','CH']}
            for heads,profile in zip(self.phase_heads,self.listen_profiles):
                mask=np.isin(np.arange(self.n),heads)
                sums['CH'].extend(profile[mask]);sums['member'].extend(profile[~mask])
            means={r:float(np.mean(v)) for r,v in sums.items()}
            self.listen_profiles=[np.where(np.isin(np.arange(self.n),heads),means['CH'],means['member'])
                                  for heads in self.phase_heads]
        elif variant=='LISTEN-CONSTANT':
            for ph,heads in enumerate(self.phase_heads):
                cap=np.full(self.n,self.c['cm_listen_s']);cap[heads]=self.c['ch_listen_s']
                target=self.listen_profiles[ph].sum();lo=self.c['sync_listen_s'];hi=float(cap.max())
                for _ in range(55):
                    mid=(lo+hi)/2
                    if np.minimum(cap,mid).sum()<target:lo=mid
                    else:hi=mid
                self.listen_profiles[ph]=np.minimum(cap,(lo+hi)/2)
        elif variant=='LISTEN-SHUFFLE':
            for ph,heads in enumerate(self.phase_heads):
                rng=np.random.default_rng(np.random.SeedSequence([sc.seed,77,ph]))
                for mask in [np.isin(np.arange(self.n),heads),~np.isin(np.arange(self.n),heads)]:
                    self.listen_profiles[ph][mask]=rng.permutation(self.listen_profiles[ph][mask])
        self.original_listen=[p.copy() for p in self.listen_profiles]
        guard=self.c['guard_listen_s']
        self.actual_profiles=[p.copy() for p in self.listen_profiles]
        # Time-envelope/capacity probes use actual guard even when charged cost is frozen.
        self.cost_frozen=bool(c.get('freeze_listen_cost',False))
        self.token_frozen=bool(c.get('freeze_token_capacity',False))
        if self.cost_frozen or self.token_frozen:
            self.baseline_profiles=[]
            for heads,struct in zip(self.phase_heads,self.phase_structures):
                old=self.c['guard_listen_s'];self.c['guard_listen_s']=.01
                self.baseline_profiles.append(self.reference_profile(heads,struct)[0])
                self.c['guard_listen_s']=old
            if self.cost_frozen:self.listen_profiles=[p.copy() for p in self.baseline_profiles]
        self.runtime_cap_profiles=[]
        for ph,profile in enumerate(self.actual_profiles):
            if self.token_frozen:
                capcfg=dict(self.c,guard_listen_s=.01)
                capacity=radio_capacity(self.baseline_profiles[ph],capcfg)
            else:capacity=radio_capacity(profile,self.c)
            self.runtime_cap_profiles.append(capacity)
        # Frozen execution obtains capacity from listening. Temporarily substitute
        # just at round entry, then restore charged values before any debit.
        self.capacity_override=self.cost_frozen or self.token_frozen

    def reference_profile(self,heads,struct):
        enabled=self.listen_enabled
        if self.fixed_listen:self.listen_enabled=False
        try:return super().reference_profile(heads,struct)
        finally:self.listen_enabled=enabled

    def install_plan(self):
        before=self.battery.copy()
        super().install_plan()
        base=self.base_profile(self.t)
        if self.c.get('audit_scalar',False):
            point,risk,_,_=self.bank.entries[self.t]
            scenarios=point[None] if self.prediction_mode=='P' else risk
            exact,viable=scalar_supremum(before,self.c['battery_j'],self.c['reserve_j'],scenarios,base,self.c['period_rounds'])
            gaps=exact[viable]-self.extra[viable]
            if (gaps < -1e-9).any() or (gaps>self.c['battery_j']/2**15+1e-9).any():
                raise AssertionError('Scalar bisection bound failed')
            self.audit_gaps.extend(gaps.tolist())
            self.plan_audit.append(dict(round=self.t,viable=int(viable.sum()),infeasible=int((~viable).sum()),
                mean_gap_j=float(gaps.mean()) if len(gaps) else 0,max_gap_j=float(gaps.max()) if len(gaps) else 0))
        gamma=self.c.get('credit_multiplier',1.)
        if gamma!=1:
            change=self.extra*(gamma-1);self.extra+=change;self.issued_credit+=float(change.sum())
            self.cmax+=change;self.credit+=change

    def choose_packet(self,i):
        if self.variant!='JOINT-FAIR':return super().choose_packet(i)
        queue=self.queues[i]
        committed=[p for p in queue if self.holds.get(p.sequence,(-1,0))[0]==i]
        candidates=committed or queue
        selected=min(candidates,key=lambda p:(self.source_fresh[p.source],p.birth,p.sequence))
        index=next(k for k,p in enumerate(queue) if p.sequence==selected.sequence)
        queue.rotate(-index);queue.popleft();queue.rotate(index);queue.appendleft(selected)
        return selected

    def block(self,packet,i,j,reason):
        super().block(packet,i,j,reason)
        if reason=='action_limit':self.probe['action_limit_CH' if i in self.ch else 'action_limit_member']+=1

    def attempt(self,i,j,packet):
        before=float(self.consumed)
        result=super().attempt(i,j,packet)
        if not result[0]:self.failure_cost.append(max(0.,float(self.consumed)-before))
        return result

    def route(self,i,chset):
        if not hasattr(self,'_probe_round') or self._probe_round!=self.t:
            self._probe_round=self.t
            if self.capacity_override:
                self.slots_left[~self.off]=self.runtime_cap_profiles[self.phase(self.t)][~self.off]
        return super().route(i,chset)

    def round(self):
        t=self.t;ph=self.phase(t);old_night=self.night_off;old_nighttotal=self.night_total
        # Original final capacity audit must see the same capacity as route().
        # Use a local module function proxy scoped to this single-process trajectory.
        if self.capacity_override:
            import service_model
            old=service_model.radio_capacity
            service_model.radio_capacity=lambda listen,c:self.runtime_cap_profiles[ph].copy()
            try:super().round()
            finally:service_model.radio_capacity=old
        else:super().round()
        capacity=self.runtime_cap_profiles[ph]
        guard=self.c['guard_listen_s'];sync=self.c['sync_listen_s']
        actual=np.maximum(self.actual_profiles[ph],sync+capacity*guard)
        envelope=float(actual[~self.off].sum()+self.slots_used.sum()*self.c['packet_bits']/self.c['bitrate_bps'])
        if envelope>self.c['round_seconds']+1e-10:raise AssertionError('Expanded time envelope')
        self.envelopes.append(envelope)
        self.probe['time_binding_rounds']+=int(envelope>=self.c['round_seconds']-1e-10)
        self.probe['zero_capacity_node_rounds']+=int((capacity==0).sum())
        self.probe['zero_capacity_selected_receiver']+=sum(int(capacity[j]==0) for i in self.neighbors for j in self.neighbors[i] if j<self.n)
        self.queue_observations.extend(len(q) for q in self.queues)
        ages=np.where(self.latest>=0,t-self.latest+1,t+1)
        for d in self.deadline_fresh:self.deadline_fresh[d]+=int(((self.latest>=0)&(ages<=d)).sum())
        if not hasattr(self,'stress'):self.stress={'stress':[0,0,0,0],'other':[0,0,0,0]}
        window='stress' if t//self.c['day_rounds'] in [5,6,7] else 'other'
        a=self.stress[window];a[0]+=int(((self.latest>=0)&(ages<=self.c['deadline_rounds'])).sum())
        a[1]+=self.n;a[2]+=self.night_off-old_night;a[3]+=self.night_total-old_nighttotal

    def metrics(self):
        row=super().metrics();row['method']=self.variant
        source=100*self.source_fresh/self.sc.rounds
        row.update(source_coverage_min_pct=float(source.min()),source_coverage_p5_pct=float(np.quantile(source,.05)),
            source_coverage_jain=float(source.sum()**2/(self.n*np.square(source).sum())) if source.any() else 0.,
            queue_p95=float(np.quantile(self.queue_observations,.95)),queue_p99=float(np.quantile(self.queue_observations,.99)),
            queue_max=max(self.queue_observations,default=0),time_envelope_max_s=max(self.envelopes,default=0),
            time_envelope_mean_s=float(np.mean(self.envelopes)),**dict(self.probe))
        if self.audit_gaps:row.update(scalar_audit_n=len(self.audit_gaps),scalar_gap_mean_j=float(np.mean(self.audit_gaps)),
            scalar_gap_p95_j=float(np.quantile(self.audit_gaps,.95)),scalar_gap_max_j=max(self.audit_gaps))
        if self.failure_cost:row.update(failed_action_n=len(self.failure_cost),failed_action_mean_j=float(np.mean(self.failure_cost)),
            failed_action_p95_j=float(np.quantile(self.failure_cost,.95)),failed_action_max_j=max(self.failure_cost))
        for d,v in self.deadline_fresh.items():row[f'coverage_D{d}_pct']=100*v/(self.n*self.sc.rounds)
        for name,(fresh,total,off,night) in self.stress.items():
            row[name+'_coverage_pct']=100*fresh/total if total else None
            row[name+'_night_off_pct']=100*off/night if night else None
        return row
