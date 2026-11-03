"""Derive compact per-source sensing masks from the immutable formal archive."""
from pathlib import Path
import csv
import hashlib
import io
import json
import zipfile
import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
SOURCE = PROJECT / 'code/experiments/rc2_confirmation/raw/rc2_formal_raw.zip'
CASE_FILE = PROJECT / 'code/experiments/rc2_confirmation/results/confirmation_480.csv'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    protocol = json.loads((HERE/'protocol.json').read_text(encoding='utf8'))
    assert sha(SOURCE) == protocol['source_sha256'][SOURCE.relative_to(PROJECT).as_posix()]
    assert sha(CASE_FILE) == protocol['source_sha256'][CASE_FILE.relative_to(PROJECT).as_posix()]
    with CASE_FILE.open(encoding='utf8', newline='') as handle:
        cases = sorted(csv.DictReader(handle), key=lambda x:int(x['case_index']))
    assert [int(r['case_index']) for r in cases] == list(range(480))
    packed = np.empty((480, 16800), dtype=np.uint8)
    arrays_sha = []
    with zipfile.ZipFile(SOURCE) as archive:
        for i, case in enumerate(cases):
            branch = 'new' if case['origin']=='new_execution' else 'reused'
            content = archive.read(f'{branch}/case_{i:04d}/arrays.npz')
            arrays_sha.append(hashlib.sha256(content).hexdigest())
            with np.load(io.BytesIO(content)) as raw:
                status = raw['sample_status']
            assert status.shape == (134400,) and np.isin(status, np.arange(1, 7)).all()
            mask = status != 5
            assert abs(mask.mean()*100-float(case['sample_completion_pct'])) < 1e-8
            packed[i] = np.packbits(mask, bitorder='big')
    out = HERE/'results/sensing_mask_480.npz'
    if out.exists():
        raise FileExistsError(out)
    np.savez_compressed(out, packed=packed, case_index=np.arange(480), rounds=np.array(1344),
                        nodes=np.array(100), source_arrays_sha256=np.asarray(arrays_sha))
    print(json.dumps({'status':'PASS','cases':480,'derived_mask_sha256':sha(out),
                      'bytes':out.stat().st_size,'simulations_started':0},indent=2))


if __name__ == '__main__':
    main()
