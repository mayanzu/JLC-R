"""Observed-point Pareto comparison from saved 480 run summaries.

Descriptive analysis only: no budget matching, inferential dominance or
continuous Pareto frontier is claimed.
"""
from collections import defaultdict
from pathlib import Path
import argparse
import csv
import math
import statistics
from analysis_core import ROOT,rows

INPUT=ROOT/'results/confirmation_480.csv'
OUTPUT=ROOT/'results/rc2_supplement'
FIELDS=['coverage_pct','sample_completion_pct','actual_energy_j','source_coverage_jain']


def write(path,records):
    with path.open('w',encoding='utf8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)


def dominates(a,b):
    aa=(a['coverage_pct'],a['sample_completion_pct'],-a['actual_energy_j'],a['source_coverage_jain'])
    bb=(b['coverage_pct'],b['sample_completion_pct'],-b['actual_energy_j'],b['source_coverage_jain'])
    return all(x>=y for x,y in zip(aa,bb)) and any(x>y for x,y in zip(aa,bb))


def calculate():
    records=rows(INPUT);assert len(records)==480
    by_cell=defaultdict(list);by_seed=defaultdict(list)
    for r in records:
        by_cell[(r['condition'],r['supply'],r['method'])].append(r)
        by_seed[(r['method'],r['seed'])].append(r)
    assert len(by_cell)==40 and len(by_seed)==60
    points=defaultdict(list)
    for (condition,supply,method),group in sorted(by_cell.items()):
        assert len(group)==12
        points[(condition,supply)].append({'condition':condition,'supply':supply,'method':method,
            'n_seeds':12,**{key:statistics.mean(float(r[key]) for r in group) for key in FIELDS}})
    seeds=[]
    for (method,seed),group in sorted(by_seed.items()):
        assert len(group)==8
        seeds.append({'method':method,'seed':seed,
                      **{key:statistics.mean(float(r[key]) for r in group) for key in FIELDS}})
    for method in sorted({r['method'] for r in seeds}):
        group=[r for r in seeds if r['method']==method];assert len(group)==12
        points[('EQUAL_CONDITION','all')].append({'condition':'EQUAL_CONDITION','supply':'all',
            'method':method,'n_seeds':12,**{key:statistics.mean(r[key] for r in group) for key in FIELDS}})
    point_rows=[];pair_rows=[]
    for cell,group in sorted(points.items()):
        assert len(group)==5
        for b in sorted(group,key=lambda r:r['method']):
            dominant=sorted(a['method'] for a in group if a['method']!=b['method'] and dominates(a,b))
            point_rows.append({**b,'nondominated_among_five':int(not dominant),'dominated_by':';'.join(dominant)})
        for a in sorted(group,key=lambda r:r['method']):
            for b in sorted(group,key=lambda r:r['method']):
                if a['method']==b['method']:continue
                pair_rows.append({'condition':cell[0],'supply':cell[1],'method':a['method'],'comparator':b['method'],
                    'coverage_delta_pp':a['coverage_pct']-b['coverage_pct'],
                    'sampling_delta_pp':a['sample_completion_pct']-b['sample_completion_pct'],
                    'energy_delta_j':a['actual_energy_j']-b['actual_energy_j'],
                    'jain_delta':a['source_coverage_jain']-b['source_coverage_jain'],
                    'dominates_comparator':int(dominates(a,b))})
    assert len(point_rows)==45 and len(pair_rows)==180
    return point_rows,pair_rows


def verify_and_reproduce(output=None,create=False):
    pts,pairs=calculate()
    for name,computed in [('pareto_observed_points_45.csv',pts),('pareto_pairwise_180.csv',pairs)]:
        if not create:
            prior=rows(OUTPUT/name);assert len(prior)==len(computed)
            for a,b in zip(prior,computed):
                for k,v in b.items():
                    if isinstance(v,(int,float)):
                        assert math.isclose(float(a[k]),v,rel_tol=0,abs_tol=1e-8),(name,k,a[k],v)
                    else:assert a[k]==v,(name,k,a[k],v)
        if output is not None:write(Path(output)/name,computed)
    return {'status':'PASS','means_checked':len(pts),'pairwise_directions':len(pairs),'simulations_started':0,
            'scope':'Descriptive dominance among five observed mean points; not a matched-budget experiment or inferential frontier.'}


if __name__=='__main__':
    import json
    p=argparse.ArgumentParser();p.add_argument('--create-output',type=Path)
    a=p.parse_args();print(json.dumps(verify_and_reproduce(a.create_output,create=bool(a.create_output)),indent=2))
