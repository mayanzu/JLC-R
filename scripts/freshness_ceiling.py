"""Recompute the observed-sensing freshness ceiling without simulation."""
from collections import defaultdict
from pathlib import Path
import csv
import gzip
import math
import statistics
import numpy as np
from analysis_core import ROOT, rows

SUPPLEMENT = ROOT/'results/rc2_supplement'
FIELDS = ['coverage_pct', 'conditional_ceiling_pct', 'delivery_freshness_deficit_pct',
          'no_fresh_sample_pct', 'source_p5_pct', 'source_p5_ceiling_pct',
          'aoi_mean_minutes', 'conditional_aoi_floor_minutes', 'sample_completion_pct']


def _node_rows():
    grouped = defaultdict(dict)
    with gzip.open(ROOT/'results/node_records_48000.csv.gz', 'rt', encoding='utf8', newline='') as handle:
        for row in csv.DictReader(handle):
            case, node = int(row['case_index']), int(row['node'])
            assert node not in grouped[case]
            grouped[case][node] = row
    assert len(grouped) == 480 and all(len(nodes) == 100 for nodes in grouped.values())
    return grouped


def _write(path, records):
    with path.open('w', encoding='utf8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def recompute(output=None):
    original = sorted(rows(ROOT/'results/confirmation_480.csv'), key=lambda r:int(r['case_index']))
    saved = sorted(rows(SUPPLEMENT/'seed_decomposition_480.csv'), key=lambda r:int(r['case_index']))
    assert len(original) == len(saved) == 480
    per_source = _node_rows()
    with np.load(SUPPLEMENT/'sensing_mask_480.npz') as data:
        packed = data['packed']; indices = data['case_index']; source_hash = data['source_arrays_sha256']
        rounds, nodes = int(data['rounds']), int(data['nodes'])
    assert packed.shape == (480, 16800) and rounds == 1344 and nodes == 100
    assert np.array_equal(indices, np.arange(480)) and len(source_hash) == 480
    records = []
    t = np.arange(rounds)[:, None]
    for i, (case, archive_row) in enumerate(zip(original, saved)):
        assert int(case['case_index']) == int(archive_row['case_index']) == i
        assert str(source_hash[i]) == archive_row['arrays_sha256']
        for key in ('method', 'condition', 'supply', 'seed', 'origin'):
            assert case[key] == archive_row[key], (i, key)
        mask = np.unpackbits(packed[i], bitorder='big').reshape(rounds, nodes).astype(bool)
        latest_sample = np.maximum.accumulate(np.where(mask, t, -1), axis=0)
        eligible = (latest_sample >= 0) & (t-latest_sample+1 <= 4)
        source_ceiling = 100*eligible.mean(axis=0)
        source_floor_age = np.where(latest_sample >= 0, t-latest_sample+1, t+1).mean(axis=0)*15
        for node in range(nodes):
            baseline = per_source[i][node]
            assert float(baseline['coverage_pct']) <= source_ceiling[node] + 1e-8, (i, node, 'coverage')
            assert float(baseline['aoi_mean_minutes']) + 1e-8 >= source_floor_age[node], (i, node, 'aoi')
        actual = float(case['coverage_pct']); ceiling = float(source_ceiling.mean())
        metrics = {'coverage_pct': actual, 'conditional_ceiling_pct': ceiling,
                   'delivery_freshness_deficit_pct': ceiling-actual,
                   'no_fresh_sample_pct': 100-ceiling,
                   'source_p5_pct': float(case['source_coverage_p5_pct']),
                   'source_p5_ceiling_pct': float(np.quantile(source_ceiling,.05)),
                   'aoi_mean_minutes': float(case['aoi_mean_minutes']),
                   'conditional_aoi_floor_minutes': float(source_floor_age.mean()),
                   'sample_completion_pct': 100*float(mask.mean())}
        for key, value in metrics.items():
            assert math.isclose(float(archive_row[key]), value, rel_tol=0, abs_tol=1e-8), (i,key,archive_row[key],value)
        assert abs(metrics['coverage_pct']+metrics['delivery_freshness_deficit_pct']+metrics['no_fresh_sample_pct']-100) < 1e-8
        records.append({**{key:case[key] for key in ('case_index','method','condition','supply','seed','origin')},
                        'arrays_sha256':str(source_hash[i]),**metrics})
    cells, seeds = defaultdict(list), defaultdict(list)
    for row in records:
        cells[(row['method'],row['condition'],row['supply'])].append(row)
        seeds[(row['method'],row['seed'])].append(row)
    assert len(cells) == 40 and len(seeds) == 60
    cell_summary=[]
    for (method,condition,supply), group in sorted(cells.items()):
        assert len(group)==12
        cell_summary.append({'method':method,'condition':condition,'supply':supply,'n_seeds':len(group),
                             **{key:statistics.mean(r[key] for r in group) for key in FIELDS}})
    seed_summary=[]
    for (method,seed),group in sorted(seeds.items()):
        assert len(group)==8
        seed_summary.append({'method':method,'seed':seed,'condition_count':len(group),
                             **{key:statistics.mean(r[key] for r in group) for key in FIELDS}})
    totals=[]
    for method in sorted({r['method'] for r in seed_summary}):
        group=[r for r in seed_summary if r['method']==method];assert len(group)==12
        totals.append({'method':method,'n_network_seeds':len(group),
                       **{key:statistics.mean(r[key] for r in group) for key in FIELDS}})
    for name, computed in [('condition_means_40.csv',cell_summary),
                           ('equal_condition_seed_means_60.csv',seed_summary),
                           ('equal_condition_means_5.csv',totals)]:
        archived=rows(SUPPLEMENT/name);assert len(archived)==len(computed)
        for a,b in zip(archived,computed):
            assert all(math.isclose(float(a[k]),b[k],rel_tol=0,abs_tol=1e-8) for k in FIELDS),name
    if output is not None:
        output=Path(output)
        for name,data in [('seed_decomposition_480.csv',records),('condition_means_40.csv',cell_summary),
                          ('equal_condition_seed_means_60.csv',seed_summary),('equal_condition_means_5.csv',totals)]:
            _write(output/('freshness_ceiling_'+name),data)
    return {'status':'PASS','cases':480,'node_bounds_checked':48000,'condition_means':40,
            'source_rounds':480*rounds*nodes,'simulations_started':0,
            'scope':'Retrospective instantaneous-delivery relaxation conditional on each observed sensing schedule; not energy matched or deployable.'}


if __name__ == '__main__':
    import json
    print(json.dumps(recompute(),indent=2))
