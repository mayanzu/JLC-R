"""Verify, regenerate saved-result outputs, or explicitly rerun confirmation."""
from pathlib import Path
from datetime import datetime
import argparse,csv,json,statistics,shutil
from analysis_core import ROOT,rows,recompute,check_archived,write_outputs
from verify import verify

def summary(protocol,out):
    data=rows(ROOT/'results/confirmation_480.csv')
    fields=['coverage_pct','source_coverage_p5_pct','source_coverage_jain','aoi_mean_minutes',
            'sample_completion_pct','fixed_demand_packet_delivery_pct','actual_energy_j','zero_coverage_sources']
    result=[]
    for method in protocol['methods']:
        for condition in protocol['conditions']:
            for supply in protocol['supplies']:
                rr=[r for r in data if r['method']==method and r['condition']==condition['name'] and float(r['supply'])==supply]
                assert len(rr)==12
                result.append(dict(method=method,condition=condition['name'],supply=supply,n_network_seeds=12,
                    **{k:statistics.mean(float(r[k]) for r in rr) for k in fields}))
    with (out/'condition_means_40.csv').open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode',required=True,choices=['verify','reproduce','rerun'])
    ap.add_argument('--study',choices=['confirmation','factorial']);ap.add_argument('--output',type=Path)
    ap.add_argument('--case-index',type=int,action='append');ap.add_argument('--dry-run',action='store_true')
    a=ap.parse_args()
    if a.mode!='rerun' and (a.study or a.case_index is not None or a.dry_run):ap.error('study, case-index and dry-run apply only to rerun')
    if a.mode=='verify' and a.output:ap.error('verify is read-only and does not accept output')
    if a.mode=='rerun' and a.study not in ('confirmation','factorial'):ap.error('rerun requires a study')
    verified=verify();p=json.loads((ROOT/'configs/formal_protocol_original.json').read_text(encoding='utf8'))
    if a.mode=='verify':print(json.dumps(verified,indent=2));return
    out=(a.output or ROOT.parent/(a.mode+'_'+datetime.now().strftime('%Y%m%d_%H%M%S'))).resolve()
    if out.is_relative_to(ROOT.resolve()):ap.error('output must be outside the frozen package')
    if a.mode=='rerun':
        if a.study=='factorial':
            from rerun_factorial import run
        else:
            from rerun import run
        print(json.dumps(run(p,out,a.case_index,a.dry_run),indent=2));return
    out.mkdir(parents=True,exist_ok=False)
    generated=recompute(p);check_archived(generated);write_outputs(out,generated);summary(p,out)
    from paper_tables import build as build_paper_tables
    build_paper_tables(p,generated,out)
    from plot import external_coverage
    from plot_panels import aggregate_effects,service_boundary
    from plot_factorial import render as factorial_figure
    from freshness_ceiling import recompute as freshness_ceiling
    from strawberry_replay import recompute as strawberry_replay
    from pareto_descriptive import verify_and_reproduce as pareto_descriptive
    external_coverage(generated['cell_primary_endpoints_holm64.csv'],out)
    aggregate_effects(generated['primary_holm8.csv'],out)
    factorial_figure(ROOT/'results/rc2_supplement/factorial_primary_holm14.csv',out)
    service_boundary(generated['fairness_age_holm72.csv'],out)
    freshness_ceiling(out)
    strawberry_replay(out)
    pareto_descriptive(out)
    for name in ['factorial_primary_holm14.csv','factorial_secondary_contrasts.csv',
                 'factorial_condition_contrasts.csv','equal_weight_effects.csv',
                 'condition_effects.csv','condition_task_summary.csv','paired_contrasts.csv']:
        shutil.copyfile(ROOT/'results/rc2_supplement'/name,out/name)
    for suffix in ['svg','pdf']:
        shutil.copyfile(ROOT/'assets'/('figure1_model_core.'+suffix),out/('figure1_model_core.'+suffix))
    shutil.copyfile(ROOT/'audit/rc2_supplement/ns3_micro_results.json',out/'ns3_micro_results.json')
    (out/'verification.json').write_text(json.dumps(verified,indent=2),encoding='utf8')
    print(json.dumps(dict(status='PASS',output=str(out),statistical_families=4,
        condition_rows=40,figures=5,simulations_started=0),indent=2))
if __name__=='__main__':main()
