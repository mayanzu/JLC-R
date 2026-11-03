"""Rebuild the data underlying the four compact manuscript tables."""
from pathlib import Path
import csv,json,statistics
from analysis_core import ROOT,rows

def write(path,items):
    with path.open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(items[0]));w.writeheader();w.writerows(items)
def build(protocol,generated,out):
    cfg=json.loads((ROOT/'configs/effective_configs.json').read_text(encoding='utf8'))['SYNTHETIC_G20']
    write(out/'table1_effective_parameters.csv',[dict(parameter=k,value=json.dumps(v,ensure_ascii=False)) for k,v in sorted(cfg.items())])
    descriptions=[
        ('JLC-R-RC2','Complete controller','ND3; reference demand trigger; relay repair'),
        ('EADCM-CE','External energy-management policy','ND5; 20% target; causal forecast; reference FIFO transport'),
        ('LANTERN-CE','External energy-aware routing policy','root reward 32; Trickle k=1; listening 0.56 s; causal rate input'),
        ('Base-hybrid','Internal base hybrid control','original prefix/reactive configuration'),
        ('Pre-recovery-JLC-R','Internal earlier JLC-R control','frozen V63 including original Guard and T/R/S')]
    write(out/'table2_methods.csv',[dict(method=a,identity=b,configuration=c) for a,b,c in descriptions])
    primary=generated['primary_holm8.csv'];effects=[]
    for control in protocol['methods'][1:]:
        a=next(r for r in primary if r['control']==control and r['endpoint']=='coverage_pct')
        b=next(r for r in primary if r['control']==control and r['endpoint']=='source_coverage_p5_pct')
        effects.append(dict(control=control,coverage_difference_pp=a['mean_difference'],coverage_ci_low=a['ci95_low'],
            coverage_ci_high=a['ci95_high'],coverage_holm_p=a['adjusted_p'],p5_difference_pp=b['mean_difference'],
            p5_ci_low=b['ci95_low'],p5_ci_high=b['ci95_high'],p5_holm_p=b['adjusted_p']))
    write(out/'table3_primary_contrasts.csv',effects)
    data=rows(ROOT/'results/confirmation_480.csv');summary=[]
    fields=['sample_completion_pct','fixed_demand_packet_delivery_pct','actual_energy_j','source_coverage_jain']
    for method in protocol['methods']:
        rr=[r for r in data if r['method']==method];assert len(rr)==96
        summary.append(dict(method=method,network_seeds=12,conditions=8,
            **{k:statistics.mean(float(r[k]) for r in rr) for k in fields}))
    write(out/'table4_tradeoffs.csv',summary)
