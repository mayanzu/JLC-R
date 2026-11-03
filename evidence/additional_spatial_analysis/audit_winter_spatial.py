"""Describe near/far winter coverage from saved records; no simulation or tests."""

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
METHODS = ("EADCM-CE", "JLC-R-RC2")
WINTER_CELLS = {
    ("WINTER_G20", 0.7), ("WINTER_G20", 1.0), ("T3_G20", 0.7), ("T3_G20", 1.0)
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def geometry(seed: int) -> np.ndarray:
    # Match ScenarioV2's independent topology stream and sink location.
    x, y = np.meshgrid((np.arange(10) + 0.5) / 10, (np.arange(10) + 0.5) / 10)
    points = np.column_stack((x.ravel(), y.ravel())) * 300.0
    points += np.random.default_rng(np.random.SeedSequence([seed, 11])).uniform(-8, 8, points.shape)
    return np.linalg.norm(points - np.array([0.0, 150.0]), axis=1)


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package = args.package.resolve()
    node_path = package / "results/node_records_48000.csv.gz"
    summary_path = package / "results/confirmation_480.csv"
    config_path = package / "configs/effective_configs.json"
    source_path = package / "code/simulation/diagnostic.py"
    configs = json.loads(config_path.read_text(encoding="utf-8"))
    if {(item["nodes"], float(item["area_m"]), float(item["range_m"]))
            for item in configs.values()} != {(100, 300.0, 120.0)}:
        raise ValueError("Static-geometry configuration does not match this audit")

    cases = {}
    seeds_geometry = {}
    with gzip.open(node_path, "rt", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            method, condition = row["method"], row["condition"]
            supply, seed, node = float(row["supply"]), int(row["seed"]), int(row["node"])
            if method not in METHODS or (condition, supply) not in WINTER_CELLS:
                continue
            case_id = int(row["case_index"])
            identity = (method, condition, supply, seed)
            case = cases.setdefault(case_id, {"identity": identity, "nodes": {}, "near": [], "far": []})
            if case["identity"] != identity or node in case["nodes"] or not 0 <= node < 100:
                raise ValueError(f"Case identity or node duplication: {case_id}/{node}")
            value = float(row["coverage_pct"])
            if not np.isfinite(value) or not 0 <= value <= 100:
                raise ValueError(f"Invalid coverage: {case_id}/{node}")
            case["nodes"][node] = value
            if seed not in seeds_geometry:
                seeds_geometry[seed] = geometry(seed)
            distance = seeds_geometry[seed][node]
            if distance <= 120.0:
                case["near"].append(value)
            elif distance >= 200.0:
                case["far"].append(value)
    if len(cases) != 96 or len(seeds_geometry) != 12:
        raise ValueError("Expected 2 methods x 4 winter cells x 12 seeds")

    with summary_path.open(encoding="utf-8-sig", newline="") as stream:
        summaries = {int(row["case_index"]): row for row in csv.DictReader(stream)}
    case_rows, by_cell, pair_blocks = [], defaultdict(list), defaultdict(set)
    max_coverage_discrepancy = 0.0
    for case_id, case in sorted(cases.items()):
        method, condition, supply, seed = case["identity"]
        row = summaries[case_id]
        if (row["method"], row["condition"], float(row["supply"]), int(row["seed"])) != case["identity"]:
            raise ValueError(f"Saved summary identity mismatch: {case_id}")
        if set(case["nodes"]) != set(range(100)) or not case["near"] or not case["far"]:
            raise ValueError(f"Incomplete node records or empty band: {case_id}")
        max_coverage_discrepancy = max(
            max_coverage_discrepancy, abs(mean(case["nodes"].values()) - float(row["coverage_pct"]))
        )
        item = {
            "case_index": case_id, "method": method, "condition": condition, "supply": supply,
            "seed": seed, "near_nodes": len(case["near"]), "near_coverage_pct": mean(case["near"]),
            "far_nodes": len(case["far"]), "far_coverage_pct": mean(case["far"]),
            "source_p5_pct": float(row["source_coverage_p5_pct"]),
            "zero_coverage_sources": int(row["zero_coverage_sources"]),
        }
        case_rows.append(item)
        by_cell[(method, condition, supply)].append(item)
        pair_blocks[(condition, supply, seed)].add(method)
    if max_coverage_discrepancy > 1e-9 or len(pair_blocks) != 48:
        raise ValueError("Whole-network coverages or matched blocks disagree")
    if any(methods != set(METHODS) for methods in pair_blocks.values()):
        raise ValueError("A winter seed-condition block is missing a method")
    if any(len(rows) != 12 for rows in by_cell.values()) or len(by_cell) != 8:
        raise ValueError("Each method and winter cell must have twelve seed records")

    cell_rows = []
    for (method, condition, supply), rows in sorted(by_cell.items()):
        cell_rows.append({
            "method": method, "condition": condition, "supply": supply, "seed_count": len(rows),
            "near_coverage_pct": mean(row["near_coverage_pct"] for row in rows),
            "far_coverage_pct": mean(row["far_coverage_pct"] for row in rows),
            "source_p5_pct": mean(row["source_p5_pct"] for row in rows),
            "zero_p5_runs": sum(row["source_p5_pct"] == 0 for row in rows),
            "zero_coverage_sources_total": sum(row["zero_coverage_sources"] for row in rows),
        })
    winter = {}
    for method in METHODS:
        cells = [row for row in cell_rows if row["method"] == method]
        winter[method] = {
            "near_coverage_pct": mean(row["near_coverage_pct"] for row in cells),
            "far_coverage_pct": mean(row["far_coverage_pct"] for row in cells),
            "source_p5_pct": mean(row["source_p5_pct"] for row in cells),
            "zero_p5_runs": sum(row["zero_p5_runs"] for row in cells),
            "zero_coverage_sources_total": sum(row["zero_coverage_sources_total"] for row in cells),
        }
    report = {
        "scope": "Post hoc descriptive summaries of saved records, with no simulation or hypothesis test.",
        "near_definition": "distance to sink <= 120 m (within nominal communication range)",
        "far_definition": "distance to sink >= 200 m",
        "aggregation": "Within-run mean across nodes in each band, then equally over 12 seeds and 4 winter cells.",
        "limitations": "Distances do not establish actual chosen routes or locate packet losses.",
        "source_sha256": {p.name: sha256(p) for p in (node_path, summary_path, config_path, source_path)},
        "script_sha256": sha256(Path(__file__)),
        "case_count": len(cases), "paired_blocks": len(pair_blocks),
        "maximum_coverage_discrepancy_pp": max_coverage_discrepancy,
        "winter_mean": winter,
    }
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    write_csv(out / "spatial_winter_by_run.csv", case_rows, list(case_rows[0]))
    write_csv(out / "spatial_winter_by_cell.csv", cell_rows, list(cell_rows[0]))
    (out / "spatial_winter_receipt.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
