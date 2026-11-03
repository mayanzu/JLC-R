"""Pair Stage C outcomes against Stage B compact evidence; write summary tables."""
from __future__ import annotations
import csv, json, math
from pathlib import Path
import numpy as np
from scipy import stats

HERE = Path(__file__).resolve().parent
STAGE_B = HERE.parent / 'stageB_20261030'
METRICS = ['coverage_pct', 'source_coverage_p5_pct', 'demand_delivery_pct',
           'sample_completion_pct', 'consumed_j']
LABEL = {'coverage_pct': 'Coverage', 'source_coverage_p5_pct': 'Source P5',
         'demand_delivery_pct': 'Delivery', 'sample_completion_pct': 'Sampling',
         'consumed_j': 'Energy (J)'}

def load_stage_b():
    rows = {}
    with (STAGE_B / 'compact_evidence_complete' / 'run_metrics.csv').open(encoding='utf8', newline='') as f:
        for r in csv.DictReader(f):
            # Canonical 24-seed arms only: overhead/q8/new-weather variants
            # duplicate (seed,cell,method) keys under altered costs and must not
            # overwrite the confirmation rows.
            if r['study'] not in ('confirmation', 'extra_confirmation'):
                continue
            key = (int(r['seed']), r['condition'], float(r['supply']), r['method'])
            rows[key] = {m: float(r[m]) for m in METRICS}
    return rows

def load_stage_c(group):
    rows = {}
    out = HERE / f'confirmation_{group}'
    for rec in sorted(out.glob('case_*/record.json')):
        d = json.loads(rec.read_text(encoding='utf8'))
        c, m = d['case'], d['metrics']
        key = (int(c['seed']), c['condition'], float(c['supply']),
               c['method'], int(c.get('deadline_rounds', 4)))
        rows[key] = {'metrics': {k: float(m[k]) for k in METRICS},
                     'planner_seconds_per_call': m.get('planner_seconds_per_call'),
                     'planner_seconds_total': m.get('planner_seconds_total'),
                     'joint_floor_violations': m.get('joint_floor_violations', 0),
                     'max_floor_shortfall_j': m.get('max_floor_shortfall_j', 0.),
                     'fdc_floor_assertions': m.get('fdc_floor_assertions', 0)}
    return rows

def paired_summary(deltas_by_seed_cell, cells, seeds):
    """deltas: {(seed,cell): {metric: delta}} -> overall seed-level t interval + per-cell means."""
    out = {}
    for metric in METRICS:
        cell_means = {f'{c}|{s}': float(np.mean([deltas_by_seed_cell[(seed, (c, s))][metric]
                                                 for seed in seeds]))
                      for c, s in cells}
        seed_level = [np.mean([deltas_by_seed_cell[(seed, (c, s))][metric]
                               for c, s in cells]) for seed in seeds]
        arr = np.asarray(seed_level)
        half = float(stats.t.ppf(.975, len(arr) - 1) * arr.std(ddof=1) / math.sqrt(len(arr)))
        out[metric] = {'equal_condition_mean_delta': float(arr.mean()),
                       'nominal_95ci': [float(arr.mean() - half), float(arr.mean() + half)],
                       'per_cell_mean_delta': cell_means}
    return out

def main():
    b = load_stage_b()
    e1 = load_stage_c('e1')
    e3 = load_stage_c('e3')
    protocol = json.loads((HERE / 'protocol_predefined.json').read_text(encoding='utf8'))
    seeds = [int(s) for s in protocol['seeds']]
    cells = [(c['name'], s) for c in protocol['conditions'] for s in protocol['supplies']]
    summary = {'protocol_sha256': None, 'reproduction': {}, 'e1': {}, 'e3': {},
               'timing': {}, 'floor_counters': {}}

    # 1. reproduction: stage C JLC-R arm vs stage B JLC-R rows
    repro = {}
    for metric in METRICS:
        diffs = [abs(e1[(seed, c, s, 'JLC-R', 4)]['metrics'][metric] - b[(seed, c, s, 'JLC-R')][metric])
                 for seed in seeds for c, s in cells]
        repro[metric] = max(diffs)
    summary['reproduction'] = {'max_abs_diff_vs_stageB': repro,
                               'exact': all(v == 0. for v in repro.values())}

    # 2. E1 paired deltas vs the stage C JLC-R replication arm (same study),
    #    with stage B controls as secondary context
    def deltas_vs(method, reference):
        out = {}
        for seed in seeds:
            for cell in cells:
                if reference == 'JLC-R':
                    ref = e1[(seed, cell[0], cell[1], 'JLC-R', 4)]['metrics']
                else:
                    ref = b[(seed, cell[0], cell[1], reference)]
                out[(seed, cell)] = {m: e1[(seed, cell[0], cell[1], method, 4)]['metrics'][m]
                                     - ref[m] for m in METRICS}
        return out
    for method in ('SIMPLE-MATCHED-PLANNER', 'POINT-PLANNER'):
        summary['e1'][method] = {
            'vs_JLC-R': paired_summary(deltas_vs(method, 'JLC-R'), cells, seeds),
            'vs_NO-JOINT-PADC': paired_summary(deltas_vs(method, 'NO-JOINT-PADC'), cells, seeds),
            'equal_condition_means': {m: float(np.mean([
                np.mean([e1[(seed, c, s, method, 4)]['metrics'][m] for seed in seeds])
                for c, s in cells])) for m in METRICS}}
    summary['e1']['JLC-R_equal_condition_means'] = {m: float(np.mean([
        np.mean([b[(seed, c, s, 'JLC-R')][m] for seed in seeds]) for c, s in cells]))
        for m in METRICS}
    for ref in ('NO-JOINT-PADC', 'CADENCE-ONLY', 'SIMPLE-PADC-CADENCE'):
        summary['e1'][f'{ref}_equal_condition_means'] = {m: float(np.mean([
            np.mean([b[(seed, c, s, ref)][m] for seed in seeds]) for c, s in cells]))
            for m in METRICS}

    # 3. timing and floor counters (14-day runs only)
    for method in ('JLC-R', 'SIMPLE-MATCHED-PLANNER', 'POINT-PLANNER'):
        rows = [e1[(seed, c, s, method, 4)] for seed in seeds for c, s in cells]
        summary['timing'][method] = {
            'mean_planner_seconds_per_call': float(np.mean([r['planner_seconds_per_call'] for r in rows])),
            'mean_planner_seconds_per_run': float(np.mean([r['planner_seconds_total'] for r in rows]))}
        summary['floor_counters'][method] = {
            'sum_joint_floor_violations': int(sum(r['joint_floor_violations'] for r in rows)),
            'max_floor_shortfall_j': float(max(r['max_floor_shortfall_j'] for r in rows)),
            'sum_fdc_floor_assertions': int(sum(r['fdc_floor_assertions'] for r in rows))}

    # 4. E3 freshness-window sensitivity (supply 1.0, four weathers)
    weathers = protocol['e3']['weather_cells']
    grid = {}
    for deadline in (2, 4, 8):
        for method in ('JLC-R', 'SIMPLE-MATCHED-PLANNER'):
            for weather in weathers:
                if deadline == 4:
                    # D=4: JLC-R from stage B; SMP from stage C e1
                    if method == 'JLC-R':
                        rec = {m: [b[(seed, weather, 1.0, 'JLC-R')][m] for seed in seeds] for m in METRICS}
                    else:
                        rec = {m: [e1[(seed, weather, 1.0, 'SIMPLE-MATCHED-PLANNER', 4)]['metrics'][m]
                                   for seed in seeds] for m in METRICS}
                else:
                    rec = {m: [e3[(seed, weather, 1.0, method, deadline)]['metrics'][m]
                               for seed in seeds] for m in METRICS}
                grid[f'D{deadline}|{method}|{weather}'] = {
                    m: {'mean': float(np.mean(v)), 'sd': float(np.std(v, ddof=1))} for m, v in rec.items()}
    summary['e3'] = {'grid': grid, 'weathers': weathers, 'supply': 1.0}
    # increment table: JLC-R minus SMP at each D per weather
    inc = {}
    for deadline in (2, 4, 8):
        for weather in weathers:
            j = grid[f'D{deadline}|JLC-R|{weather}']
            s = grid[f'D{deadline}|SIMPLE-MATCHED-PLANNER|{weather}']
            inc[f'D{deadline}|{weather}'] = {m: j[m]['mean'] - s[m]['mean']
                                             for m in ('coverage_pct', 'source_coverage_p5_pct')}
    summary['e3']['jlcr_minus_smp'] = inc

    out = HERE / 'analysis_complete'
    out.mkdir(exist_ok=True)
    (out / 'stage_c_summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf8')
    (out / 'stage_c_tables.md').write_text(render_tables(summary, seeds), encoding='utf8')
    print(json.dumps({'reproduction_exact': summary['reproduction']['exact'],
                      'repro_max_diff': summary['reproduction']['max_abs_diff_vs_stageB'],
                      'smp_vs_jlcr': summary['e1']['SIMPLE-MATCHED-PLANNER']['vs_JLC-R']['coverage_pct'],
                      'pp_vs_jlcr': summary['e1']['POINT-PLANNER']['vs_JLC-R']['coverage_pct']}, indent=2))

def render_tables(s, seeds):
    L = []
    L.append('# Stage C result tables (descriptive; nominal intervals)\n')
    r = s['reproduction']
    L.append(f"## Reproduction check (stage C JLC-R vs stage B JLC-R)\n\nexact={r['exact']}; max abs diff per metric: "
             + ', '.join(f"{k}={v:.3g}" for k, v in r['max_abs_diff_vs_stageB'].items()) + '\n')
    L.append('\n## E1 equal-condition means (8 cells x 24 seeds)\n')
    header = '| Method | ' + ' | '.join(LABEL[m] for m in METRICS) + ' |\n'
    L.append(header)
    L.append('|---|' + '---|' * len(METRICS) + '\n')
    for name, key in [('JLC-R', ('top', 'JLC-R_equal_condition_means')),
                      ('Simple matched planner (SMP)', ('arm', 'SIMPLE-MATCHED-PLANNER')),
                      ('Point planner (PP)', ('arm', 'POINT-PLANNER')),
                      ('No-joint PADC', ('top', 'NO-JOINT-PADC_equal_condition_means')),
                      ('Cadence-only', ('top', 'CADENCE-ONLY_equal_condition_means')),
                      ('Simple PADC-cadence', ('top', 'SIMPLE-PADC-CADENCE_equal_condition_means'))]:
        if key[0] == 'top':
            row = s['e1'][key[1]]
        else:
            row = s['e1'][key[1]]['equal_condition_means']
        L.append(f"| {name} | " + ' | '.join(f"{row[m]:.2f}" for m in METRICS) + ' |\n')
    L.append('\n## E1 paired deltas vs JLC-R (equal-condition mean of seed-level deltas, nominal 95% CI)\n')
    L.append('| Arm | ' + ' | '.join(LABEL[m] for m in METRICS) + ' |\n')
    L.append('|---|' + '---|' * len(METRICS) + '\n')
    for method in ('SIMPLE-MATCHED-PLANNER', 'POINT-PLANNER'):
        d = s['e1'][method]['vs_JLC-R']
        cells_ = []
        for m in METRICS:
            x = d[m]
            cells_.append(f"{x['equal_condition_mean_delta']:+.2f} [{x['nominal_95ci'][0]:+.2f},{x['nominal_95ci'][1]:+.2f}]")
        L.append(f"| {method} − JLC-R | " + ' | '.join(cells_) + ' |\n')
    for method in ('SIMPLE-MATCHED-PLANNER', 'POINT-PLANNER'):
        d = s['e1'][method]['vs_NO-JOINT-PADC']
        cells_ = [f"{d[m]['equal_condition_mean_delta']:+.2f}" for m in METRICS]
        L.append(f"| {method} − No-joint PADC | " + ' | '.join(cells_) + ' |\n')
    L.append('\n### Per-cell coverage / Source P5 deltas (SMP − JLC-R)\n')
    L.append('| Cell | ΔCoverage | ΔSource P5 |\n|---|---|---|\n')
    d = s['e1']['SIMPLE-MATCHED-PLANNER']['vs_JLC-R']
    for cell, v in d['coverage_pct']['per_cell_mean_delta'].items():
        L.append(f"| {cell} | {v:+.2f} | {d['source_coverage_p5_pct']['per_cell_mean_delta'][cell]:+.2f} |\n")
    L.append('\n## Planner cost and floor counters\n')
    L.append('| Arm | s/call | s/run | Σfloor violations | max shortfall (J) | ΣFDC asserts |\n|---|---|---|---|---|---|\n')
    for method in ('JLC-R', 'SIMPLE-MATCHED-PLANNER', 'POINT-PLANNER'):
        t, fc = s['timing'][method], s['floor_counters'][method]
        L.append(f"| {method} | {t['mean_planner_seconds_per_call']:.4f} | {t['mean_planner_seconds_per_run']:.1f} "
                 f"| {fc['sum_joint_floor_violations']} | {fc['max_floor_shortfall_j']:.3g} "
                 f"| {fc['sum_fdc_floor_assertions']} |\n")
    L.append('\n## E3 freshness-window sensitivity (supply 1.0, 24 seeds, mean [sd])\n')
    L.append('| D | Method | ' + ' | '.join(f'{w} Cov / P5' for w in s['e3']['weathers']) + ' |\n')
    L.append('|---|---|' + '---|' * len(s['e3']['weathers']) + '\n')
    g = s['e3']['grid']
    for deadline in (2, 4, 8):
        for method in ('JLC-R', 'SIMPLE-MATCHED-PLANNER'):
            row = [f"{g[f'D{deadline}|{method}|{w}']['coverage_pct']['mean']:.2f} / "
                   f"{g[f'D{deadline}|{method}|{w}']['source_coverage_p5_pct']['mean']:.2f}"
                   for w in s['e3']['weathers']]
            L.append(f"| {deadline} | {method} | " + ' | '.join(row) + ' |\n')
    L.append('\n### JLC-R − SMP increment by D (coverage / Source P5)\n')
    L.append('| Cell | D=2 | D=4 | D=8 |\n|---|---|---|---|\n')
    inc = s['e3']['jlcr_minus_smp']
    for w in s['e3']['weathers']:
        row = [f"{inc[f'D{d}|{w}']['coverage_pct']:+.2f} / {inc[f'D{d}|{w}']['source_coverage_p5_pct']:+.2f}"
               for d in (2, 4, 8)]
        L.append(f"| {w} | " + ' | '.join(row) + ' |\n')
    return ''.join(L)

if __name__ == '__main__':
    main()
