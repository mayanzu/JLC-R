"""Run only the current JLC-R controller into a new project-local directory.

This wrapper does not change the frozen controller or the physical model.
No execution occurs on import or with --help.
"""
from pathlib import Path
import argparse,hashlib,json,sys
import numpy as np
from current_io import PROJECT,ROOT,load_config,build_scenario
from validation_model import StreamingBank
from jlc_r import JLCR

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--condition',required=True,choices=['SYNTHETIC_G20','WINTER_G20','T2_G20','T3_G20'])
    p.add_argument('--seed',required=True,type=int)
    p.add_argument('--supply',required=True,type=float,choices=[1.0,0.7])
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    design=json.loads((ROOT/'current_design.json').read_text(encoding='utf-8'))
    condition=next(x for x in design['conditions'] if x['name']==a.condition)
    output=a.output.resolve()
    if not output.is_relative_to(PROJECT):p.error('--output must stay inside the project')
    if output.exists():p.error('--output must be a new directory; retained results cannot be overwritten')
    c=load_config(condition);sc=build_scenario(c,a.seed,design['days'],a.supply,condition)
    bank=StreamingBank(sc)
    sim=JLCR(c,sc,bank,v63_mechanism='relay_repair')
    sim.diagnostic_condition=a.condition
    sim.diagnostic_policy='JLC-R-HYB-V63'
    metrics=sim.run()
    record=dict(algorithm='JLC-R',implementation_id='JLC-R-HYB-V63',condition=a.condition,seed=a.seed,supply=a.supply,metrics=metrics,source_sha256=hashlib.sha256((ROOT/'v63_model.py').read_bytes()).hexdigest())
    output.mkdir(parents=True,exist_ok=False)
    def encode(x):
        if isinstance(x,np.generic):return x.item()
        if isinstance(x,np.ndarray):return x.tolist()
        raise TypeError(type(x).__name__)
    (output/'run.json').write_text(json.dumps(record,indent=2,default=encode)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(output),algorithm='JLC-R',condition=a.condition,seed=a.seed)))

if __name__=='__main__':main()
