"""Retrieve public, CC-BY-4.0 strawberry-farm data and verify publisher hashes."""
from pathlib import Path
import hashlib
import json
import requests

HERE=Path(__file__).resolve().parent
BASE='https://data.mendeley.com/public-api/datasets/cjb4vy4mzj'
HEADERS={'User-Agent':'JLC-R reproducibility study; dataset attribution retained'}


def main():
    out=HERE/'raw'
    out.mkdir(exist_ok=False)
    metadata=requests.get(BASE,params={'version':3},headers=HEADERS,timeout=60)
    metadata.raise_for_status()
    (out/'dataset_metadata.json').write_bytes(metadata.content)
    info=metadata.json()
    assert info['doi']['id']=='10.17632/cjb4vy4mzj.3'
    assert info['data_licence']['short_name']=='CC BY 4.0'
    files=requests.get(BASE+'/files',params={'folder_id':'root','version':3},headers=HEADERS,timeout=60)
    files.raise_for_status()
    (out/'dataset_file_metadata.json').write_bytes(files.content)
    entries=files.json()
    assert {e['filename'] for e in entries}=={'D_moisture.txt','D_valve.txt','D_flowmeter.txt'}
    receipt=[]
    for entry in entries:
        res=requests.get(entry['content_details']['download_url'],headers=HEADERS,timeout=60)
        res.raise_for_status()
        digest=hashlib.sha256(res.content).hexdigest()
        assert digest==entry['content_details']['sha256_hash'],entry['filename']
        assert len(res.content)==entry['content_details']['size'],entry['filename']
        (out/entry['filename']).write_bytes(res.content)
        receipt.append({'name':entry['filename'],'size':len(res.content),'sha256':digest})
    (HERE/'download_receipt.json').write_text(json.dumps({'status':'PASS','doi':info['doi']['id'],
      'licence':'CC BY 4.0','source':'https://data.mendeley.com/datasets/cjb4vy4mzj/3',
      'citation':'Manzano, J. M. et al. (2023), Mendeley Data V3, doi:10.17632/cjb4vy4mzj.3',
      'files':receipt},indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':'PASS','files':receipt},indent=2))


if __name__=='__main__':
    main()
