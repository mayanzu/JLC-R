"""Refresh this package's file manifest after an intentional source edit."""
from pathlib import Path
import hashlib
ROOT=Path(__file__).resolve().parents[1];DEST=ROOT/'audit/checksums.sha256'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def main():
    files=sorted((p for p in ROOT.rglob('*') if p.is_file() and p!=DEST
        and '.git' not in p.parts and '__pycache__' not in p.parts and p.suffix!='.pyc'),
        key=lambda p:p.relative_to(ROOT).as_posix())
    DEST.write_text(''.join(f'{sha(p)}  {p.relative_to(ROOT).as_posix()}\n' for p in files),encoding='utf8')
    print(f'Checksummed {len(files)} package files; no simulation was run.')
if __name__=='__main__':main()
