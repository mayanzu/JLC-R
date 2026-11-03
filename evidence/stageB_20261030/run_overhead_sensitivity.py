"""Common 1.32 wire-overhead stress on the existing abstract executor.

Not a full protocol calibration: no contention dynamics, exact ACK energy
allocation, or ns-3 controllers are implemented here.
"""
from pathlib import Path
import argparse,hashlib,json
import run_stage_b as base
H=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['pilot','confirmation'],required=True)
    ap.add_argument('--workers',type=int,default=2);args=ap.parse_args()
    p=json.loads((H/'protocol_predefined.json').read_text(encoding='utf8'))
    x=json.loads((H/'overhead_protocol.json').read_text(encoding='utf8'))
    assert x['parent_protocol_sha256']==sha(H/'protocol_predefined.json')
    multiplier=x['factor']
    amended=[]
    for condition in p['conditions']:
        initial=base.load_config(condition)
        cfg=dict(condition['config'])
        for key in ['elec_j_per_bit','fs_j_per_bit_m2','mp_j_per_bit_m4']:
            cfg[key]=initial[key]*multiplier
        cfg['bitrate_bps']=initial['bitrate_bps']/multiplier
        updated=dict(condition,config=cfg);amended.append(updated)
    p['conditions']=amended
    if args.phase=='pilot':
        cases=[{'index':i+1,'seed':60503,'condition':'SYNTHETIC_G20','supply':1.0,
                'method':method,'days':2,'pilot':True}
               for i,method in enumerate(x['methods'])]
        out=H/'overhead_pilot'
    else:
        lock=json.loads((H/'overhead_lock.json').read_text(encoding='utf8'))
        if lock['runner_sha256']!=sha(Path(__file__)) or lock['protocol_sha256']!=sha(H/'overhead_protocol.json'):
            raise SystemExit('Overhead design changed after lock')
        if json.loads((H/'overhead_pilot/completion.json').read_text(encoding='utf8'))['status']!='COMPLETE':
            raise SystemExit('Overhead pilot failure')
        cases=x['cases'];out=H/'overhead_confirmation'
    if not base.submit(cases,p,out,args.workers):raise SystemExit(1)
if __name__=='__main__':main()
