"""Read-only integrity, resource-ledger and statistical checks."""
from pathlib import Path
from collections import defaultdict,Counter
import csv,gzip,hashlib,json,math
import numpy as np
from analysis_core import ROOT,rows,recompute,check_archived

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def verify_manifest():
    manifest=ROOT/'audit/checksums.sha256';assert manifest.is_file(),'Missing frozen checksum manifest'
    count=0;listed=set()
    for line in manifest.read_text(encoding='utf8').splitlines():
        digest,relative=line.split('  ',1);p=(ROOT/relative).resolve()
        assert p.is_relative_to(ROOT.resolve()) and p.is_file(),relative
        assert relative not in listed and sha(p)==digest,relative;listed.add(relative);count+=1
    assert count>0
    present={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()
             and p!=manifest and '__pycache__' not in p.parts and '.git' not in p.parts}
    assert listed==present,dict(unlisted=sorted(present-listed),missing=sorted(listed-present))
    mapping=json.loads((ROOT/'audit/frozen_source_mapping.json').read_text(encoding='utf8'))
    for r in mapping['sources']:
        p=(ROOT/r['package_path']).resolve();assert p.is_relative_to(ROOT.resolve()) and sha(p)==r['sha256'],r['original_identity']
    assert mapping['original_protocol_sha256']==sha(ROOT/'configs/formal_protocol_original.json')
    return count,len(mapping['sources'])
def verify():
    count,sources=verify_manifest();p=json.loads((ROOT/'configs/formal_protocol_original.json').read_text(encoding='utf8'))
    records=rows(ROOT/'results/confirmation_480.csv');assert len(records)==480
    expected={(c['method'],c['condition'],float(c['supply']),int(c['seed'])) for c in p['cases']}
    actual={(r['method'],r['condition'],float(r['supply']),int(r['seed'])) for r in records}
    assert actual==expected and len(actual)==480
    assert Counter(r['origin'] for r in records)=={'new_execution':288,'reuse':192}
    grouped=defaultdict(list)
    with gzip.open(ROOT/'results/node_records_48000.csv.gz','rt',encoding='utf8',newline='') as f:
        for r in csv.DictReader(f):grouped[int(r['case_index'])].append(r)
    assert len(grouped)==480 and sum(map(len,grouped.values()))==48000
    max_node=max_global=0.
    for case in records:
        index=int(case['case_index']);rr=grouped[index];assert len(rr)==100 and {int(r['node']) for r in rr}==set(range(100))
        assert all((r['method'],r['condition'],float(r['supply']),int(r['seed']))==
                   (case['method'],case['condition'],float(case['supply']),int(case['seed'])) for r in rr)
        residuals=[]
        for r in rr:
            v=lambda k:float(r[k]);assert all(math.isfinite(v(k)) for k in ['initial_j','harvest_j','spill_j','base_j','data_j','control_j','final_j'])
            residual=v('initial_j')+v('harvest_j')-sum(v(k) for k in ['spill_j','base_j','data_j','control_j','final_j'])
            assert abs(residual)<=1e-8 and -1e-12<=v('final_j')<=4+1e-12
            residuals.append(residual)
        max_node=max(max_node,max(abs(x) for x in residuals));max_global=max(max_global,abs(sum(residuals)))
        assert abs(sum(residuals))<=1e-6
        cov=np.asarray([float(r['coverage_pct']) for r in rr]);age=np.asarray([float(r['aoi_mean_minutes']) for r in rr])
        jain=float(cov.sum()**2/(100*(cov**2).sum())) if cov.any() else 0.
        for k,value in [('coverage_pct',cov.mean()),('source_coverage_p5_pct',np.quantile(cov,.05)),
                        ('source_coverage_jain',jain),('aoi_mean_minutes',age.mean()),('source_coverage_min_pct',cov.min())]:
            assert math.isclose(float(case[k]),value,rel_tol=1e-9,abs_tol=1e-8),(index,k,case[k],value)
        assert int(case['zero_coverage_sources'])==int((cov==0).sum())
        costs=sum(float(r[k]) for r in rr for k in ['base_j','data_j','control_j'])
        assert math.isclose(float(case['actual_energy_j']),costs,rel_tol=1e-9,abs_tol=1e-6),(index,'energy')
        outcomes=['delivered','expired','overflow','outstanding','unsensed','routing_drop']
        assert sum(int(case[k]) for k in outcomes)==134400
        assert math.isclose(float(case['sample_completion_pct']),100*(134400-int(case['unsensed']))/134400,abs_tol=1e-8)
        assert math.isclose(float(case['fixed_demand_packet_delivery_pct']),100*int(case['delivered'])/134400,abs_tol=1e-8)
    generated=recompute(p);stats=check_archived(generated)
    from additional_analysis import verify as verify_additional
    supplementary=verify_additional()
    from freshness_ceiling import recompute as verify_ceiling
    ceiling=verify_ceiling()
    from strawberry_replay import recompute as verify_strawberry
    strawberry=verify_strawberry()
    from pareto_descriptive import verify_and_reproduce as verify_pareto
    pareto=verify_pareto()
    micro=json.loads((ROOT/'audit/rc2_supplement/ns3_micro_results.json').read_text(encoding='utf8'))
    assert micro['status']=='PASS' and micro['source_sha256']==sha(ROOT/'audit/rc2_supplement/execution_sources/ns3_lrwpan_micro.cc')
    checks={r['mode']:r for r in micro['cases']};assert set(checks)=={'single','serial','hidden','oversize'}
    assert checks['single']['rx']==1 and checks['serial']['rx']==2
    assert checks['hidden']['rx']==1 and checks['hidden']['no_ack']==1 and checks['hidden']['phy_rx_drop']==1
    assert checks['oversize']['frame_too_long']==1 and all(r['mtu_bytes']==114 for r in checks.values())
    return dict(status='PASS',manifest_files=count,frozen_original_sources=sources,cases=480,node_ledgers=48000,
        tests_recomputed=stats,network_seed_n=12,max_node_energy_error_j=max_node,max_global_energy_error_j=max_global,
        supplementary=supplementary,freshness_ceiling=ceiling,strawberry_replay=strawberry,pareto=pareto,
        ns3_micro={'status':'PASS','stored_cases':4,'simulation_rerun':False},simulations_started=0,
        scope='Saved seed/source summaries and ledgers; detailed round arrays and method-specific logs are not bundled.')
