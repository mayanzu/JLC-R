"""EADCM's multi-day checkpoint/backtracking policy, common paid FIFO transport.

No JLC-specific planner, sorting, recovery or forwarding reservation. Whole
macro-round duty/sleep quantization is explicit and audited before admission.
"""
from pathlib import Path
from collections import deque,Counter
import sys
import numpy as np
PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'code/simulation'))
from strengthening_model import ResourceMixin
from service_model import ServiceSimulator,radio_capacity
from eadcm_policy import EADCM


class EADCMCommonHost(ResourceMixin,ServiceSimulator):
    def __init__(self,c,sc,bank,*,forecast_days=3,target_fraction=.2,forced_period=None):
        if forecast_days not in (3,5):raise ValueError('unregistered forecast horizon')
        if forced_period is not None and forced_period not in (1,2,3,4):raise ValueError('invalid fixture period')
        super().__init__(dict(c),sc,bank,'FIXED')
        self.method='EADCM-common-environment';self.forecast_days=forecast_days;self.target=target_fraction
        self.forced_period=forced_period
        self.next_active=np.zeros(self.n,int);self.periods_rounds=np.ones(self.n,int)
        self.activity_rows=[];self.planning_rows=[];self.counts=Counter()
        self.source_fresh=np.zeros(self.n,int);self.source_age_sum=np.zeros(self.n)
        self.node_base=np.zeros(self.n);self.node_data=np.zeros(self.n);self.node_control=np.zeros(self.n)
        self.node_harvest=np.zeros(self.n);self.node_spill=np.zeros(self.n);self.initial_b=self.battery.copy()
        self.max_node_error=0.;self.max_global_error=0.;self.max_envelope=0.
        self.day_active_cost=np.zeros(self.n);self.day_active_count=np.zeros(self.n,int)
        # Source expects measured/calibrated application power. In simulation,
        # use the public physical-model estimate until own completed duties exist.
        initial=[]
        for ph,listen in enumerate(self.listen_profiles):
            cost=(c['sleep_w']*c['round_seconds']+c['radio_idle_w']*(listen+c.get('sync_extra_listen_s',0.))
                  +c['sense_j_per_bit']*c['packet_bits']+c['control_j_per_node_period']/c['period_rounds'])
            initial.append(cost+self.phase_structures[ph][2])
        self.active_cost=np.mean(initial,axis=0)

    def debit(self,i,e,category):
        super().debit(i,e,category)
        if hasattr(self,'node_base'):
            target=self.node_data if category=='comm' else self.node_control if category=='control' else self.node_base
            target[i]+=e

    def install_plan(self):
        ph=self.phase(self.t);heads=self.phase_heads[ph];parent,rank,_=self.phase_structures[ph]
        self.ch=heads.copy();self.parent=parent.copy();self.rank=rank.copy();self.next_hop=parent.copy()
        self.next_hop[heads]=self.reference_next[ph][heads]
        self.periods+=1

    def plan_day(self):
        c=self.c
        observed=self.day_active_count>0
        self.active_cost[observed]=self.day_active_cost[observed]/self.day_active_count[observed]
        self.day_active_cost[:]=0;self.day_active_count[:]=0
        if self.forced_period is not None:
            self.periods_rounds[:]=self.forced_period;return
        point,_,_,_=self.bank.entries[self.t]
        assert point.shape==(self.n,c['day_rounds']) and self.t%c['day_rounds']==0
        hourly=point.reshape(self.n,24,4).sum(axis=2)
        forecasts=np.tile(hourly[:,None,:],(1,self.forecast_days,1))
        for i in range(self.n):
            # P_duty is mean energy over one active macro-round, not a claim
            # that radio or CPU is continuously on for900s.
            power=max(c['off_w'],self.active_cost[i]/c['round_seconds'])
            manager=EADCM(capacity_j=c['battery_j'],duty_power_w=power,duty_s=c['round_seconds'],
                sleep_power_w=c['off_w'],sleep_options_s=[k*c['round_seconds'] for k in range(4)],
                target_fraction=self.target)
            plan=manager.plan(float(self.battery[i]),forecasts[i],issued_at_s=self.t*c['round_seconds'],
                              observed_until_s=self.t*c['round_seconds'])
            q=1+round(plan.sleeps_s[0]/c['round_seconds']);assert q in (1,2,3,4)
            self.periods_rounds[i]=q
            self.planning_rows.append(dict(round=self.t,node=i,forecast_days=self.forecast_days,period_rounds=q,
                feasible=plan.feasible,required_initial_j=plan.required_initial_j,states=plan.states_evaluated,
                measured_active_energy_j=float(self.active_cost[i]),battery_j=float(self.battery[i]),
                forecast_total_j=float(forecasts[i].sum()),observations_through_round=self.t-1))
        # Do not advance an existing next-active timer at replan: sleep already
        # committed before midnight completes, as in a sleeping device.

    def route_fifo(self,i):
        if self.off[i]:return
        j=int(self.next_hop[i])
        for _ in range(self.c['max_ch_actions_round']):
            if not self.queues[i]:break
            packet=self.queues[i][0]
            if packet.last_try_round==self.t and packet.round_tries>=self.c['max_link_attempts']:break
            ok,why=ResourceMixin.attempt(self,i,j,packet)
            if ok:self.queues[i].popleft()
            elif why!='link_loss' or packet.round_tries>=self.c['max_link_attempts']:break

    def round(self):
        c=self.c;t=self.t;n=self.n
        if t%c['period_rounds']==0:self.install_plan()
        if t%c['day_rounds']==0:self.plan_day()
        active=t>=self.next_active
        self.next_active[active]=t+self.periods_rounds[active]
        listen=self.listen_profiles[self.phase(t)]
        self.sync_paid[:]=False;self.slots_used[:]=0;self.slots_left=radio_capacity(listen,c)
        self.round_comm[:]=0;self.round_base[:]=0;self.round_control[:]=0
        self.quota=np.maximum(0.,self.battery-c['reserve_j']);self.credit=self.battery.copy()
        before=self.node_base+self.node_data+self.node_control
        for i in range(n):
            queue=deque()
            for packet in self.queues[i]:
                if t-packet.birth>=c['deadline_rounds']:
                    self.expired+=1;self.finalize(packet,'expired')
                else:queue.append(packet)
            self.queues[i]=queue
            if not active[i]:
                self.off[i]=True;self.slots_left[i]=0
                self.debit(i,min(self.battery[i],c['off_w']*c['round_seconds']),'base')
                self.unsensed+=1;self.outcomes['unsensed']+=1;self.sample_status[t*n+i]=5
                self.counts['intentional_sleep_node_rounds']+=1
            else:
                ResourceMixin.prepare_sync_activity(self,i,float(listen[i]))
                self.counts['scheduled_active_node_rounds']+=1
        self.demand+=n;self.off_rounds+=int(self.off.sum())
        self.quota=np.maximum(0.,self.battery-c['reserve_j'])
        heads=set(map(int,self.ch))
        for i in range(n):
            if i not in heads:self.route_fifo(i)
        for i in self.ch[np.argsort(-self.rank[self.ch])]:self.route_fifo(int(i))
        assert not self.holds and not self.hold_slots
        consumed=self.node_base+self.node_data+self.node_control-before
        sampled=self.sample_status[t*n:t*n+n]!=5
        self.day_active_cost[sampled]+=consumed[sampled];self.day_active_count[sampled]+=1
        envelope=float(np.maximum(0,listen[~self.off]-c['sync_listen_s']).sum()
                       +self.slots_used.sum()*c['packet_bits']/c['bitrate_bps'])
        self.max_envelope=max(self.max_envelope,envelope);assert envelope<=99.98 and (self.slots_left>=0).all()
        h=self.sc.harvest[self.sc.warm+t];spill=np.maximum(self.battery+h-c['battery_j'],0.)
        self.battery=np.minimum(c['battery_j'],self.battery+h)
        self.node_harvest+=h;self.node_spill+=spill;self.harvested+=float(h.sum());self.spilled+=float(spill.sum())
        error=self.initial_b+self.node_harvest-self.node_spill-self.node_base-self.node_data-self.node_control-self.battery
        self.max_node_error=max(self.max_node_error,float(np.abs(error).max()))
        self.max_global_error=max(self.max_global_error,abs(self.initial_sum+self.harvested-self.consumed-self.spilled-self.battery.sum()))
        assert self.max_node_error<=1e-8 and self.max_global_error<=1e-6 and (self.battery>=-1e-12).all()
        age=np.where(self.latest>=0,t-self.latest+1,t+1);fresh=(self.latest>=0)&(age<=c['deadline_rounds'])
        self.source_fresh+=fresh;self.source_age_sum+=age*c['round_seconds']/60
        self.logs.append(dict(round=t,coverage=float(fresh.mean()),aoi_minutes=float(age.mean()*c['round_seconds']/60)))
        for i in range(n):
            self.activity_rows.append(dict(round=t,node=i,scheduled_active=bool(active[i]),sampled=bool(sampled[i]),
                actual_energy_j=float(consumed[i]),next_active_round=int(self.next_active[i])))
        self.t+=1

    def node_rows(self):
        return [dict(node=i,initial_j=float(self.initial_b[i]),harvest_j=float(self.node_harvest[i]),
            spill_j=float(self.node_spill[i]),base_j=float(self.node_base[i]),data_j=float(self.node_data[i]),
            control_j=float(self.node_control[i]),final_j=float(self.battery[i])) for i in range(self.n)]

    def metrics(self):
        for queue in self.queues:
            for packet in queue:
                if not packet.finalized:self.finalize(packet,'outstanding')
        assert sum(self.outcomes[k] for k in ['delivered','expired','overflow','outstanding','unsensed'])==self.demand
        assert np.count_nonzero(self.sample_status)==self.demand
        source=100*self.source_fresh/self.t
        return dict(method=self.method,forecast_days=self.forecast_days,coverage_pct=float(source.mean()),
            source_coverage_p5_pct=float(np.quantile(source,.05)),
            source_coverage_jain=float(source.sum()**2/(self.n*(source**2).sum())) if source.any() else 0.,
            aoi_mean_minutes=float(self.source_age_sum.mean()/self.t),max_node_energy_error_j=self.max_node_error,
            max_energy_balance_error_j=self.max_global_error,timing_misses=self.timing_misses,max_late_envelope_s=self.max_envelope,
            outcomes=dict(self.outcomes),counts=dict(self.counts),forwarding_holds_created=0,
            quantization='Duty900s, extra sleep0/900/1800/2700s, hourly time-average energy model',
            scope='Complete planning and duty policy, common FIFO reference transport; admission requires quantization audit')
