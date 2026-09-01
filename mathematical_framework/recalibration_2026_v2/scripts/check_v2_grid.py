#!/usr/bin/env python3
"""Fail-closed completeness and safety check for the full V2 delta grid."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from recalib_common import (
    delta_trajectory_specs,
    load_json,
    load_yaml,
    verify_input_lock,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--input-lock", required=True)
    parser.add_argument("--grid-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    protocol_path = Path(args.protocol).resolve()
    input_lock_path = Path(args.input_lock).resolve()
    verify_input_lock(input_lock_path, protocol_path)
    protocol = load_yaml(protocol_path)
    root = Path(args.grid_root).resolve()
    expected_eval = int(protocol["delta_calibration"]["partition"]["evaluation_n"])
    expected_runs = (
        len(delta_trajectory_specs(protocol))
        * len(protocol["delta_calibration"]["delta_grid"])
    )

    harm_csvs = sorted(root.glob("trajectory_*/delta_*/delta_harm_events.csv"))
    harm_summaries = sorted(root.glob(
        "trajectory_*/delta_*/delta_harm_events.summary.json"
    ))
    experiment_summaries = sorted(root.glob("trajectory_*/delta_*/summary.json"))
    partition_maps = sorted(root.glob("trajectory_*/delta_*/partition_map.json"))
    errors = []
    counts = {
        "expected_runs": expected_runs,
        "harm_csv": len(harm_csvs),
        "harm_summary": len(harm_summaries),
        "experiment_summary": len(experiment_summaries),
        "partition_map": len(partition_maps),
    }
    for key in ("harm_csv", "harm_summary", "experiment_summary", "partition_map"):
        if counts[key] != expected_runs:
            errors.append(f"{key}: {counts[key]} != {expected_runs}")

    bad_eval_summaries = []
    missing_dbox = []
    for path in harm_summaries:
        summary = load_json(path)
        if int(summary.get("evaluation_n_per_block", -1)) != expected_eval:
            bad_eval_summaries.append(str(path))
        if not bool(summary.get("dbox_available")):
            missing_dbox.append(str(path))
    if bad_eval_summaries:
        errors.append(f"non-{expected_eval} evaluation summaries: {len(bad_eval_summaries)}")
    if missing_dbox:
        errors.append(f"d_box unavailable: {len(missing_dbox)}")

    bad_partitions = []
    expected_counts = (
        int(protocol["delta_calibration"]["partition"]["proposal_n"]),
        int(protocol["delta_calibration"]["partition"]["gate_n"]),
        expected_eval,
    )
    for path in partition_maps:
        partition = load_json(path)
        for block in partition["blocks"]:
            actual = (
                len(block["proposal_ids"]),
                len(block["gate_ids"]),
                len(block["evaluation_ids"]),
            )
            if actual != expected_counts:
                bad_partitions.append({"path": str(path), "actual": actual})
                break
    if bad_partitions:
        errors.append(f"invalid asymmetric partitions: {len(bad_partitions)}")

    gate_violations = 0
    empty_dbox_rows = 0
    for path in harm_csvs:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                gate_violations += int(row["committed_gate_violation"])
                empty_dbox_rows += int(row["dbox_after"] == "")
    if gate_violations:
        errors.append(f"committed gate violations: {gate_violations}")
    if empty_dbox_rows:
        errors.append(f"rows missing d_box: {empty_dbox_rows}")

    report = {
        "version": "v2_grid_check_v1",
        "ok": not errors,
        "errors": errors,
        "counts": counts,
        "evaluation_n_per_block": expected_eval,
        "committed_gate_violations": gate_violations,
        "rows_missing_dbox": empty_dbox_rows,
    }
    write_json(Path(args.output).resolve(), report)
    print(json.dumps(report, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
