"""Gerndt et al. 2025, DOI10.3390/s25144500, Sec.4 complete planning kernel.

Includes hourly consumption, storage/charging saturation, intra-day survival,
daily checkpoints and the backward stack search in Algorithm1. This is an
isolated policy implementation, NOT yet a shared-network external baseline.
The charging function must be supplied by the common physical model; no
measured hardware charging curve is invented.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Plan:
    sleeps_s: tuple
    feasible: bool
    required_initial_j: float
    states_evaluated: int


class EADCM:
    def __init__(self, *, capacity_j, duty_power_w, duty_s, sleep_power_w,
                 sleep_options_s, target_fraction=0.2, charge_power_w=None):
        vals=(capacity_j,duty_power_w,duty_s,sleep_power_w,target_fraction)
        if not all(math.isfinite(x) for x in vals):raise ValueError('nonfinite parameter')
        if capacity_j<=0 or duty_s<=0 or duty_power_w<sleep_power_w or sleep_power_w<0:
            raise ValueError('invalid energy model')
        opts=tuple(sorted(set(sleep_options_s)))
        if not opts or any(not math.isfinite(x) or x<0 for x in opts):
            raise ValueError('invalid sleep options')
        if not 0<=target_fraction<=1:raise ValueError('invalid target')
        self.capacity=capacity_j; self.duty_power=duty_power_w; self.duty_s=duty_s
        self.sleep_power=sleep_power_w;self.options=opts
        self.target=target_fraction*capacity_j
        self.charge_power=charge_power_w or (lambda fraction: math.inf)

    def hourly_load_j(self,sleep_s):
        # Source Eq.(3); same seconds/Joules throughout.
        return (self.duty_power*self.duty_s+self.sleep_power*sleep_s)*3600/(self.duty_s+sleep_s)

    def _hour(self,battery,harvest,load):
        surplus=harvest-load
        if surplus<0:return battery+surplus
        limit=self.charge_power(battery/self.capacity)
        if math.isnan(limit) or limit<0:raise ValueError('invalid charging model')
        return min(self.capacity,battery+min(surplus,limit*3600))

    def forward(self,initial,harvest_day,sleep_s):
        load=self.hourly_load_j(sleep_s);b=initial
        for h in harvest_day:
            b=self._hour(b,h,load)
            if b < -1e-10:return b,False
        return b,True

    def required_initial(self,harvest_day,sleep_s,end_j):
        if self.charge_power(0.) == math.inf and self.charge_power(1.) == math.inf:
            if not 0 <= end_j <= self.capacity:return math.inf
            required=end_j;load=self.hourly_load_j(sleep_s)
            for h in reversed(harvest_day):
                required=max(0.,required+load-h)
                if required>self.capacity+1e-10:return math.inf
            return required
        # Numerical inversion of F_RSOC, including F_E_min's intra-day
        # nondepletion constraint. Equivalent to backwards hourly inversion
        # for monotone charging curves; caller must validate monotonicity.
        # No actual future trace enters this API: harvest_day is a forecast.
        end,ok=self.forward(self.capacity,harvest_day,sleep_s)
        if not ok or end<end_j-1e-10:return math.inf
        lo=0.;hi=self.capacity
        for _ in range(64):
            mid=(lo+hi)/2;end,ok=self.forward(mid,harvest_day,sleep_s)
            if ok and end>=end_j:hi=mid
            else:lo=mid
        return hi

    def plan(self,initial_j,forecast_j,*,issued_at_s,observed_until_s):
        if issued_at_s>observed_until_s:raise ValueError('forecast issued in the future')
        if not math.isfinite(initial_j) or not 0<=initial_j<=self.capacity:
            raise ValueError('invalid initial battery')
        days=tuple(tuple(row) for row in forecast_j)
        if not days or any(len(row)!=24 for row in days):raise ValueError('need24 hourly values per day')
        if any(not math.isfinite(h) or h<0 for row in days for h in row):raise ValueError('invalid forecast')
        nd=len(days);longest=self.options[-1];choice=[longest]*nd
        checkpoints=[initial_j]
        for row in days[:-1]:
            b,ok=self.forward(checkpoints[-1],row,longest)
            checkpoints.append(b if ok else -math.inf)
        required_end=self.target;d=nd-1;stack=[];evaluated=0
        while d>=0:
            found=[]
            for sleep in reversed(self.options):
                req=self.required_initial(days[d],sleep,required_end);evaluated+=1
                if req<=checkpoints[d]+1e-10:
                    found.append((d,req,sleep));choice[d]=sleep
                else:break
            if found:
                # Retain all longer valid alternatives for Algorithm1's pop.
                stack.extend(found[:-1]);_,required_end,choice[d]=found[-1]
                d-=1
                continue
            if not stack:return Plan(tuple([longest]*nd),False,math.inf,evaluated)
            day,required_end,sleep=stack.pop();choice[day]=sleep;d=day-1
            # Earlier choices will be recomputed. Later choices stay fixed,
            # exactly as in the source stack algorithm.
        return Plan(tuple(choice),True,required_end,evaluated)
