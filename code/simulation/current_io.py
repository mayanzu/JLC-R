"""Input loading for the current JLC-R entry point. No simulation runs on import."""
from pathlib import Path
import json
import numpy as np
from validation_model import ScenarioV2, DEFAULTS

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[1]

def load_config(condition=None,extra=None):
    c=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
    c.update(DEFAULTS)
    if condition:c.update(condition.get('config',{}))
    if extra:c.update(extra)
    return c

def build_scenario(c,seed,days,supply,condition):
    # Same operation order and arrays as the frozen input builder.
    sc=ScenarioV2(c,seed,days,supply)
    if condition.get('weather_file'):
        ghi=np.loadtxt(PROJECT/condition['weather_file'],delimiter=',',skiprows=1)[:,1]
        if len(ghi)!=sc.warm+sc.rounds+sc.tail:raise ValueError('Measured weather length mismatch')
        sc.harvest=ghi[:,None]/1000*sc.solar_scale[None,:]
        sc.observed=sc.harvest.copy()
    sc.diagnostic_supply=supply
    return sc
