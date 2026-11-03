"""After complete matrices, compare original against common wire-overhead stress."""
from pathlib import Path
import csv,hashlib,json
import numpy as np
import analyze_completed_studies as a
h=Path(__file__).resolve().parent
p=json.loads((h/'protocol_predefined.json').read_text(encoding='utf8'))
x=json.loads((h/'overhead_protocol.json').read_text(encoding='utf8'))
out=h/'overhead_analysis_complete'
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    if out.exists():raise SystemExit('Refusing overwrite')
    if not (h/'confirmation/completion.json').exists() or not (h/'overhead_confirmation/completion.json').exists():
        raise SystemExit('WAIT: both full matrices required')
    lock=json.loads((h/'overhead_lock.json').read_text(encoding='utf8'))
    assert lock['protocol_sha256']==sha(h/'overhead_protocol.json')
    assert lock['runner_sha256']==sha(h/'run_overhead_sensitivity.py')
    assert lock['base_runner_sha256']==sha(h/'run_stage_b.py')
    print('Independently validating original and stress raw records',flush=True)
    original=a.load_complete('confirmation',[dict(c,days=p['days']) for c in p['cases']])
    stress=a.load_complete('overhead_confirmation',x['cases'])
    cells=[(c['name'],s) for c in p['conditions'] for s in p['supplies']]
    rows=[]
    for field in ['coverage_pct','source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes','demand_delivery_pct','consumed_j']:
        def contrast(matrix,seed):
            return a.average(matrix,'JLC-R',seed,field,cells)-a.average(matrix,'EADCM-CE',seed,field,cells)
        d0=[contrast(original,seed) for seed in p['seeds']]
        d1=[contrast(stress,seed) for seed in p['seeds']]
        ds=[v-u for u,v in zip(d0,d1)]
        for name,vec in [('original',d0),('overhead_1p32',d1),('change_of_contrast',ds)]:
            z=a.paired(vec)
            rows.append({'endpoint':field,'scenario':name,'n':z['n'],'mean_difference':z['mean_difference'],
                         'ci95_low':z['ci95_low'],'ci95_high':z['ci95_high'],
                         'definition':'JLC-R minus EADCM; change is stressed contrast minus original contrast',
                         'interpretation':'exploratory nominal interval; common abstract overhead stress, not full protocol calibration'})
    out.mkdir()
    with (out/'overhead_exploratory.csv').open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    receipt={'status':'PASS','original_cases_validated':len(original),'stress_cases_validated':len(stress),
             'network_seeds':len(p['seeds']),'cells':len(cells),'factor':x['factor'],
             'scope':'no added contention/retries; coefficient and airtime surrogate, not a full protocol implementation',
             'analysis_sha256':sha(Path(__file__)),
             'outputs':{'overhead_exploratory.csv':sha(out/'overhead_exploratory.csv')}}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
    print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
