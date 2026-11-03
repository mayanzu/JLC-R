"""Exploratory q=8 cadence threshold. Frozen JLC-R remains the paired control."""
from pathlib import Path
import argparse,hashlib,json,sys,traceback
from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
import numpy as np
H=Path(__file__).resolve().parent
sys.path.insert(0,str(H))
import run_stage_b as base
import cadence
ORIGINAL=cadence.choose_cadence
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def choose_q8(budget_j,head_j,member_sleep_j,member_increment_j):
    f=np.clip((budget_j-head_j-member_sleep_j)/np.maximum(member_increment_j,1e-30),0.,1.)
    return np.where(f>=1.-1e-12,1,np.where(f>=.5-1e-12,2,np.where(f>=.25-1e-12,4,8))).astype(int)
class Q8Candidate(base.JLCR):
    def __init__(self,c,sc,bank):
        self.q8_node_periods=0
        super().__init__(c,sc,bank)
    def install_plan(self):
        super().install_plan()
        self.q8_node_periods+=int(np.count_nonzero(self.cadence==8))
    def metrics(self):
        m=super().metrics();m['study_comparator']='Q8-EXPLORE';m['q8_node_periods']=self.q8_node_periods
        return m
def construct(method,c,sc):
    if method!='Q8-EXPLORE':raise ValueError(method)
    return Q8Candidate(c,sc,base.StreamingBank(sc))
def worker(job):
    base.construct=construct
    old=cadence.choose_cadence
    cadence.choose_cadence=choose_q8
    try:return base.run_case(job)
    finally:cadence.choose_cadence=old
def submit(cases,protocol,out,workers):
    out.mkdir(parents=True,exist_ok=False)
    base.dump(out/'run_plan.json',{'cases':len(cases),'workers':workers,'protocol_sha256':sha(H/'q8_protocol.json'),
                                   'runner_sha256':sha(Path(__file__))})
    todo=iter(cases);done=[];failure=None
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures={}
        def start():
            try:c=next(todo)
            except StopIteration:return
            futures[pool.submit(worker,(c,protocol,str(out/f"case_{c['index']:06d}")))]=c
        for _ in range(workers):start()
        while futures:
            ready,_=wait(futures,return_when=FIRST_COMPLETED)
            for future in ready:
                case=futures.pop(future)
                try:
                    result=future.result();done.append(result)
                    print(json.dumps({'completed':len(done),'total':len(cases),**result}),flush=True)
                except Exception as e:
                    failure={'case':case,'exception':repr(e)};print(json.dumps({'FAILED':failure}),flush=True)
                if failure is None:start()
    base.dump(out/'completion.json',{'status':'FAIL' if failure else 'COMPLETE',
                                    'completed':done,'failure':failure,'planned_cases':len(cases)})
    return failure is None
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=('pilot','confirmation'),required=True)
    ap.add_argument('--workers',type=int,default=1);a=ap.parse_args()
    p=json.loads((H/'protocol_predefined.json').read_text(encoding='utf8'))
    q=json.loads((H/'q8_protocol.json').read_text(encoding='utf8'))
    if q['parent_protocol_sha256']!=sha(H/'protocol_predefined.json'):raise SystemExit('Parent protocol mismatch')
    for rel,digest in p['frozen_source_sha256'].items():
        if sha(base.PACKAGE/rel)!=digest:raise SystemExit('Frozen source changed: '+rel)
    assert choose_q8(np.array([1.,.6,.3,.1]),np.zeros(4),np.zeros(4),np.ones(4)).tolist()==[1,2,4,8]
    if a.phase=='pilot':
        cases=[{'index':i+1,'seed':s,'condition':'SYNTHETIC_G20','supply':1.,
                'method':'Q8-EXPLORE','days':2,'pilot':True} for i,s in enumerate(p['pilot']['seeds'])]
        out=H/'q8_pilot'
    else:
        lock=json.loads((H/'q8_lock.json').read_text(encoding='utf8'))
        if lock['runner_sha256']!=sha(Path(__file__)) or lock['protocol_sha256']!=sha(H/'q8_protocol.json'):
            raise SystemExit('q8 design changed after lock')
        if json.loads((H/'q8_pilot/completion.json').read_text(encoding='utf8'))['status']!='COMPLETE':
            raise SystemExit('q8 pilot failure')
        cases=q['cases'];out=H/'q8_confirmation'
    if not submit(cases,p,out,a.workers):raise SystemExit(1)
if __name__=='__main__':main()
