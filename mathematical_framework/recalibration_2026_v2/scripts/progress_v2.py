#!/usr/bin/env python3
"""Report resumable V2 grid progress and a simple recent-rate ETA."""
from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

from recalib_common import delta_trajectory_specs, load_yaml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--grid-root", required=True)
    args = parser.parse_args()
    protocol = load_yaml(Path(args.protocol).resolve())
    root = Path(args.grid_root).resolve()
    total = (
        len(delta_trajectory_specs(protocol))
        * len(protocol["delta_calibration"]["delta_grid"])
    )
    completed = sorted(
        root.glob("trajectory_*/delta_*/delta_harm_events.summary.json"),
        key=lambda path: path.stat().st_mtime,
    )
    done = len(completed)
    remaining = max(0, total - done)
    print(f"completed: {done}/{total} ({100.0 * done / total:.2f}%)")
    print(f"remaining: {remaining}")
    if done >= 2:
        recent = completed[-min(31, done):]
        elapsed = recent[-1].stat().st_mtime - recent[0].stat().st_mtime
        intervals = len(recent) - 1
        if elapsed > 0 and intervals > 0:
            seconds_per_run = elapsed / intervals
            print(f"recent_seconds_per_run: {seconds_per_run:.1f}")
            print("estimated_remaining:", timedelta(seconds=int(
                seconds_per_run * remaining
            )))
    if completed:
        print("latest:", completed[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
