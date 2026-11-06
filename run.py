"""Run the current JLC-R controller; write outputs outside this code-only package."""
from pathlib import Path
import argparse,hashlib,json,sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'code/simulation'))
import numpy as np
from validation_model import ScenarioV2,StreamingBank
from jlc_r import JLCR

def load_config():
    return json.loads((ROOT/'config.json').read_text(encoding='utf8'))

def build_scenario(config,seed,days,supply,weather=None):
    scenario=ScenarioV2(config,seed,days,supply)
    if weather is not None:
        values=np.loadtxt(weather,delimiter=',',skiprows=1)
        if values.ndim!=2 or values.shape[1]<2:
            raise ValueError('Weather CSV requires a header and GHI in its second column')
        ghi=values[:,1]
        if len(ghi)!=scenario.warm+scenario.rounds+scenario.tail:
            raise ValueError('Weather rows must cover warm-up, evaluated rounds and forecast tail')
        if not np.isfinite(ghi).all() or (ghi<0).any():
            raise ValueError('GHI must be finite and nonnegative')
        scenario.harvest=ghi[:,None]/1000*scenario.solar_scale[None,:]
        scenario.observed=scenario.harvest.copy()
    scenario.diagnostic_supply=supply
    return scenario

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed',type=int,required=True)
    parser.add_argument('--days',type=int,default=14)
    parser.add_argument('--supply',type=float,choices=[1.0,0.7],default=1.0)
    parser.add_argument('--weather',type=Path,help='Optional external 15-minute GHI CSV; default: synthetic weather')
    parser.add_argument('--source-protection',choices=['spatial','unweighted','off','admission','headroom','priority','joint'],default='spatial')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    if args.days<1:parser.error('--days must be positive')
    if output.is_relative_to(ROOT):parser.error('--output must be outside this code-only package')
    if output.exists():parser.error('--output must be new')
    from verify import verify_files
    manifest=verify_files()
    config=load_config();scenario=build_scenario(config,args.seed,args.days,args.supply,args.weather)
    simulator=JLCR(config,scenario,StreamingBank(scenario),source_protection=args.source_protection)
    metrics=simulator.run()
    def encode(value):
        if isinstance(value,np.generic):return value.item()
        if isinstance(value,np.ndarray):return value.tolist()
        raise TypeError(type(value).__name__)
    record=dict(algorithm='JLC-R',implementation_id=manifest['implementation_id'],seed=args.seed,days=args.days,supply=args.supply,source_protection=args.source_protection,weather_sha256=hashlib.sha256(args.weather.read_bytes()).hexdigest() if args.weather else None,config=config,metrics=metrics)
    output.mkdir(parents=True,exist_ok=False)
    (output/'run.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,default=encode)+'\n',encoding='utf8')
    print(json.dumps(dict(status='COMPLETE',output=str(output),implementation=manifest['implementation_id'])))

if __name__=='__main__':main()
