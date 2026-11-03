"""Run prespecified NOAA September trajectory without changing frozen input package."""
from pathlib import Path
import argparse, hashlib, json
import run_stage_b as base
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--phase',choices=['pilot','confirmation'],required=True)
    ap.add_argument('--workers',type=int,default=2)
    args=ap.parse_args()
    protocol=json.loads((HERE/'protocol_predefined.json').read_text(encoding='utf8'))
    spec=protocol['new_weather_prespecified']
    provenance=json.loads((HERE/'new_weather/provenance.json').read_text(encoding='utf8'))
    weather=HERE/'new_weather/ghi_15min_loader.csv'
    loader=json.loads((HERE/'new_weather/loader_manifest.json').read_text(encoding='utf8'))
    if loader['loader_sha256']!=sha(weather) or provenance['processed_sha256']!=loader['timestamped_sha256'] or provenance['output_rows']!=1632:
        raise SystemExit('Weather input or provenance changed')
    cond=next(c for c in protocol['conditions'] if c['name']=='T2_G20')
    cond=dict(cond,name='NOAA_SEPT2024_G20',weather_file=str(weather))
    protocol['conditions'].append(cond)
    if args.phase=='pilot':
        cases=[{'index':i+1,'seed':60503,'condition':cond['name'],'supply':1.0,
                'method':method,'days':14,'pilot':True}
               for i,method in enumerate(spec['methods'])]
        out=HERE/'new_weather_pilot'
    else:
        lock=json.loads((HERE/'weather_study_lock.json').read_text(encoding='utf8'))
        if lock['runner_sha256']!=sha(Path(__file__)) or lock['processed_weather_sha256']!=sha(weather):
            raise SystemExit('Weather runner or input differs from lock')
        if json.loads((HERE/'new_weather_pilot/completion.json').read_text(encoding='utf8'))['status']!='COMPLETE':
            raise SystemExit('Weather pilot failed')
        cases=[]
        for seed in spec['seeds']:
            for supply in spec['supplies']:
                for method in spec['methods']:
                    cases.append({'index':len(cases)+1,'seed':seed,'condition':cond['name'],
                                  'supply':supply,'method':method,'days':14})
        out=HERE/'new_weather_confirmation'
    if not base.submit(cases,protocol,out,args.workers):raise SystemExit(1)
if __name__=='__main__':main()
