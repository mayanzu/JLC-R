"""Descriptive follow-up on complete independently audited matrices; no new hypothesis tests."""
from pathlib import Path
import csv,hashlib,json
import numpy as np
from scipy import stats
import analyze_completed_studies as a
h=Path(__file__).resolve().parent
p=json.loads((h/'protocol_predefined.json').read_text(encoding='utf8'))
x=json.loads((h/'extra_comparators_predefined.json').read_text(encoding='utf8'))
out=h/'descriptive_followup_complete'
fields=['coverage_pct','source_coverage_p5_pct','source_coverage_jain',
        'aoi_mean_minutes','demand_delivery_pct','sample_completion_pct','consumed_j']
def write(name,rows):
 with (out/name).open('w',encoding='utf8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def main():
 if out.exists():raise SystemExit('Refusing overwrite')
 audit=json.loads((h/'analysis_complete/receipt.json').read_text(encoding='utf8'))
 assert audit['status']=='COMPLETE' and audit['validated_main']==1152 and audit['validated_additional']==576
 lookup={}
 for folder,cases in [('confirmation',[dict(c,days=p['days']) for c in p['cases']]),('extra_confirmation',x['cases'])]:
  completion=json.loads((h/folder/'completion.json').read_text(encoding='utf8'))
  assert completion['status']=='COMPLETE'
  for case in cases:
   d=h/folder/f"case_{case['index']:06d}"
   r=json.loads((d/'record.json').read_text(encoding='utf8'));m=dict(r['metrics'])
   assert all(r['case'][k]==case[k] for k in ('index','seed','condition','supply','method','days'))
   with (d/'node_ledgers.csv').open(encoding='utf8',newline='') as f:nodes=list(csv.DictReader(f))
   assert len(nodes)==100
   energy=sum(float(v[k]) for v in nodes for k in ('base_j','data_j','control_j'))
   if 'consumed_j' in m:assert abs(float(m['consumed_j'])-energy)<1e-6
   m['consumed_j']=energy
   outcome=m.get('outcomes',m);demand=case['days']*96*100
   delivery=100*int(outcome['delivered'])/demand
   completion_pct=100*(demand-int(outcome['unsensed']))/demand
   if 'demand_delivery_pct' in m:assert abs(m['demand_delivery_pct']-delivery)<1e-8
   if 'sample_completion_pct' in m:assert abs(m['sample_completion_pct']-completion_pct)<1e-8
   m.update(demand_delivery_pct=delivery,sample_completion_pct=completion_pct)
   key=(case['method'],case['condition'],float(case['supply']),int(case['seed']))
   assert key not in lookup
   lookup[key]=m
 methods=p['methods']+x['methods'];cells=[(c['name'],s) for c in p['conditions'] for s in p['supplies']]
 meanrows=[];diffrows=[];cellrows=[]
 for method in methods:
  for field in fields:
   v=np.asarray([a.average(lookup,method,seed,field,cells) for seed in p['seeds']])
   meanrows.append({'method':method,'endpoint':field,'n':24,'mean':float(v.mean()),'sd_between_seeds':float(v.std(ddof=1))})
   if method!='JLC-R':
    d=[a.average(lookup,'JLC-R',seed,field,cells)-a.average(lookup,method,seed,field,cells) for seed in p['seeds']]
    q=a.paired(d)
    diffrows.append({'control':method,'endpoint':field,'n':24,'mean_difference':q['mean_difference'],
                     'nominal_ci95_low':q['ci95_low'],'nominal_ci95_high':q['ci95_high'],
                     'interpretation':'post hoc descriptive; nominal interval; no additional significance claim'})
 for method in ['NO-FLOOR','NO-HOLD']:
  for field in fields:
   for cond,supply in cells:
    d=[a.average(lookup,'JLC-R',seed,field,[(cond,supply)])-
       a.average(lookup,method,seed,field,[(cond,supply)]) for seed in p['seeds']]
    q=a.paired(d)
    cellrows.append({'control':method,'endpoint':field,'condition':cond,'supply':supply,
                     'n':24,'mean_difference':q['mean_difference'],'nominal_ci95_low':q['ci95_low'],
                     'nominal_ci95_high':q['ci95_high'],
                     'interpretation':'post hoc cell description; no multiplicity-adjusted inference'})
 out.mkdir()
 write('method_means.csv',meanrows);write('paired_differences.csv',diffrows);write('floor_hold_by_cell.csv',cellrows)
 receipt={'status':'PASS','cases_read':len(lookup),'n_seeds':24,'cell_count':8,
          'scope':'post hoc descriptions; underlying arrays and energy ledgers previously independently audited',
          'delivery':'100 * delivered / fixed offered demand','sampling':'100 * (demand-unsensed) / demand',
          'energy':'sum of base, data and control over all nodes',
          'input_primary_receipt_sha256':hashlib.sha256((h/'analysis_complete/receipt.json').read_bytes()).hexdigest(),
          'analysis_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'outputs':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in out.iterdir()}}
 (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
 print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
