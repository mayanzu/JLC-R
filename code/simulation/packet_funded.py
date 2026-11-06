"""Packet-funded controller shared by the source-aware method and controls."""
from cadence import ReserveCadenceCandidate
from credit_floor import enforce_credit_floor

class PacketFundedJLCR(ReserveCadenceCandidate):
    """The locked complete controller; configuration cannot drift silently."""
    def __init__(self,*args,**kwargs):
        locked=dict(horizon_days=3,trigger_mode='reference',v63_mechanism='relay_repair')
        for key,value in locked.items():
            if key in kwargs and kwargs[key]!=value:
                raise ValueError(f'{key} must equal the locked value {value!r}')
            kwargs[key]=value
        super().__init__(*args,**kwargs)
        self.floor_correction_count = 0
        self.floor_correction_max_j = 0.0
        self.floor_correction_total_j = 0.0

    def install_plan(self):
        super().install_plan()
        enforce_credit_floor(self)

    def metrics(self):
        row = super().metrics()
        row.update(credit_floor_revision='20261105',
                   floor_correction_count=self.floor_correction_count,
                   floor_correction_max_j=self.floor_correction_max_j,
                   floor_correction_total_j=self.floor_correction_total_j)
        return row

__all__=['PacketFundedJLCR']
