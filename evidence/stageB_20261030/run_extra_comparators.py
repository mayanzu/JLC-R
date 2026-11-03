"""Additional preregistered cadence controls, using the same paid common executor."""
from pathlib import Path
import argparse, hashlib, json, os, sys, traceback
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import numpy as np
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import run_stage_b as base
from cadence import ReserveCadenceCandidate
from recent_baselines import DutyControlSimulator
from optimized_model import OptimizedSimulator

ORIGINAL_INSTALL=OptimizedSimulator.install_plan
METHODS=['CADENCE-ONLY','NO-JOINT-PADC','SIMPLE-PADC-CADENCE']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def independent_install(sim):
    # Existing PADC adapter computes a causal duty rule and nonbinding
    # communication permission; physical reserve, debits, slots and paid
    # admission still bind. This is a broad comparative control, not an
    # estimate of one isolated joint-planning parameter.
    sim.slot_planning=False
    DutyControlSimulator.install_plan(sim)
class SupplementController(ReserveCadenceCandidate):
    def __init__(self, c, sc, bank, method):
        independent = method in ('NO-JOINT-PADC','SIMPLE-PADC-CADENCE')
        simple = method=='SIMPLE-PADC-CADENCE'
        self.study_method=method
        self.study_independent=independent
        cfg=dict(c)
        if independent:cfg.update(fdc_enabled=False,hyb_enabled=False)
        guard='none' if method in ('CADENCE-ONLY','SIMPLE-PADC-CADENCE') else 'reference'
        v63='off' if simple else 'relay_repair'
        super().__init__(cfg,sc,bank,horizon_days=3,trigger_mode=guard,v63_mechanism=v63)
        if method in ('CADENCE-ONLY','SIMPLE-PADC-CADENCE'):
            self.dev_variant='off';self.pf_enabled=False
        self.keep_lock=not simple
        self.simple=simple
        if independent:
            self.duty_policy='PADC-DC';self.duty_sum=0.;self.duty_count=0
        if not self.reserve_enabled:raise AssertionError('Paid admission disabled')
    def metrics(self):
        result=super().metrics()
        result['study_comparator']=self.study_method
        if self.study_independent:
            result['mean_listen_fraction']=self.duty_sum/self.duty_count if self.duty_count else None
            result['floor_enabled']=0
            result['planning_mode']='independent_padc_nonbinding_permission'
        return result
    def attempt(self,i,j,packet):
        result=super().attempt(i,j,packet)
        if self.simple and (self.holds or self.hold_slots or np.any(self.forward_holds) or np.any(self.forward_slot_holds)):
            raise AssertionError('Simple control retained forwarding obligations')
        return result

def construct(method,c,sc):
    if method not in METHODS:raise ValueError(method)
    return SupplementController(c,sc,base.StreamingBank(sc),method)

def worker(job):
    case, protocol, folder=job
    base.construct=construct
    original=OptimizedSimulator.install_plan
    try:
        if case['method'] in ('NO-JOINT-PADC','SIMPLE-PADC-CADENCE'):
            OptimizedSimulator.install_plan=independent_install
        result=base.run_case(job)
        folder=Path(folder)
        record=json.loads((folder/'record.json').read_text(encoding='utf8'))
        metrics=record['metrics']
        if metrics['grant_energy_j']<=0:raise AssertionError('Expected paid control frames absent')
        if case['method']=='SIMPLE-PADC-CADENCE' and metrics['held_packet_actions']!=0:
            raise AssertionError('No-hold comparison unexpectedly used a held packet')
        check=json.loads((folder/'validation.json').read_text(encoding='utf8'))
        check['paid_handshake_enabled']=True
        check['additional_comparator_checks']='PASS'
        base.dump(folder/'validation.json',check)
        return result
    except BaseException as exc:
        folder=Path(folder)
        if folder.exists() and not (folder/'failure.json').exists():
            base.dump(folder/'failure.json',{'type':type(exc).__name__,'message':str(exc),
                                             'traceback':traceback.format_exc()})
        raise
    finally:
        OptimizedSimulator.install_plan=original

def submit(cases,protocol,out,workers,pre):
    out.mkdir(parents=True,exist_ok=False)
    base.dump(out/'run_plan.json',{'cases':len(cases),'workers':workers,
                                   'protocol_sha256':sha(HERE/'protocol_predefined.json'),
                                   'extra_protocol_sha256':sha(HERE/'extra_comparators_predefined.json'),
                                   'runner_sha256':sha(Path(__file__))})
    todo=iter(cases);done=[];failure=None
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures={}
        def start():
            try:case=next(todo)
            except StopIteration:return
            folder=out/f"case_{case['index']:06d}"
            futures[pool.submit(worker,(case,protocol,str(folder)))]=case
        for _ in range(workers):start()
        while futures:
            ready,_=wait(futures,return_when=FIRST_COMPLETED)
            for fut in ready:
                case=futures.pop(fut)
                try:
                    result=fut.result();done.append(result)
                    print(json.dumps({'completed':len(done),'total':len(cases),**result}),flush=True)
                except Exception as exc:
                    failure={'case':case,'exception':repr(exc)}
                    print(json.dumps({'FAILED':failure}),flush=True)
                if failure is None:start()
    base.dump(out/'completion.json',{'status':'FAIL' if failure else 'COMPLETE',
                                    'completed':done,'failure':failure,'planned_cases':len(cases)})
    return failure is None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--phase',choices=('pilot','confirmation'),required=True)
    ap.add_argument('--workers',type=int,default=2)
    args=ap.parse_args()
    protocol=json.loads((HERE/'protocol_predefined.json').read_text(encoding='utf8'))
    extra=json.loads((HERE/'extra_comparators_predefined.json').read_text(encoding='utf8'))
    if extra['parent_protocol_sha256']!=sha(HERE/'protocol_predefined.json'):
        raise SystemExit('Parent protocol changed')
    for rel,expected in protocol['frozen_source_sha256'].items():
        if sha(base.PACKAGE/rel)!=expected:raise SystemExit('Frozen input altered: '+rel)
    if args.phase=='pilot':
        cases=[]
        for seed in protocol['pilot']['seeds']:
            for method in METHODS:
                cases.append({'index':len(cases)+1,'seed':seed,'condition':'SYNTHETIC_G20',
                              'supply':1.0,'method':method,'days':2,'pilot':True})
        out=HERE/'extra_pilot'
    else:
        lock=json.loads((HERE/'extra_study_lock.json').read_text(encoding='utf8'))
        if lock['runner_sha256']!=sha(Path(__file__)) or lock['protocol_sha256']!=sha(HERE/'extra_comparators_predefined.json'):
            raise SystemExit('Additional comparator lock differs')
        pilot=json.loads((HERE/'extra_pilot/completion.json').read_text(encoding='utf8'))
        if pilot['status']!='COMPLETE':raise SystemExit('Additional pilot failed')
        cases=extra['cases'];out=HERE/'extra_confirmation'
    if not submit(cases,protocol,out,args.workers,extra):raise SystemExit(1)
if __name__=='__main__':main()
