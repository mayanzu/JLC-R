"""Independently audit the conditional ceiling using rolling Boolean windows."""
from pathlib import Path
import csv
import io
import itertools
import json
import zipfile
import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
RAW = PROJECT / 'code/experiments/rc2_confirmation/raw/rc2_formal_raw.zip'
CSV = HERE / 'results/seed_decomposition_480.csv'
THRESHOLD = 4


def measures(latest, status):
    nrounds, n = latest.shape
    sample = status.reshape(nrounds, n) != 5
    padded = np.pad(sample, ((THRESHOLD-1, 0), (0, 0)), constant_values=False)
    recent = np.zeros_like(sample)
    for lag in range(THRESHOLD):
        recent |= padded[THRESHOLD-1-lag:THRESHOLD-1-lag+nrounds]
    t = np.arange(nrounds)[:, None]
    fresh = (latest >= 0) & (latest > t - THRESHOLD)
    assert not (fresh & ~recent).any()
    sample_last = np.full(n, -1, dtype=int)
    age = 0
    for k in range(nrounds):
        sample_last = np.where(sample[k], k, sample_last)
        age += np.where(sample_last >= 0, k-sample_last+1, k+1).sum()
    return {'coverage_pct': 100*fresh.mean(),
            'conditional_ceiling_pct': 100*recent.mean(),
            'delivery_freshness_deficit_pct': 100*(recent & ~fresh).mean(),
            'no_fresh_sample_pct': 100*(~recent).mean(),
            'source_p5_pct': np.quantile(100*fresh.mean(axis=0), .05),
            'source_p5_ceiling_pct': np.quantile(100*recent.mean(axis=0), .05),
            'conditional_aoi_floor_minutes': 15*age/(nrounds*n),
            'sample_completion_pct': 100*sample.mean()}


def exhaustive_toy():
    # For every sensing pattern in a five-round trace, enumerate every
    # physically unconstrained choice of a previously generated packet (or
    # no delivery). Updating latest by max permits out-of-order arrivals.
    patterns = trajectories = 0
    for pattern in itertools.product((0, 1), repeat=5):
        source_births = [t for t, flag in enumerate(pattern) if flag]
        options = [[-1, *[b for b in source_births if b <= t]] for t in range(5)]
        ideal_latest = []
        for t in range(5):
            available = [b for b in source_births if b <= t]
            ideal_latest.append(max(available) if available else -1)
        ideal_fresh = sum(x >= 0 and t-x+1 <= THRESHOLD for t,x in enumerate(ideal_latest))
        ideal_aoi = sum((t-x+1 if x >= 0 else t+1) for t,x in enumerate(ideal_latest))
        for deliveries in itertools.product(*options):
            recent = -1
            actual_fresh = actual_aoi = 0
            for t, birth in enumerate(deliveries):
                recent = max(recent, birth)
                actual_fresh += int(recent >= 0 and t-recent+1 <= THRESHOLD)
                actual_aoi += (t-recent+1 if recent >= 0 else t+1)
            assert actual_fresh <= ideal_fresh and actual_aoi >= ideal_aoi
            trajectories += 1
        patterns += 1
    return patterns, trajectories


def main():
    patterns, trajectories = exhaustive_toy()
    with CSV.open(encoding='utf8', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 480
    nfields = 0
    with zipfile.ZipFile(RAW) as archive:
        for row in rows:
            branch = 'new' if row['origin'] == 'new_execution' else 'reused'
            name = f"{branch}/case_{int(row['case_index']):04d}/arrays.npz"
            with np.load(io.BytesIO(archive.read(name))) as data:
                values = measures(data['latest'], data['sample_status'])
            for key, value in values.items():
                assert abs(float(row[key])-float(value)) < 1e-8, (name, key, row[key], value)
                nfields += 1
    receipt = {'status': 'PASS', 'toy_sensing_patterns': patterns,
               'toy_delivery_trajectories': trajectories, 'case_records': len(rows),
               'independent_field_checks': nfields, 'simulations_started': 0,
               'method': 'Boolean rolling freshness windows; independent single-source exhaustive schedules; independent age recursion.'}
    (HERE/'results/independent_audit.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
