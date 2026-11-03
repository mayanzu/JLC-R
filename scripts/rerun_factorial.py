"""Explicitly rerun saved RC2 factorial cases into a new external directory."""
from __future__ import annotations

import csv
import json
import sys
import traceback
from pathlib import Path

import numpy as np
from analysis_core import ROOT,rows

sys.path.insert(0,str(ROOT/'code/simulation'))
from cadence import ReserveCadenceCandidate
from current_io import load_config,build_scenario
from validation_model import StreamingBank


class FactorialController(ReserveCadenceCandidate):
    """The V63 parent remains active in every combination."""
    def __init__(self,c,sc,bank,activity,guard,recovery):
        super().__init__(c,sc,bank,horizon_days=3 if activity else None,
                         trigger_mode='reference' if guard else 'none',
                         v63_mechanism='relay_repair')
        if not recovery:
            self.dev_variant='off'
            self.pf_enabled=False


def encode(x):
    if isinstance(x,np.generic):return x.item()
    if isinstance(x,np.ndarray):return x.tolist()
    raise TypeError(type(x).__name__)


def dump(path,obj):
    path.write_text(json.dumps(obj,indent=2,default=encode)+'\n',encoding='utf8')


def write_csv(path,records):
    if not records:return
    with path.open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)


def run_case(index,case,protocol,out):
    folder=out/f'case_{index:04d}';folder.mkdir(exist_ok=False)
    bits=case['bits']
    try:
        cond=next(c for c in protocol['conditions'] if c['name']==case['condition'])
        c=load_config(cond);sc=build_scenario(c,int(case['seed']),protocol['days'],float(case['supply']),cond)
        sim=FactorialController(c,sc,StreamingBank(sc),*(v=='1' for v in bits))
        latest=[];battery=[]
        for _ in range(sc.rounds):
            sim.round();latest.append(sim.latest.copy());battery.append(sim.battery.copy())
        metrics=sim.metrics()
        latest=np.asarray(latest);battery=np.asarray(battery);node_rows=sim.node_rows()
        t=np.arange(sc.rounds)[:,None]
        cov=((latest>=0)&(t-latest+1<=4)).mean(axis=0)*100
        age=np.where(latest>=0,t-latest+1,t+1).mean()*15
        computed={'coverage_pct':float(cov.mean()),'source_coverage_p5_pct':float(np.quantile(cov,.05)),
                  'source_coverage_jain':float(cov.sum()**2/(100*(cov**2).sum())) if cov.any() else 0.,
                  'aoi_mean_minutes':float(age),'sample_completion_pct':float(metrics['sample_completion_pct']),
                  'fixed_demand_packet_delivery_pct':100*int(metrics['delivered'])/(sc.rounds*100),
                  'actual_energy_j':sum(row[k] for row in node_rows for k in ('base_j','data_j','control_j'))}
        for key,value in computed.items():
            assert abs(value-float(case[key]))<=1e-8,(index,key,value,case[key])
        assert np.isfinite(battery).all() and battery.min()>=-1e-12 and battery.max()<=c['battery_j']+1e-12
        assert metrics['max_node_energy_error_j']<=1e-8 and metrics['max_energy_balance_error_j']<=1e-6
        assert metrics['timing_misses']==0 and metrics['max_hold_violation_j']<=1e-8 and metrics['max_slot_violation']<=1e-8
        assert np.count_nonzero(sim.sample_status)==sc.rounds*100
        assert sum(int(metrics.get(k,0)) for k in ('delivered','expired','overflow','outstanding','unsensed','routing_drop'))==sc.rounds*100
        np.savez_compressed(folder/'arrays.npz',latest=latest,battery=battery,sample_status=sim.sample_status)
        write_csv(folder/'node_ledgers.csv',node_rows)
        dump(folder/'record.json',{'case_index':index,'factorial_case':case,'metrics':metrics,'computed':computed,
                                   'kind':'explicit technical rerun; not independent confirmation'})
        dump(folder/'validation.json',{'status':'PASS','saved_outcomes_matched':list(computed)})
    except BaseException as exc:
        dump(folder/'failure.json',{'case_index':index,'case':case,'error':repr(exc),'traceback':traceback.format_exc()})
        raise


def run(protocol,out,indices=None,dry_run=False):
    all_cases=rows(ROOT/'results/rc2_supplement/factorial_seed_records_768.csv')
    assert len(all_cases)==768
    selected=list(enumerate(all_cases))
    if indices is not None:
        wanted=set(indices);assert len(wanted)==len(indices),'Duplicate case index'
        selected=[(i,r) for i,r in selected if i in wanted]
        assert len(selected)==len(wanted),'Unknown case index'
    plan={'study':'factorial','cases':len(selected),'rounds_per_case':protocol['days']*96,
          'original_network_seeds':True,'new_formal_claim':False,'output':str(out)}
    if dry_run:return {**plan,'dry_run':True,'simulations_started':0}
    out=Path(out).resolve();assert not out.is_relative_to(ROOT.resolve()),'Output must be outside the package'
    out.mkdir(parents=True,exist_ok=False);dump(out/'run_plan.json',plan)
    completed=[]
    for index,case in selected:
        run_case(index,case,protocol,out);completed.append(index)
        print(f'Completed {len(completed)}/{len(selected)}: case {index}',flush=True)
    dump(out/'completed.json',{'status':'COMPLETE','cases':completed,'formal_claim':False})
    return {**plan,'dry_run':False,'simulations_started':len(completed)}
