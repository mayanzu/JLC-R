"""Independent RFC6206 Sec.4 timer, with ContikiRPL source defaults.

Sources: rfc-editor.org/rfc/rfc6206.html;
contiki-os/contiki/core/net/rpl/rpl-conf.h (Imin2^12ms,8 doublings,k10).
No radio energy or route policy is implemented here. The host must pay/deliver
each emitted advertisement; a timer event is not a free received DIO.
"""
import math,random

class Trickle:
    def __init__(self,*,minimum_s=4.096,doublings=8,redundancy=10,seed=0):
        if not math.isfinite(minimum_s) or minimum_s<=0 or doublings<0 or int(doublings)!=doublings:
            raise ValueError('invalid interval')
        if redundancy<0 or int(redundancy)!=redundancy:raise ValueError('invalid redundancy')
        self.minimum=minimum_s;self.maximum=minimum_s*2**doublings;self.k=redundancy
        self.rng=random.Random(seed);self.now=0.;self.interval=minimum_s;self.start=0.
        self.count=0;self.sent=False;self.transmit_at=self.rng.uniform(minimum_s/2,minimum_s)
        self.emitted=0;self.suppressed=0;self.resets=0

    def _start(self,start,length):
        self.start=start;self.interval=length;self.count=0;self.sent=False
        self.transmit_at=start+self.rng.uniform(length/2,length)

    def advance(self,now):
        if not math.isfinite(now) or now<self.now:raise ValueError('time must be causal and monotone')
        due=[]
        while True:
            end=self.start+self.interval
            event=min(end,self.transmit_at if not self.sent else math.inf)
            if event>now:break
            if not self.sent and self.transmit_at<=end:
                self.sent=True
                if self.k==0 or self.count<self.k:due.append(self.transmit_at);self.emitted+=1
                else:self.suppressed+=1
            else:self._start(end,min(2*self.interval,self.maximum))
        self.now=now;return due

    def consistent(self,now):
        if now!=self.now:raise ValueError('Advance timer first; do not silently lose pending TX events')
        self.count+=1

    def inconsistent(self,now):
        if now!=self.now:raise ValueError('Advance timer first')
        if self.interval>self.minimum:
            self._start(now,self.minimum);self.resets+=1
