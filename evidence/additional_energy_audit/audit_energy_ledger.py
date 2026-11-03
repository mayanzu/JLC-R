"""Reconcile the saved 480-run node ledgers; never runs a simulation."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean


PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = PROJECT
DEFAULT_OUTPUT = PROJECT.parent / "energy_ledger_audit"
METHODS = {
    "JLC-R-RC2",
    "EADCM-CE",
    "LANTERN-CE",
    "Base-hybrid",
    "Pre-recovery-JLC-R",
}
FIELDS = ("initial", "harvest", "spill", "base", "data", "control", "final")


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    node_path = args.package / "results" / "node_records_48000.csv.gz"
    summary_path = args.package / "results" / "confirmation_480.csv"
    cases = {}
    paired_node_harvest = defaultdict(dict)
    max_node_residual = 0.0
    count = 0

    with gzip.open(node_path, "rt", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            count += 1
            case_id = int(row["case_index"])
            identity = (row["method"], row["condition"], row["supply"], row["seed"])
            record = cases.setdefault(
                case_id,
                {"identity": identity, "nodes": set(), **{field: 0.0 for field in FIELDS}},
            )
            if record["identity"] != identity or row["node"] in record["nodes"]:
                raise ValueError(f"Inconsistent case or duplicate node: {case_id}")
            record["nodes"].add(row["node"])
            values = {field: float(row[field + "_j"]) for field in FIELDS}
            for field in FIELDS:
                record[field] += values[field]
            residual = (
                values["initial"] + values["harvest"] - values["spill"]
                - values["base"] - values["data"] - values["control"] - values["final"]
            )
            max_node_residual = max(max_node_residual, abs(residual))
            node_key = (row["condition"], row["supply"], row["seed"], row["node"])
            if row["method"] in paired_node_harvest[node_key]:
                raise ValueError(f"Duplicate paired node: {node_key}")
            paired_node_harvest[node_key][row["method"]] = values["harvest"]

    if count != 48000 or len(cases) != 480:
        raise ValueError(f"Unexpected ledger size: {count} rows, {len(cases)} cases")
    if any(len(case["nodes"]) != 100 for case in cases.values()):
        raise ValueError("Each run must contain 100 distinct nodes")

    with summary_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    summaries = {int(row["case_index"]): row for row in rows}
    if len(rows) != 480 or len(summaries) != 480 or set(summaries) != set(cases):
        raise ValueError("Summary records do not match the node ledgers")

    paired_runs = defaultdict(dict)
    max_summary_difference = 0.0
    max_case_residual = 0.0
    for case_id, case in cases.items():
        row = summaries[case_id]
        identity = tuple(row[field] for field in ("method", "condition", "supply", "seed"))
        if identity != case["identity"] or identity[0] not in METHODS:
            raise ValueError(f"Summary identity mismatch: {case_id}")
        case["consumption"] = sum(case[field] for field in ("base", "data", "control"))
        max_summary_difference = max(
            max_summary_difference, abs(case["consumption"] - float(row["actual_energy_j"]))
        )
        residual = (
            case["initial"] + case["harvest"] - case["spill"]
            - case["consumption"] - case["final"]
        )
        max_case_residual = max(max_case_residual, abs(residual))
        key = identity[1:]
        if identity[0] in paired_runs[key]:
            raise ValueError(f"Duplicate paired run: {key}")
        paired_runs[key][identity[0]] = case

    if len(paired_runs) != 96 or any(set(group) != METHODS for group in paired_runs.values()):
        raise ValueError("Expected 96 complete five-method matched blocks")
    cell_seeds = defaultdict(set)
    for condition, supply, seed in paired_runs:
        cell_seeds[(condition, supply)].add(seed)
    if len(cell_seeds) != 8 or any(len(seeds) != 12 for seeds in cell_seeds.values()):
        raise ValueError("Expected eight condition/supply cells with twelve seeds each")
    if len({frozenset(seeds) for seeds in cell_seeds.values()}) != 1:
        raise ValueError("The same twelve network seeds must appear in every cell")
    if any(set(group) != METHODS for group in paired_node_harvest.values()):
        raise ValueError("Missing matched node harvest record")
    max_harvest_difference = max(
        max(group.values()) - min(group.values()) for group in paired_node_harvest.values()
    )
    if max(max_node_residual, max_case_residual, max_summary_difference, max_harvest_difference) > 1e-7:
        raise ValueError("Energy balance, matched harvest, or published total failed validation")

    averages = {}
    for method in sorted(METHODS):
        selected = [case for case in cases.values() if case["identity"][0] == method]
        if len(selected) != 96:
            raise ValueError(f"Unexpected number of cases for {method}")
        averages[method] = {
            field: mean(case[field] for case in selected)
            for field in (*FIELDS, "consumption")
        }

    expected_table = {
        "JLC-R-RC2": 1617.25,
        "EADCM-CE": 1504.36,
        "LANTERN-CE": 2145.06,
        "Base-hybrid": 1690.20,
        "Pre-recovery-JLC-R": 1690.31,
    }
    if any(round(averages[m]["consumption"], 2) != value for m, value in expected_table.items()):
        raise ValueError("Mean expenditure does not reproduce the manuscript energy summary")

    lantern = averages["LANTERN-CE"]
    differences = {}
    for comparator in ("JLC-R-RC2", "EADCM-CE"):
        other = averages[comparator]
        differences[comparator] = {
            "higher_lantern_consumption_j": lantern["consumption"] - other["consumption"],
            "less_lantern_spill_j": other["spill"] - lantern["spill"],
            "less_lantern_final_j": other["final"] - lantern["final"],
        }
        result = differences[comparator]
        if abs(result["higher_lantern_consumption_j"]
               - result["less_lantern_spill_j"] - result["less_lantern_final_j"]) > 1e-7:
            raise ValueError("Paired energy difference does not balance")

    output = args.output_dir or DEFAULT_OUTPUT / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "description": "Equal-weight means across eight condition/supply cells and twelve paired seeds.",
        "node_rows": count,
        "runs": len(cases),
        "paired_blocks": len(paired_runs),
        "input_sha256": {str(node_path): digest(node_path), str(summary_path): digest(summary_path)},
        "maximum_absolute_node_balance_error_j": max_node_residual,
        "maximum_absolute_run_balance_error_j": max_case_residual,
        "maximum_run_consumption_vs_summary_difference_j": max_summary_difference,
        "maximum_paired_node_harvest_difference_j": max_harvest_difference,
        "means_j": averages,
        "lantern_minus_comparator_decomposition_j": differences,
    }
    (output / "energy_ledger_summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    columns = ["case_index", "method", "condition", "supply", "seed",
               *[field + "_j" for field in FIELDS], "consumption_j", "balance_error_j"]
    with (output / "energy_ledger_by_run.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for case_id, case in sorted(cases.items()):
            method, condition, supply, seed = case["identity"]
            row = dict(case_index=case_id, method=method, condition=condition, supply=supply, seed=seed)
            row.update({field + "_j": case[field] for field in FIELDS})
            row["consumption_j"] = case["consumption"]
            row["balance_error_j"] = (
                case["initial"] + case["harvest"] - case["spill"]
                - case["consumption"] - case["final"]
            )
            writer.writerow(row)
    print(json.dumps({"output": str(output), **report}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
