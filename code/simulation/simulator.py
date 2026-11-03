"""Causal paired-trace simulation base; see MODEL_SPEC.md for abstractions."""
from __future__ import annotations
from dataclasses import dataclass
from collections import deque
import numpy as np
from scipy.sparse.csgraph import shortest_path


def keyed_uniform(seed,*keys):
    """Stateless exogenous draw, independent of policy RNG consumption."""
    bits=(1<<64)-1
    x=int(seed)&bits
    for key in keys:
        x=(x ^ (int(key)+0x9E3779B97F4A7C15+(x<<6)+(x>>2)))&bits
    # Avalanche the final key as well: adjacent attempt IDs must not produce
    # almost identical variates and artificially correlated retransmissions.
    x=(x+0x9E3779B97F4A7C15)&bits
    x=((x^(x>>30))*0xBF58476D1CE4E5B9)&bits
    x=((x^(x>>27))*0x94D049BB133111EB)&bits
    x=x^(x>>31)
    return ((x>>11)+0.5)/(1<<53)


def daylight(t,day_rounds=96):
    hour=(np.asarray(t)%day_rounds)*24/day_rounds
    return np.where((hour>=6)&(hour<18),np.sin(np.pi*(hour-6)/12),0.0)


def prefix_feasible(initial,cap,reserve,harvest,cost):
    """Vector arrays [scenario,node,time] and [node,time]."""
    battery=np.broadcast_to(initial,harvest.shape[:2]).copy()
    ok=np.ones(harvest.shape[1],bool)
    for h in range(harvest.shape[2]):
        after=battery-cost[:,h]
        ok &= (after>=reserve-1e-10).all(axis=0)
        battery=np.minimum(cap,after+harvest[:,:,h])
    return ok


def prefix_caps(initial,cap,reserve,harvest,base,period,weights):
    viable=prefix_feasible(initial,cap,reserve,harvest,base)
    low=np.zeros_like(initial); high=np.full_like(initial,cap)
    for _ in range(12):
        middle=(low+high)/2
        cost=base.copy(); cost[:,:period]+=middle[:,None]*weights[None,:]
        ok=prefix_feasible(initial,cap,reserve,harvest,cost)&viable
        low=np.where(ok,middle,low); high=np.where(ok,high,middle)
    return np.where(viable,low,0.0),viable


@dataclass
class Packet:
    source:int
    birth:int
    sequence:int
    tries:int=0


class Scenario:
    def __init__(self,cfg,seed,days,supply=1.0,forced_cloud=False):
        self.cfg=cfg; self.seed=seed; self.rounds=days*cfg['day_rounds']
        rng=np.random.default_rng(seed)
        n=cfg['nodes']; side=int(np.ceil(np.sqrt(n)))
        gx,gy=np.meshgrid((np.arange(side)+0.5)/side,(np.arange(side)+0.5)/side)
        self.pos=np.column_stack((gx.ravel()[:n],gy.ravel()[:n]))*cfg['area_m']
        self.pos+=rng.uniform(-8,8,self.pos.shape)
        self.sink=np.array([0.0,cfg['area_m']/2])
        self.shade=rng.uniform(0.70,1.0,n)
        self.solar_scale=cfg['solar_peak_j_per_round']*supply*self.shade
        warm=2*cfg['day_rounds']; self.warm=warm
        times=np.arange(-warm,self.rounds)
        factors=np.empty(len(times)); state=0; innovation=0.0
        last_day=None
        for idx,t in enumerate(times):
            day=t//cfg['day_rounds']
            if day!=last_day:
                if state==0: state=int(rng.random()>0.80)
                else: state=int(rng.random()<0.55)
                last_day=day
            mean=1.0 if state==0 else 0.4
            if forced_cloud and day in cfg['test_forced_cloud_days']: mean=0.22
            innovation=0.85*innovation+rng.normal(0,0.035)
            factors[idx]=np.clip(mean+innovation,0.05,1.15)
        self.harvest=daylight(times,cfg['day_rounds'])[:,None]*self.solar_scale[None,:]*factors[:,None]
        # Measurement affects predictions only, never physical recharge.
        self.observed=np.maximum(0,self.harvest+rng.normal(0,0.001,self.harvest.shape))
        self.observed[daylight(times,cfg['day_rounds'])==0]=0


class Predictor:
    def __init__(self,scenario):
        self.scenario=scenario; self.c=scenario.cfg; self.multiplier=0.65
        self.errors=deque(maxlen=192); self.residuals=[]; self.issued=[]
        for idx in range(scenario.warm):
            phase=daylight(idx-scenario.warm,self.c['day_rounds'])
            if phase>0.10:
                ratio=np.median(scenario.observed[idx]/(scenario.solar_scale*phase))
                self.errors.append(self.multiplier-ratio)
                self.multiplier=self.c['forecast_beta']*self.multiplier+(1-self.c['forecast_beta'])*ratio

    def update(self,t):
        if t==0:return
        prev=t-1; phase=daylight(prev,self.c['day_rounds'])
        measured=self.scenario.observed[self.scenario.warm+prev]
        if phase>0.10:
            ratio=float(np.median(measured/(self.scenario.solar_scale*phase)))
            self.errors.append(self.multiplier-ratio)
            self.multiplier=self.c['forecast_beta']*self.multiplier+(1-self.c['forecast_beta'])*ratio
        keep=[]
        for issued_at,pred in self.issued:
            h=prev-issued_at
            if 0<=h<pred.shape[1]:
                self.residuals.append(float(np.mean((pred[:,h]-measured)**2)))
            if h+1<pred.shape[1]:keep.append((issued_at,pred))
        self.issued=keep

    def forecast(self,t,rng):
        h=self.c['forecast_rounds']; phase=daylight(t+np.arange(h),self.c['day_rounds'])
        base=self.scenario.solar_scale[:,None]*phase[None,:]
        point=base*np.clip(self.multiplier,0.05,1.15)
        errors=np.asarray(self.errors) if self.errors else np.array([0.3])
        scenarios=[point]
        for _ in range(self.c['scenario_count']-2):
            start=int(rng.integers(len(errors)))
            block=errors[(start+np.arange(h))%len(errors)]
            scenarios.append(base*np.clip(self.multiplier-block,0,1.15))
        conservative=max(0.0,float(np.quantile(errors,0.9)))
        scenarios.append(base*np.clip(self.multiplier-conservative,0,1.15))
        rho=1/(1+max(0,float(errors.mean()))+float(errors.std()))
        self.issued.append((t,point.copy()))
        return point,np.stack(scenarios),max(0.05,rho)


class Simulator:
    INPUTS=12+5*7
    METHODS=('RULE','BULK','PREFIX','MVO_PREFIX','LEGACY_D3QN')
    def __init__(self,cfg,scenario,method,agent=None,training=False,seed=0):
        self.c=cfg; self.sc=scenario; self.method=method; self.agent=agent; self.training=training
        self.rng=np.random.default_rng(seed+70001); self.n=cfg['nodes']; self.t=0
        self.battery=np.full(self.n,cfg['battery_j']*cfg['initial_battery_fraction'])
        self.initial_sum=float(self.battery.sum()); self.consumed=0.0; self.harvested=0.0; self.spilled=0.0
        self.queues=[deque() for _ in range(self.n)]
        self.generated=0; self.demand=0; self.delivered=0; self.expired=0; self.overflow=0
        self.unsensed=0; self.latest=np.full(self.n,-1,int)
        self.off=np.zeros(self.n,bool); self.off_rounds=0; self.night_off=0; self.night_total=0
        self.credit=np.zeros(self.n); self.extra=np.zeros(self.n); self.cmax=np.zeros(self.n)
        self.quota=np.zeros(self.n); self.rho=0.5
        self.base_bill=np.zeros(self.n); self.comm_bill=np.zeros(self.n)
        self.last_load=np.zeros(self.n); self.actual_period=np.zeros(self.n); self.period_comm=np.zeros(self.n)
        self.last_parent=None; self.reclusters=0; self.changed=0
        self.control_energy=0.; self.inference_energy=0.; self.tx_attempts=0; self.link_success=0
        self.pred=Predictor(scenario); self.periods=0; self.infeasible_nodes=0
        self.logs=[]; self.ch=np.array([],int)
        allpos=np.vstack((scenario.pos,scenario.sink))
        self.distance=np.linalg.norm(allpos[:,None,:]-allpos[None,:,:],axis=2)
        self.prob=np.clip(0.97-0.25*(self.distance/cfg['range_m'])**2,0.55,0.99)
        self.adj=(self.distance<=cfg['range_m'])&(self.distance>0)
        d0=np.sqrt(cfg['fs_j_per_bit_m2']/cfg['mp_j_per_bit_m4'])
        amp=np.where(self.distance<d0,cfg['fs_j_per_bit_m2']*self.distance**2,cfg['mp_j_per_bit_m4']*self.distance**4)
        self.tx_cost=cfg['packet_bits']*(1.05*cfg['elec_j_per_bit']+amp)
        self.structure_cache={}
        self.base_cm=cfg['sleep_w']*cfg['round_seconds']+cfg['radio_idle_w']*cfg['cm_listen_s']
        self.base_ch=cfg['sleep_w']*cfg['round_seconds']+cfg['radio_idle_w']*cfg['ch_listen_s']
        cols,rows=cfg['cluster_cols'],cfg['cluster_rows']
        self.groups=[]; self.centers=[]
        for row in range(rows):
            for col in range(cols):
                center=np.array([(col+.5)/cols,(row+.5)/rows])*cfg['area_m']; self.centers.append(center)
                membership=(np.floor(scenario.pos[:,0]/cfg['area_m']*cols).clip(0,cols-1)==col)&(np.floor(scenario.pos[:,1]/cfg['area_m']*rows).clip(0,rows-1)==row)
                ids=np.flatnonzero(membership)
                if not len(ids):raise ValueError('empty geographical cell')
                nearest=ids[np.argsort(np.linalg.norm(scenario.pos[ids]-center,axis=1))[:5]]
                self.groups.append(nearest)

    def tx_energy(self,i,j):
        return float(self.tx_cost[i,j])

    def structure(self,heads):
        key=tuple(heads)
        if key in self.structure_cache:return self.structure_cache[key]
        vertices=np.r_[heads,self.n]
        weights=np.where(self.adj[np.ix_(vertices,vertices)],1/self.prob[np.ix_(vertices,vertices)],np.inf)
        np.fill_diagonal(weights,0)
        dist=shortest_path(weights,directed=False,indices=len(heads))
        if not np.isfinite(dist).all():return None
        cm_cost=self.distance[:self.n,heads].copy(); cm_cost[~self.adj[:self.n,heads]]=np.inf
        for k,i in enumerate(heads):cm_cost[i,k]=0
        pindex=np.argmin(cm_cost,axis=1)
        if not np.isfinite(cm_cost[np.arange(self.n),pindex]).all():return None
        parent=heads[pindex]; rank=np.full(self.n+1,np.inf); rank[heads]=dist[:-1]; rank[self.n]=0
        # Fixed reference routing determines anticipated traffic and energy.
        counts=np.bincount(pindex,minlength=len(heads)).astype(float)
        load=np.zeros(self.n)
        cm=np.flatnonzero(parent!=np.arange(self.n)); destination=parent[cm]
        probability=self.prob[cm,destination]
        load[cm]+=self.tx_cost[cm,destination]/probability
        np.add.at(load,destination,self.c['packet_bits']*(self.c['elec_j_per_bit']+self.c['aggregate_j_per_bit'])/probability)
        for k in np.argsort(-dist[:-1]):
            i=heads[k]; eligible=np.flatnonzero(self.adj[i,vertices]&(dist<dist[k]-1e-9))
            if not len(eligible):return None
            jidx=eligible[np.argmin(1/self.prob[i,vertices[eligible]]+dist[eligible])]
            j=vertices[jidx]
            load[i]+=counts[k]*self.tx_energy(i,j)/self.prob[i,j]
            if j<self.n:
                load[j]+=counts[k]*self.c['packet_bits']*(self.c['elec_j_per_bit']+self.c['aggregate_j_per_bit'])/self.prob[i,j]
                counts[jidx]+=counts[k]
        result=(parent,rank,load)
        if len(self.structure_cache)>4096:self.structure_cache.clear()
        self.structure_cache[key]=result
        return result

    def choose_plan(self,point,scenarios):
        c=self.c; n=self.n
        def decode(q):return np.array([g[np.argmax(q[g])] for g in self.groups],int)
        def evaluate(u):
            heads=decode(u[n:]); struct=self.structure(heads)
            if struct is None:return 1e6,None
            parent,rank,load=struct
            base=np.full(n,self.base_cm); base[heads]=self.base_ch
            base+=c['sense_j_per_bit']*c['packet_bits']
            availability=np.maximum(self.battery-c['reserve_j']+point[:,:c['period_rounds']].sum(axis=1)-base*c['period_rounds'],0)
            affordable=np.minimum(load*c['period_rounds'],availability*u[:n])
            deficit=np.maximum(load*c['period_rounds']-affordable,0).sum()/(load.sum()*c['period_rounds']+1e-9)
            projected=self.battery-base*c['period_rounds']-affordable+point[:,:c['period_rounds']].sum(axis=1)
            projected=np.clip(projected,0,c['battery_j'])
            cv=projected.std()/(projected.mean()+0.15)
            near=np.maximum(0,base*c['period_rounds']+c['reserve_j']-self.battery).sum()/n
            change=0 if self.last_parent is None else np.mean(parent!=self.last_parent)
            feedback=0.15*np.mean(self.last_load[heads]/(self.battery[heads]+0.15))
            value=4*deficit+0.8*cv+2*near+0.05*change+feedback+0.05*load.sum()
            return float(value),(heads,parent,rank,load,u[:n])
        if self.method in ('MVO_PREFIX','LEGACY_D3QN'):
            p,iters=c['mvo_population'],c['mvo_iterations']
            pop=self.rng.uniform(0,1,(p,2*n)); pop[:,:n]=self.rng.uniform(0.65,1,(p,n))
            # Seed a robust spatial solution, without fixing the search outcome.
            pop[0,n:]=0
            for g in self.groups:pop[0,n+g[0]]=1
            pop[0,:n]=1
            best_cost=np.inf; best=None; best_u=None
            for it in range(iters):
                evaluated=[evaluate(u) for u in pop]
                costs=np.array([e[0] for e in evaluated]); order=np.argsort(costs)
                if costs[order[0]]<best_cost:
                    best_cost=float(costs[order[0]]); best=evaluated[order[0]][1]; best_u=pop[order[0]].copy()
                rankidx=np.empty(p,int); rankidx[order]=np.arange(p)
                probability=(p-rankidx).astype(float); probability/=probability.sum()
                old=pop.copy(); wep=0.2+0.6*(it+1)/iters; tdr=1-((it+1)/iters)**(1/6)
                for k in range(p):
                    donor=self.rng.choice(p,2*n,p=probability)
                    replace=self.rng.random(2*n)<rankidx[k]/max(1,p-1)
                    pop[k,replace]=old[donor[replace],np.flatnonzero(replace)]
                    worm=self.rng.random(2*n)<wep
                    sign=np.where(self.rng.random(2*n)<0.5,-1,1)
                    pop[k,worm]=best_u[worm]+sign[worm]*tdr*self.rng.random(worm.sum())
                np.clip(pop,0,1,out=pop); pop[0]=best_u
            result=best
        else:
            q=self.battery/(c['battery_j'])+0.10*self.sc.shade
            heads=decode(q)
            struct=self.structure(heads)
            result=None if struct is None else (heads,*struct,np.ones(n))
        if result is None:
            heads=np.array([g[0] for g in self.groups]); struct=self.structure(heads)
            if struct is None:raise RuntimeError('canonical CH backbone disconnected')
            result=(heads,*struct,np.ones(n))
        heads,parent,rank,load,z=result
        base=np.full(n,self.base_cm); base[heads]=self.base_ch
        base+=c['sense_j_per_bit']*c['packet_bits']
        changed=np.zeros(n,bool) if self.last_parent is None else parent!=self.last_parent
        ctrl=np.full(n,c['control_j_per_node_period'])+changed*c['recluster_j_per_changed_node']
        if self.method=='RULE':extra=np.full(n,1e6); viable=np.ones(n,bool)
        elif self.method=='BULK':
            extra=np.maximum(0,0.3*self.battery+point[:,:c['period_rounds']].sum(axis=1)-base*c['period_rounds'])
            viable=np.ones(n,bool)
        else:
            horizon=c['forecast_rounds']; period=c['period_rounds']
            future_base=self.base_cm+(self.base_ch-self.base_cm)*len(heads)/n+c['sense_j_per_bit']*c['packet_bits']
            # Future rotation/service is explicitly an approximation.
            future_base+=0.65*load.mean()
            costs=np.full((n,horizon),future_base); costs[:,:period]=base[:,None]
            costs[:,0]+=ctrl
            extra,viable=prefix_caps(self.battery,c['battery_j'],c['reserve_j'],scenarios,costs,period,np.full(period,1/period))
            extra*=z
            self.infeasible_nodes+=int((~viable).sum())
        self.periods+=1
        if self.last_parent is not None:
            self.changed+=int(changed.sum()); self.reclusters+=int(changed.any())
        self.ch=heads; self.parent=parent; self.rank=rank; self.expected_load=load
        self.neighbors={}
        for i in heads:
            candidate=np.r_[heads,self.n]
            candidate=candidate[self.adj[i,candidate]&(rank[candidate]<rank[i]-1e-9)]
            self.neighbors[int(i)]=np.sort(candidate)[:c['candidates']]
        self.last_parent=parent.copy(); self.extra=extra; self.cmax=base*c['period_rounds']+extra+ctrl
        self.credit=self.cmax.copy(); self.actual_period[:]=0; self.period_comm[:]=0
        for i,e in enumerate(ctrl):self.spend(i,float(min(e,self.battery[i])),category='control')

    def spend(self,i,energy,category='comm'):
        if energy<0 or energy>self.battery[i]+1e-9:raise AssertionError('battery overdraft')
        self.battery[i]-=energy; self.consumed+=energy; self.actual_period[i]+=energy
        self.credit[i]-=energy
        if category=='comm':self.quota[i]-=energy; self.comm_bill[i]+=energy; self.period_comm[i]+=energy
        elif category=='control':self.control_energy+=energy
        elif category=='inference':self.inference_energy+=energy
        else:self.base_bill[i]+=energy

    def observe(self,i):
        c=self.c; packet=self.queues[i][0] if self.queues[i] else None
        age=0 if packet is None else self.t-packet.birth
        candidate=self.neighbors[i]
        obs=[self.battery[i]/c['battery_j'],min(3,self.quota[i]/(self.expected_load[i]+1e-6))/3,
             len(self.queues[i])/c['max_queue'],age/c['deadline_rounds'],self.rho,
             np.sin(2*np.pi*self.t/c['day_rounds']),np.cos(2*np.pi*self.t/c['day_rounds']),
             min(self.rank[i]/6,2),(self.t%c['period_rounds'])/c['period_rounds'],
             float(packet is not None),float(i in self.ch),self.pred.multiplier]
        mask=np.zeros(c['candidates']+1,bool); ids=np.full(c['candidates'],-1,int)
        for k in range(c['candidates']):
            if k>=len(candidate):obs.extend([0]*7);continue
            j=int(candidate[k]); ids[k]=j; cost=self.tx_energy(i,j)
            if j==self.n:bj=1.; qj=1.; qlen=0.; alive=True
            else:
                bj=self.cached_battery[j]/c['battery_j']; qj=min(3,self.cached_quota[j]/(self.expected_load[j]+1e-6))/3
                qlen=self.cached_queue[j]/c['max_queue']; alive=not self.cached_off[j]
            obs.extend([bj,qj,qlen,self.prob[i,j],(self.rank[i]-self.rank[j])/6,cost/0.002,float(j==self.n)])
            receiver_cost=c['packet_bits']*(c['elec_j_per_bit']+c['aggregate_j_per_bit'])
            receiver_estimate_ok=j==self.n or (self.cached_battery[j]>=receiver_cost+c['reserve_j'] and self.cached_quota[j]>=receiver_cost)
            mask[k]=(packet is not None and alive and receiver_estimate_ok and self.battery[i]>=cost+c['reserve_j'] and self.quota[i]>=cost)
        mask[-1]=True
        return np.asarray(obs,np.float32),mask,ids

    def transmit(self,i,j,packet):
        c=self.c; etx=self.tx_energy(i,j)
        erx=c['packet_bits']*(c['elec_j_per_bit']+c['aggregate_j_per_bit'])
        if self.battery[i]<etx+c['reserve_j'] or self.quota[i]<etx:return False,0.,'budget'
        if j<self.n and (self.off[j] or self.battery[j]<erx+c['reserve_j'] or self.quota[j]<erx):return False,0.,'receiver'
        self.spend(i,etx)
        if j<self.n:self.spend(j,erx)
        self.tx_attempts+=1
        attempt=packet.tries; packet.tries+=1
        success=keyed_uniform(self.sc.seed,self.t,i,j,packet.sequence,attempt)<self.prob[i,j]
        if not success:return False,etx+(erx if j<self.n else 0),'link'
        self.link_success+=1; packet.tries=0
        if j==self.n:
            self.delivered+=1; self.latest[packet.source]=max(self.latest[packet.source],packet.birth)
        elif len(self.queues[j])<c['max_queue']:self.queues[j].append(packet)
        else:self.overflow+=1
        return True,etx+(erx if j<self.n else 0),'sink' if j==self.n else 'relay'

    def greedy(self,i,mask,ids):
        valid=np.flatnonzero(mask[:-1])
        if not len(valid):return self.c['candidates']
        scores=[]
        for k in valid:
            j=ids[k]
            tail=0 if j==self.n else 0.04*self.cached_queue[j]+0.15/(self.cached_battery[j]+0.15)
            scores.append(1/self.prob[i,j]+self.rank[j]+tail)
        return int(valid[np.argmin(scores)])

    def round(self):
        c=self.c; n=self.n; self.pred.update(self.t)
        if self.t%c['period_rounds']==0:
            if self.t:self.last_load=0.7*self.last_load+0.3*self.period_comm/c['period_rounds']
            point,scenarios,self.rho=self.pred.forecast(self.t,self.rng)
            self.choose_plan(point,scenarios)
        self.quota=self.extra/c['period_rounds']
        ch_set=set(self.ch.tolist())
        for i in range(n):
            kept=deque()
            for packet in self.queues[i]:
                if self.t-packet.birth>=c['deadline_rounds']:self.expired+=1
                else:kept.append(packet)
            self.queues[i]=kept
            basal=self.base_ch if i in ch_set else self.base_cm
            sense=c['sense_j_per_bit']*c['packet_bits']
            if self.off[i] and self.battery[i]>=max(c['recovery_j'],basal+sense):self.off[i]=False
            if not self.off[i] and self.battery[i]>=basal+sense:
                self.spend(i,basal+sense,'base'); self.generated+=1
                if len(self.queues[i])<c['max_queue']:self.queues[i].append(Packet(i,self.t,self.t*n+i))
                else:self.overflow+=1
            else:
                self.off[i]=True; self.unsensed+=1
                self.spend(i,min(self.battery[i],c['off_w']*c['round_seconds']),'base')
        self.demand+=n; self.off_rounds+=int(self.off.sum())
        if daylight(self.t,c['day_rounds'])==0:
            self.night_off+=int(self.off.sum()); self.night_total+=n
        # One paid telemetry observation per macro round, not omniscient packet-level reads.
        self.cached_battery=self.battery.copy(); self.cached_quota=self.quota.copy()
        self.cached_queue=np.array([len(q) for q in self.queues]); self.cached_off=self.off.copy()
        for i in range(n):
            if i in ch_set or self.off[i] or self.off[self.parent[i]]:continue
            for _ in range(c['max_ch_actions_round']):
                if not self.queues[i]:break
                packet=self.queues[i][0]
                ok,energy,why=self.transmit(i,int(self.parent[i]),packet)
                if ok:self.queues[i].popleft()
                elif why!='link' or packet.tries>=c['max_link_attempts']:break
        for i in self.ch[np.argsort(-self.rank[self.ch])]:
            i=int(i)
            if self.off[i]:continue
            actions=0
            while self.queues[i] and actions<c['max_ch_actions_round']:
                o,mask,ids=self.observe(i)
                if self.agent is None:a=self.greedy(i,mask,ids)
                else:
                    if self.battery[i]<c['inference_j']+c['reserve_j']:break
                    self.spend(i,c['inference_j'],'inference')
                    a=self.agent.select(o,mask,self.training)
                actions+=1
                packet=self.queues[i][0]; age=self.t-packet.birth
                if a==c['candidates']:
                    reward=-0.12*(1+age/c['deadline_rounds']); stopped=True
                else:
                    j=int(ids[a]); ok,energy,why=self.transmit(i,j,packet)
                    reward=-0.03*energy/0.001
                    if ok:
                        self.queues[i].popleft()
                        reward+=1.0 if why=='sink' else 0.10*(self.rank[i]-self.rank[j])
                    else:reward-=0.08 if why=='link' else 0.12
                    stopped=(not ok and why!='link') or packet.tries>=c['max_link_attempts']
                if self.agent is not None and self.training:
                    no,nm,_=self.observe(i)
                    # Local scheduled routing episode ends on WAIT/empty queue;
                    # full environmental battery state is NOT reset.
                    self.agent.remember(o,mask,a,reward,no,nm,stopped or not self.queues[i])
                if stopped:break
        harvest=self.sc.harvest[self.sc.warm+self.t]
        before=self.battery.copy(); after=before+harvest
        spill=np.maximum(after-c['battery_j'],0)
        self.battery=np.minimum(after,c['battery_j'])
        self.harvested+=float(harvest.sum()); self.spilled+=float(spill.sum())
        ledger=self.initial_sum+self.harvested-self.consumed-self.spilled-float(self.battery.sum())
        if abs(ledger)>1e-6:raise AssertionError(f'energy conservation error {ledger}')
        ages=np.where(self.latest>=0,self.t-self.latest+1,self.t+1)
        coverage=np.mean((self.latest>=0)&(ages<=c['deadline_rounds']))
        self.logs.append({'round':self.t,'day':self.t/c['day_rounds'],'battery_mean_j':float(self.battery.mean()),
                          'coverage':float(coverage),'aoi_minutes':float(ages.mean()*c['round_seconds']/60),
                          'off_fraction':float(self.off.mean()),'solar_mean_j':float(harvest.mean()),
                          'queue_mean':float(np.mean([len(q) for q in self.queues])),'rho':self.rho,
                          'energy_balance_error_j':ledger})
        self.t+=1

    def run(self):
        for _ in range(self.sc.rounds):self.round()
        return self.metrics()

    def metrics(self):
        logs=self.logs
        outstanding=sum(len(q) for q in self.queues)
        assert self.generated==self.delivered+self.expired+self.overflow+outstanding
        return {'method':self.method,'seed':self.sc.seed,'nodes':self.n,'days':self.sc.rounds/self.c['day_rounds'],
                'coverage_pct':100*np.mean([v['coverage'] for v in logs]),
                'aoi_mean_minutes':float(np.mean([v['aoi_minutes'] for v in logs])),
                'aoi_p95_round_mean_minutes':float(np.quantile([v['aoi_minutes'] for v in logs],.95)),
                'off_pct':100*self.off_rounds/(self.n*self.sc.rounds),
                'night_off_pct':100*self.night_off/max(1,self.night_total),
                'demand_delivery_pct':100*self.delivered/self.demand,
                'pdr_generated_pct':100*self.delivered/max(1,self.generated),
                'sample_completion_pct':100*self.generated/self.demand,
                'consumed_j':self.consumed,'control_j':self.control_energy,'inference_j':self.inference_energy,
                'harvested_j':self.harvested,'spilled_j':self.spilled,
                'energy_per_delivered_j':self.consumed/max(1,self.delivered),
                'generated':self.generated,'delivered':self.delivered,'expired':self.expired,
                'unsensed':self.unsensed,'overflow':self.overflow,'outstanding':outstanding,
                'reclusters':self.reclusters,'changed_assignments':self.changed,
                'infeasible_node_periods':self.infeasible_nodes,'node_periods':self.n*self.periods,
                'link_success_pct':100*self.link_success/max(1,self.tx_attempts),
                'forecast_rmse_j_per_round':float(np.sqrt(np.mean(self.pred.residuals))) if self.pred.residuals else 0.,
                'max_energy_balance_error_j':max(abs(v['energy_balance_error_j']) for v in logs)}
