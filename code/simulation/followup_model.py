"""Configurable causal banks and observation windows; frozen simulators imported."""
from __future__ import annotations
from collections import deque
import hashlib
import numpy as np
from review_model import ReviewSimulator,ScenarioV2,ForecastBank,DEFAULTS
from simulator import Predictor,daylight


class ConfigurablePredictor(Predictor):
    def __init__(self,sc):
        super().__init__(sc)
        self.errors=deque(self.errors,maxlen=int(self.c.get('residual_history',192)))
        if self.errors.maxlen<1: raise ValueError('history must be positive')
        if not 0<=self.c.get('residual_quantile',.9)<=1: raise ValueError('quantile outside [0,1]')
        if self.c['scenario_count']<2: raise ValueError('at least point and conservative paths required')

    def forecast(self,t,rng):
        horizon=self.c['forecast_rounds']
        phase=daylight(t+np.arange(horizon),self.c['day_rounds'])
        base=self.scenario.solar_scale[:,None]*phase[None,:]
        point=base*np.clip(self.multiplier,.05,1.15)
        errors=np.asarray(self.errors) if self.errors else np.array([.3])
        scenarios=[point]
        for _ in range(self.c['scenario_count']-2):
            start=int(rng.integers(len(errors)))
            block=errors[(start+np.arange(horizon))%len(errors)]
            scenarios.append(base*np.clip(self.multiplier-block,0,1.15))
        conservative=max(0.,float(np.quantile(errors,self.c.get('residual_quantile',.9))))
        scenarios.append(base*np.clip(self.multiplier-conservative,0,1.15))
        rho=1/(1+max(0,float(errors.mean()))+float(errors.std()))
        self.issued.append((t,point.copy()))
        return point,np.stack(scenarios),max(.05,rho)


class StreamingBank:
    """Sequential, bounded forecast storage; only earlier observations enter a query.

    Diagnostics may inspect future truth after issuing a forecast; their values
    are never returned to the controller. Fresh bank per simulation trajectory.
    """
    def __init__(self,sc,diagnostics=False):
        self.sc=sc; self.pred=ConfigurablePredictor(sc); self.entries=self
        self.updated=-1; self.current_t=None; self.current=None
        self.signature=hashlib.sha256(); self.diagnostics=diagnostics
        self.cal={h:dict(count=0,sse=0.,covered=0,cumulative_count=0,short=0,
                         cumulative_sse=0.) for h in [1,4,16,48,96]}

    def __getitem__(self,t):
        if t==self.current_t:return self.current
        if self.current_t is not None and t<self.current_t:raise ValueError('streaming bank cannot rewind')
        if t%self.sc.cfg['period_rounds'] or not 0<=t<self.sc.rounds:raise ValueError('invalid issuance round')
        for tt in range(self.updated+1,t+1):self.pred.update(tt)
        self.updated=t
        rng=np.random.default_rng(np.random.SeedSequence([self.sc.seed,44,t]))
        point,risk,rho=self.pred.forecast(t,rng)
        point.flags.writeable=False;risk.flags.writeable=False
        self.current_t=t;self.current=(point,risk,rho,self.pred.multiplier)
        self.signature.update(point.tobytes());self.signature.update(risk.tobytes())
        if self.diagnostics:self.observe_truth(t,point,risk)
        return self.current

    def observe_truth(self,t,point,risk):
        for h,v in self.cal.items():
            actual=self.sc.harvest[self.sc.warm+t:self.sc.warm+t+h].T
            day=point[:,h-1]>0
            error=point[day,h-1]-actual[day,h-1]
            v['count']+=int(day.sum());v['sse']+=float(np.square(error).sum())
            v['covered']+=int(((actual[day,h-1]>=risk[:,day,h-1].min(axis=0))&
                                (actual[day,h-1]<=risk[:,day,h-1].max(axis=0))).sum())
            v['cumulative_count']+=self.sc.cfg['nodes']
            v['short']+=int((actual.sum(axis=1)<risk[:,:,:h].sum(axis=2).min(axis=0)-1e-12).sum())
            v['cumulative_sse']+=float(np.square(point[:,:h].sum(axis=1)-actual.sum(axis=1)).sum())

    @property
    def rmse(self):
        for tt in range(self.updated+1,self.sc.rounds):self.pred.update(tt)
        self.updated=self.sc.rounds-1
        return float(np.sqrt(np.mean(self.pred.residuals))) if self.pred.residuals else 0.

    def calibration_rows(self):
        return [dict(horizon=h,daylight_point_rmse_j=np.sqrt(v['sse']/max(1,v['count'])),
                     daylight_envelope_coverage_pct=100*v['covered']/max(1,v['count']),
                     cumulative_below_scenario_min_pct=100*v['short']/max(1,v['cumulative_count']),
                     cumulative_point_rmse_j=np.sqrt(v['cumulative_sse']/max(1,v['cumulative_count'])))
                for h,v in self.cal.items()]


class FollowupSimulator(ReviewSimulator):
    def __init__(self,c,sc,bank,policy='JOINT',windows=False):
        super().__init__(c,sc,bank,policy)
        self._base_profiles={};self.record_windows=windows;self.window_rows=[];self.window_node_rows=[]
        self.window_start=0;self.window_age=np.zeros(self.n);self.window_fresh=np.zeros(self.n,int)
        self.window_last=np.full(self.n,-1,int);self.window_gap=np.zeros(self.n,int)
        self.window_night=0;self.window_night_total=0
        self.post_age=np.zeros(self.n);self.post_fresh=np.zeros(self.n,int)
        self.post_start=14*c['day_rounds'];self.post_last=np.full(self.n,self.post_start-1,int)
        self.post_gap=np.zeros(self.n,int);self.post_night=0;self.post_night_total=0

    def base_profile(self,t,low=None):
        ph=self.phase(t)
        if ph not in self._base_profiles:
            c=self.c;base=np.empty((self.n,c['forecast_rounds']))
            for k in range(c['forecast_rounds']):
                phase=self.phase(t+k)
                base[:,k]=(c['sleep_w']*c['round_seconds']+
                    c['radio_idle_w']*self.listen_profiles[phase]+
                    c['radio_idle_w']*c.get('sync_extra_listen_s',0.)+
                    c['sense_j_per_bit']*c['packet_bits']+
                    c['control_j_per_node_period']/c['period_rounds'])
                if k>=c['period_rounds']:
                    base[:,k]+=c.get('future_relay_fraction',.65)*(
                        self.phase_structures[phase][2]+self.grant_profiles[phase])
            base.flags.writeable=False;self._base_profiles[ph]=base
        return self._base_profiles[ph]

    def round(self):
        old_latest=self.latest.copy();old_night=self.night_off;old_night_total=self.night_total
        super().round()
        if not self.record_windows:return
        t=self.t-1;ages=np.where(self.latest>=0,t-self.latest+1,t+1)
        self.window_age+=ages*self.c['round_seconds']/60
        self.window_fresh+=((self.latest>=0)&(ages<=self.c['deadline_rounds']))
        advanced=self.latest>old_latest
        self.window_gap[advanced]=np.maximum(self.window_gap[advanced],t-self.window_last[advanced])
        self.window_last[advanced]=t
        self.window_night+=self.night_off-old_night
        self.window_night_total+=self.night_total-old_night_total
        if t>=self.post_start:
            self.post_age+=ages*self.c['round_seconds']/60
            self.post_fresh+=((self.latest>=0)&(ages<=self.c['deadline_rounds']))
            self.post_gap[advanced]=np.maximum(self.post_gap[advanced],t-self.post_last[advanced])
            self.post_last[advanced]=t
            self.post_night+=self.night_off-old_night
            self.post_night_total+=self.night_total-old_night_total
        if self.t%(14*self.c['day_rounds'])==0 or self.t==self.sc.rounds:self.finish_window()
        if self.t==self.sc.rounds and self.t>self.post_start:
            self.record_period('postburnin',self.post_start,self.post_age,self.post_fresh,
                               self.post_last,self.post_gap,self.post_night,self.post_night_total)

    def finish_window(self):
        self.record_period('window',self.window_start,self.window_age,self.window_fresh,
                           self.window_last,self.window_gap,self.window_night,self.window_night_total)
        self.window_start=self.t;self.window_age[:]=0;self.window_fresh[:]=0
        self.window_last[:]=self.t-1;self.window_gap[:]=0
        self.window_night=0;self.window_night_total=0

    def record_period(self,kind,start,age_sum,fresh_sum,last,gap_rounds,night,night_total):
        length=self.t-start;minutes=self.c['round_seconds']/60
        gap=np.maximum(gap_rounds,self.t-1-last)*minutes
        age=age_sum/length;fresh=100*fresh_sum/length
        never=last<start
        label=dict(kind=kind,start_day=start//self.c['day_rounds'],end_day=self.t//self.c['day_rounds'])
        self.window_rows.append(dict(**label,coverage_pct=float(fresh.mean()),aoi_mean_minutes=float(age.mean()),
            source_aoi_p95_minutes=float(np.quantile(age,.95)),no_update_pct=float(100*never.mean()),
            longest_gap_p95_minutes=float(np.quantile(gap,.95)),night_off_pct=100*night/max(1,night_total)))
        self.window_node_rows.extend(dict(**label,node=i,mean_aoi_minutes=float(age[i]),coverage_pct=float(fresh[i]),
            no_update=int(never[i]),longest_no_update_minutes=float(gap[i])) for i in range(self.n))
