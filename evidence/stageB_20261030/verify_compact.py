"""Recompute 24-seed summary statistics from the compact supplementary evidence.

This read-only verification does not launch network simulations. Full original
round arrays are stored separately; their hashes are recorded in run_metrics.
"""
from pathlib import Path
import argparse,csv,gzip,hashlib,json,math
from collections import defaultdict
import numpy as np
from scipy import stats
H=Path(__file__).resolve().parent
def sha(p):
 d=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):d.update(block)
 return d.hexdigest()
def rows(path):
 with path.open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))
def paired(v):
 v=np.asarray(v,float);assert v.shape==(24,) and np.isfinite(v).all()
 mean=float(v.mean());sd=float(v.std(ddof=1))
 if sd==0:return {'mean_difference':mean,'ci95_low':None,'ci95_high':None,'p':None}
 se=sd/math.sqrt(24);d=float(stats.t.ppf(.975,23)*se)
 return {'mean_difference':mean,'ci95_low':mean-d,'ci95_high':mean+d,
         'p':float(2*stats.t.sf(abs(mean/se),23))}
def eq(a,b):
 if a is None or b is None or a=='' or b=='':return (a is None or a=='') and (b is None or b=='')
 return math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-8)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=H)
 ap.add_argument('--record-root',type=Path);arg=ap.parse_args()
 root=arg.root.resolve();case_root=(arg.record_root or root/'case_records').resolve()
 protocol=json.loads((root/'protocol_predefined.json').read_text(encoding='utf8'))
 evidence=root/'compact_evidence_complete';receipt=json.loads((evidence/'receipt.json').read_text(encoding='utf8'))
 assert receipt['status']=='PASS' and receipt['cases']==2280 and receipt['source_rows']==228000
 for name,digest in receipt['outputs'].items():assert sha(evidence/name)==digest
 raw=rows(evidence/'run_metrics.csv')
 assert len(raw)==2280
 indexes={};lookup={}
 for r in raw:
  k=(r['study'],int(r['index']))
  logical=(r['study'],r['method'],r['condition'],float(r['supply']),int(r['seed']))
  assert k not in indexes and logical not in lookup
  indexes[k]=r;lookup[logical]=r
  d=case_root/r['study']/f"case_{int(r['index']):06d}"
  rec=json.loads((d/'record.json').read_text(encoding='utf8'))
  valid=json.loads((d/'validation.json').read_text(encoding='utf8'))
  assert valid['status']=='PASS' and all(str(rec['case'][f])==r[f] for f in ['seed','condition','method'])
  m=rec['metrics'];ns=rows(d/'node_ledgers.csv')
  assert len(ns)==100 and len({int(x['node']) for x in ns})==100
  energy=sum(float(x[v]) for x in ns for v in ('base_j','data_j','control_j'))
  assert abs(energy-float(r['consumed_j']))<1e-8
  assert max(abs(float(x['initial_j'])+float(x['harvest_j'])-float(x['spill_j'])-
                 float(x['base_j'])-float(x['data_j'])-float(x['control_j'])-float(x['final_j'])) for x in ns)<1e-8
  for key in ('coverage_pct','source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes'):
   assert eq(m[key],r[key]),(k,key)
  outcomes=m.get('outcomes',m);demand=int(r['rounds'])*100
  assert eq(100*int(outcomes['delivered'])/demand,r['demand_delivery_pct'])
  assert eq(100*(demand-int(outcomes['unsensed']))/demand,r['sample_completion_pct'])
 source=defaultdict(list)
 with gzip.open(evidence/'source_coverage_and_gaps.csv.gz','rt',encoding='utf8',newline='') as f:
  for x in csv.DictReader(f):source[(x['study'],int(x['index']))].append(x)
 assert len(source)==2280 and sum(map(len,source.values()))==228000
 far={}
 for k,rr in source.items():
  assert k in indexes and len(rr)==100 and len({int(x['node']) for x in rr})==100
  c=np.array([float(x['coverage_pct']) for x in rr]);g=np.array([float(x['longest_unfresh_gap_minutes']) for x in rr])
  ref=indexes[k]
  assert eq(c.mean(),ref['coverage_pct']) and eq(np.quantile(c,.05),ref['source_coverage_p5_pct'])
  assert eq(np.quantile(g,.95),ref['longest_unfresh_gap_p95_minutes'])
  assert eq(c.sum()**2/(100*(c**2).sum()) if c.any() else 0.,ref['source_coverage_jain'])
  values=[float(x['coverage_pct']) for x in rr if math.hypot(float(x['x_m']),float(x['y_m'])-150)>=200]
  assert values;far[k]=float(np.mean(values))
 cells=[(c['name'],float(s)) for c in protocol['conditions'] for s in protocol['supplies']]
 seeds=protocol['seeds']
 def value(study,method,cond,supply,seed,field):
  r=lookup[(study,method,cond,float(supply),int(seed))]
  if field=='far_coverage_pct':return far[(study,int(r['index']))]
  return float(r[field])
 def avg(study,method,seed,field,cs):
  return float(np.mean([value(study,method,c,s,seed,field) for c,s in cs]))
 primary=rows(root/'analysis_complete/primary_holm2.csv')
 ps=[]
 for entry,ctl in zip(primary,['NO-FLOOR','NO-HOLD']):
  assert entry['contrast']=='JLC-R minus '+ctl
  d=[avg('confirmation','JLC-R',seed,'source_coverage_p5_pct',cells)-
     avg('confirmation',ctl,seed,'source_coverage_p5_pct',cells) for seed in seeds]
  z=paired(d)
  for k in ('mean_difference','ci95_low','ci95_high','p'):assert eq(z[k],entry[k]),('primary',ctl,k)
  ps.append(z['p'])
 order=np.argsort(ps,kind='stable');adj=np.empty(2);run=0.
 for rank,i in enumerate(order):
  run=max(run,(2-rank)*ps[i]);adj[i]=min(1.,run)
 for entry,v in zip(primary,adj):assert eq(v,entry['holm2_adjusted_p'])
 qplan=json.loads((root/'q8_protocol.json').read_text(encoding='utf8'))
 qcells=[(c,float(s)) for c,s in qplan['conditions']]
 qstats=rows(root/'q8_analysis_complete/q8_exploratory.csv')
 qfields=['coverage_pct','source_coverage_p5_pct','far_coverage_pct','demand_delivery_pct','consumed_j','longest_unfresh_gap_p95_minutes']
 for r in qstats:
  cs=qcells if r['cell']=='equal_three_winter_cells' else [(r['cell'].split('/')[0],float(r['cell'].split('/')[1]))]
  d=[avg('q8_confirmation','Q8-EXPLORE',seed,r['endpoint'],cs)-
     avg('confirmation','JLC-R',seed,r['endpoint'],cs) for seed in seeds]
  z=paired(d)
  for a,b in [('mean_difference','mean_q8_minus_jlcr'),('ci95_low','nominal_ci95_low'),('ci95_high','nominal_ci95_high')]:
   assert eq(z[a],r[b]),('q8',r['cell'],r['endpoint'],a)
 over=rows(root/'overhead_analysis_complete/overhead_exploratory.csv')
 for r in over:
  field=r['endpoint']
  def v(study,seed):
   return avg(study,'JLC-R',seed,field,cells)-avg(study,'EADCM-CE',seed,field,cells)
  orig=[v('confirmation',seed) for seed in seeds];stress=[v('overhead_confirmation',seed) for seed in seeds]
  data={'original':orig,'overhead_1p32':stress,'change_of_contrast':[b-a for a,b in zip(orig,stress)]}[r['scenario']]
  z=paired(data)
  for k in ('mean_difference','ci95_low','ci95_high'):assert eq(z[k],r[k]),('overhead',field,r['scenario'],k)
 print(json.dumps({'status':'PASS','simulations_started':0,'case_records':len(raw),'source_rows':sum(map(len,source.values())),
  'tests':'ledger balance, node and run metrics, Holm-2, q8 and overhead summaries',
  'raw_array_limit':'round-level arrays are external; their stored SHA-256 allows separate verification'},indent=2))
if __name__=='__main__':main()
