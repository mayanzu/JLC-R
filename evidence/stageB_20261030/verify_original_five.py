"""Read-only verification of 24-seed five-method extension from compact evidence."""
from pathlib import Path
import argparse,csv,gzip,hashlib,json,math
from collections import defaultdict
import numpy as np
from scipy import stats
H=Path(__file__).resolve().parent
def sha(path):
 d=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):d.update(block)
 return d.hexdigest()
def read(path):
 with path.open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))
def close(a,b):
 if a in (None,'') or b in (None,''):return a in (None,'') and b in (None,'')
 return math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-8)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=H);ap.add_argument('--record-root',type=Path)
 args=ap.parse_args();root=args.root.resolve();record_root=(args.record_root or root/'case_records').resolve()
 p=json.loads((root/'protocol_predefined.json').read_text(encoding='utf8'))
 x=json.loads((root/'original_controls_protocol.json').read_text(encoding='utf8'))
 receipt=json.loads((root/'original_controls_compact/receipt.json').read_text(encoding='utf8'))
 assert receipt['status']=='PASS' and receipt['cases']==384 and receipt['source_rows']==38400
 for name,digest in receipt['outputs'].items():assert sha(root/'original_controls_compact'/name)==digest
 base=[r for r in read(root/'compact_evidence_complete/run_metrics.csv')
       if r['study']=='confirmation' and r['method'] in ('JLC-R','EADCM-CE','LANTERN-CE')]
 added=read(root/'original_controls_compact/run_metrics.csv')
 assert len(base)==576 and len(added)==384
 lookup={}
 for r in base+added:
  k=(r['method'],r['condition'],float(r['supply']),int(r['seed']))
  assert k not in lookup;lookup[k]=r
  if r['study']=='original_controls_confirmation':
   folder=record_root/r['study']/f"case_{int(r['index']):06d}"
   record=json.loads((folder/'record.json').read_text(encoding='utf8'))
   validation=json.loads((folder/'validation.json').read_text(encoding='utf8'))
   assert validation['status']=='PASS'
   assert all(str(record['case'][f])==r[f] for f in ('seed','condition','method'))
   for field in ('coverage_pct','source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes'):
    assert close(record['metrics'][field],r[field])
   nodes=read(folder/'node_ledgers.csv');assert len(nodes)==100
   energy=sum(float(n[k]) for n in nodes for k in ('base_j','data_j','control_j'))
   assert close(energy,r['consumed_j'])
   assert max(abs(float(n['initial_j'])+float(n['harvest_j'])-float(n['spill_j'])-
                  float(n['base_j'])-float(n['data_j'])-float(n['control_j'])-
                  float(n['final_j'])) for n in nodes)<1e-8
 groups=defaultdict(list)
 with gzip.open(root/'original_controls_compact/source_coverage_and_gaps.csv.gz','rt',encoding='utf8',newline='') as f:
  for r in csv.DictReader(f):groups[int(r['index'])].append(r)
 assert len(groups)==384 and sum(map(len,groups.values()))==38400
 for r in added:
  rr=groups[int(r['index'])];assert len(rr)==100 and len({int(x['node']) for x in rr})==100
  cov=np.asarray([float(x['coverage_pct']) for x in rr])
  gap=np.asarray([float(x['longest_unfresh_gap_minutes']) for x in rr])
  assert close(cov.mean(),r['coverage_pct']) and close(np.quantile(cov,.05),r['source_coverage_p5_pct'])
  assert close(np.quantile(gap,.95),r['longest_unfresh_gap_p95_minutes'])
 cells=[(c['name'],float(s)) for c in p['conditions'] for s in p['supplies']]
 seeds=p['seeds'];summary=read(root/'original_five_method_analysis/five_method_holm8.csv')
 seed_data=read(root/'original_five_method_analysis/paired_seed_differences.csv')
 assert len(summary)==8 and len(seed_data)==192 and len(seeds)==24
 tests=[]
 for control in ('EADCM-CE','LANTERN-CE','Base-hybrid','Pre-recovery-JLC-R'):
  for field in ('coverage_pct','source_coverage_p5_pct'):
   values=[]
   for seed in seeds:
    left=np.mean([float(lookup[('JLC-R',c,s,seed)][field]) for c,s in cells])
    right=np.mean([float(lookup[(control,c,s,seed)][field]) for c,s in cells])
    d=left-right;values.append(d)
    matched=[v for v in seed_data if int(v['seed'])==seed and v['control']==control and v['endpoint']==field]
    assert len(matched)==1 and close(matched[0]['difference'],d)
   values=np.asarray(values);mu=float(values.mean());sd=float(values.std(ddof=1));se=sd/math.sqrt(24)
   row=next(r for r in summary if r['control']==control and r['endpoint']==field)
   if sd==0:
    assert row['undefined_t']=='True' and row['ci95_low']=='' and row['ci95_high']=='' and row['p']==''
    pval=1.
    assert close(row['mean_difference'],mu)
   else:
    q=float(stats.t.ppf(.975,23)*se);pval=float(2*stats.t.sf(abs(mu/se),23))
    for key,value in [('mean_difference',mu),('ci95_low',mu-q),('ci95_high',mu+q),('p',pval)]:assert close(row[key],value)
   tests.append((row,pval))
 order=sorted(range(8),key=lambda i:tests[i][1]);running=0.;adjusted=[0.]*8
 for rank,i in enumerate(order):
  running=max(running,(8-rank)*tests[i][1]);adjusted[i]=min(1.,running)
 for (row,_),value in zip(tests,adjusted):assert close(row['holm8_adjusted_p'],value)
 cellrows=read(root/'original_five_method_analysis/cell_descriptive.csv');assert len(cellrows)==64
 cellps=[]
 for row in cellrows:
  control=row['control'];field=row['endpoint'];condition=row['condition'];supply=float(row['supply'])
  v=np.asarray([float(lookup[('JLC-R',condition,supply,seed)][field])-
                float(lookup[(control,condition,supply,seed)][field]) for seed in seeds])
  mean=float(v.mean());sd=float(v.std(ddof=1))
  assert close(row['mean_difference'],mean)
  if sd==0:
   assert row['undefined_t']=='True' and row['p']=='';pval=1.
  else:
   se=sd/math.sqrt(24);half=float(stats.t.ppf(.975,23)*se)
   pval=float(2*stats.t.sf(abs(mean/se),23))
   for k,value in [('ci95_low',mean-half),('ci95_high',mean+half),('p',pval)]:assert close(row[k],value)
  cellps.append(pval)
 order=sorted(range(64),key=lambda i:cellps[i]);running=0.;adj=[0.]*64
 for rank,i in enumerate(order):
  running=max(running,(64-rank)*cellps[i]);adj[i]=min(1.,running)
 for row,value in zip(cellrows,adj):assert close(row['holm64_adjusted_p'],value)
 print(json.dumps({'status':'PASS','simulations_started':0,'controls_cases':len(added),
  'all_five_method_cases':len(lookup),'control_source_rows':38400,
  'statistics':'all paired differences, nominal intervals, Holm-8 and exploratory Holm-64 recomputed',
  'round_array_limit':'round-level arrays are external and hashed per case'},indent=2))
if __name__=='__main__':main()
