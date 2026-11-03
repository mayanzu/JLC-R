"""RC2 candidate entry. Frozen V63 remains its inherited resource kernel."""
from cadence import ReserveCadenceCandidate

class JLCR(ReserveCadenceCandidate):
    """The locked complete controller; configuration cannot drift silently."""
    def __init__(self,*args,**kwargs):
        locked=dict(horizon_days=3,trigger_mode='reference',v63_mechanism='relay_repair')
        for key,value in locked.items():
            if key in kwargs and kwargs[key]!=value:
                raise ValueError(f'{key} must equal the locked value {value!r}')
            kwargs[key]=value
        super().__init__(*args,**kwargs)

__all__=['JLCR']
