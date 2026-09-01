#!/usr/bin/env python3
"""Compact, null-safe report for the frozen V2 delta decision."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from recalib_common import load_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection-dir", required=True)
    args = parser.parse_args()
    root = Path(args.selection_dir).resolve()
    selected = load_json(root / "selected_delta.json")
    with (root / "delta_calibration_summary.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))
    print("status:", selected["status"])
    print("selected_delta_W:", selected["selected_delta_W"])
    print("selected_delta_I:", selected["selected_delta_I_volume_matched"])
    print("eligible_grid_values:", selected["eligible_grid_values"])
    print()
    print(f"{'delta':>5} {'info':>5} {'harm':>5} {'upper95':>10} {'commit':>7} {'coverage':>10} {'eligible':>8}")
    for row in rows:
        print(
            f"{float(row['delta_W']):5.1f} "
            f"{int(row['informative_events']):5d} "
            f"{int(row['harm_events']):5d} "
            f"{float(row['harm_upper_exact_one_sided']):10.6f} "
            f"{int(row['nonzero_commits']):7d} "
            f"{float(row['update_coverage']):10.6f} "
            f"{int(row['eligible']):8d}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
