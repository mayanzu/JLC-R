"""Execute only the288 new externals after exact-lock user authorization."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse,json
from rc2_runtime import HERE,read,sha,verify_sources
from rc2_execute import require_authorization,execute,dump

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    if not args.execute:
        print('No simulation. Inspect protocol.md and run verify_lock.py. Explicit --execute and matching authorization.json are both required.');return
    auth=require_authorization();p=read(HERE/'protocol.json');verify_sources(p)
    assert not list(HERE.glob('execution_*')),'An attempt already exists; diagnose and create an explicitly documented retry, do not automatically repeat288.'
    out=HERE/('execution_'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d_%H%M%S'));out.mkdir(exist_ok=False)
    dump(out/'execution_lock.json',dict(protocol_sha256=sha(HERE/'protocol.json'),authorization=auth,new_cases=288,reused=192))
    dump(out/'reused_records.json',read(HERE/'reuse_inventory.json'))
    cases=[c for c in p['cases'] if c['execution']=='new_execution'];assert len(cases)==288
    completed=[];failed=[]
    with ProcessPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(execute,c['index'],str(out)):c['index'] for c in cases}
        for fut in as_completed(futures):
            try:completed.append(fut.result())
            except BaseException as exc:failed.append(dict(index=futures[fut],error=str(exc)))
            dump(out/'progress.json',dict(completed=len(completed),failed=failed,planned=288,formal_rounds_started=True))
            print(json.dumps(dict(completed=len(completed),failed=len(failed),planned=288)),flush=True)
    dump(out/'completed.json',dict(status='COMPLETE' if not failed else 'INCOMPLETE_NO_INFERENCE',completed=completed,failed=failed,reused=192))
    if failed:raise SystemExit('Retain failures and all records; technical diagnosis required. No seed replacement or automatic rerun.')
if __name__=='__main__':main()
