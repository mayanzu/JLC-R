"""Pack the recorded fresh-delivery ages needed for the farm replay."""
from pathlib import Path
import csv
import hashlib
import io
import json
import zipfile
import numpy as np

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[2]
RAW=PROJECT/'code/experiments/rc2_confirmation/raw/rc2_formal_raw.zip'
CASES=PROJECT/'code/experiments/rc2_confirmation/results/confirmation_480.csv'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    protocol=json.loads((HERE/'protocol.json').read_text(encoding='utf8'))
    assert sha(RAW)==protocol['source_sha256'][RAW.relative_to(PROJECT).as_posix()]
    with CASES.open(encoding='utf8',newline='') as f:rows=sorted(csv.DictReader(f),key=lambda x:int(x['case_index']))
    assert [int(r['case_index']) for r in rows]==list(range(480))
    ages=np.zeros((480,1344,100),dtype=np.uint8);hashes=[];t=np.arange(1344)[:,None]
    with zipfile.ZipFile(RAW) as archive:
        for i,r in enumerate(rows):
            branch='new' if r['origin']=='new_execution' else 'reused'
            content=archive.read(f'{branch}/case_{i:04d}/arrays.npz');hashes.append(hashlib.sha256(content).hexdigest())
            with np.load(io.BytesIO(content)) as raw:latest=raw['latest']
            age=t-latest+1;fresh=(latest>=0)&(age<=4)
            assert abs(100*fresh.mean()-float(r['coverage_pct']))<1e-8
            ages[i]=np.where(fresh,age,0)
    path=HERE/'results/delivery_fresh_age_480.npz'
    if path.exists():raise FileExistsError(path)
    np.savez_compressed(path,age=ages,case_index=np.arange(480),source_arrays_sha256=np.asarray(hashes))
    print(json.dumps({'status':'PASS','bytes':path.stat().st_size,'sha256':sha(path),'cases':len(rows),'simulations_started':0},indent=2))


if __name__=='__main__':main()
