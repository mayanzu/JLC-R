"""Recheck complete original-five-method 24-seed extension and compute the registered Holm-8 family."""
from pathlib import Path
import csv,hashlib,json
import numpy as np
import analyze_completed_studies as a
h=Path(__file__).resolve().parent
p=json.loads((h/'protocol_predefined.json').read_text(encoding='utf8'))
x=json.loads((h/'original_controls_protocol.json').read_text(encoding='utf8'))
out=h/'original_five_method_analysis'
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
def write(name,rows):
    with (out/name).open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def main():
    if out.exists():raise SystemExit('Refusing overwrite')
    for name in ['confirmation/completion.json','original_controls_confirmation/completion.json']:
        if not (h/name).exists():raise SystemExit('WAIT: both full matrices are required')
    lock=json.loads((h/'original_controls_lock.json').read_text(encoding='utf8'))
    assert lock['protocol_sha256']==sha(h/'original_controls_protocol.json')
    assert lock['runner_sha256']==sha(h/'run_original_controls.py')
    assert lock['base_runner_sha256']==sha(h/'run_stage_b.py')
    print('Independently validating original main and internal-control arrays and ledgers',flush=True)
    main=a.load_complete('confirmation',[dict(c,days=p['days']) for c in p['cases']])
    internal=a.load_complete('original_controls_confirmation',x['cases'])
    data={**main,**internal}
    controls=['EADCM-CE','LANTERN-CE','Base-hybrid','Pre-recovery-JLC-R']
    fields=['coverage_pct','source_coverage_p5_pct']
    cells=[(c['name'],s) for c in p['conditions'] for s in p['supplies']]
    seeds=p['seeds'];rows=[];raw=[];cell_rows=[];means=[]
    for ctl in controls:
     for field in fields:
      diffs=[]
      for seed in seeds:
       left=a.average(data,'JLC-R',seed,field,cells)
       right=a.average(data,ctl,seed,field,cells)
       d=left-right;diffs.append(d)
       raw.append({'seed':seed,'control':ctl,'endpoint':field,'jlcr_mean':left,'control_mean':right,'difference':d})
      result=a.paired(diffs)
      rows.append({'control':ctl,'endpoint':field,'cell':'equal_weight_8cell',**result})
      for cond,supply in cells:
       v=[a.average(data,'JLC-R',seed,field,[(cond,supply)])-
          a.average(data,ctl,seed,field,[(cond,supply)]) for seed in seeds]
       q=a.paired(v)
       cell_rows.append({'control':ctl,'endpoint':field,'condition':cond,'supply':supply,
                         'n':q['n'],'mean_difference':q['mean_difference'],'ci95_low':q['ci95_low'],
                         'ci95_high':q['ci95_high'],'t':q['t'],'df':q['df'],'p':q['p'],
                         'interpretation':'post hoc exploratory; nominal interval'})
    assert len(cell_rows)==64
    # Preserve the complete family when a contrast has zero variance:
    # use conservative p=1 for correction and flag the undefined t statistic.
    cp=[r['p'] if r['p'] is not None else 1. for r in cell_rows]
    order=sorted(range(64),key=lambda i:cp[i]);adjusted=[None]*64;running=0.
    for rank,i in enumerate(order):
        running=max(running,(64-rank)*cp[i]);adjusted[i]=min(1.,running)
    for r,v in zip(cell_rows,adjusted):
        r.update(undefined_t=(r['p'] is None),holm64_adjusted_p=v,reject_05=(r['p'] is not None and v<.05))
    values=[r['p'] if r['p'] is not None else 1. for r in rows]
    order=sorted(range(len(values)),key=lambda i:values[i]);adjusted=[None]*len(values);running=0.
    for rank,i in enumerate(order):
        running=max(running,(len(values)-rank)*values[i]);adjusted[i]=min(1.,running)
    for r,v in zip(rows,adjusted):
        r.update(undefined_t=(r['p'] is None),holm8_adjusted_p=v,reject_05=(r['p'] is not None and v<.05))
    for method in ['JLC-R',*controls]:
     for field in fields:
      vector=[a.average(data,method,seed,field,cells) for seed in seeds]
      means.append({'method':method,'endpoint':field,'n':len(seeds),
                    'mean_equal_weight_8cell':float(np.mean(vector)),
                    'sd_between_seeds':float(np.std(vector,ddof=1))})
    out.mkdir()
    write('five_method_holm8.csv',rows);write('paired_seed_differences.csv',raw)
    write('cell_descriptive.csv',cell_rows);write('method_means.csv',means)
    receipt={'status':'PASS','unit':'network seed','network_seeds':24,
      'main_cases_independently_validated':len(main),'original_controls_cases_independently_validated':len(internal),
      'family':'four five-method contrasts times two endpoints; paired t tests with Holm-8',
      'uncertainty':'nominal unadjusted individual 95% intervals',
      'classification':'secondary family distinct from pre-existing floor/hold Holm-2',
      'cell_family':'post hoc exploratory Holm-64 across four controls, eight cells and two endpoints',
      'cell_plan_sha256':sha(h/'original_five_cell_exploratory_plan.json'),
      'seed_history_limit':x['history_limit'],'analysis_sha256':sha(Path(__file__)),
      'protocol_sha256':sha(h/'original_controls_protocol.json'),
      'outputs':{p.name:sha(p) for p in out.iterdir()}}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
    print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
