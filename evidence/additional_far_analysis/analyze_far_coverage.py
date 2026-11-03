"""Recompute far-source coverage from saved node summaries without network simulations.

Reconstruct only the seeded static topology used by ScenarioV2, identify
sources at least 200 m from the sink, and average their saved fresh coverage.
No controllers, packet service, weather replay or performance matrix is run.
"""
from pathlib import Path
import argparse
import collections
import csv
import gzip
import hashlib
import json
import math
import statistics
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT.parent.parent / '算法最小复现包' / 'JLC-R'
WINTER = [('WINTER_G20', 1.0), ('WINTER_G20', 0.7), ('T3_G20', 1.0), ('T3_G20', 0.7)]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def positions(seed, nodes, area):
    """Static topology only, matching the archived ScenarioV2 constructor."""
    side = int(np.ceil(np.sqrt(nodes)))
    x, y = np.meshgrid((np.arange(side) + .5) / side, (np.arange(side) + .5) / side)
    points = np.column_stack((x.ravel()[:nodes], y.ravel()[:nodes])) * area
    rng = np.random.default_rng(np.random.SeedSequence([seed, 11]))
    points += rng.uniform(-8, 8, points.shape)
    return points, np.array([0., area / 2])


def write_csv(path, data, fields):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, default=PACKAGE)
    parser.add_argument('--output', type=Path, required=True, help='new directory for descriptive results')
    args = parser.parse_args()
    pkg = args.package.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    paths = {'runs': pkg/'results/confirmation_480.csv',
             'nodes': pkg/'results/node_records_48000.csv.gz',
             'configs': pkg/'configs/effective_configs.json',
             'scenario_source': pkg/'code/simulation/diagnostic.py'}
    runs = read_csv(paths['runs'])
    nodes = read_csv(paths['nodes'])
    cfg = json.loads(paths['configs'].read_text(encoding='utf-8'))
    config_pairs = {(v['nodes'], float(v['area_m'])) for v in cfg.values()}
    assert config_pairs == {(100, 300.0)}, config_pairs
    grouped = collections.defaultdict(list)
    for row in nodes:
        grouped[int(row['case_index'])].append(row)
    assert len(runs) == len(grouped) == 480 and len(nodes) == 48000
    derived, keymap, masks = [], {}, {}
    maxerr = 0.0
    for case in runs:
        case_id = int(case['case_index'])
        records = grouped[case_id]
        assert len(records) == 100
        assert all((r['method'], r['condition'], r['supply'], r['seed']) ==
                   (case['method'], case['condition'], case['supply'], case['seed']) for r in records)
        records.sort(key=lambda r: int(r['node']))
        assert [int(r['node']) for r in records] == list(range(100))
        values = np.array([float(r['coverage_pct']) for r in records])
        assert np.isfinite(values).all() and (values >= 0).all() and (values <= 100).all()
        maxerr = max(maxerr, abs(values.mean() - float(case['coverage_pct'])))
        seed = int(case['seed'])
        if seed not in masks:
            pos, sink = positions(seed, 100, 300.0)
            masks[seed] = np.linalg.norm(pos-sink, axis=1) >= 200.0
        mask = masks[seed]
        assert mask.any()
        mean = float(values[mask].mean())
        row = {'case_index': case_id, 'method': case['method'], 'condition': case['condition'],
               'supply': float(case['supply']), 'seed': seed, 'far_nodes': int(mask.sum()),
               'far_coverage_pct': mean}
        derived.append(row)
        key = (row['method'], row['condition'], row['supply'], seed)
        assert key not in keymap
        keymap[key] = mean
    assert maxerr < 1e-9
    seeds = sorted(masks)
    assert len(seeds) == 12
    comparison = []
    for condition, supply in WINTER:
        jlc = [keymap[('JLC-R-RC2', condition, supply, seed)] for seed in seeds]
        ead = [keymap[('EADCM-CE', condition, supply, seed)] for seed in seeds]
        comparison.append({'condition': condition, 'supply': supply, 'n_seeds': len(seeds),
                           'jlc_far_pct': statistics.mean(jlc), 'eadcm_far_pct': statistics.mean(ead),
                           'paired_difference_pp': statistics.mean(a-b for a, b in zip(jlc, ead))})
    jlc_seed = [statistics.mean(keymap[('JLC-R-RC2', c, s, seed)] for c, s in WINTER) for seed in seeds]
    ead_seed = [statistics.mean(keymap[('EADCM-CE', c, s, seed)] for c, s in WINTER) for seed in seeds]
    summary = {'winter_jlc_pct': statistics.mean(jlc_seed), 'winter_eadcm_pct': statistics.mean(ead_seed),
               'winter_difference_pp': statistics.mean(a-b for a, b in zip(jlc_seed, ead_seed)),
               'cell_difference_min_pp': min(r['paired_difference_pp'] for r in comparison),
               'cell_difference_max_pp': max(r['paired_difference_pp'] for r in comparison)}
    write_csv(out/'far_coverage_480.csv', derived,
              ['case_index','method','condition','supply','seed','far_nodes','far_coverage_pct'])
    write_csv(out/'far_coverage_winter_comparison.csv', comparison,
              ['condition','supply','n_seeds','jlc_far_pct','eadcm_far_pct','paired_difference_pp'])
    receipt = {'status':'PASS', 'scope':'Post hoc descriptive analysis of saved source coverages; no network simulations or hypothesis tests.',
               'source_sha256':{k:sha(v) for k,v in paths.items()}, 'script_sha256':sha(Path(__file__)),
               'numpy_version':np.__version__, 'seed_count':len(seeds), 'run_count':len(runs),
               'node_record_count':len(nodes), 'source_distance_threshold_m':200,
               'far_nodes_min':min(int(v.sum()) for v in masks.values()),
               'far_nodes_max':max(int(v.sum()) for v in masks.values()),
               'max_whole_network_coverage_error_pp':maxerr, 'summary':summary,
               'limitations':'Topology is reconstructed from the archived seed and configuration; the summaries cannot localize where a packet failed.'}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(receipt,indent=2,ensure_ascii=False))


if __name__ == '__main__':
    main()
