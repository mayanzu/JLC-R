"""Process the preselected independent NOAA period using the frozen paper QC rule."""
from datetime import datetime, timedelta
from pathlib import Path
import csv, hashlib, json
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE/'new_weather'
RAW=ROOT/'raw'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
protocol=json.loads((HERE/'protocol_predefined.json').read_text(encoding='utf8'))
spec=protocol['new_weather_prespecified']
local_start=datetime(2024,9,1)
offset=int(spec['utc_offset_hours'])
utc_start=local_start-timedelta(hours=offset)
utc_end=utc_start+timedelta(days=17)
assert spec['local_standard_window']=='2024-09-01T00:00:00/2024-09-18T00:00:00'
files=sorted(RAW.glob('tbl24*.dat'))
if len(files)!=18:
    raise RuntimeError(f'Expected 18 daily NOAA files, got {len(files)}')
rows=[];sources=[]
for path in files:
    data=np.loadtxt(path,skiprows=2)
    if data.ndim!=2 or data.shape[0]!=1440 or data.shape[1]<14:
        raise ValueError(f'Unexpected raw daily file shape {path.name}: {data.shape}')
    stamps=[datetime(int(r[0]),int(r[2]),int(r[3]),int(r[4]),int(r[5])) for r in data]
    ghi=np.where(data[:,9]==0,data[:,8],np.nan)
    recon=(~np.isfinite(ghi))&(data[:,11]==0)&(data[:,13]==0)
    ghi[recon]=data[recon,10]*np.maximum(0,np.cos(np.deg2rad(data[recon,7])))+data[recon,12]
    negative=int(np.count_nonzero(np.isfinite(ghi)&(ghi<0)))
    ghi=np.where(np.isfinite(ghi),np.maximum(0.,ghi),np.nan)
    rows.extend((t,float(v),bool(rec)) for t,v,rec in zip(stamps,ghi,recon) if utc_start<=t<utc_end)
    sources.append({'file':path.name,'url':'https://gml.noaa.gov/aftp/data/radiation/surfrad/Boulder_CO/2024/'+path.name,
                    'sha256':sha(path),'bytes':path.stat().st_size,
                    'negative_all_daily_values_clamped':negative})
rows.sort(key=lambda x:x[0])
expected=17*1440
if len(rows)!=expected or any(t!=utc_start+timedelta(minutes=i) for i,(t,_,_) in enumerate(rows)):
    raise RuntimeError('Missing, duplicate, or misordered NOAA minute timestamps')
values=np.asarray([r[1] for r in rows])
missing=~np.isfinite(values)
starts=np.flatnonzero(np.diff(np.r_[False,missing,False].astype(int))==1)
ends=np.flatnonzero(np.diff(np.r_[False,missing,False].astype(int))==-1)
interpolated=0;maxgap=0
for a,b in zip(starts,ends):
    length=int(b-a); maxgap=max(maxgap,length)
    if length>5 or a==0 or b==len(values):
        raise ValueError(f'Unresolved data-quality gap at {a}: length={length}')
    values[a:b]=np.linspace(values[a-1],values[b],length+2)[1:-1]
    interpolated+=length
if not np.isfinite(values).all():
    raise ValueError('Unresolved irradiance')
means=values.reshape(-1,15).mean(axis=1)
out=ROOT/'ghi_15min.csv'
if out.exists(): raise RuntimeError('Refusing to overwrite processed NOAA file')
with out.open('w',encoding='utf8',newline='') as handle:
    writer=csv.writer(handle);writer.writerow(['local_standard_time','GHI_W_m2'])
    for i,v in enumerate(means):
        writer.writerow([(local_start+timedelta(minutes=i*15)).isoformat(),repr(float(v))])
report={'status':'PASS','site':spec['site'],'local_start':local_start.isoformat(),
        'utc_start':utc_start.isoformat(),'utc_end_exclusive':utc_end.isoformat(),
        'utc_offset_hours':offset,'time_basis':'local standard time, no DST',
        'raw_sources':sources,'minutes':len(rows),'output_rows':len(means),
        'reconstructed_minutes':sum(r[2] for r in rows),
        'interpolated_minutes':interpolated,'max_interpolated_gap_minutes':maxgap,
        'qc_rule':spec['weather_QC'],'processed_sha256':sha(out),
        'scored_mean_daily_irradiation_kwh_m2':float(means[192:192+1344].sum()*.25/1000/14),
        'conversion':'H=s*shade*0.12*GHI/1000, no second daylight multiplier'}
(ROOT/'provenance.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
print(json.dumps({k:v for k,v in report.items() if k!='raw_sources'},indent=2))
