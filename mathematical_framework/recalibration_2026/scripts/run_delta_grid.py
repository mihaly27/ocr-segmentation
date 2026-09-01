#!/usr/bin/env python3
"""Resumable orchestration of the frozen stateful delta grid on Node01."""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

from recalib_common import load_yaml, write_json


def run(command: list[str], execute: bool) -> None:
    print(shlex.join(command), flush=True)
    if execute:
        subprocess.run(command, check=True)


def delta_label(delta: float) -> str:
    return f"delta_{delta:04.1f}".replace(".", "p")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--w-json", required=True)
    parser.add_argument("--phase1-selected", required=True)
    parser.add_argument("--corpora-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--only-delta", type=float, action="append")
    parser.add_argument("--only-seed", type=int, action="append")
    parser.add_argument("--max-new-runs", type=int)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    protocol_path = Path(args.protocol).resolve()
    protocol = load_yaml(protocol_path)
    scripts = Path(__file__).resolve().parent
    corpora = Path(args.corpora_root).resolve()
    output = Path(args.output_root).resolve()
    w_dataset = corpora / "w_calibration"
    phase1_selected = Path(args.phase1_selected).resolve()
    w_json = Path(args.w_json).resolve()

    deltas = [float(x) for x in protocol["delta_calibration"]["delta_grid"]]
    specs = [
        {
            "seed": int(item["seed"]),
            "condition": str(item["condition"]),
            "role": str(item["role"]),
        }
        for item in protocol["delta_calibration"]["trajectory_specs"]
    ]
    if args.only_delta:
        requested = args.only_delta
        unknown = [x for x in requested if not any(abs(x-y) <= 1e-12 for y in deltas)]
        if unknown:
            raise SystemExit(f"Requested deltas outside frozen grid: {unknown}")
        deltas = requested
    if args.only_seed:
        unknown = sorted(set(args.only_seed) - {item["seed"] for item in specs})
        if unknown:
            raise SystemExit(f"Requested seeds outside frozen protocol: {unknown}")
        specs = [item for item in specs if item["seed"] in set(args.only_seed)]

    planned = []
    new_runs = 0
    for spec in specs:
        seed = int(spec["seed"])
        condition = str(spec["condition"])
        trajectory_dataset = corpora / f"delta_{seed}_{condition}"
        trajectory_root = output / f"trajectory_{seed}_{condition}"
        composed = trajectory_root / "composite_manifest.jsonl"
        dev_selected = trajectory_root / "dev_selected.json"
        if not composed.exists() or not dev_selected.exists():
            command = [
                args.python, str(scripts / "compose_manifest.py"),
                "--phase1-selected", str(phase1_selected),
                "--phase1-manifest", str(w_dataset / "annotations.jsonl"),
                "--phase1-root", str(w_dataset),
                "--trajectory-manifest", str(trajectory_dataset / "annotations.jsonl"),
                "--trajectory-root", str(trajectory_dataset),
                "--trajectory-label", f"{seed}-{condition}",
                "--output-manifest", str(composed),
                "--output-dev-selected", str(dev_selected),
            ]
            run(command, args.execute)
            if not args.execute:
                planned.append({
                    "kind": "compose", "seed": seed, "condition": condition,
                    "command": command,
                })

        for delta in deltas:
            run_dir = trajectory_root / delta_label(delta)
            harm_csv = run_dir / "delta_harm_events.csv"
            if harm_csv.exists() and (run_dir / "summary.json").exists():
                print(f"SKIP completed {run_dir}")
                continue
            if args.max_new_runs is not None and new_runs >= args.max_new_runs:
                continue
            experiment = [
                args.python, str(scripts / "run_parameterized_experiment.py"),
                "--repo-root", str(repo),
                "--protocol", str(protocol_path),
                "--w-json", str(w_json),
                "--delta", str(delta),
                "--mode", "delta",
                "--manifest", str(composed),
                "--dev-selected", str(dev_selected),
                "--output", str(run_dir),
                "--shared-cache", str(output / "cache_shared_global"),
                "--trajectory-seed", str(seed),
                "--stream-conditions", f"clean,{condition},clean",
                "--workers", str(args.workers),
                "--timeout", str(args.timeout),
            ]
            harm = [
                args.python, str(scripts / "evaluate_delta_harm.py"),
                "--repo-root", str(repo),
                "--protocol", str(protocol_path),
                "--run-dir", str(run_dir),
                "--manifest", str(composed),
                "--output", str(harm_csv),
                "--workers", str(args.workers),
                "--timeout", str(args.timeout),
            ]
            experiment_completed = (run_dir / "summary.json").exists()
            if experiment_completed:
                print(f"SKIP experiment; harm audit pending {run_dir}")
            else:
                run(experiment, args.execute)
            run(harm, args.execute)
            planned.append({
                "kind": "delta_run",
                "seed": seed,
                "condition": condition,
                "role": spec["role"],
                "delta": delta,
                "experiment_command": experiment,
                "harm_command": harm,
                "experiment_already_completed": experiment_completed,
            })
            new_runs += 1

    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "delta_grid_plan.json", {
        "execute": bool(args.execute),
        "selected_trajectory_specs": specs,
        "selected_deltas": deltas,
        "new_runs": new_runs,
        "items": planned,
    })
    if not args.execute:
        print("Plan only. Re-run with --execute after reviewing delta_grid_plan.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
