"""Export compact source- and run-level records from independently audited round arrays."""
from pathlib import Path
import csv,gzip,hashlib,json
import numpy as np
h=Path(__file__).resolve().parent
p=json.loads((h/'protocol_predefined.json').read_text(encoding='utf8'))
x=json.loads((h/'extra_comparators_predefined.json').read_text(encoding='utf8'))
q=json.loads((h/'q8_protocol.json').read_text(encoding='utf8'))
o=json.loads((h/'overhead_protocol.json').read_text(encoding='utf8'))
out=h/'compact_evidence_complete'
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
def pos(seed):
 x,y=np.meshgrid((np.arange(10)+.5)/10,(np.arange(10)+.5)/10)
 points=np.column_stack((x.ravel(),y.ravel()))*300.
 return points+np.random.default_rng(np.random.SeedSequence([seed,11])).uniform(-8,8,points.shape)
def main():
 if out.exists():raise SystemExit('Refusing overwrite')
 for f in ('analysis_complete/receipt.json','q8_analysis_complete/receipt.json','overhead_analysis_complete/receipt.json'):
  z=json.loads((h/f).read_text(encoding='utf8'));assert z['status'] in ('PASS','COMPLETE'),f
 maincases=[dict(c,days=p['days']) for c in p['cases']]
 spec=p['new_weather_prespecified'];w=[]
 for seed in spec['seeds']:
  for supply in spec['supplies']:
   for method in spec['methods']:
    w.append({'index':len(w)+1,'seed':seed,'condition':'NOAA_SEPT2024_G20','supply':supply,'method':method,'days':14})
 studies=[('confirmation',maincases),('extra_confirmation',x['cases']),('new_weather_confirmation',w),
          ('q8_confirmation',q['cases']),('overhead_confirmation',o['cases'])]
 out.mkdir()
 runfields=['study','index','seed','condition','supply','method','rounds','coverage_pct',
            'source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes','demand_delivery_pct',
            'sample_completion_pct','consumed_j','longest_unfresh_gap_p95_minutes','npz_sha256']
 sourcefields=['study','index','node','x_m','y_m','coverage_pct','longest_unfresh_gap_minutes']
 count=0
 with (out/'run_metrics.csv').open('w',encoding='utf8',newline='') as rf,\
      gzip.open(out/'source_coverage_and_gaps.csv.gz','wt',encoding='utf8',newline='') as sf:
  rw=csv.DictWriter(rf,fieldnames=runfields);rw.writeheader()
  sw=csv.DictWriter(sf,fieldnames=sourcefields);sw.writeheader()
  for folder,cases in studies:
   done=json.loads((h/folder/'completion.json').read_text(encoding='utf8'))
   assert done['status']=='COMPLETE' and done['planned_cases']==len(cases)
   for c in cases:
    d=h/folder/f"case_{c['index']:06d}"
    record=json.loads((d/'record.json').read_text(encoding='utf8'));m=record['metrics']
    assert json.loads((d/'validation.json').read_text(encoding='utf8'))['status']=='PASS'
    with np.load(d/'arrays.npz') as z:
     latest=z['latest'];t=np.arange(latest.shape[0])[:,None]
     fresh=(latest>=0)&(t-latest+1<=4);coverage=fresh.mean(axis=0)*100
     last=np.maximum.accumulate(np.where(fresh,t,-1),axis=0)
     gaps=np.where(fresh,0,t-last).max(axis=0)*15
     ages=np.where(latest>=0,t-latest+1,t+1)
     mean=float(coverage.mean());p5=float(np.quantile(coverage,.05))
     jain=float(coverage.sum()**2/(100*(coverage**2).sum())) if coverage.any() else 0.
     aoi=float(ages.mean()*15)
     for key,value in [('coverage_pct',mean),('source_coverage_p5_pct',p5),
                       ('source_coverage_jain',jain),('aoi_mean_minutes',aoi)]:
      assert abs(float(m[key])-value)<1e-8,(folder,c['index'],key)
    with (d/'node_ledgers.csv').open(encoding='utf8',newline='') as f:nodes=list(csv.DictReader(f))
    assert len(nodes)==100
    energy=sum(float(r[k]) for r in nodes for k in ('base_j','data_j','control_j'))
    outcomes=m.get('outcomes',m);demand=latest.shape[0]*100
    delivered=100*int(outcomes['delivered'])/demand
    sampled=100*(demand-int(outcomes['unsensed']))/demand
    point=pos(int(c['seed']))
    if 'x_m' in nodes[0]:
     assert all(abs(float(r['x_m'])-point[int(r['node']),0])<1e-8 and
                abs(float(r['y_m'])-point[int(r['node']),1])<1e-8 for r in nodes)
    row={'study':folder,'index':c['index'],'seed':c['seed'],'condition':c['condition'],
         'supply':c['supply'],'method':c['method'],'rounds':latest.shape[0],
         'coverage_pct':mean,'source_coverage_p5_pct':p5,'source_coverage_jain':jain,
         'aoi_mean_minutes':aoi,'demand_delivery_pct':delivered,'sample_completion_pct':sampled,
         'consumed_j':energy,'longest_unfresh_gap_p95_minutes':float(np.quantile(gaps,.95)),
         'npz_sha256':sha(d/'arrays.npz')}
    rw.writerow(row)
    sw.writerows({'study':folder,'index':c['index'],'node':i,'x_m':point[i,0],'y_m':point[i,1],
                  'coverage_pct':coverage[i],'longest_unfresh_gap_minutes':int(gaps[i])} for i in range(100))
    count+=1
   print(folder,'cases',len(cases),'completed',count,flush=True)
 assert count==2280
 receipt={'status':'PASS','cases':count,'source_rows':count*100,
          'gap_definition':'longest consecutive non-fresh rounds times 15 minutes, including boundary intervals',
          'source_coordinates':'topology stream [seed,11], checked against all available node-ledger coordinates',
          'raw_arrays':'retained separately; SHA-256 per run in run_metrics.csv',
          'outputs':{f.name:sha(f) for f in out.iterdir()}}
 (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
 print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
