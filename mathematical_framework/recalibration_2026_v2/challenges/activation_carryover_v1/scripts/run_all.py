#!/usr/bin/env python3
"""Plan or execute all frozen V2.1 challenge trajectories."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from challenge_common import load_yaml, sequence_by_seed, verify_lock, write_json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--protocol", required=True)
    ap.add_argument("--input-lock", required=True)
    ap.add_argument("--phase1-selected", required=True)
    ap.add_argument("--w-dataset-root", required=True)
    ap.add_argument("--corpora-root", required=True)
    ap.add_argument("--output-root", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--only-seed", type=int, action="append")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo_root).resolve(); protocol_path = Path(args.protocol).resolve()
    lock_path = Path(args.input_lock).resolve(); corpora = Path(args.corpora_root).resolve()
    out = Path(args.output_root).resolve(); out.mkdir(parents=True, exist_ok=True)
    protocol = load_yaml(protocol_path); lock = verify_lock(lock_path, protocol_path)
    roles = {row["role"]: Path(row["path"]).resolve() for row in lock["locked_files"]}
    seeds = sorted(sequence_by_seed(protocol))
    if args.only_seed:
        requested = set(args.only_seed)
        if not requested <= set(seeds):
            raise SystemExit("--only-seed contains a seed outside the frozen protocol")
        seeds = [s for s in seeds if s in requested]
    compose = roles["v2_compose_manifest"]
    runner = Path(__file__).resolve().with_name("run_challenge.py")
    jobs = []
    for seed in seeds:
        dataset = corpora / f"challenge_{seed}"
        traj_manifest = dataset / "annotations.jsonl"
        combined = out / "manifests" / f"trajectory_{seed}.jsonl"
        selected = out / "manifests" / f"trajectory_{seed}.dev_selected.json"
        target = out / f"trajectory_{seed}"
        jobs.append({"seed": seed, "dataset": str(dataset), "manifest": str(combined),
                     "dev_selected": str(selected), "output": str(target),
                     "completed": (target / "summary.json").exists()})
    write_json(out / "challenge_plan.json", {"execute": args.execute, "jobs": jobs,
               "selected": len(jobs), "completed": sum(j["completed"] for j in jobs),
               "new_runs": sum(not j["completed"] for j in jobs)})
    print(json.dumps({"execute": args.execute, "selected": len(jobs),
                      "completed": sum(j["completed"] for j in jobs),
                      "new_runs": sum(not j["completed"] for j in jobs)}, indent=2))
    if not args.execute:
        return 0
    for index, job in enumerate(jobs, 1):
        if job["completed"]:
            print(f"[{index}/{len(jobs)}] seed={job['seed']} already complete", flush=True); continue
        dataset = Path(job["dataset"]); combined = Path(job["manifest"]); selected = Path(job["dev_selected"])
        if not (dataset / "annotations.jsonl").is_file():
            raise SystemExit(f"Missing corpus: {dataset}")
        combined.parent.mkdir(parents=True, exist_ok=True)
        if not combined.exists() or not selected.exists():
            subprocess.run([sys.executable, str(compose), "--phase1-selected", str(Path(args.phase1_selected).resolve()),
                "--phase1-manifest", str(Path(args.w_dataset_root).resolve() / "annotations.jsonl"),
                "--phase1-root", str(Path(args.w_dataset_root).resolve()), "--trajectory-manifest", str(dataset / "annotations.jsonl"),
                "--trajectory-root", str(dataset), "--trajectory-label", str(job["seed"]),
                "--output-manifest", str(combined), "--output-dev-selected", str(selected)], check=True)
        print(f"[{index}/{len(jobs)}] seed={job['seed']} running", flush=True)
        subprocess.run([sys.executable, str(runner), "--repo-root", str(repo), "--protocol", str(protocol_path),
            "--input-lock", str(lock_path), "--manifest", str(combined), "--dev-selected", str(selected),
            "--output", job["output"], "--trajectory-seed", str(job["seed"]),
            "--workers", str(args.workers), "--timeout", str(args.timeout)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
