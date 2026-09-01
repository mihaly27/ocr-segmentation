#!/usr/bin/env python3
"""Freeze the V2 code and external V1 inputs before any V2 corpus exists."""
from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
import sys
from pathlib import Path

from recalib_common import load_json, load_yaml, sha256_file, write_json


EXCLUDED_PARTS = {"corpora", "outputs", "__pycache__"}
EXCLUDED_NAMES = {"v2_input_lock.json"}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def file_record(path: Path, role: str) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise SystemExit(f"Missing locked input ({role}): {path}")
    return {"role": role, "path": str(path), "sha256": sha256_file(path)}


def verify_manifest(root: Path, manifest: Path) -> int:
    count = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split("  ", 1)
        path = root / relative
        if not path.is_file() or sha256_file(path) != digest:
            raise SystemExit(f"V1 freeze-manifest verification failed: {path}")
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--v1-root", required=True)
    parser.add_argument("--v2-root", required=True)
    parser.add_argument("--generator", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    v1 = Path(args.v1_root).resolve()
    v2 = Path(args.v2_root).resolve()
    protocol_path = v2 / "protocol.yaml"
    protocol = load_yaml(protocol_path)
    output = Path(args.output).resolve()
    if output != (v2 / "v2_input_lock.json").resolve():
        raise SystemExit("V2 input lock must be written to v2_input_lock.json")
    if output.exists():
        raise SystemExit("V2 input lock already exists; never overwrite it")

    dirty = git(repo, "status", "--porcelain")
    if dirty:
        raise SystemExit("Working tree must be clean before locking V2 inputs")
    branch = git(repo, "branch", "--show-current")
    if branch != "research/bounded-adaptation-recalibration-v2":
        raise SystemExit(f"Unexpected V2 branch: {branch}")

    v1_output = v1 / "outputs"
    v1_selection_path = v1_output / "delta_selection" / "selected_delta.json"
    v1_selection = load_json(v1_selection_path)
    if (
        v1_selection.get("status") != protocol["provenance"]["v1_expected_status"]
        or v1_selection.get("selected_delta_W") is not None
    ):
        raise SystemExit("V1 outcome is not the frozen inconclusive pilot")
    with (v1_output / "delta_selection" / "delta_calibration_summary.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        informative = {int(row["informative_events"]) for row in csv.DictReader(handle)}
    expected_info = int(protocol["provenance"]["v1_expected_informative_events_per_delta"])
    if informative != {expected_info}:
        raise SystemExit(f"Unexpected V1 informative-event counts: {informative}")

    v1_manifest = v1_output / "MANIFEST.sha256"
    v1_manifest_count = verify_manifest(v1_output, v1_manifest)

    locked = [
        file_record(protocol_path, "v2_protocol"),
        file_record(Path(args.generator), "synthetic_generator"),
        file_record(repo / "mathematical_framework" / "ips_main_experiment.py", "historical_engine"),
        file_record(repo / "ips_single_image" / "config.yaml", "reference_pipeline_config"),
        file_record(v1_output / "w_calibration.json", "v1_independent_W"),
        file_record(v1_output / "w_phase1_local" / "selected_samples.json", "v1_phase1_selected"),
        file_record(v1 / "corpora" / "w_calibration" / "annotations.jsonl", "v1_W_annotations"),
        file_record(v1_selection_path, "v1_failed_selection"),
        file_record(v1_output / "delta_selection" / "delta_calibration_summary.csv", "v1_delta_summary"),
        file_record(v1_manifest, "v1_freeze_manifest"),
        file_record(v1_output / "freeze_summary.json", "v1_freeze_summary"),
    ]
    for path in sorted(v2.rglob("*")):
        if not path.is_file() or path.name in EXCLUDED_NAMES:
            continue
        relative = path.relative_to(v2)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.resolve() == protocol_path.resolve():
            continue
        locked.append(file_record(path, f"v2_code:{relative.as_posix()}"))

    tesseract = subprocess.run(
        ["tesseract", "--version"], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    ).stdout.splitlines()[0]
    record = {
        "version": "v2_input_lock_v1",
        "status": "v2_inputs_locked_before_generation",
        "protocol": locked[0],
        "git": {
            "branch": branch,
            "commit_before_lock_file": git(repo, "rev-parse", "HEAD"),
            "working_tree_before_lock_file": "clean",
        },
        "environment": {
            "python_executable": sys.executable,
            "python_version": platform.python_version(),
            "tesseract_version": tesseract,
        },
        "v1_evidence": {
            "status": v1_selection["status"],
            "selected_delta_W": None,
            "informative_events_per_delta": expected_info,
            "verified_manifest_file_count": v1_manifest_count,
            "pooled_into_v2": False,
        },
        "locked_files": locked,
    }
    write_json(output, record)
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
