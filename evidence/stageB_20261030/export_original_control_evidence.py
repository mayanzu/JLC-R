"""Compact source-level evidence for the completed original-control seed extension."""
from pathlib import Path
import csv,gzip,hashlib,json
import numpy as np
h=Path(__file__).resolve().parent
plan=json.loads((h/'original_controls_protocol.json').read_text(encoding='utf8'))
out=h/'original_controls_compact'
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
def pos(seed):
 x,y=np.meshgrid((np.arange(10)+.5)/10,(np.arange(10)+.5)/10)
 points=np.column_stack((x.ravel(),y.ravel()))*300.
 return points+np.random.default_rng(np.random.SeedSequence([seed,11])).uniform(-8,8,points.shape)
def main():
 if out.exists():raise SystemExit('Refusing overwrite')
 path=h/'original_controls_confirmation/completion.json'
 if not path.exists():raise SystemExit('WAIT: original internal-control matrix must complete')
 done=json.loads(path.read_text(encoding='utf8'))
 assert done['status']=='COMPLETE' and done['planned_cases']==len(plan['cases'])==384
 receipt=h/'original_five_method_analysis/receipt.json'
 assert json.loads(receipt.read_text(encoding='utf8'))['status']=='PASS'
 out.mkdir()
 runfields=['study','index','seed','condition','supply','method','rounds','coverage_pct',
            'source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes','demand_delivery_pct',
            'sample_completion_pct','consumed_j','longest_unfresh_gap_p95_minutes','npz_sha256']
 sourcefields=['study','index','node','x_m','y_m','coverage_pct','longest_unfresh_gap_minutes']
 with (out/'run_metrics.csv').open('w',encoding='utf8',newline='') as rf,\
      gzip.open(out/'source_coverage_and_gaps.csv.gz','wt',encoding='utf8',newline='') as sf:
  rw=csv.DictWriter(rf,fieldnames=runfields);rw.writeheader()
  sw=csv.DictWriter(sf,fieldnames=sourcefields);sw.writeheader()
  for c in plan['cases']:
   folder=h/'original_controls_confirmation'/f"case_{c['index']:06d}"
   r=json.loads((folder/'record.json').read_text(encoding='utf8'));m=r['metrics']
   assert json.loads((folder/'validation.json').read_text(encoding='utf8'))['status']=='PASS'
   with np.load(folder/'arrays.npz') as z:
    latest=z['latest'];t=np.arange(latest.shape[0])[:,None]
    fresh=(latest>=0)&(t-latest+1<=4);cov=fresh.mean(axis=0)*100
    last=np.maximum.accumulate(np.where(fresh,t,-1),axis=0)
    gaps=np.where(fresh,0,t-last).max(axis=0)*15
    ages=np.where(latest>=0,t-latest+1,t+1)
    vals={'coverage_pct':float(cov.mean()),'source_coverage_p5_pct':float(np.quantile(cov,.05)),
          'source_coverage_jain':float(cov.sum()**2/(100*(cov**2).sum())) if cov.any() else 0.,
          'aoi_mean_minutes':float(ages.mean()*15)}
    for k,v in vals.items():assert abs(float(m[k])-v)<1e-8,(c['index'],k)
   with (folder/'node_ledgers.csv').open(encoding='utf8',newline='') as f:nodes=list(csv.DictReader(f))
   assert len(nodes)==100
   energy=sum(float(n[k]) for n in nodes for k in ('base_j','data_j','control_j'))
   assert abs(energy-float(m['consumed_j']))<1e-6
   outcomes=m.get('outcomes',m);demand=latest.shape[0]*100
   xy=pos(int(c['seed']))
   assert all(abs(float(n['x_m'])-xy[int(n['node']),0])<1e-8 and
              abs(float(n['y_m'])-xy[int(n['node']),1])<1e-8 for n in nodes)
   row={'study':'original_controls_confirmation','index':c['index'],'seed':c['seed'],
        'condition':c['condition'],'supply':c['supply'],'method':c['method'],'rounds':latest.shape[0],
        **vals,'demand_delivery_pct':100*int(outcomes['delivered'])/demand,
        'sample_completion_pct':100*(demand-int(outcomes['unsensed']))/demand,
        'consumed_j':energy,'longest_unfresh_gap_p95_minutes':float(np.quantile(gaps,.95)),
        'npz_sha256':sha(folder/'arrays.npz')}
   rw.writerow(row)
   sw.writerows({'study':'original_controls_confirmation','index':c['index'],'node':i,
                 'x_m':xy[i,0],'y_m':xy[i,1],'coverage_pct':cov[i],
                 'longest_unfresh_gap_minutes':int(gaps[i])} for i in range(100))
 receipt={'status':'PASS','cases':384,'source_rows':38400,
          'gap_definition':'longest consecutive non-fresh rounds times 15 minutes, including boundary intervals',
          'raw_arrays':'retained separately; SHA-256 per run in run_metrics.csv',
          'outputs':{f.name:sha(f) for f in out.iterdir()}}
 (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
 print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
