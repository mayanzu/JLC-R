"""Analyze complete q8 winter exploration against matched frozen JLC-R; never partial."""
from pathlib import Path
import csv,hashlib,json,math
from functools import lru_cache
import numpy as np
from scipy import stats
import analyze_completed_studies as a
h=Path(__file__).resolve().parent
p=json.loads((h/'protocol_predefined.json').read_text(encoding='utf8'))
q=json.loads((h/'q8_protocol.json').read_text(encoding='utf8'))
out=h/'q8_analysis_complete'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def far(folder,idx):
    path=h/folder/f'case_{idx:06d}'/'node_ledgers.csv'
    with path.open(encoding='utf8',newline='') as f:rows=list(csv.DictReader(f))
    vals=[float(r['coverage_pct']) for r in rows
          if math.hypot(float(r['x_m']),float(r['y_m'])-150.)>=200.]
    assert vals
    return float(np.mean(vals))
@lru_cache(maxsize=None)
def fresh_gap_p95(folder,idx):
    path=h/folder/f'case_{idx:06d}'/'arrays.npz'
    with np.load(path) as a:
        latest=a['latest']
        t=np.arange(latest.shape[0])[:,None]
        fresh=(latest>=0)&(t-latest+1<=4)
        last=np.maximum.accumulate(np.where(fresh,t,-1),axis=0)
        gap=np.where(fresh,0,t-last)
        return float(np.quantile(gap.max(axis=0)*15,.95))
def run():
    if out.exists():raise SystemExit('Refusing overwrite')
    if not (h/'q8_confirmation/completion.json').exists() or not (h/'confirmation/completion.json').exists():
        raise SystemExit('WAIT: complete q8 and primary control matrices required')
    lock=json.loads((h/'q8_lock.json').read_text(encoding='utf8'))
    assert lock['protocol_sha256']==sha(h/'q8_protocol.json')
    assert lock['runner_sha256']==sha(h/'run_q8.py')
    assert lock['base_runner_sha256']==sha(h/'run_stage_b.py')
    maincases=[dict(c,days=p['days']) for c in p['cases']]
    print('Independently validating main and q8 raw records',flush=True)
    main=a.load_complete('confirmation',maincases)
    other=a.load_complete('q8_confirmation',q['cases'])
    mainindex={(c['condition'],float(c['supply']),c['seed']):c['index']
               for c in maincases if c['method']=='JLC-R'}
    qindex={(c['condition'],float(c['supply']),c['seed']):c['index'] for c in q['cases']}
    cells=[(c,float(s)) for c,s in q['conditions']]
    fields=['coverage_pct','source_coverage_p5_pct','far_coverage_pct',
            'demand_delivery_pct','consumed_j','longest_unfresh_gap_p95_minutes']
    def val(method,condition,supply,seed,field):
        key=(condition,float(supply),seed)
        if field in ('far_coverage_pct','longest_unfresh_gap_p95_minutes'):
            folder='q8_confirmation' if method=='Q8-EXPLORE' else 'confirmation'
            idx=qindex[key] if method=='Q8-EXPLORE' else mainindex[key]
            return far(folder,idx) if field=='far_coverage_pct' else fresh_gap_p95(folder,idx)
        matrix=other if method=='Q8-EXPLORE' else main
        return float(matrix[(method,condition,float(supply),seed)][field])
    result=[]
    for label,chosen in [('equal_three_winter_cells',cells)]+[(f'{c}/{s}',[(c,s)]) for c,s in cells]:
        for field in fields:
            delta=[np.mean([val('Q8-EXPLORE',c,s,seed,field)-val('JLC-R',c,s,seed,field)
                            for c,s in chosen]) for seed in p['seeds']]
            r=a.paired(delta)
            result.append({'cell':label,'endpoint':field,'n':r['n'],'mean_q8_minus_jlcr':r['mean_difference'],
                           'nominal_ci95_low':r['ci95_low'],'nominal_ci95_high':r['ci95_high'],
                           'interpretation':'exploratory; nominal interval; no multiplicity decision'})
    periods=[float(m['q8_node_periods']) for m in other.values()]
    out.mkdir()
    with (out/'q8_exploratory.csv').open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
    receipt={'status':'PASS','control':'paired frozen JLC-R on same 24 seeds and 3 winter cells',
             'q8_cases':len(other),'q8_node_periods_min':min(periods),'q8_node_periods_mean':float(np.mean(periods)),
             'q8_node_periods_max':max(periods),'analysis_sha256':sha(Path(__file__)),
             'outputs':{'q8_exploratory.csv':sha(out/'q8_exploratory.csv')},
             'gap_definition':'per source, maximum consecutive non-fresh rounds, including both observation boundaries; P95 across 100 sources',
             'inference':'conditional on 3 winter cells; no automatic algorithm selection; dynamic/CH-exempt cadence does not obey a simple universal 50% cap'}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
    print(json.dumps(receipt,indent=2))
if __name__=='__main__':run()
