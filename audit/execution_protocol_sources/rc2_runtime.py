"""Frozen RC2 plus two external and two internal methods; import executes0rounds."""
from pathlib import Path
import hashlib,json,sys
HERE=Path(__file__).resolve().parent;PROJECT=HERE.parents[2]
read=lambda p:json.loads(p.read_text(encoding='utf8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
LOCATIONS=dict(rgp='temp/current_research/jlcr2_demand_guard_20261025_221513',
    rc2='temp/current_research/coverage_cadence_20261027_081600',
    energy='temp/current_research/eadcm_common_executor_20261027_003004/src',
    routing='temp/current_research/lantern_router_mac_20261027_013347/src')
for rel in ['code/simulation',*LOCATIONS.values()]:sys.path.insert(0,str(PROJECT/rel))
import cadence,bootstrap
assert Path(cadence.__file__).resolve()==PROJECT/LOCATIONS['rc2']/'cadence.py'
assert Path(bootstrap.__file__).resolve()==PROJECT/LOCATIONS['rc2']/'bootstrap.py'
from v63_model import RelayRepairHYB
from v6_model import HYBSimulator
from eadcm_host import EADCMCommonHost
from lantern_host import LanternCommonHost
from current_io import load_config,build_scenario
from validation_model import StreamingBank
def make(method,c,sc):
    bank=StreamingBank(sc)
    if method=='JLC-R-RC2':return cadence.ReserveCadenceCandidate(c,sc,bank,horizon_days=3,trigger_mode='reference',v63_mechanism='relay_repair')
    if method=='EADCM-CE':return EADCMCommonHost(c,sc,bank,forecast_days=5,target_fraction=.2)
    if method=='LANTERN-CE':return LanternCommonHost(c,sc,bank,maximum_reward=32.,trickle_redundancy=1,data_header_bits=64,uniform_listen_s=.56)
    if method=='Base-hybrid':return HYBSimulator(c,sc,bank)
    if method=='Pre-recovery-JLC-R':return RelayRepairHYB(c,sc,bank,v63_mechanism='relay_repair')
    raise ValueError(method)
def verify_sources(protocol):
    for group in ['source_sha256','input_sha256']:
        for rel,h in protocol[group].items():assert sha(PROJECT/rel)==h,rel
    for rel,h in protocol['execution_source_sha256'].items():assert sha(HERE/rel)==h,rel
def array_sha(a):return hashlib.sha256(a.tobytes(order='C')).hexdigest()
def signature(sc,s):
    r={k:array_sha(getattr(sc,k)) for k in ['pos','shade','harvest','observed']}
    r.update(link_probability=array_sha(s.prob),clock_bias=array_sha(s.clock_bias));return r
