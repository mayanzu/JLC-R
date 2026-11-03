"""Exact sign-flip sensitivity for the two fixed 24-seed P5 contrasts."""
from pathlib import Path
import csv,hashlib,json
import numpy as np
h=Path(__file__).resolve().parent
p=json.loads((h/'protocol_predefined.json').read_text(encoding='utf8'))
with (h/'compact_evidence_complete/run_metrics.csv').open(encoding='utf8',newline='') as f:
 records=list(csv.DictReader(f))
lookup={(r['method'],r['condition'],float(r['supply']),int(r['seed'])):float(r['source_coverage_p5_pct'])
        for r in records if r['study']=='confirmation'}
cells=[(c['name'],s) for c in p['conditions'] for s in p['supplies']]
def halfsums(values):
 x=np.array([0.])
 for value in values:x=np.concatenate((x+value,x-value))
 return x
def main():
 out=h/'signflip_sensitivity_24'
 if out.exists():raise SystemExit('Refusing overwrite')
 contrasts=[]
 for ctl in ['NO-FLOOR','NO-HOLD']:
  diff=np.array([np.mean([lookup[('JLC-R',c,s,seed)]-lookup[(ctl,c,s,seed)] for c,s in cells])
                 for seed in p['seeds']],float)
  assert len(diff)==24
  a=halfsums(diff[:12]);b=halfsums(diff[12:])
  threshold=abs(diff.sum())-1e-11
  count=sum(int(np.count_nonzero(np.abs(a[i:i+128,None]+b[None,:])>=threshold))
            for i in range(0,len(a),128))
  exact=count/(2**24)
  contrasts.append({'control':ctl,'n':24,'patterns':2**24,'extreme_patterns':count,
                    'mean_difference':float(diff.mean()),'exact_p':exact})
 order=sorted(range(2),key=lambda i:contrasts[i]['exact_p']);running=0.;adj=[None,None]
 for rank,i in enumerate(order):
  running=max(running,(2-rank)*contrasts[i]['exact_p']);adj[i]=min(1.,running)
 for row,v in zip(contrasts,adj):row['holm2_adjusted_p']=v
 out.mkdir()
 with (out/'signflip_holm2.csv').open('w',encoding='utf8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(contrasts[0]));w.writeheader();w.writerows(contrasts)
 receipt={'status':'PASS','classification':'post hoc robustness sensitivity; primary paired-t family unchanged',
          'assumption':'symmetry of seed-level differences under the null',
          'input_sha256':hashlib.sha256((h/'compact_evidence_complete/run_metrics.csv').read_bytes()).hexdigest(),
          'output_sha256':hashlib.sha256((out/'signflip_holm2.csv').read_bytes()).hexdigest()}
 (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
 print(json.dumps(contrasts,indent=2))
if __name__=='__main__':main()
