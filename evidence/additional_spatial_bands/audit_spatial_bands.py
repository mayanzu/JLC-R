"""Recompute spatial service from saved node records; no network simulation."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

import numpy as np


PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = PROJECT.parent / "算法最小复现包" / "JLC-R"
METHODS = {"JLC-R-RC2", "EADCM-CE", "LANTERN-CE", "Base-hybrid", "Pre-recovery-JLC-R"}
WINTER = {"WINTER_G20", "T3_G20"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def positions(seed: int) -> np.ndarray:
    # ScenarioV2 uses the independent [seed, 11] topology stream.
    x, y = np.meshgrid((np.arange(10) + 0.5) / 10, (np.arange(10) + 0.5) / 10)
    points = np.column_stack((x.ravel(), y.ravel())) * 300.0
    points += np.random.default_rng(np.random.SeedSequence([seed, 11])).uniform(-8, 8, points.shape)
    return points


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    package = args.package.resolve()
    paths = {
        "nodes": package / "results/node_records_48000.csv.gz",
        "runs": package / "results/confirmation_480.csv",
        "configs": package / "configs/effective_configs.json",
        "topology": package / "code/simulation/diagnostic.py",
        "cells": package / "code/simulation/simulator.py",
    }
    cfg = json.loads(paths["configs"].read_text(encoding="utf-8"))
    config_shapes = {
        (v["nodes"], float(v["area_m"]), float(v["range_m"]), v["cluster_cols"], v["cluster_rows"])
        for v in cfg.values()
    }
    if config_shapes != {(100, 300.0, 120.0, 4, 3)}:
        raise ValueError(f"Unexpected source geometry: {config_shapes}")

    with paths["runs"].open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    runs = {int(row["case_index"]): row for row in rows}
    if len(rows) != 480 or len(runs) != 480:
        raise ValueError("Expected 480 distinct run summaries")
    nodes = defaultdict(dict)
    with gzip.open(paths["nodes"], "rt", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            case, node = int(row["case_index"]), int(row["node"])
            if case not in runs or node in nodes[case]:
                raise ValueError(f"Unknown case or duplicate node: {case}/{node}")
            run = runs[case]
            if any(row[key] != run[key] for key in ("method", "condition", "supply", "seed")):
                raise ValueError(f"Identity mismatch: {case}/{node}")
            value = float(row["coverage_pct"])
            if not np.isfinite(value) or not 0 <= value <= 100:
                raise ValueError(f"Invalid source coverage: {case}/{node}")
            nodes[case][node] = value
    if len(nodes) != 480 or sum(map(len, nodes.values())) != 48000:
        raise ValueError("Expected 48,000 distinct source records")

    masks = {}
    case_rows, cell_rows = [], []
    discrepancies = {"network_mean": 0.0, "source_p5": 0.0, "zero_count": 0}
    for case_id, run in sorted(runs.items()):
        method, seed = run["method"], int(run["seed"])
        if method not in METHODS or set(nodes[case_id]) != set(range(100)):
            raise ValueError(f"Unexpected method or incomplete case: {case_id}")
        if seed not in masks:
            p = positions(seed)
            distance = np.linalg.norm(p - np.array([0.0, 150.0]), axis=1)
            col = np.floor(p[:, 0] / 300 * 4).clip(0, 3).astype(int)
            row = np.floor(p[:, 1] / 300 * 3).clip(0, 2).astype(int)
            cell = row * 4 + col
            masks[seed] = {
                "near": distance <= 120, "mid": (distance > 120) & (distance < 200),
                "far": distance >= 200, "cell": cell,
            }
            if any(not masks[seed][key].any() for key in ("near", "mid", "far")):
                raise ValueError(f"Empty distance band: {seed}")
            if set(cell) != set(range(12)):
                raise ValueError(f"Empty geographic cell: {seed}")
        m = masks[seed]
        values = np.array([nodes[case_id][i] for i in range(100)])
        discrepancies["network_mean"] = max(
            discrepancies["network_mean"], abs(float(values.mean()) - float(run["coverage_pct"]))
        )
        discrepancies["source_p5"] = max(
            discrepancies["source_p5"], abs(float(np.quantile(values, 0.05)) - float(run["source_coverage_p5_pct"]))
        )
        zero_count = int(np.count_nonzero(values == 0))
        discrepancies["zero_count"] = max(discrepancies["zero_count"], abs(zero_count - int(run["zero_coverage_sources"])))
        coverage_by_cell = [float(values[m["cell"] == cell].mean()) for cell in range(12)]
        item = {
            "case_index": case_id, "method": method, "condition": run["condition"],
            "supply": float(run["supply"]), "seed": seed,
            "near_nodes": int(m["near"].sum()), "near_pct": float(values[m["near"]].mean()),
            "mid_nodes": int(m["mid"].sum()), "mid_pct": float(values[m["mid"]].mean()),
            "far_nodes": int(m["far"].sum()), "far_pct": float(values[m["far"]].mean()),
            "worst_cell_pct": min(coverage_by_cell), "source_p5_pct": float(np.quantile(values, 0.05)),
            "zero_coverage_pct": float(zero_count),
        }
        case_rows.append(item)
        for cell in range(12):
            cell_rows.append({
                "case_index": case_id, "method": method, "condition": run["condition"],
                "supply": float(run["supply"]), "seed": seed, "cell": cell,
                "cell_nodes": int((m["cell"] == cell).sum()), "cell_coverage_pct": coverage_by_cell[cell],
            })
    if len(masks) != 12 or max(discrepancies.values()) > 1e-9:
        raise ValueError(f"Stored summaries disagree with reconstructed values: {discrepancies}")

    groups = defaultdict(list)
    for row in case_rows:
        groups[(row["method"], row["condition"], row["supply"])].append(row)
    if len(groups) != 40 or any(len(v) != 12 for v in groups.values()):
        raise ValueError("Expected five methods, eight cells, and twelve seeds per cell")
    fields = ("near_pct", "mid_pct", "far_pct", "worst_cell_pct", "source_p5_pct", "zero_coverage_pct")
    condition_rows = [
        dict(method=method, condition=condition, supply=supply, seed_count=len(records),
             **{field: mean(r[field] for r in records) for field in fields})
        for (method, condition, supply), records in sorted(groups.items())
    ]
    winter_rows = []
    for method in sorted(METHODS):
        selected = [r for r in condition_rows if r["method"] == method and r["condition"] in WINTER]
        if len(selected) != 4:
            raise ValueError("Four winter weather-supply cells are required")
        winter_rows.append(dict(method=method, weather_supply_cells=4, seeds_per_cell=12,
                                **{field: mean(r[field] for r in selected) for field in fields}))

    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    write_csv(out / "spatial_by_run_480.csv", case_rows)
    write_csv(out / "spatial_by_geographic_cell_5760.csv", cell_rows)
    write_csv(out / "spatial_by_condition_40.csv", condition_rows)
    write_csv(out / "spatial_winter_means_5.csv", winter_rows)
    receipt = {
        "scope": "Post hoc descriptive summaries from saved node coverage; no simulation or hypothesis test.",
        "distance_bands_m": {"near": "d <= 120", "mid": "120 < d < 200", "far": "d >= 200"},
        "geographic_cells": "4 x 3 grid assigned by the same clipped position rule as the simulator",
        "worst_cell": "Minimum of 12 geographic-cell mean source coverages, within each run.",
        "source_p5": "Linear 5th percentile across the 100 sources in each run.",
        "zero_coverage": "100 times the number of sources with zero fresh coverage divided by 100 sources.",
        "winter_aggregation": "Per-run outcomes; equal means over 12 seeds and the four winter weather-supply cells.",
        "case_count": len(case_rows), "source_records": sum(map(len, nodes.values())),
        "geographic_cell_records": len(cell_rows), "network_seeds": len(masks),
        "maximum_discrepancies": discrepancies, "winter_means": winter_rows,
        "source_sha256": {name: sha256(path) for name, path in paths.items()},
        "script_sha256": sha256(Path(__file__)),
        "limitations": "Spatial source summaries do not identify routes, loss locations, or causal mechanisms.",
    }
    (out / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
