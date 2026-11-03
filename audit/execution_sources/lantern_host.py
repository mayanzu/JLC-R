"""Complete LANTERN upward decision chain in the common S200/G20 executor.

Explicit adaptations: previous-completed-macro rate estimates, MOP0 relevant
upward RPL, equal aggregate listening, paid serialized control and RPI bytes.
No claim of reproducing the author's Cooja/Contiki system is made here.
"""
from pathlib import Path
from collections import Counter,deque
import math,sys
import numpy as np
PROJECT=Path(__file__).resolve().parents[4];sys.path.insert(0,str(PROJECT/'code/simulation'))
from service_model import ServiceSimulator,radio_capacity
from strengthening_model import ResourceMixin
from simulator import keyed_uniform
from rpl_upward import UpwardRPL,Advertisement,INF,rank_error
from rpl_trickle import Trickle
from causal_meter import CausalRateMeter
from router_mac import maximum_symmetric

class LanternCommonHost(ResourceMixin,ServiceSimulator):
    def __init__(self,c,sc,bank=None,*,maximum_reward,trickle_redundancy=10,data_header_bits=64,uniform_listen_s=None):
        super().__init__(dict(c),sc,bank,'FIXED')
        self.method='LANTERN-causal-rate-common';self.maximum_reward=maximum_reward;self.k=trickle_redundancy
        self.data_header_bits=data_header_bits
        self.routers=[UpwardRPL(i,root=self.n,capacity_j=c['battery_j'],maximum_reward=maximum_reward,
             seed=int(np.random.SeedSequence([sc.seed,772,i]).generate_state(1)[0])) for i in range(self.n+1)]
        self.timers=[None]*self.n+[self.new_timer(self.n,0.)]
        self.pending=np.zeros(self.n+1,bool);self.sequence=np.zeros(self.n+1,int)
        maximum=maximum_symmetric(c,data_header_bits)
        allowance=maximum['listening_s'] if uniform_listen_s is None else float(uniform_listen_s)
        if not c['sync_listen_s']<=allowance<=c['ch_listen_s']:raise ValueError('MAC allowance outside shared limits')
        slots=int(np.floor((allowance-c['sync_listen_s'])/c['guard_listen_s']+1e-9))
        envelope=self.n*(allowance-c['sync_listen_s'])+self.n*slots*(c['packet_bits']+data_header_bits)/c['bitrate_bps']
        if envelope>maximum['window_s']+1e-9:raise ValueError('MAC allocation exceeds common late window')
        self.listening=np.full(self.n,allowance)
        self.meter=CausalRateMeter(self.n);self.now=0.;self.service_elapsed=0.;self.frame_airtime=0.
        self.node_base=np.zeros(self.n);self.node_data=np.zeros(self.n);self.node_control=np.zeros(self.n)
        self.node_harvest=np.zeros(self.n);self.node_spill=np.zeros(self.n);self.initial_b=self.battery.copy()
        self.source_fresh=np.zeros(self.n,int);self.source_age_sum=np.zeros(self.n)
        self.network_counts=Counter();self.control_rows=[];self.meter_rows=[];self.parent_rows=[]
        self.max_node_error=0.;self.max_global_error=0.;self.max_envelope=0.
        self.parent=np.full(self.n,-1,int);self.rank=np.full(self.n+1,INF);self.rank[-1]=256
        self.ch=np.arange(self.n);self.nud_failures=Counter();self.blocked=set()
        worst_offset=40e-6*c['sync_interval_s']+c['sync_jitter_s']+c['sync_turnaround_s']
        assert worst_offset<=c['guard_listen_s'] # covers every control sender/receiver
    def new_timer(self,i,now):
        timer=Trickle(redundancy=self.k,seed=int(np.random.SeedSequence([self.sc.seed,775,i]).generate_state(1)[0]))
        timer._start(now,timer.minimum);timer.now=now;return timer
    def debit(self,i,e,category):
        super().debit(i,e,category)
        if hasattr(self,'node_base'):
            target=self.node_data if category=='comm' else self.node_control if category=='control' else self.node_base
            target[i]+=e
    def finalize(self,packet,status):
        if status=='routing_drop':
            if packet.finalized:raise AssertionError('duplicate terminal sample')
            packet.finalized=True;self.outcomes[status]+=1;self.sample_status[packet.sequence]=6
        else:super().finalize(packet,status)
    def advance(self,now):
        if now<self.now-1e-9:raise ValueError('clock rewind')
        self.meter.advance(now)
        for i,timer in enumerate(self.timers):
            if timer is not None:
                due=timer.advance(now)
                if due:
                    self.network_counts['Trickle_requests']+=len(due)
                    self.network_counts['coalesced_DIO_requests']+=max(0,len(due)-int(not self.pending[i]))
                    self.pending[i]=True
        self.now=now
    def power_gate(self,i):
        enabled=self.routers[i].policy.update_power_state(float(self.battery[i]))
        if not enabled:self.off[i]=True
        return enabled
    def reset_timer(self,i):
        if self.timers[i] is None:self.timers[i]=self.new_timer(i,self.now)
        else:self.timers[i].inconsistent(self.now)
    def refresh(self,i):
        r=self.routers[i];old=r.rank;r.select(self.now,explore=False)
        if old!=r.rank:self.reset_timer(i)
        if r.poison_pending:self.pending[i]=True
    def charge_frame(self,sender,bits,kind,wire=b''):
        root=sender==self.n;c=self.c
        if not root and (self.off[sender] or self.slots_left[sender]<=0):return False,[]
        max_endpoints=int(not root)+sum(not self.off[int(i)] and self.slots_left[int(i)]>0
            for i in np.flatnonzero(self.adj[sender,:self.n]))
        if self.now+max_endpoints*(c['guard_listen_s']+bits/c['bitrate_bps'])>(self.t+1)*900+1e-9:
            return False,[]
        if not root:
            d=c['range_m'];d0=math.sqrt(c['fs_j_per_bit_m2']/c['mp_j_per_bit_m4'])
            amp=c['fs_j_per_bit_m2']*d*d if d<d0 else c['mp_j_per_bit_m4']*d**4
            tx=bits*(1.05*c['elec_j_per_bit']+amp)
            if self.available(sender)<tx:return False,[]
            self.use_slot(sender);self.debit(sender,tx,'control')
        else:tx=0.
        count=0 if root else 1;paid=[];decoded=[];rx=bits*c['elec_j_per_bit']
        sequence=int(self.sequence[sender]);self.sequence[sender]+=1
        for i in np.flatnonzero(self.adj[sender,:self.n]):
            i=int(i)
            if self.off[i] or self.slots_left[i]<=0 or self.available(i)<rx:continue
            self.use_slot(i);self.debit(i,rx,'control');count+=1;paid.append(i)
            if keyed_uniform(self.sc.seed,773,self.t,sender,i,sequence)<self.prob[sender,i]:decoded.append(i)
        if not root and self.adj[sender,self.n] and keyed_uniform(self.sc.seed,773,self.t,sender,self.n,sequence)<self.prob[sender,self.n]:
            decoded.append(self.n)
        elapsed=count*(c['guard_listen_s']+bits/c['bitrate_bps'])
        self.service_elapsed+=elapsed;self.frame_airtime+=count*bits/c['bitrate_bps']
        self.network_counts[kind+'_TX']+=1;self.network_counts[kind+'_RX_paid']+=len(paid)
        self.control_rows.append(dict(round=self.t,now_s=self.now,sender=sender,kind=kind,bits=bits,
            paid_receivers=';'.join(map(str,paid)),decoded_receivers=';'.join(map(str,decoded)),
            node_tx_energy_j=tx,node_rx_energy_j=len(paid)*rx,wire_hex=wire.hex()))
        for i in paid:self.power_gate(i)
        if not root:self.power_gate(sender)
        self.advance(self.t*c['round_seconds']+800.02+self.service_elapsed)
        return True,decoded
    def send_dio(self,sender):
        r=self.routers[sender]
        if r.version is None:return False
        root=sender==self.n
        if not root:
            self.refresh(sender)
            if self.off[sender]:return False
        battery=0. if root else float(self.battery[sender]);ema=0. if root else float(self.meter.eema[sender])
        frame=r.advertisement(battery,ema,int(self.sequence[sender]),self.now)
        wire=frame.wire(self.k);assert len(wire)*8==576
        stamp=self.now;rates_until=self.meter.rates_observed_until
        success,receivers=self.charge_frame(sender,len(wire)*8,'DIO',wire)
        if not success:return False
        self.pending[sender]=False
        if frame.rank==INF and r.poison_pending:r.poison_sent(self.now)
        if not root:
            self.meter_rows.append(dict(round=self.t,sender=sender,sampled_at_s=stamp,rates_observed_until_s=rates_until,
                eema_j=ema,estimated_harvest10_j=float(self.meter.h10[sender]),
                estimated_consumption10_j=float(self.meter.c10[sender]),battery_margin_j=frame.battery_margin,
                rank=frame.rank,max_q=frame.max_q))
        decoded=Advertisement.decode(wire)
        for i in receivers:
            rr=self.routers[i]
            if not rr.policy.enabled:continue
            old_rank=rr.rank;old_version=rr.version;status=rr.receive(decoded,self.now)
            if status=='stale_version':continue
            if old_version!=rr.version or self.timers[i] is None:self.timers[i]=self.new_timer(i,self.now)
            elif old_rank!=rr.rank:self.reset_timer(i)
            else:self.timers[i].consistent(self.now)
            if rr.rank<INF:self.blocked.discard(i)
            if rr.poison_pending:self.pending[i]=True
        return True
    def send_dis(self,sender):
        if self.off[sender]:return False
        wire=(sender.to_bytes(2,'big')+(2).to_bytes(2,'big')+int(self.sequence[sender]).to_bytes(4,'big')+b'\x00\x00')
        success,receivers=self.charge_frame(sender,len(wire)*8,'DIS',wire)
        if success:
            for i in receivers:
                if self.routers[i].rank<INF:self.reset_timer(i)
        return success
    def attempt_data(self,i,j,p):
        # Frame-sizing context: application payload remains c.packet_bits.
        # The original fee/slot/timing/random kernel charges the actual frame
        # payload+RPI, without changing any physical coefficient or source file.
        cfg=self.c;bits=cfg['packet_bits'];original_tx=self.tx_cost[i,j]
        if self.now+2*(cfg['guard_listen_s']+(bits+self.data_header_bits)/cfg['bitrate_bps'])>(self.t+1)*900+1e-9:
            return False,'mac_window'
        self.c=dict(cfg,packet_bits=bits+self.data_header_bits)
        self.tx_cost[i,j]=original_tx*(bits+self.data_header_bits)/bits
        before=int(self.slots_used.sum());sender_rank=self.routers[i].rank
        try:ok,why=ResourceMixin.attempt(self,i,j,p)
        finally:self.c=cfg;self.tx_cost[i,j]=original_tx
        endpoints=int(self.slots_used.sum())-before
        framed_bits=bits+self.data_header_bits
        self.service_elapsed+=endpoints*(cfg['guard_listen_s']+framed_bits/cfg['bitrate_bps'])
        self.frame_airtime+=endpoints*framed_bits/cfg['bitrate_bps']
        self.advance(self.t*cfg['round_seconds']+800.02+self.service_elapsed)
        if ok:
            self.routers[i].mark_reachable(j,self.now)
            if j<self.n:self.routers[j].mark_reachable(i,self.now)
        if ok and j<self.n and not p.finalized:
            state=rank_error(p,sender_rank,self.routers[j].rank)
            if state=='drop':
                self.queues[j].remove(p);self.finalize(p,'routing_drop');self.network_counts['RPI_loop_drops']+=1;self.reset_timer(j)
            elif state=='marked':self.network_counts['RPI_first_rank_errors']+=1
        self.power_gate(i)
        if j<self.n:self.power_gate(j)
        return ok,why
    def service_window(self):
        c=self.c;n=self.n;self.blocked=set();actions=np.zeros(n,int)
        packet_parents={}
        dis_sent=set();failed_controls=set()
        for i in range(n):self.refresh(i)
        while self.now<(self.t+1)*900-1e-8:
            pending=[i for i in range(n+1) if self.pending[i] and i not in failed_controls
                     and (i==n or (not self.off[i] and self.slots_left[i]>0))]
            if pending:
                # Ordering is an execution convention; no remote state enters OF.
                i=min(pending,key=lambda i:(i!=n,(i*37+self.t*17)%(n+1)))
                if not self.send_dio(i):failed_controls.add(i)
                continue
            undiscovered=[i for i in range(n) if self.routers[i].rank==INF and i not in dis_sent
                          and not self.off[i] and self.slots_left[i]>0]
            if undiscovered:
                i=undiscovered[0];dis_sent.add(i);self.send_dis(i);continue
            order=sorted(range(n),key=lambda i:(-self.routers[i].rank,i))
            ready=[i for i in order if i not in self.blocked and not self.off[i] and self.slots_left[i]>0
                   and actions[i]<c['max_ch_actions_round'] and self.queues[i] and self.routers[i].rank<INF]
            if ready:
                i=ready[0];r=self.routers[i];p=self.queues[i][0];key=(i,p.sequence)
                j=packet_parents.get(key)
                if j not in r.eligible(self.now):
                    j=r.select(self.now,explore=True);packet_parents[key]=j
                    self.network_counts['per_packet_parent_selections']+=1
                if j is None:
                    self.blocked.add(i)
                    if r.poison_pending:self.pending[i]=True
                    continue
                if p.last_try_round==self.t and p.round_tries>=c['max_link_attempts']:
                    self.blocked.add(i);continue
                ok,why=self.attempt_data(i,j,p);actions[i]+=1
                if ok:self.queues[i].popleft();self.nud_failures[(i,j)]=0
                else:
                    if why in ['link_loss','receiver_off','receiver_energy','receiver_credit']:
                        self.nud_failures[(i,j)]+=1
                        if self.nud_failures[(i,j)]>=c['max_link_attempts']:
                            r.failed_neighbor(j,self.now);self.reset_timer(i)
                            if r.poison_pending:self.pending[i]=True
                    if why!='link_loss' or p.round_tries>=c['max_link_attempts']:self.blocked.add(i)
                continue
            # No packet action available: allow future Trickle control events
            # within the paid common late window, without adding listen slots.
            events=[min(x.start+x.interval,x.transmit_at if not x.sent else math.inf)
                    for i,x in enumerate(self.timers) if x is not None and (i==n or (not self.off[i] and self.slots_left[i]>0))]
            future=min(events,default=math.inf)
            if future>=(self.t+1)*900 or not math.isfinite(future):break
            # Account the idle elapsed time so later actions cannot rewind time.
            self.service_elapsed=max(self.service_elapsed,future-(self.t*900+800.02))
            self.advance(future)
            if self.service_elapsed>99.98:raise AssertionError('late MAC clock overflow')
        self.parent=np.array([-1 if r.parent is None else r.parent for r in self.routers[:n]],int)
        self.rank=np.array([r.rank for r in self.routers],int)
    def round(self):
        c=self.c;t=self.t;n=self.n;self.advance(t*900)
        self.sync_paid[:]=False;self.slots_used[:]=0;self.slots_left=radio_capacity(self.listening,c)
        self.round_comm[:]=0;self.round_base[:]=0;self.round_control[:]=0
        self.quota=np.maximum(0.,self.battery-c['reserve_j']);self.credit=self.battery.copy()
        before=self.node_base+self.node_data+self.node_control
        for i in range(n):
            queue=deque()
            for p in self.queues[i]:
                if t-p.birth>=c['deadline_rounds']:self.expired+=1;self.finalize(p,'expired')
                else:queue.append(p)
            self.queues[i]=queue
            if not self.power_gate(i):
                self.off[i]=True;self.debit(i,min(float(self.battery[i]),c['off_w']*900),'base')
                self.unsensed+=1;self.outcomes['unsensed']+=1;self.sample_status[t*n+i]=5;self.slots_left[i]=0
            else:ResourceMixin.prepare_sync_activity(self,i,float(self.listening[i]));self.power_gate(i)
        self.demand+=n;self.off_rounds+=int(self.off.sum())
        self.quota=np.maximum(0.,self.battery-c['reserve_j'])
        self.service_elapsed=0.;self.frame_airtime=0.
        self.advance(t*900+800.02);self.service_window()
        envelope=float(np.maximum(0,self.listening-self.c['sync_listen_s']).sum()+self.frame_airtime)
        self.max_envelope=max(self.max_envelope,envelope)
        assert envelope<=99.98 and self.service_elapsed<=99.98+1e-8
        assert (self.slots_left>=0).all() and not self.holds and not self.hold_slots
        # Advance the old meter rates to the physical boundary first.
        self.advance((t+1)*900)
        h=self.sc.harvest[self.sc.warm+t];spill=np.maximum(self.battery+h-c['battery_j'],0.)
        self.battery=np.minimum(c['battery_j'],self.battery+h)
        self.node_harvest+=h;self.node_spill+=spill;self.harvested+=float(h.sum());self.spilled+=float(spill.sum())
        consumed=self.node_base+self.node_data+self.node_control-before
        self.meter.commit((t+1)*900,h,consumed)
        err=self.initial_b+self.node_harvest-self.node_spill-self.node_base-self.node_data-self.node_control-self.battery
        self.max_node_error=max(self.max_node_error,float(np.abs(err).max()))
        self.max_global_error=max(self.max_global_error,abs(self.initial_sum+self.harvested-self.consumed-self.spilled-self.battery.sum()))
        assert self.max_node_error<=1e-8 and self.max_global_error<=1e-6 and (self.battery>=-1e-12).all()
        age=np.where(self.latest>=0,t-self.latest+1,t+1);fresh=(self.latest>=0)&(age<=4)
        self.source_fresh+=fresh;self.source_age_sum+=age*15
        self.logs.append(dict(round=t,coverage=float(fresh.mean()),aoi_minutes=float(age.mean()*15)))
        self.t+=1
    def node_rows(self):
        return [dict(node=i,initial_j=float(self.initial_b[i]),harvest_j=float(self.node_harvest[i]),spill_j=float(self.node_spill[i]),
            base_j=float(self.node_base[i]),data_j=float(self.node_data[i]),control_j=float(self.node_control[i]),final_j=float(self.battery[i])) for i in range(self.n)]
    def metrics(self):
        for queue in self.queues:
            for p in queue:
                if not p.finalized:self.finalize(p,'outstanding')
        statuses=['delivered','expired','overflow','outstanding','unsensed','routing_drop']
        assert sum(self.outcomes[k] for k in statuses)==self.demand
        assert np.count_nonzero(self.sample_status)==self.demand
        cov=100*self.source_fresh/self.t
        return dict(method=self.method,maximum_reward=self.maximum_reward,trickle_redundancy=self.k,
            coverage_pct=float(cov.mean()),source_coverage_p5_pct=float(np.quantile(cov,.05)),
            source_coverage_jain=float(cov.sum()**2/(self.n*(cov**2).sum())) if cov.any() else 0.,
            aoi_mean_minutes=float(self.source_age_sum.mean()/self.t),max_node_energy_error_j=self.max_node_error,
            max_energy_balance_error_j=self.max_global_error,timing_misses=self.timing_misses,max_late_envelope_s=self.max_envelope,
            counts=dict(self.network_counts),RPL_counts=dict(sum((r.counts for r in self.routers),Counter())),
            outcomes=dict(self.outcomes),control_energy_j=float(self.node_control.sum()),uniform_listen_s=float(self.listening[0]),
            DIO_bits=576,DIS_bits=80,RPI_bits=self.data_header_bits,forwarding_holds_created=0,
            meter='Previous completed900s own energy-rate estimates; original10s EEMA, no physical redistribution',
            RPL_scope='Complete relevant upwardMOP0 repair/discovery/poison/version/Trickle/RPI; not full IPv6 stack')
