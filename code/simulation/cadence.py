"""Early local multi-day reserve cadence, preserving frozen RGP transport.

The outer activation decision is a conservative load estimate, not a new
hard survival theorem. The original all-awake robust plan and physical checks
still bind. Fixed sampling obligations and D4 evaluation remain unchanged.
"""
from collections import Counter
import numpy as np
from bootstrap import RGPController

def choose_cadence(budget_j,head_j,member_sleep_j,member_increment_j):
    fraction=np.clip((budget_j-head_j-member_sleep_j)/np.maximum(member_increment_j,1e-30),0.,1.)
    return np.where(fraction>=1.-1e-12,1,np.where(fraction>=.5-1e-12,2,4)).astype(int)

class ReserveCadenceCandidate(RGPController):
    def __init__(self,*args,horizon_days=None,**kwargs):
        if horizon_days not in (None,3,5):raise ValueError('Only registered3/5 or off')
        self.horizon_days=horizon_days;self.activation_counts=Counter();self.activation_rows=[];self.cadence_plans=[]
        super().__init__(*args,**kwargs)
        if self.c['deadline_rounds']!=4 or self.c['period_rounds']!=4:raise ValueError('Registered D4/P4 only')
        self.cadence=np.ones(self.n,int)

    def install_plan(self):
        super().install_plan()
        if self.horizon_days is None:return
        c=self.c;point=self.bank.entries[self.t][0];assert point.shape==(self.n,96)
        fixed=(c['sleep_w']*900+c['radio_idle_w']*c['sync_extra_listen_s']+
            c['sense_j_per_bit']*c['packet_bits']+c['control_j_per_node_period']/c['period_rounds'])
        head=np.zeros(self.n);member_sleep=np.zeros(self.n);member_increment=np.zeros(self.n)
        for h in range(c['day_rounds']):
            ph=self.phase(self.t+h);heads=np.zeros(self.n,bool);heads[self.phase_heads[ph]]=True
            active=fixed+c['radio_idle_w']*self.reference_listening[ph]+self.phase_structures[ph][2]+self.grant_profiles[ph]
            sleep=c['off_w']*900
            head+=np.where(heads,active,0.);member_sleep+=np.where(heads,0.,sleep)
            member_increment+=np.where(heads,0.,np.maximum(0.,active-sleep))
        budget=np.maximum(0.,self.battery-c['reserve_j'])/self.horizon_days+point.sum(axis=1)
        self.cadence=choose_cadence(budget,head,member_sleep,member_increment)
        for i in range(self.n):self.cadence_plans.append(dict(round=self.t,node=i,horizon_days=self.horizon_days,
            battery_j=float(self.battery[i]),forecast_day_j=float(point[i].sum()),budget_day_j=float(budget[i]),
            head_day_j=float(head[i]),member_sleep_day_j=float(member_sleep[i]),member_increment_day_j=float(member_increment[i]),cadence=int(self.cadence[i])))

    def may_sleep(self,i):
        if self.horizon_days is None or i in self.ch or self.t%int(self.cadence[i])==0:return False
        if self.forward_holds[i]>1e-12 or self.forward_slot_holds[i]>0:return False
        return not any(not p.finalized and p.source!=i for p in self.queues[i])

    def prepare_sync_activity(self,i,listen):
        if not self.may_sleep(i):return super().prepare_sync_activity(i,listen)
        c=self.c;self.debit(i,min(self.battery[i],c['off_w']*900),'base')
        self.off[i]=True;self.slots_left[i]=0;self.cached_off[i]=True
        self.unsensed+=1;self.outcomes['unsensed']+=1;self.sample_status[self.t*self.n+i]=5
        self.activation_counts['intentional_sleep_node_rounds']+=1
        self.activation_rows.append(dict(round=self.t,node=i,horizon_days=self.horizon_days,cadence=int(self.cadence[i]),
            energy_j=float(self.round_base[i]),is_ch=False))
        for name,value in dict(battery_pre_sync_j=float(self.battery[i]),battery_post_sync_j=float(self.battery[i]),
            sync_attempted=0,sync_completed=0,sync_windows_completed=0,sync_energy_paid_j=0,
            sync_incomplete_energy_j=0,peer_cache_valid=0,traffic_eligible=0).items():self.add(name,i,value)

    def metrics(self):
        m=super().metrics();m.update(coverage_development_variant='RGP-EARLY-RESERVE-CADENCE',horizon_days=self.horizon_days,
            activation_counts=dict(self.activation_counts),outer_reserve_guarantee_claimed=False)
        return m
