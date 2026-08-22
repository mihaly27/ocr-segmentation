#!/usr/bin/env python3
"""Fail-fast validation of the preregistered protocol and Node01 state."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from recalib_common import load_json, load_yaml, sha256_file, write_json


def command(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        list(args), cwd=cwd, check=True, text=True, capture_output=True
    )
    return completed.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--environment-lock", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    protocol_path = Path(args.protocol).resolve()
    environment_path = Path(args.environment_lock).resolve()
    protocol = load_yaml(protocol_path)
    environment = load_json(environment_path)

    errors: list[str] = []
    warnings: list[str] = []

    expected_commit = str(protocol["provenance"]["base_git_commit"])
    actual_commit = command("git", "rev-parse", "HEAD", cwd=repo)
    ancestor_check = subprocess.run(
        ["git", "merge-base", "--is-ancestor", expected_commit, actual_commit],
        cwd=repo,
    )
    base_is_ancestor = ancestor_check.returncode == 0
    if not base_is_ancestor:
        errors.append(f"Frozen base {expected_commit} is not an ancestor of HEAD {actual_commit}")

    git_status = command("git", "status", "--porcelain=v1", cwd=repo)
    if git_status and not args.allow_dirty:
        errors.append("Working tree is dirty; commit the overlay before execution")
    elif git_status:
        warnings.append("Dirty working tree explicitly allowed for this verification")

    historical = float(protocol["provenance"]["historical_delta_W_excluded"])
    grid = [float(x) for x in protocol["delta_calibration"]["delta_grid"]]
    if any(abs(x - historical) <= 1e-12 for x in grid):
        errors.append("Historical delta appears as an exact calibration grid point")
    if grid != sorted(set(grid)) or not grid or grid[0] != 0.0:
        errors.append("Delta grid must be unique, sorted and start at zero")

    coords = protocol["parameter_space"]["coordinates"]
    vectors = [
        protocol["parameter_space"]["reference_state"],
        protocol["parameter_space"]["normalization_D_diag"],
        protocol["parameter_space"]["hard_lower"],
        protocol["parameter_space"]["hard_upper"],
        protocol["parameter_space"]["raw_grid_levels"],
    ]
    if any(len(v) != len(coords) for v in vectors):
        errors.append("Parameter-space vectors do not match the coordinate count")

    delta_cfg = protocol["delta_calibration"]
    trajectory_specs = delta_cfg["trajectory_specs"]
    seeds = [int(item["seed"]) for item in trajectory_specs]
    if len(seeds) != len(set(seeds)):
        errors.append("Delta trajectory generator seeds are not unique")
    targets = Counter(
        str(item["condition"]) for item in trajectory_specs
        if str(item["role"]) == "informative_target"
    )
    if targets != Counter({"touch": 20, "broken": 20, "combo": 20}):
        errors.append(f"Unexpected informative-target allocation: {dict(targets)}")
    if int(delta_cfg["minimum_informative_events"]) > sum(targets.values()):
        errors.append("Minimum informative events exceed independent target trajectories")
    stream_template = list(delta_cfg["stream_template"])
    clean_needed = int(delta_cfg["reference_clean_n"]) + (
        stream_template.count("clean") * int(delta_cfg["block_size"])
    )
    clean_generated = int(delta_cfg["generator_n_each"]) // 2
    if clean_generated < clean_needed:
        errors.append(
            f"Targeted corpus provides {clean_generated} clean rows but needs {clean_needed}"
        )

    packages = {}
    for distribution in ("numpy", "opencv-python", "pillow", "pytesseract", "PyYAML"):
        try:
            packages[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            packages[distribution] = None
            errors.append(f"Missing Python package: {distribution}")

    expected_packages = environment["core_packages"]
    for name, expected in expected_packages.items():
        actual = packages.get(name)
        if actual != expected:
            errors.append(f"Package {name}: actual={actual!r}, expected={expected!r}")

    tesseract = command("tesseract", "--version").splitlines()[0]
    if str(environment["tesseract_version"]) not in tesseract:
        errors.append(f"Tesseract mismatch: {tesseract}")

    report = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "repo_root": str(repo),
        "frozen_base_commit": expected_commit,
        "git_head": actual_commit,
        "frozen_base_is_ancestor": base_is_ancestor,
        "git_status_porcelain": git_status,
        "python_executable": sys.executable,
        "python_version": sys.version,
        "packages": packages,
        "tesseract": tesseract,
        "protocol_sha256": sha256_file(protocol_path),
        "environment_lock_sha256": sha256_file(environment_path),
    }
    write_json(Path(args.output).resolve(), report)
    print(json.dumps(report, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
