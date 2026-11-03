"""Explicitly rerun one archived 24-seed case to a new external directory."""
from pathlib import Path
import argparse, hashlib, json, math, sys, zipfile

ROOT=Path(__file__).resolve().parents[1]
B=ROOT/'evidence/stageB_20261030'
C=ROOT/'evidence/stageC_20261030'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--study',required=True,choices=['confirmation','extra_confirmation','new_weather_confirmation','q8_confirmation','overhead_confirmation','original_controls_confirmation','e1','e3'])
    ap.add_argument('--case-index',required=True,type=int)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--dry-run',action='store_true')
    a=ap.parse_args();out=a.output.resolve()
    if out.is_relative_to(ROOT.resolve()) or out.exists():ap.error('output must be a new directory outside the package')
    stage_c=a.study in ('e1','e3');group=('confirmation_'+a.study) if stage_c else a.study
    source=C if stage_c else B
    with zipfile.ZipFile(source/'case_records.zip') as z:
        record=json.loads(z.read(f'{group}/case_{a.case_index:06d}/record.json'))
    case=record['case'];p=json.loads((source/'protocol_predefined.json').read_text(encoding='utf8'))
    for rel,digest in p['frozen_source_sha256'].items():
        assert sha(ROOT/rel)==digest,rel
    if stage_c:
        lock=json.loads((C/'study_lock.json').read_text(encoding='utf8'))
        assert sha(C/'run_stage_c.py')==lock['runner_sha256'] and sha(C/'protocol_predefined.json')==lock['protocol_sha256']
    print(json.dumps({'study':a.study,'case':case,'output':str(out),'dry_run':a.dry_run,'new_independent_evidence':False},indent=2),flush=True)
    if a.dry_run:return
    sys.path[:0]=[str(B),str(ROOT/'scripts'),str(ROOT/'code/simulation')]
    out.mkdir(parents=True,exist_ok=False)
    target=out/f"case_{a.case_index:06d}"
    if stage_c:
        import importlib.util
        spec=importlib.util.spec_from_file_location('frozen_stage_c',C/'run_stage_c.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.run_case((case,p,str(target)))
    else:
        import run_stage_b as base
        if a.study=='extra_confirmation':
            import run_extra_comparators as worker
            call=worker.worker
        elif a.study=='q8_confirmation':
            import run_q8 as worker
            call=worker.worker
        else:call=base.run_case
        if a.study=='new_weather_confirmation':
            cond=next(x for x in p['conditions'] if x['name']=='T2_G20')
            p['conditions'].append(dict(cond,name='NOAA_SEPT2024_G20',weather_file=str(B/'new_weather/ghi_15min_loader.csv')))
        if a.study=='overhead_confirmation':
            factor=json.loads((B/'overhead_protocol.json').read_text(encoding='utf8'))['factor']
            updated=[]
            for cond in p['conditions']:
                initial=base.load_config(cond);cfg=dict(cond['config'])
                for key in ('elec_j_per_bit','fs_j_per_bit_m2','mp_j_per_bit_m4'):cfg[key]=initial[key]*factor
                cfg['bitrate_bps']=initial['bitrate_bps']/factor
                updated.append(dict(cond,config=cfg))
            p['conditions']=updated
        call((case,p,str(target)))
    fresh=json.loads((target/'record.json').read_text(encoding='utf8'))['metrics']
    old=record['metrics'];fields=('coverage_pct','source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes','sample_completion_pct','demand_delivery_pct','consumed_j')
    diffs={k:abs(float(fresh[k])-float(old[k])) for k in fields}
    assert all(math.isclose(float(fresh[k]),float(old[k]),rel_tol=1e-9,abs_tol=1e-6) for k in fields),diffs
    receipt={'status':'PASS','study':a.study,'case_index':a.case_index,'metric_absolute_differences':diffs,
             'scope':'one technical rerun of an existing seed; not independent confirmation'}
    (out/'comparison.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf8')
    print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
