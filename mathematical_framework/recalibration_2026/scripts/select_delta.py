#!/usr/bin/env python3
"""Apply the preregistered exact-binomial delta selection rule."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from recalib_common import (
    clopper_pearson_upper,
    load_json,
    load_yaml,
    sha256_file,
    write_csv,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--w-json", required=True)
    parser.add_argument("--harm-csv", required=True, nargs="+")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    protocol_path = Path(args.protocol).resolve()
    w_path = Path(args.w_json).resolve()
    output = Path(args.output_dir).resolve()
    protocol = load_yaml(protocol_path)
    w_obj = load_json(w_path)
    config = protocol["delta_calibration"]
    frozen_grid = [float(x) for x in config["delta_grid"]]
    frozen_seeds = {str(item["seed"]) for item in config["trajectory_specs"]}

    grouped: dict[float, list[dict[str, Any]]] = defaultdict(list)
    seen_units: set[tuple[float, str, int]] = set()
    input_records = []
    for raw_path in args.harm_csv:
        path = Path(raw_path).resolve()
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        input_records.append({"path": str(path), "sha256": sha256_file(path)})
        for row in rows:
            delta = float(row["delta_W"])
            if not any(abs(delta - x) <= 1e-12 for x in frozen_grid):
                raise SystemExit(f"Observed delta outside frozen grid: {delta}")
            key = (delta, str(row["trajectory_seed"]), int(row["block_index"]))
            if key in seen_units:
                raise SystemExit(f"Duplicate event unit: {key}")
            seen_units.add(key)
            grouped[delta].append(row)

    missing_grid = [delta for delta in frozen_grid if delta not in grouped]
    if missing_grid:
        raise SystemExit(f"Missing completed grid values: {missing_grid}")

    confidence = float(config["one_sided_confidence"])
    n_min = int(config["minimum_informative_events"])
    coverage_min = float(config["minimum_nonzero_commit_coverage"])
    upper_max = float(config["harm_upper_bound"])
    summary_rows = []
    eligible = []
    for delta in frozen_grid:
        rows = grouped[delta]
        observed_seeds = {str(row["trajectory_seed"]) for row in rows}
        if observed_seeds != frozen_seeds:
            raise SystemExit(
                f"Delta {delta} has trajectory seeds {sorted(observed_seeds)}, "
                f"expected {sorted(frozen_seeds)}"
            )
        informative = [row for row in rows if int(row["informative"]) == 1]
        informative_per_seed: dict[str, int] = defaultdict(int)
        for row in informative:
            informative_per_seed[str(row["trajectory_seed"])] += 1
        repeated_units = {
            seed: count for seed, count in informative_per_seed.items() if count > 1
        }
        if repeated_units:
            raise SystemExit(
                f"Delta {delta} violates one-informative-event-per-seed independence: "
                f"{repeated_units}"
            )
        n = len(informative)
        harms = sum(int(row["H"]) for row in informative)
        commits = sum(int(row["committed_nonzero"]) for row in informative)
        coverage = commits / n if n else 0.0
        upper = clopper_pearson_upper(harms, n, confidence) if n else 1.0
        is_eligible = bool(n >= n_min and coverage >= coverage_min and upper <= upper_max)
        if is_eligible:
            eligible.append(delta)
        summary_rows.append({
            "delta_W": delta,
            "informative_events": n,
            "harm_events": harms,
            "harm_rate": harms / n if n else "",
            "harm_upper_exact_one_sided": upper,
            "nonzero_commits": commits,
            "update_coverage": coverage,
            "eligible": int(is_eligible),
        })

    selected = max(eligible) if eligible else None
    if selected is None:
        status = "calibration_failure"
    elif selected == 0.0:
        status = "delta_zero_only"
    else:
        status = "positive_delta_selected"

    w_diag = [float(x) for x in w_obj["W_z_diag"]]
    delta_i = None if selected is None else float(
        selected / (math.prod(w_diag) ** (1.0 / (2.0 * len(w_diag))))
    )
    output.mkdir(parents=True, exist_ok=True)
    table_path = output / "delta_calibration_summary.csv"
    write_csv(table_path, summary_rows)
    result = {
        "version": "delta_calibration_selection_v1",
        "status": status,
        "selected_delta_W": selected,
        "selected_delta_I_volume_matched": delta_i,
        "W_z_diag": w_diag,
        "selection_rule": config["selection_rule"],
        "minimum_informative_events": n_min,
        "minimum_nonzero_commit_coverage": coverage_min,
        "harm_upper_bound": upper_max,
        "one_sided_confidence": confidence,
        "eligible_grid_values": eligible,
        "protocol": {"path": str(protocol_path), "sha256": sha256_file(protocol_path)},
        "W_file": {"path": str(w_path), "sha256": sha256_file(w_path)},
        "harm_inputs": input_records,
        "summary_table": {"path": str(table_path), "sha256": sha256_file(table_path)},
    }
    selection_path = output / "selected_delta.json"
    write_json(selection_path, result)
    frozen = {
        "coordinates": w_obj["coordinates"],
        "D_diag": w_obj["D_diag"],
        "W_z_diag": w_diag,
        "W_theta_diag": w_obj["W_theta_diag"],
        "delta_W": selected,
        "delta_I_volume_matched": delta_i,
        "calibration_status": status,
        "selected_delta_json_sha256": sha256_file(selection_path),
    }
    write_json(output / "frozen_recalibration_config.json", frozen)
    print(json.dumps(result, indent=2))
    return 0 if selected is not None else 3


if __name__ == "__main__":
    raise SystemExit(main())
