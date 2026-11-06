"""Download locked comparison evidence and reproduce manuscript comparison data."""
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess,sys,tempfile,urllib.request,zipfile
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def bundle(args,spec):
    destination=args.cache.resolve()
    if destination.is_relative_to(ROOT):raise ValueError('--cache must be outside the code repository')
    if destination.exists():
        manifest=destination/'MANIFEST.json'
        if not manifest.is_file() or sha(manifest)!=spec['manifest_sha256']:
            raise ValueError('Existing cache does not match this evidence version; choose a new --cache')
        return destination
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.jlcr-fetch-',dir=destination.parent) as raw:
        work=Path(raw);archive=work/'evidence.zip'
        if args.archive:shutil.copyfile(args.archive,archive)
        else:
            print('Downloading '+spec['archive_url'],flush=True)
            request=urllib.request.Request(spec['archive_url'],headers={'User-Agent':'JLC-R-reproduction/1.0'})
            with urllib.request.urlopen(request,timeout=60) as response,archive.open('wb') as stream:shutil.copyfileobj(response,stream)
        if sha(archive)!=spec['archive_sha256']:raise ValueError('Evidence archive SHA-256 mismatch')
        extracted=work/'extracted';extracted.mkdir()
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                path=(extracted/item.filename).resolve()
                if not path.is_relative_to(extracted.resolve()) or '\\' in item.filename or (item.external_attr>>16)&0o170000==0o120000:
                    raise ValueError('Unsafe evidence archive entry')
            z.extractall(extracted)
        if sha(extracted/'MANIFEST.json')!=spec['manifest_sha256']:raise ValueError('Evidence manifest SHA-256 mismatch')
        extracted.rename(destination)
    return destination

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['fetch','verify','reproduce','rerun'],required=True)
    parser.add_argument('--cache',type=Path,default=ROOT.parent/'JLC-R-comparison-data-v2026.11.06')
    parser.add_argument('--archive',type=Path,help='Optional offline copy of the exact release ZIP')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--suite',choices=['final','support','duration','development'],default='final')
    parser.add_argument('--case-index',type=int)
    parser.add_argument('--all-cases',action='store_true')
    args=parser.parse_args()
    if args.mode in ['reproduce','rerun'] and args.output is None:parser.error('--output is required')
    if args.output and (args.output.resolve().is_relative_to(ROOT) or args.output.exists()):parser.error('--output must be new and outside the repository')
    if args.mode=='rerun' and ((args.case_index is None)==(not args.all_cases)):parser.error('choose --case-index or --all-cases')
    from verify import verify_files
    verify_files()
    spec=json.loads((ROOT/'paper_bundle.json').read_text(encoding='utf8'))
    data=bundle(args,spec)
    command=[sys.executable,'-X','utf8','-B',str(data/'compare.py'),'--mode','verify' if args.mode in ['fetch','verify'] else args.mode]
    if args.output:command+=['--output',str(args.output.resolve())]
    if args.mode=='rerun':
        command+=['--suite',args.suite]
        command+=['--all-cases'] if args.all_cases else ['--case-index',str(args.case_index)]
    subprocess.run(command,check=True)

if __name__=='__main__':main()
