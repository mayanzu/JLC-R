"""Post hoc spatial summaries from already validated 24-seed source coverage."""
from pathlib import Path
from collections import defaultdict
import argparse,csv,gzip,hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
DEFAULT=ROOT.parent/'temp/current_research/stageB_20261030'
FIELDS=['near_pct','mid_pct','far_pct','worst_cell_pct','source_p5_pct',
        'zero_sources_pct','longest_unfresh_gap_p95_h']
def read(path):
 with path.open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))
def write(path,rows):
 with path.open('w',encoding='utf8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('--input',type=Path,default=DEFAULT)
 ap.add_argument('--output',type=Path,required=True)
 ap.add_argument('--include-original-controls',action='store_true')
 a=ap.parse_args();h=a.input.resolve();out=a.output.resolve()
 if out.exists():raise SystemExit('Refusing overwrite')
 groups=[('confirmation',h/'compact_evidence_complete')]
 if a.include_original_controls:groups.append(('original_controls_confirmation',h/'original_controls_compact'))
 cases=[]
 for study,evidence in groups:
  receipt=json.loads((evidence/'receipt.json').read_text(encoding='utf8'));assert receipt['status']=='PASS'
  run=[r for r in read(evidence/'run_metrics.csv') if r['study']==study]
  index={int(r['index']):r for r in run};assert len(index)==len(run)
  src=defaultdict(list)
  with gzip.open(evidence/'source_coverage_and_gaps.csv.gz','rt',encoding='utf8',newline='') as f:
   for r in csv.DictReader(f):
    if r['study']==study:src[int(r['index'])].append(r)
  assert set(src)==set(index) and all(len(v)==100 for v in src.values())
  for n,rr in src.items():
   run=index[n];rr.sort(key=lambda x:int(x['node']))
   assert [int(x['node']) for x in rr]==list(range(100))
   xy=np.array([[float(x['x_m']),float(x['y_m'])] for x in rr])
   coverage=np.array([float(x['coverage_pct']) for x in rr])
   gaps=np.array([float(x['longest_unfresh_gap_minutes']) for x in rr])
   assert abs(coverage.mean()-float(run['coverage_pct']))<1e-8
   assert abs(np.quantile(coverage,.05)-float(run['source_coverage_p5_pct']))<1e-8
   dist=np.linalg.norm(xy-np.array([0.,150.]),axis=1)
   masks=[dist<=120,(dist>120)&(dist<200),dist>=200]
   assert all(np.any(m) for m in masks)
   cells=(np.floor(xy[:,1]/300*3).clip(0,2).astype(int)*4+
          np.floor(xy[:,0]/300*4).clip(0,3).astype(int))
   assert set(cells)==set(range(12))
   cases.append({'study':study,'index':n,'method':run['method'],'condition':run['condition'],
     'supply':float(run['supply']),'seed':int(run['seed']),
     'near_pct':float(coverage[masks[0]].mean()),'mid_pct':float(coverage[masks[1]].mean()),
     'far_pct':float(coverage[masks[2]].mean()),
     'worst_cell_pct':min(float(coverage[cells==i].mean()) for i in range(12)),
     'source_p5_pct':float(np.quantile(coverage,.05)),
     'zero_sources_pct':float(np.count_nonzero(coverage==0)),
     'longest_unfresh_gap_p95_h':float(np.quantile(gaps,.95)/60)})
 methods=sorted({r['method'] for r in cases});seeds=sorted({r['seed'] for r in cases})
 assert len(seeds)==24
 levels=defaultdict(list)
 for r in cases:levels[(r['method'],r['condition'],r['supply'])].append(r)
 assert all(len(rs)==24 for rs in levels.values())
 bycond=[{'method':m,'condition':c,'supply':s,'n':len(rs),
          **{field:float(np.mean([r[field] for r in rs])) for field in FIELDS}}
         for (m,c,s),rs in sorted(levels.items())]
 winter=[];overall=[]
 for method in methods:
  selections=[r for r in bycond if r['method']==method]
  winter_cells=[r for r in selections if r['condition'] in ('WINTER_G20','T3_G20')]
  assert len(selections)==8 and len(winter_cells)==4
  winter.append({'method':method,'cells':4,'seeds':24,**{k:float(np.mean([r[k] for r in winter_cells])) for k in FIELDS}})
  overall.append({'method':method,'cells':8,'seeds':24,**{k:float(np.mean([r[k] for r in selections])) for k in FIELDS}})
 out.mkdir(parents=True)
 write(out/'spatial_by_run.csv',cases);write(out/'spatial_by_condition.csv',bycond)
 write(out/'spatial_overall.csv',overall);write(out/'spatial_winter.csv',winter)
 receipt={'status':'PASS','cases':len(cases),'methods':methods,'seeds':24,
  'definition':'bands by sink distance, worst of 12 4x3 cell means per run, zero source coverage over full observation period',
  'aggregation':'per-run summaries, then equal averaging across seeds and cells',
  'source_files':{str(evidence.relative_to(h)):{n:hashlib.sha256((evidence/n).read_bytes()).hexdigest()
                  for n in ('run_metrics.csv','source_coverage_and_gaps.csv.gz')} for _,evidence in groups},
  'interpretation':'post hoc descriptive only; no causal or per-cell hypothesis test',
  'outputs':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in out.iterdir()}}
 (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
 print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
