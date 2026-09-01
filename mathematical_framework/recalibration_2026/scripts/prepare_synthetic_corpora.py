#!/usr/bin/env python3
"""Generate the disjoint synthetic corpora declared in protocol.yaml."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from recalib_common import load_json, load_yaml, sha256_file, write_json


def expected_jobs(protocol: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    if mode in {"w", "all"}:
        cfg = protocol["w_calibration"]
        jobs.append({
            "name": "w_calibration",
            "seed": int(cfg["generator_seed"]),
            "n": int(cfg["generator_n"]),
            "perturb": "all",
        })
    if mode in {"delta", "all"}:
        cfg = protocol["delta_calibration"]
        for spec in cfg["trajectory_specs"]:
            seed = int(spec["seed"])
            condition = str(spec["condition"])
            jobs.append({
                "name": f"delta_{seed}_{condition}",
                "seed": seed,
                "n": int(cfg["generator_n_each"]),
                "perturb": f"clean,{condition}",
                "condition": condition,
                "role": str(spec["role"]),
            })
    if mode in {"confirmation", "all"}:
        cfg = protocol["confirmation"]
        for seed in cfg["trajectory_generator_seeds"]:
            jobs.append({
                "name": f"confirmation_{int(seed)}",
                "seed": int(seed),
                "n": int(cfg["generator_n_each"]),
                "perturb": "all",
            })
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--generator", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--mode", choices=("w", "delta", "confirmation", "all"), default="all")
    parser.add_argument(
        "--selected-delta",
        help="Required before confirmation generation; selected_delta.json from the frozen calibration",
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    protocol_path = Path(args.protocol).resolve()
    generator = Path(args.generator).resolve()
    output_root = Path(args.output_root).resolve()
    protocol = load_yaml(protocol_path)
    if not generator.exists():
        raise SystemExit(f"Generator not found: {generator}")
    selection_record = None
    selection_metadata = None
    if args.mode in {"confirmation", "all"}:
        if not args.selected_delta:
            raise SystemExit("--selected-delta is required before confirmation generation")
        selection_path = Path(args.selected_delta).resolve()
        selection_record = load_json(selection_path)
        if selection_record.get("selected_delta_W") is None:
            raise SystemExit("Delta calibration has no selected radius; confirmation is blocked")
        selection_metadata = {
            "path": str(selection_path),
            "sha256": sha256_file(selection_path),
        }

    records = []
    for job in expected_jobs(protocol, args.mode):
        name = str(job["name"])
        seed = int(job["seed"])
        count = int(job["n"])
        perturb = str(job["perturb"])
        destination = output_root / name
        command = [
            args.python,
            str(generator),
            "--out", str(destination),
            "--n", str(count),
            "--seed", str(seed),
            "--perturb", perturb,
        ]
        status = "planned"
        if destination.exists():
            cfg_path = destination / "dataset_config.json"
            if not cfg_path.exists():
                raise SystemExit(f"Existing destination is incomplete: {destination}")
            cfg = load_json(cfg_path)
            if int(cfg.get("seed", -1)) != seed or int(cfg.get("n", -1)) != count:
                raise SystemExit(f"Existing dataset conflicts with frozen protocol: {destination}")
            if perturb != "all" and list(cfg.get("perturbations", [])) != perturb.split(","):
                raise SystemExit(f"Existing perturbations conflict with frozen protocol: {destination}")
            status = "reused"
        elif not args.dry_run:
            subprocess.run(command, check=True)
            status = "generated"

        record = {
            "name": name,
            "seed": seed,
            "n": count,
            "perturb": perturb,
            "condition": job.get("condition"),
            "role": job.get("role"),
            "path": str(destination),
            "status": status,
            "command": command,
        }
        for filename in ("dataset_config.json", "manifest.csv", "annotations.jsonl"):
            path = destination / filename
            if path.exists():
                record[f"{filename}_sha256"] = sha256_file(path)
        records.append(record)

    report = {
        "protocol": str(protocol_path),
        "protocol_sha256": sha256_file(protocol_path),
        "generator": str(generator),
        "generator_sha256": sha256_file(generator),
        "mode": args.mode,
        "dry_run": bool(args.dry_run),
        "selected_delta_W": (
            None if selection_record is None else selection_record["selected_delta_W"]
        ),
        "selected_delta_source": selection_metadata,
        "datasets": records,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    write_json(output_root / f"corpus_generation_{args.mode}.json", report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
