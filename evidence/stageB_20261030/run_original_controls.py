"""Complete original JLC-Base/JLC-Core comparisons on the locked candidate seeds."""
from pathlib import Path
import argparse,hashlib,json
import run_stage_b as base
H=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=('pilot','confirmation'),required=True)
    ap.add_argument('--workers',type=int,default=6);args=ap.parse_args()
    p=json.loads((H/'protocol_predefined.json').read_text(encoding='utf8'))
    x=json.loads((H/'original_controls_protocol.json').read_text(encoding='utf8'))
    assert x['parent_protocol_sha256']==sha(H/'protocol_predefined.json')
    for rel,digest in p['frozen_source_sha256'].items():
        assert sha(base.PACKAGE/rel)==digest,rel
    if args.phase=='pilot':
        cases=[{'index':i+1,'seed':60503,'condition':'SYNTHETIC_G20','supply':1.,
                'method':method,'days':2,'pilot':True} for i,method in enumerate(x['methods'])]
        out=H/'original_controls_pilot'
    else:
        lock=json.loads((H/'original_controls_lock.json').read_text(encoding='utf8'))
        assert lock['protocol_sha256']==sha(H/'original_controls_protocol.json')
        assert lock['runner_sha256']==sha(Path(__file__))
        assert lock['base_runner_sha256']==sha(H/'run_stage_b.py')
        assert json.loads((H/'original_controls_pilot/completion.json').read_text(encoding='utf8'))['status']=='COMPLETE'
        cases=x['cases'];out=H/'original_controls_confirmation'
    if not base.submit(cases,p,out,args.workers):raise SystemExit(1)
if __name__=='__main__':main()
