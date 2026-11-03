"""Read-only lock and raw-reference check. Never starts simulations."""
from rc2_runtime import HERE,PROJECT,read,sha,verify_sources
import json

def main():
    p=read(HERE/'protocol.json');verify_sources(p)
    assert len(p['methods'])==5 and len(p['cases'])==480 and len(p['seeds'])==12
    assert sum(c['execution']=='new_execution' for c in p['cases'])==288
    assert sum(c['execution']=='reuse' for c in p['cases'])==192
    assert len({(c['method'],c['condition'],c['supply'],c['seed']) for c in p['cases']})==480
    for field,name in [('reuse_inventory_sha256','reuse_inventory.json'),('initialization_audit_sha256','paired_initialization_audit.json'),('effective_configs_sha256','effective_configs.json')]:assert sha(HERE/name)==p[field]
    for rel,h in p['source_sha256'].items():assert sha(HERE/'source_snapshot'/rel)==h
    for r in read(HERE/'reuse_inventory.json'):
        for name,h in r['files'].items():assert sha(PROJECT/r['directory']/name)==h
    for m,e in p['method_entries'].items():
        import hashlib
        h=hashlib.sha256(json.dumps(e,sort_keys=True,separators=(',',':')).encode()).hexdigest();assert h==p['method_configuration_sha256'][m]
    assert read(HERE/'reuse_audit.json')['eligible']==192
    assert p['primary_family']['hypotheses']==8
    for line in (HERE/'checksums.sha256').read_text(encoding='utf8').splitlines() if (HERE/'checksums.sha256').exists() else []:
        h,rel=line.split('  ',1);assert sha(HERE/rel)==h,rel
    print(json.dumps(dict(status='PASS',protocol_sha256=sha(HERE/'protocol.json'),source_files=len(p['source_sha256']),
        methods=5,logical_cases=480,reused_eligible=192,new_execution_cases=288,simulation_rounds_executed=0,
        authorization_present=(HERE/'authorization.json').exists()),indent=2))
if __name__=='__main__':main()
