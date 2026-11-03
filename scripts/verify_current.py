"""Verify both paper cohorts without simulation; use a new external work directory."""
from pathlib import Path
import argparse, csv, hashlib, json, math, shutil, subprocess, sys, zipfile

ROOT = Path(__file__).resolve().parents[1]
E = ROOT/'evidence'
B = E/'stageB_20261030'
C = E/'stageC_20261030'
N = E/'ns3_fragment'

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def run(*args):
    print('+', ' '.join(map(str,args)), flush=True)
    subprocess.run([sys.executable,'-B',*map(str,args)],check=True)

def unpack(source,dest):
    dest.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(source) as z:
        assert z.testzip() is None, source
        for x in z.infolist():
            target=(dest/x.filename).resolve()
            assert target.is_relative_to(dest.resolve()) and not x.is_dir(),x.filename
        z.extractall(dest)

def compare(a,b,path='root'):
    if isinstance(a,dict):
        assert isinstance(b,dict) and a.keys()==b.keys(),path
        for k in a:compare(a[k],b[k],path+'.'+k)
    elif isinstance(a,list):
        assert isinstance(b,list) and len(a)==len(b),path
        for i,(x,y) in enumerate(zip(a,b)):compare(x,y,f'{path}[{i}]')
    elif isinstance(a,(int,float)) and not isinstance(a,bool):
        assert isinstance(b,(int,float)) and math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-9),(path,a,b)
    else:assert a==b,(path,a,b)

def verify_stage_c_records(work):
    protocol=json.loads((C/'protocol_predefined.json').read_text(encoding='utf8'))
    lock=json.loads((C/'study_lock.json').read_text(encoding='utf8'))
    assert sha(C/'protocol_predefined.json')==lock['protocol_sha256']
    assert sha(C/'run_stage_c.py')==lock['runner_sha256']
    for rel,digest in protocol['frozen_source_sha256'].items():assert sha(ROOT/rel)==digest,rel
    counts={}
    for group,n in [('e1',576),('e3',384)]:
        folder=work/f'confirmation_{group}'
        cases=protocol[group]['cases'];assert len(cases)==n
        for case in cases:
            d=folder/f"case_{case['index']:06d}"
            record=json.loads((d/'record.json').read_text(encoding='utf8'))
            val=json.loads((d/'validation.json').read_text(encoding='utf8'))
            assert val['status']=='PASS' and record['case']==case
            with (d/'node_ledgers.csv').open(encoding='utf8',newline='') as f:nodes=list(csv.DictReader(f))
            assert len(nodes)==100 and len({int(x['node']) for x in nodes})==100
            energy=sum(float(x[k]) for x in nodes for k in ('base_j','data_j','control_j'))
            assert math.isclose(energy,record['metrics']['consumed_j'],rel_tol=1e-9,abs_tol=1e-6)
            assert max(abs(float(x['initial_j'])+float(x['harvest_j'])-sum(float(x[k]) for k in ('spill_j','base_j','data_j','control_j','final_j'))) for x in nodes)<1e-8
        counts[group]=n
    return counts

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work-dir',type=Path,required=True,help='New directory outside the package for extracted evidence and verification outputs')
    args=ap.parse_args();work=args.work_dir.resolve()
    if work.is_relative_to(ROOT.resolve()) or work.exists():ap.error('work directory must be new and outside the package')
    work.mkdir(parents=True)
    run(ROOT/'scripts/reproduce.py','--mode','verify')
    mechanisms=E/'additional_mechanism_audit'
    run(mechanisms/'audit_mechanism_counts.py','--package',ROOT,
        '--records',mechanisms/'source_records','--output',work/'mechanism_counts')
    for name in ('mechanism_counts_by_run_96.csv','mechanism_counts_by_condition_8.csv'):
        assert sha(work/'mechanism_counts'/name)==sha(mechanisms/name),name
    unpack(B/'case_records.zip',work/'stage_b_records')
    run(B/'verify_compact.py','--record-root',work/'stage_b_records')
    run(B/'verify_original_five.py','--record-root',work/'stage_b_records')
    cwork=work/'stageC_20261030'
    unpack(C/'case_records.zip',cwork)
    counts=verify_stage_c_records(cwork)
    for name in ('protocol_predefined.json','analyze_stage_c.py'):shutil.copyfile(C/name,cwork/name)
    bwork=work/'stageB_20261030'/'compact_evidence_complete';bwork.mkdir(parents=True)
    shutil.copyfile(B/'compact_evidence_complete/run_metrics.csv',bwork/'run_metrics.csv')
    for name in ('protocol_predefined.json','signflip_24.py'):
        shutil.copyfile(B/name,bwork.parent/name)
    run(bwork.parent/'signflip_24.py')
    assert sha(bwork.parent/'signflip_sensitivity_24/signflip_holm2.csv')==sha(B/'signflip_sensitivity_24/signflip_holm2.csv')
    run(cwork/'analyze_stage_c.py')
    generated=json.loads((cwork/'analysis_complete/stage_c_summary.json').read_text(encoding='utf8'))
    saved=json.loads((C/'analysis_complete/stage_c_summary.json').read_text(encoding='utf8'))
    compare(generated,saved)
    ns=work/'ns3_fragment';ns.mkdir()
    for name in ('fragment_trials_128.csv','summarize_fragment.py'):shutil.copyfile(N/name,ns/name)
    lock=json.loads((N/'fragment_lock.json').read_text(encoding='utf8'))
    assert sha(N/'fragment_micro.cc')==lock['source_sha256'] and sha(N/'fragment_protocol.json')==lock['protocol_sha256']
    run(ns/'summarize_fragment.py')
    receipt=json.loads((N/'fragment_summary_receipt.json').read_text(encoding='utf8'))
    assert sha(ns/'fragment_summary.csv')==receipt['summary_sha256']
    assert sha(N/'fragment_trials_128.csv')==receipt['source_sha256']
    figures=E/'current_paper_figures'
    paper=json.loads((figures/'paper_build_manifest.json').read_text(encoding='utf8'))
    for stem in ('fig1_system','fig2_algorithm','fig3_aggregate','fig4_external','fig5_factorial','fig6_boundaries'):
        for suffix in ('.pdf','.svg'):
            name=stem+suffix
            assert sha(figures/name)==paper['input_sha256']['figures/'+name],name
    result={'status':'PASS','legacy_12_seed_cases':480,'mechanism_counter_records':96,'stage_b_cases':2664,'stage_c_cases':counts,
            'fragment_sender_records':896,'figure_files':12,'signflip_patterns_per_contrast':2**24,'simulations_started':0,
            'round_level_arrays_included':False,
            'stage_c_replication_bit_exact':saved['reproduction']['exact'],
            'stage_c_replication_max_abs_difference':saved['reproduction']['max_abs_diff_vs_stageB']}
    (work/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
