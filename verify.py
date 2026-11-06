"""Verify the source closure; optionally execute a two-round synthetic smoke check."""
from pathlib import Path
import argparse,ast,hashlib,json,os,sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent

def verify_files():
    manifest=json.loads((ROOT/'source_manifest.json').read_text(encoding='utf8'))
    files=set()
    for directory,subdirs,names in os.walk(ROOT):
        subdirs[:]=[name for name in subdirs if name not in {'.git','__pycache__'}]
        for name in names:
            if name=='.git' or name.endswith(('.pyc','.pyo')):continue
            files.add((Path(directory)/name).relative_to(ROOT).as_posix())
    assert files==set(manifest['files_sha256'])|{'source_manifest.json'},'Unexpected or missing package files'
    for name,digest in manifest['files_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    source=ROOT/'code/simulation';modules={p.stem for p in source.glob('*.py')};pending=['jlc_r'];seen=set()
    while pending:
        name=pending.pop()
        if name in seen:continue
        seen.add(name)
        for node in ast.walk(ast.parse((source/(name+'.py')).read_text(encoding='utf8'))):
            imported=[a.name.split('.')[0] for a in node.names] if isinstance(node,ast.Import) else [node.module.split('.')[0]] if isinstance(node,ast.ImportFrom) and node.module else []
            pending.extend(n for n in imported if n in modules)
    assert seen==modules==set(manifest['runtime_modules']),'Runtime closure mismatch'
    for name,digest in manifest['frozen_parent_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    return manifest

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--smoke',action='store_true');args=parser.parse_args()
    manifest=verify_files();report=dict(status='PASS',implementation=manifest['implementation_id'],runtime_modules=len(manifest['runtime_modules']),frozen_parent_modules=len(manifest['frozen_parent_sha256']),smoke_rounds=0,formal_performance_runs_started=0)
    if args.smoke:
        sys.path.insert(0,str(ROOT/'code/simulation'))
        import numpy as np
        from run import load_config,build_scenario
        from jlc_r import JLCR
        from validation_model import StreamingBank
        config=load_config();scenario=build_scenario(config,1320352547,14,1.0)
        simulator=JLCR(config,scenario,StreamingBank(scenario))
        for _ in range(2):simulator.round()
        assert simulator.public_source_mode=='spatial'
        assert simulator.horizon_days==3 and simulator.tg_mode=='reference' and simulator.v63_mechanism=='relay_repair'
        assert simulator.generated+simulator.unsensed==2*config['nodes']
        assert np.all(simulator.battery>=-1e-10) and np.all(simulator.battery<=config['battery_j']+1e-10)
        residual=simulator.initial_sum+simulator.harvested-simulator.consumed-simulator.spilled-float(simulator.battery.sum())
        assert abs(residual)<1e-6
        prefix=~simulator.fdc_active
        assert np.all(simulator.extra[prefix]>=simulator.planned_floor[prefix])
        report.update(smoke_rounds=2,energy_residual_j=residual)
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
