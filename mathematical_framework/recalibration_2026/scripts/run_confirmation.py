#!/usr/bin/env python3
"""Run the untouched confirmatory trajectories after W and delta are frozen."""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

from recalib_common import load_json, load_yaml, sha256_file, write_json


def run(command: list[str], execute: bool) -> None:
    print(shlex.join(command), flush=True)
    if execute:
        subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--w-json", required=True)
    parser.add_argument("--selected-delta", required=True)
    parser.add_argument("--phase1-selected", required=True)
    parser.add_argument("--corpora-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--only-seed", type=int, action="append")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    protocol_path = Path(args.protocol).resolve()
    protocol = load_yaml(protocol_path)
    selection_path = Path(args.selected_delta).resolve()
    selection = load_json(selection_path)
    delta = selection.get("selected_delta_W")
    if delta is None:
        raise SystemExit("Delta calibration failed; confirmation is blocked")

    scripts = Path(__file__).resolve().parent
    corpora = Path(args.corpora_root).resolve()
    output = Path(args.output_root).resolve()
    w_dataset = corpora / "w_calibration"
    phase1_selected = Path(args.phase1_selected).resolve()
    w_json = Path(args.w_json).resolve()
    expected_w_hash = str(selection.get("W_file", {}).get("sha256", ""))
    if not expected_w_hash or sha256_file(w_json) != expected_w_hash:
        raise SystemExit("W file does not match the W frozen by delta selection")
    seeds = [int(x) for x in protocol["confirmation"]["trajectory_generator_seeds"]]
    if args.only_seed:
        unknown = sorted(set(args.only_seed) - set(seeds))
        if unknown:
            raise SystemExit(f"Requested seeds outside frozen confirmation set: {unknown}")
        seeds = args.only_seed

    items = []
    for seed in seeds:
        dataset = corpora / f"confirmation_{seed}"
        trajectory = output / f"trajectory_{seed}"
        manifest = trajectory / "composite_manifest.jsonl"
        dev_selected = trajectory / "dev_selected.json"
        if not manifest.exists() or not dev_selected.exists():
            compose = [
                args.python, str(scripts / "compose_manifest.py"),
                "--phase1-selected", str(phase1_selected),
                "--phase1-manifest", str(w_dataset / "annotations.jsonl"),
                "--phase1-root", str(w_dataset),
                "--trajectory-manifest", str(dataset / "annotations.jsonl"),
                "--trajectory-root", str(dataset),
                "--trajectory-label", str(seed),
                "--output-manifest", str(manifest),
                "--output-dev-selected", str(dev_selected),
            ]
            run(compose, args.execute)
            items.append({"kind": "compose", "seed": seed, "command": compose})

        run_dir = trajectory / "confirmatory_main"
        if (run_dir / "summary.json").exists():
            print(f"SKIP completed {run_dir}")
            continue
        command = [
            args.python, str(scripts / "run_parameterized_experiment.py"),
            "--repo-root", str(repo),
            "--protocol", str(protocol_path),
            "--w-json", str(w_json),
            "--delta", str(delta),
            "--mode", "confirmation",
            "--manifest", str(manifest),
            "--dev-selected", str(dev_selected),
            "--output", str(run_dir),
            "--shared-cache", str(output / "cache_shared_global"),
            "--trajectory-seed", str(seed),
            "--workers", str(args.workers),
            "--timeout", str(args.timeout),
        ]
        run(command, args.execute)
        items.append({"kind": "confirmation", "seed": seed, "command": command})

    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "confirmation_plan.json", {
        "execute": bool(args.execute),
        "selected_delta_W": delta,
        "selected_delta_source": str(selection_path),
        "seeds": seeds,
        "items": items,
    })
    if not args.execute:
        print("Plan only. Generate confirmation corpora only after delta freeze, then re-run with --execute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
