"""Budget diagnostics. The shared topology/radio primitives supply the physical layer."""
from __future__ import annotations
from collections import Counter, deque
from dataclasses import dataclass
import numpy as np
from simulator import Simulator, Predictor, daylight, keyed_uniform


class ScenarioV2:
    """Independent random streams; horizon extension cannot change past data."""
    def __init__(self,c,seed,days,supply=1.):
        self.cfg=c; self.seed=seed; self.rounds=days*c['day_rounds']
        self.warm=2*c['day_rounds']; self.tail=c['forecast_rounds']
        topo=np.random.default_rng(np.random.SeedSequence([seed,11]))
        weather=np.random.default_rng(np.random.SeedSequence([seed,22]))
        meter=np.random.default_rng(np.random.SeedSequence([seed,33]))
        n=c['nodes']; side=int(np.ceil(np.sqrt(n)))
        gx,gy=np.meshgrid((np.arange(side)+.5)/side,(np.arange(side)+.5)/side)
        self.pos=np.column_stack((gx.ravel()[:n],gy.ravel()[:n]))*c['area_m']
        self.pos+=topo.uniform(-8,8,self.pos.shape)
        self.sink=np.array([0.,c['area_m']/2]); self.shade=topo.uniform(.7,1,n)
        self.solar_scale=c['solar_peak_j_per_round']*supply*self.shade
        times=np.arange(-self.warm,self.rounds+self.tail)
        factor=np.empty(len(times)); state=0; innovation=0.; last_day=None
        for idx,tt in enumerate(times):
            day=tt//c['day_rounds']
            if day!=last_day:
                state=int(weather.random()>(.80 if state==0 else .45)); last_day=day
            mean=1. if state==0 else .4
            if day in c['test_forced_cloud_days']:mean=.22
            innovation=.85*innovation+weather.normal(0,.035)
            factor[idx]=np.clip(mean+innovation,.05,1.15)
        phase=daylight(times,c['day_rounds'])
        self.harvest=phase[:,None]*self.solar_scale[None,:]*factor[:,None]
        # Irradiance measured at the powered gateway, mapped through calibrated
        # constant node shading. Offline node telemetry is NOT the predictor.
        measured=np.maximum(0,factor+meter.normal(0,.025,len(times)))
        self.observed=phase[:,None]*self.solar_scale[None,:]*measured[:,None]


class ForecastBank:
    """Precomputation is causal; each signature sees only earlier observations."""
    def __init__(self,sc):
        self.sc=sc; self.entries={}; pred=Predictor(sc); period=sc.cfg['period_rounds']
        for tt in range(sc.rounds):
            pred.update(tt)
            if tt%period==0:
                rng=np.random.default_rng(np.random.SeedSequence([sc.seed,44,tt]))
                point,risk,rho=pred.forecast(tt,rng)
                point.flags.writeable=False; risk.flags.writeable=False
                self.entries[tt]=(point,risk,rho,pred.multiplier)
        self.rmse=float(np.sqrt(np.mean(pred.residuals))) if pred.residuals else 0.


def battery_path(initial,capacity,harvest,cost,reserve):
    """No intermediate lower clipping: TOTAL is a planning end-balance rule.

    Negative intermediate values are hypothetical only; execution never lends
    physical energy. Both budget types account for upper-capacity saturation.
    """
    unconstrained=initial[None,:,None]+np.cumsum(harvest-cost[None,:,:],axis=2)
    spill=np.maximum.accumulate(np.maximum(unconstrained-capacity,0),axis=2)
    after_harvest=unconstrained-spill
    before=np.concatenate((np.broadcast_to(initial,harvest.shape[:2])[:,:,None],
                           after_harvest[:,:,:-1]),axis=2)
    margins=before-cost[None,:,:]-reserve
    bad=margins < -1e-10
    first_bad=np.where(bad.any(axis=2),bad.argmax(axis=2),-1)
    return margins.min(axis=2),after_harvest[:,:,-1]-reserve,first_bad


def budget_caps(initial,capacity,reserve,harvest,base,period,constraint):
    low=np.zeros_like(initial); high=np.full_like(initial,capacity)
    weights=np.full(period,1/period)
    minimum,end,first=battery_path(initial,capacity,harvest,base,reserve)
    viable=((minimum if constraint=='PREFIX' else end)>=-1e-10).all(axis=0)
    for _ in range(15):
        mid=(low+high)/2
        costs=base.copy(); costs[:,:period]+=mid[:,None]*weights
        m,e,_=battery_path(initial,capacity,harvest,costs,reserve)
        ok=((m if constraint=='PREFIX' else e)>=-1e-10).all(axis=0)&viable
        low=np.where(ok,mid,low); high=np.where(ok,high,mid)
    return np.where(viable,low,0),viable,minimum.min(axis=0),end.min(axis=0),first


@dataclass
class Sample:
    source:int
    birth:int
    sequence:int
    tries:int=0
    round_tries:int=0
    last_try_round:int=-1
    last_reason:str='never_attempted'
    history:int=0
    finalized:bool=False


REASONS=['sender_energy','sender_credit','receiver_energy','receiver_credit',
         'receiver_off','cached_receiver_credit','cached_receiver_energy',
         'cached_unavailable','link_loss','no_route','action_limit','queue_overflow']
BITS={reason:1<<i for i,reason in enumerate(REASONS)}


class DiagnosticSimulator(Simulator):
    def __init__(self,c,sc,bank,method,writer=None,topology='scheduled',load_model='schedule',fallback=False):
        super().__init__(c,sc,'PREFIX',None,False,sc.seed)
        self.method=method; self.bank=bank; self.writer=writer
        self.topology=topology; self.load_model=load_model; self.fallback=fallback
        self.prediction_mode,self.constraint=method.split('_')[:2]
        self.reasons=Counter(); self.outcomes=Counter(); self.block_history=Counter()
        self.sample_status=np.zeros(self.n*sc.rounds,np.uint8)
        self.fee=Counter(); self.false_infeasible=0; self.true_base_infeasible=0
        self.low_listen_node_periods=0; self.unused_credit=0.; self.issued_credit=0.
        self.fallback_node_periods=0; self.effective_infeasible=0
        self.round_comm=np.zeros(self.n); self.round_base=np.zeros(self.n); self.round_control=np.zeros(self.n)
        self.last_message=np.full(self.n,-1,int)
        self.cached_battery=np.full(self.n,np.nan); self.cached_quota=np.full(self.n,np.nan)
        self.cached_queue=np.full(self.n,np.nan); self.cached_off=np.ones(self.n,bool)
        self.phase_structures=[]; self.phase_heads=[]
        count=max(len(g) for g in self.groups)
        for k in range(1 if topology=='static' else count):
            heads=np.array([g[k%len(g)] for g in self.groups],int)
            structure=self.structure(heads)
            if structure is None:
                heads=np.array([g[0] for g in self.groups],int); structure=self.structure(heads)
            if structure is None:raise ValueError('fixed topology has no valid backbone')
            self.phase_heads.append(heads); self.phase_structures.append(structure)
        self.low_listen=np.zeros(self.n,bool)

    def phase(self,t):return (t//self.c['period_rounds'])%len(self.phase_heads)

    def base_profile(self,t,low=None):
        c=self.c; h=c['forecast_rounds']; period=c['period_rounds']
        base=np.empty((self.n,h)); extra_load=np.empty_like(base)
        low=np.zeros(self.n,bool) if low is None else low
        for k in range(h):
            ph=self.phase(t+k); heads=self.phase_heads[ph]
            base[:,k]=self.base_cm; base[heads,k]=np.where(low[heads],self.base_cm,self.base_ch)
            base[:,k]+=c['sense_j_per_bit']*c['packet_bits']+c['control_j_per_node_period']/period
            extra_load[:,k]=self.phase_structures[ph][2]
            if k>=period:base[:,k]+=0.65*extra_load[:,k]
        if self.load_model=='legacy_average':
            ph=self.phase(t)
            pooled=self.base_cm+(self.base_ch-self.base_cm)*len(self.phase_heads[ph])/self.n
            pooled+=c['sense_j_per_bit']*c['packet_bits']+c['control_j_per_node_period']/period
            pooled+=.65*self.phase_structures[ph][2].mean()
            base[:,period:]=pooled
        return base

    def install_plan(self):
        c=self.c; t=self.t; ph=self.phase(t)
        point,risk,self.rho,multiplier=self.bank.entries[t]
        self.pred.multiplier=multiplier
        actual=self.sc.harvest[self.sc.warm+t:self.sc.warm+t+c['forecast_rounds']].T[None,:,:]
        chosen={'P':point[None,:,:],'U':risk,'O':actual}[self.prediction_mode]
        base=self.base_profile(t)
        x,viable,min_margin,end_margin,first=budget_caps(self.battery,c['battery_j'],c['reserve_j'],chosen,base,c['period_rounds'],self.constraint)
        initially_viable=viable.copy(); effective_viable=viable.copy()
        use_fallback=np.zeros(self.n,bool)
        if self.fallback:
            period=c['period_rounds']
            nx,nv,_,_,_=budget_caps(self.battery,c['battery_j'],c['reserve_j'],
                chosen[:,:,:period],base[:,:period],period,'PREFIX')
            use_fallback=~viable&nv
            x=np.where(use_fallback,nx,x)
            effective_viable=viable|nv
            self.fallback_node_periods+=int(use_fallback.sum())
        self.effective_infeasible+=int((~effective_viable).sum())
        omin,oend,ofirst=battery_path(self.battery,c['battery_j'],actual,base,c['reserve_j'])
        oracle_viable=((omin if self.constraint=='PREFIX' else oend)>=-1e-10).all(axis=0)
        self.false_infeasible+=int((~viable&oracle_viable).sum())
        self.true_base_infeasible+=int((~oracle_viable).sum())
        self.infeasible_nodes+=int((~viable).sum()); self.periods+=1
        heads=self.phase_heads[ph]; parent,rank,load=self.phase_structures[ph]
        changed=np.zeros(self.n,bool) if self.last_parent is None else parent!=self.last_parent
        self.reclusters+=int(changed.any()); self.changed+=int(changed.sum())
        self.ch=heads; self.parent=parent; self.rank=rank; self.expected_load=load
        self.last_parent=parent.copy(); self.extra=x; self.issued_credit+=float(x.sum())
        self.cmax=base[:,:c['period_rounds']].sum(axis=1)+x
        self.credit=self.cmax.copy(); self.actual_period[:]=0; self.period_comm[:]=0
        self.neighbors={}
        for i in heads:
            candidate=np.r_[heads,self.n]
            self.neighbors[int(i)]=np.sort(candidate[self.adj[i,candidate]&(rank[candidate]<rank[i]-1e-9)])[:c['candidates']]
        # Fixed exogenous schedule uses prepaid per-round telemetry, with no
        # candidate-dependent reclustering fee; identical across six methods.
        if self.writer:
            for i in range(self.n):
                bad=first[:,i]; bad=bad[bad>=0]
                obad=ofirst[:,i]; obad=obad[obad>=0]
                self.writer('period',dict(round=t,node=i,ch=int(i in heads),battery_j=self.battery[i],
                    base_energy_horizon_j=base[i].sum(),extra_credit_j=x[i],
                    forecast_viable=int(viable[i]),oracle_same_cost_viable=int(oracle_viable[i]),
                    false_infeasible=int(not viable[i] and oracle_viable[i]),
                    min_forecast_margin_j=min_margin[i],end_forecast_margin_j=end_margin[i],
                    min_oracle_margin_j=omin[:,i].min(),end_oracle_margin_j=oend[:,i].min(),
                    first_forecast_bad_h=int(bad.min()) if len(bad) else -1,
                    first_oracle_bad_h=int(obad.min()) if len(obad) else -1,
                    fallback=int(use_fallback[i]),effective_viable=int(effective_viable[i]),
                    initially_viable=int(initially_viable[i])))

    def debit(self,i,e,category):
        if e<0 or e>self.battery[i]+1e-9:raise AssertionError('physical overdraft')
        self.spend(i,e,category); self.fee[category]+=e
        if category=='comm':self.round_comm[i]+=e
        elif category=='control':self.round_control[i]+=e
        else:self.round_base[i]+=e

    def block(self,packet,i,j,reason):
        packet.last_reason=reason; packet.history|=BITS.get(reason,0)
        self.reasons[reason]+=1
        if self.writer:self.writer('event',dict(round=self.t,sequence=packet.sequence,source=packet.source,
            sender=i,receiver=j,age_rounds=self.t-packet.birth,event=reason,
            sender_battery_j=self.battery[i],sender_credit_j=self.quota[i],
            receiver_battery_j=self.battery[j] if 0<=j<self.n else -1,
            receiver_credit_j=self.quota[j] if 0<=j<self.n else -1))

    def finalize(self,packet,status):
        if packet.finalized or self.sample_status[packet.sequence]:raise AssertionError('sample finalized twice')
        packet.finalized=True; self.outcomes[status]+=1
        self.sample_status[packet.sequence]={'delivered':1,'expired':2,'overflow':3,'outstanding':4}[status]
        if status=='expired':self.outcomes['expired_after_'+packet.last_reason]+=1
        for reason,bit in BITS.items():
            if packet.history&bit:self.block_history[reason]+=1
        if self.writer:self.writer('sample',dict(sequence=packet.sequence,source=packet.source,
            birth_round=packet.birth,final_round=self.t,status=status,last_reason=packet.last_reason,
            block_history=packet.history))

    def attempt(self,i,j,packet):
        c=self.c; etx=self.tx_energy(i,j)
        erx=c['packet_bits']*c['elec_j_per_bit']; eagg=c['packet_bits']*c['aggregate_j_per_bit']
        if self.battery[i]<etx+c['reserve_j']:
            self.block(packet,i,j,'sender_energy'); return False,'sender_energy'
        if self.quota[i]<etx:
            self.block(packet,i,j,'sender_credit'); return False,'sender_credit'
        self.debit(i,etx,'comm')
        if j<self.n:
            if self.off[j]:self.block(packet,i,j,'receiver_off'); return False,'receiver_off'
            if self.battery[j]<erx+eagg+c['reserve_j']:
                self.block(packet,i,j,'receiver_energy'); return False,'receiver_energy'
            if self.quota[j]<erx+eagg:
                self.block(packet,i,j,'receiver_credit'); return False,'receiver_credit'
            self.debit(j,erx,'comm')
        if packet.last_try_round!=self.t:packet.round_tries=0; packet.last_try_round=self.t
        count=packet.tries; packet.tries+=1; packet.round_tries+=1
        self.tx_attempts+=1
        success=keyed_uniform(self.sc.seed,self.t,i,j,packet.sequence,count)<self.prob[i,j]
        if not success:
            self.block(packet,i,j,'link_loss'); return False,'link_loss'
        self.link_success+=1; packet.tries=0; packet.round_tries=0
        if j==self.n:
            self.delivered+=1; self.latest[packet.source]=max(self.latest[packet.source],packet.birth)
            self.finalize(packet,'delivered')
        else:
            self.debit(j,eagg,'comm')
            if len(self.queues[j])<c['max_queue']:self.queues[j].append(packet)
            else:
                self.overflow+=1; packet.last_reason='queue_overflow'; self.finalize(packet,'overflow')
        if self.writer:self.writer('event',dict(round=self.t,sequence=packet.sequence,source=packet.source,
            sender=i,receiver=j,age_rounds=self.t-packet.birth,event='delivered' if j==self.n else 'relayed',
            sender_battery_j=self.battery[i],sender_credit_j=self.quota[i],
            receiver_battery_j=self.battery[j] if j<self.n else -1,
            receiver_credit_j=self.quota[j] if j<self.n else -1))
        return True,'success'

    def no_action_reason(self,i):
        ids=self.neighbors[i]
        if not len(ids):return 'no_route'
        cheapest=min(self.tx_energy(i,int(j)) for j in ids)
        if self.battery[i]<cheapest+self.c['reserve_j']:return 'sender_energy'
        if self.quota[i]<cheapest:return 'sender_credit'
        erx=self.c['packet_bits']*(self.c['elec_j_per_bit']+self.c['aggregate_j_per_bit'])
        if all(j<self.n and self.cached_off[j] for j in ids):return 'cached_unavailable'
        if all(j<self.n and (self.cached_off[j] or self.cached_quota[j]<erx) for j in ids):return 'cached_receiver_credit'
        return 'cached_receiver_energy'

    def round(self):
        c=self.c; n=self.n
        if self.t%c['period_rounds']==0:self.install_plan()
        self.quota=self.extra/c['period_rounds']
        self.round_comm[:]=0; self.round_base[:]=0; self.round_control[:]=0
        chset=set(self.ch.tolist())
        for i in range(n):
            alive=deque()
            for packet in self.queues[i]:
                if self.t-packet.birth>=c['deadline_rounds']:
                    self.expired+=1; self.finalize(packet,'expired')
                else:alive.append(packet)
            self.queues[i]=alive
            basal=self.base_ch if i in chset and not self.low_listen[i] else self.base_cm
            sense=c['sense_j_per_bit']*c['packet_bits']; control=c['control_j_per_node_period']/c['period_rounds']
            required=basal+sense+control
            if self.off[i] and self.battery[i]>=max(c['recovery_j'],required):self.off[i]=False
            if not self.off[i] and self.battery[i]>=required:
                self.debit(i,basal+sense,'base'); self.debit(i,control,'control')
                self.generated+=1; packet=Sample(i,self.t,self.t*n+i)
                if len(self.queues[i])<c['max_queue']:self.queues[i].append(packet)
                else:
                    self.overflow+=1; packet.last_reason='queue_overflow'; self.finalize(packet,'overflow')
                self.cached_battery[i]=self.battery[i]; self.cached_quota[i]=self.quota[i]
                self.cached_queue[i]=len(self.queues[i]); self.cached_off[i]=False; self.last_message[i]=self.t
            else:
                self.off[i]=True; self.unsensed+=1; self.outcomes['unsensed']+=1
                self.sample_status[self.t*n+i]=5
                self.debit(i,min(self.battery[i],c['off_w']*c['round_seconds']),'base')
                # No new offline telemetry: values and timestamp remain stale.
        self.demand+=n; self.off_rounds+=int(self.off.sum())
        stale=(self.last_message<0)|(self.t-self.last_message>1)
        self.cached_off[stale]=True
        if daylight(self.t,c['day_rounds'])==0:
            self.night_off+=int(self.off.sum()); self.night_total+=n
        for i in range(n):
            if i in chset:continue
            if self.off[i]:
                if self.queues[i]:self.block(self.queues[i][0],i,int(self.parent[i]),'sender_energy')
                continue
            for _ in range(c['max_ch_actions_round']):
                if not self.queues[i]:break
                packet=self.queues[i][0]; ok,why=self.attempt(i,int(self.parent[i]),packet)
                if ok:self.queues[i].popleft()
                elif why!='link_loss' or packet.round_tries>=c['max_link_attempts']:break
        for i in self.ch[np.argsort(-self.rank[self.ch])]:
            i=int(i)
            if self.off[i]:
                if self.queues[i]:self.block(self.queues[i][0],i,-1,'sender_energy')
                continue
            for _ in range(c['max_ch_actions_round']):
                if not self.queues[i]:break
                packet=self.queues[i][0]; _,mask,ids=self.observe(i)
                a=self.greedy(i,mask,ids)
                if a==c['candidates']:
                    self.block(packet,i,-1,self.no_action_reason(i)); break
                ok,why=self.attempt(i,int(ids[a]),packet)
                if ok:self.queues[i].popleft()
                elif why!='link_loss' or packet.round_tries>=c['max_link_attempts']:break
            else:
                if self.queues[i]:self.block(self.queues[i][0],i,-1,'action_limit')
        self.unused_credit+=float(np.maximum(self.quota,0).sum())
        harvest=self.sc.harvest[self.sc.warm+self.t]
        over=self.battery+harvest-c['battery_j']
        spilled=np.maximum(over,0); self.battery=np.minimum(c['battery_j'],self.battery+harvest)
        self.harvested+=float(harvest.sum()); self.spilled+=float(spilled.sum())
        error=self.initial_sum+self.harvested-self.consumed-self.spilled-self.battery.sum()
        if abs(error)>1e-6:raise AssertionError('energy conservation')
        ages=np.where(self.latest>=0,self.t-self.latest+1,self.t+1)
        coverage=float(np.mean((self.latest>=0)&(ages<=c['deadline_rounds'])))
        counts=Counter(self.reasons)
        self.logs.append(dict(round=self.t,day=self.t/c['day_rounds'],coverage=coverage,
            aoi_minutes=float(ages.mean()*c['round_seconds']/60),battery_mean_j=float(self.battery.mean()),
            off_fraction=float(self.off.mean()),queue_mean=float(np.mean([len(q) for q in self.queues])),
            solar_mean_j=float(harvest.mean()),rho=self.rho,energy_balance_error_j=float(error),
            sender_credit_events=counts['sender_credit'],receiver_credit_events=counts['receiver_credit'],
            cached_receiver_credit_events=counts['cached_receiver_credit'],
            physical_events=counts['sender_energy']+counts['receiver_energy']+counts['receiver_off']))
        if self.writer:
            for i in range(n):self.writer('node',dict(round=self.t,node=i,ch=int(i in chset),
                battery_j=self.battery[i],off=int(self.off[i]),queue=len(self.queues[i]),
                base_j=self.round_base[i],comm_j=self.round_comm[i],control_j=self.round_control[i],
                quota_start_j=self.extra[i]/c['period_rounds'],quota_left_j=self.quota[i],
                telemetry_age=self.t-self.last_message[i] if self.last_message[i]>=0 else -1,
                low_listen=int(self.low_listen[i])))
        self.t+=1

    def metrics(self):
        for q in self.queues:
            for packet in q:
                if not packet.finalized:self.finalize(packet,'outstanding')
        m=super().metrics(); m['forecast_rmse_j_per_round']=self.bank.rmse
        m.update(topology=self.topology,load_model=self.load_model,fallback=int(self.fallback),
                 false_infeasible_node_periods=self.false_infeasible,
                 oracle_base_infeasible_node_periods=self.true_base_infeasible,
                 false_infeasible_pct=100*self.false_infeasible/(self.n*self.periods),
                 forecast_infeasible_pct=100*self.infeasible_nodes/(self.n*self.periods),
                 oracle_base_infeasible_pct=100*self.true_base_infeasible/(self.n*self.periods),
                 low_listen_node_periods=self.low_listen_node_periods,
                 fallback_node_periods=self.fallback_node_periods,
                 effective_infeasible_pct=100*self.effective_infeasible/(self.n*self.periods),
                 base_consumed_j=self.fee['base'],comm_consumed_j=self.fee['comm'],
                 unused_extra_credit_j=self.unused_credit,issued_extra_credit_j=self.issued_credit)
        assert sum(self.outcomes[k] for k in ['delivered','expired','overflow','outstanding','unsensed'])==self.demand
        assert np.count_nonzero(self.sample_status)==self.demand
        return m
