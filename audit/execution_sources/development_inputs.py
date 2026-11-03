"""Only disjoint2023 development data; formal2024 files are never loaded."""
from pathlib import Path
import json,sys
import numpy as np
HERE=Path(__file__).resolve().parents[1];PROJECT=HERE.parents[2]
sys.path.insert(0,str(PROJECT/'code/simulation'))
from current_io import load_config,build_scenario
from validation_model import StreamingBank

_cache={}
CELLS=[('ample_CO',1.0),('winter_IL',1.0),('winter_IL',.7)]

def make_input(split,cell,seed):
    key=(split,cell,seed)
    if key not in _cache:
        site,supply=CELLS[cell]
        design=json.loads((PROJECT/'code/simulation/current_design.json').read_text(encoding='utf8'))
        cond=next(x for x in design['conditions'] if x['name']=='SYNTHETIC_G20')
        c=load_config(cond);sc=build_scenario(c,seed,14,supply,cond)
        ghi=np.loadtxt(HERE/'weather'/(site+'_'+split+'.csv'),delimiter=',',skiprows=1,usecols=[1])
        days=3 if split=='train' else 2
        assert len(ghi)==sc.warm+days*c['day_rounds']+sc.tail
        sc.rounds=days*c['day_rounds'];sc.harvest=ghi[:,None]/1000*sc.solar_scale[None,:]
        sc.observed=sc.harvest.copy()
        sc.harvest.flags.writeable=False;sc.observed.flags.writeable=False
        _cache[key]=(c,sc)
    return _cache[key]
