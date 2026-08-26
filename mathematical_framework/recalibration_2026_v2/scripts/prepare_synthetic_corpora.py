#!/usr/bin/env python3
"""Generate only the disjoint corpora declared by the locked V2 protocol."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from recalib_common import (
    delta_trajectory_specs,
    load_json,
    load_yaml,
    sha256_file,
    verify_input_lock,
    write_json,
)


def expected_jobs(protocol: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    if mode == "delta":
        config = protocol["delta_calibration"]
        for spec in delta_trajectory_specs(protocol):
            jobs.append({
                "name": f"delta_{spec['seed']}_{spec['condition']}",
                "seed": int(spec["seed"]),
                "n": int(config["generator_n_each"]),
                "perturb": f"clean,{spec['condition']}",
                "condition": spec["condition"],
                "role": spec["role"],
            })
    else:
        config = protocol["confirmation"]
        for seed in config["trajectory_generator_seeds"]:
            jobs.append({
                "name": f"confirmation_{int(seed)}",
                "seed": int(seed),
                "n": int(config["generator_n_each"]),
                "perturb": "all",
                "condition": None,
                "role": "untouched_confirmation",
            })
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--input-lock", required=True)
    parser.add_argument("--generator", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--mode", choices=("delta", "confirmation"), required=True)
    parser.add_argument("--selected-delta")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    protocol_path = Path(args.protocol).resolve()
    lock_path = Path(args.input_lock).resolve()
    lock = verify_input_lock(lock_path, protocol_path)
    protocol = load_yaml(protocol_path)
    generator = Path(args.generator).resolve()
    output_root = Path(args.output_root).resolve()

    locked_generator = next(
        item for item in lock["locked_files"] if item["role"] == "synthetic_generator"
    )
    if generator != Path(locked_generator["path"]).resolve():
        raise SystemExit("Generator path differs from the V2 input lock")
    if sha256_file(generator) != locked_generator["sha256"]:
        raise SystemExit("Generator hash differs from the V2 input lock")

    selection_metadata = None
    if args.mode == "confirmation":
        if not args.selected_delta:
            raise SystemExit("--selected-delta is required before confirmation generation")
        selection_path = Path(args.selected_delta).resolve()
        selection = load_json(selection_path)
        if selection.get("status") != "positive_delta_selected":
            raise SystemExit("Positive V2 delta is not frozen; confirmation is blocked")
        if selection.get("protocol", {}).get("sha256") != sha256_file(protocol_path):
            raise SystemExit("Selected delta does not belong to this V2 protocol")
        selection_metadata = {
            "path": str(selection_path),
            "sha256": sha256_file(selection_path),
            "selected_delta_W": selection["selected_delta_W"],
        }

    records = []
    for job in expected_jobs(protocol, args.mode):
        destination = output_root / job["name"]
        command = [
            args.python, str(generator),
            "--out", str(destination),
            "--n", str(job["n"]),
            "--seed", str(job["seed"]),
            "--perturb", str(job["perturb"]),
        ]
        status = "planned"
        quarantined = None
        if destination.exists():
            config_path = destination / "dataset_config.json"
            if not config_path.exists():
                if args.dry_run:
                    raise SystemExit(f"Existing V2 corpus is incomplete: {destination}")
                quarantine = output_root / "_incomplete"
                quarantine.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                quarantined = quarantine / f"{destination.name}_{stamp}"
                if quarantined.exists():
                    raise SystemExit(f"Quarantine destination already exists: {quarantined}")
                destination.rename(quarantined)
                subprocess.run(command, check=True)
                status = "regenerated_after_quarantine"
            else:
                config = load_json(config_path)
                if int(config.get("seed", -1)) != int(job["seed"]):
                    raise SystemExit(f"V2 seed conflict: {destination}")
                if int(config.get("n", -1)) != int(job["n"]):
                    raise SystemExit(f"V2 corpus-size conflict: {destination}")
                expected = (
                    config.get("perturbations", []) if job["perturb"] == "all"
                    else str(job["perturb"]).split(",")
                )
                if job["perturb"] != "all" and list(config.get("perturbations", [])) != expected:
                    raise SystemExit(f"V2 perturbation conflict: {destination}")
                status = "reused"
        elif not args.dry_run:
            subprocess.run(command, check=True)
            status = "generated"

        record = {
            **job,
            "path": str(destination),
            "status": status,
            "quarantined_incomplete_path": None if quarantined is None else str(quarantined),
            "command": command,
        }
        for filename in ("dataset_config.json", "manifest.csv", "annotations.jsonl"):
            path = destination / filename
            if path.exists():
                record[f"{filename}_sha256"] = sha256_file(path)
        records.append(record)

    output_root.mkdir(parents=True, exist_ok=True)
    report = {
        "version": "v2_corpus_generation_v1",
        "protocol": {"path": str(protocol_path), "sha256": sha256_file(protocol_path)},
        "input_lock": {"path": str(lock_path), "sha256": sha256_file(lock_path)},
        "generator": {"path": str(generator), "sha256": sha256_file(generator)},
        "mode": args.mode,
        "dry_run": bool(args.dry_run),
        "selected_delta": selection_metadata,
        "datasets": records,
    }
    write_json(output_root / f"corpus_generation_{args.mode}.json", report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
