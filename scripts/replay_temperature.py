"""Recompute the station-temperature task from a saved or rerun delivery array."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path

import numpy as np
from analysis_core import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--arrays',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve()
    if out.is_relative_to(ROOT.resolve()):p.error('Output must be outside the package')
    with (ROOT/'results/rc2_supplement/temperature_15m_1344.csv').open(encoding='utf8',newline='') as f:
        rr=list(csv.DictReader(f))
    assert len(rr)==1344
    truth=np.asarray([float(r['air_temperature_c']) if r['quality_valid']=='1' else np.nan for r in rr])
    source=ROOT/'audit/rc2_supplement/execution_sources/replay.py'
    spec=importlib.util.spec_from_file_location('saved_temperature_replay',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with np.load(a.arrays) as arrays:
        result=module.evaluate(arrays['latest'],truth)
    out.mkdir(parents=True,exist_ok=False)
    (out/'task_metrics.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'status':'PASS','output':str(out),'simulations_started':0},indent=2))


if __name__=='__main__':main()
