#!/usr/bin/env python3
"""Verify the committed V2 input lock and clean research branch."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from recalib_common import verify_input_lock, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--input-lock", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    protocol = Path(args.protocol).resolve()
    lock_path = Path(args.input_lock).resolve()
    output = Path(args.output).resolve()
    errors = []
    try:
        lock = verify_input_lock(lock_path, protocol)
    except Exception as exc:
        lock = None
        errors.append(str(exc))

    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, check=True,
        text=True, stdout=subprocess.PIPE,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True,
        text=True, stdout=subprocess.PIPE,
    ).stdout.strip()
    if branch != "research/bounded-adaptation-recalibration-v2":
        errors.append(f"unexpected branch: {branch}")
    if dirty:
        errors.append("working tree is dirty; commit the V2 input lock before execution")

    report = {
        "ok": not errors,
        "errors": errors,
        "branch": branch,
        "lock_status": None if lock is None else lock["status"],
    }
    write_json(output, report)
    print(json.dumps(report, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
