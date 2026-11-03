"""Audit saved RC2 mechanism counters, preserving source hashes; no simulation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean


PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = PROJECT.parent / "算法最小复现包" / "JLC-R"
DEFAULT_RECORDS = (
    PROJECT / "temp/current_research/rc2_confirmation_lock_20261027_091500"
    / "execution_20261027_095300/runs"
)

COUNTERS = {
    "guard_ready_requests": ("trigger_guard_counts", "reference_ready_requests"),
    "guard_inactive_requests": ("trigger_guard_counts", "inactive_requests"),
    "guard_paid_upstream_responses": ("trigger_guard_counts", "paid_upstream_responses"),
    "guard_protected_member_requests": ("complete_transit_guard_counts", "protected_member_requests"),
    "guard_additional_slot_only_denials": ("complete_transit_guard_counts", "additional_slot_only_denials"),
    "recovery_attempts": ("dev_counts", "extra_attempts"),
    "recovery_successful_hops": ("dev_counts", "extra_successful_hops"),
    "recovery_denied": ("dev_counts", "extra_grant_denied"),
    "recovery_link_losses": ("dev_counts", "extra_link_loss"),
}
TOP_LEVEL = ("transit_protect_denials", "hold_created", "held_packet_actions", "held_packet_hop_successes")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_path = args.package.resolve() / "results/confirmation_480.csv"
    with run_path.open(encoding="utf-8-sig", newline="") as stream:
        table = list(csv.DictReader(stream))
    selected = [r for r in table if r["method"] == "JLC-R-RC2"]
    if len(table) != 480 or len(selected) != 96:
        raise ValueError("Expected 96 RC2 records in the 480-run summary")

    def load(row: dict) -> tuple[dict, bytes]:
        case = int(row["case_index"])
        nested = args.records / f"case_{case:04d}" / "record.json"
        flat = args.records / f"case_{case:04d}.json"
        source = nested if nested.is_file() else flat
        raw = source.read_bytes()
        if sha(raw) != row["source_record_sha256"]:
            raise ValueError(f"Original record hash mismatch: {case}")
        record = json.loads(raw)
        meta = record["case"]
        if (int(meta["index"]), meta["method"], meta["condition"], float(meta["supply"]), int(meta["seed"])) != (
            case, row["method"], row["condition"], float(row["supply"]), int(row["seed"])
        ):
            raise ValueError(f"Run identity mismatch: {case}")
        m = record["metrics"]
        if abs(float(m["coverage_pct"]) - float(row["coverage_pct"])) > 1e-9:
            raise ValueError(f"Coverage mismatch: {case}")
        result = {
            "case_index": case, "condition": row["condition"], "supply": float(row["supply"]),
            "seed": int(row["seed"]), "record_sha256": sha(raw),
        }
        for output_name, (group, key) in COUNTERS.items():
            if group not in m:
                raise ValueError(f"Missing counter group {group} in case {case}")
            result[output_name] = int(m[group].get(key, 0))
        for key in TOP_LEVEL:
            if key not in m:
                raise ValueError(f"Missing {key} in case {case}")
            result[key] = int(m[key])
        if result["guard_ready_requests"] + result["guard_inactive_requests"] != result["guard_protected_member_requests"]:
            raise ValueError(f"Guard trigger accounting mismatch: {case}")
        if result["recovery_successful_hops"] > result["recovery_attempts"]:
            raise ValueError(f"Recovery accounting mismatch: {case}")
        return result, raw

    with ThreadPoolExecutor(max_workers=12) as executor:
        loaded = list(executor.map(load, selected))
    loaded.sort(key=lambda item: item[0]["case_index"])
    case_rows = [item[0] for item in loaded]
    cells = defaultdict(list)
    for row in case_rows:
        cells[(row["condition"], row["supply"])].append(row)
    if len(cells) != 8 or any(len(rows) != 12 for rows in cells.values()):
        raise ValueError("Expected eight weather-supply conditions with twelve seeds")
    keys = (*COUNTERS.keys(), *TOP_LEVEL)
    condition_rows = [
        dict(condition=condition, supply=supply, seed_count=len(rows),
             **{key: mean(row[key] for row in rows) for key in keys})
        for (condition, supply), rows in sorted(cells.items())
    ]
    equal_means = {key: mean(row[key] for row in condition_rows) for key in keys}
    pooled = {key: sum(row[key] for row in case_rows) for key in keys}
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    original = out / "source_records"
    original.mkdir()
    for row, raw in loaded:
        (original / f"case_{row['case_index']:04d}.json").write_bytes(raw)
    write_csv(out / "mechanism_counts_by_run_96.csv", case_rows)
    write_csv(out / "mechanism_counts_by_condition_8.csv", condition_rows)
    report = {
        "scope": "Saved full-JLC-R aggregate counters only; no new simulation or causal attribution.",
        "aggregation": "Per 14-day 100-node run; equal means over 12 paired seeds and 8 weather-supply cells.",
        "source_case_count": len(case_rows),
        "confirmation_sha256": sha(run_path.read_bytes()),
        "script_sha256": sha(Path(__file__).read_bytes()),
        "equal_condition_means_per_run": equal_means,
        "pooled_counts_across_96_runs": pooled,
        "interpretation": {
            "guard_ready_requests": "Member requests at protected CHs where a reference upstream cache is ready; events, not distinct packets.",
            "guard_additional_slot_only_denials": "Member requests rejected by the triggered extra slot threshold when the original guard and energy checks passed.",
            "recovery_attempts": "Extra candidate actions attempted by the bounded recovery loop.",
            "recovery_successful_hops": "Recovery actions that succeeded at the next hop, which may or may not be the sink.",
            "held_packet_actions": "Actions involving an already held packet; not a count of priority-induced changes or saved packets.",
        },
        "unavailable_from_aggregate_records": [
            "final delivery and freshness of packets affected by individual Guard or recovery events",
            "counterfactual outcome of each denied request",
            "the number of actions changed specifically by committed-first priority",
            "per-action bottleneck CH battery, credit and Guard balances",
        ],
    }
    (out / "receipt.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
