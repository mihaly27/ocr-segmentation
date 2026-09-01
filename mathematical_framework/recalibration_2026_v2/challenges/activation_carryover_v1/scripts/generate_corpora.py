#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from challenge_common import load_json, load_yaml, sequence_by_seed, sha256_file, verify_lock, write_json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--protocol", required=True)
    ap.add_argument("--input-lock", required=True)
    ap.add_argument("--generator", required=True)
    ap.add_argument("--output-root", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    protocol_path = Path(args.protocol).resolve()
    lock = verify_lock(Path(args.input_lock).resolve(), protocol_path)
    protocol = load_yaml(protocol_path)
    sequence_by_seed(protocol)
    generator = Path(args.generator).resolve()
    locked = {x["role"]: x for x in lock["locked_files"]}["synthetic_generator"]
    if generator != Path(locked["path"]).resolve() or sha256_file(generator) != locked["sha256"]:
        raise SystemExit("Generator differs from V2.1 input lock")
    root = Path(args.output_root).resolve()
    n = int(protocol["design"]["generator_n_each"])
    perturb = ",".join(str(x) for x in protocol["design"]["generator_perturbations"])
    records = []
    for seed in protocol["design"]["trajectory_seeds"]:
        seed = int(seed)
        dst = root / f"challenge_{seed}"
        command = [args.python, str(generator), "--out", str(dst), "--n", str(n), "--seed", str(seed), "--perturb", perturb]
        status = "planned"
        if dst.exists():
            cfg_path = dst / "dataset_config.json"
            if not cfg_path.is_file():
                raise SystemExit(f"Incomplete existing corpus: {dst}")
            cfg = load_json(cfg_path)
            if int(cfg.get("seed", -1)) != seed or int(cfg.get("n", -1)) != n:
                raise SystemExit(f"Existing corpus conflicts with protocol: {dst}")
            if list(cfg.get("perturbations", [])) != perturb.split(","):
                raise SystemExit(f"Existing perturbations conflict with protocol: {dst}")
            status = "reused"
        elif not args.dry_run:
            subprocess.run(command, check=True)
            status = "generated"
        records.append({"seed": seed, "path": str(dst), "status": status, "command": command})
    root.mkdir(parents=True, exist_ok=True)
    report = {
        "version": "v21_challenge_corpus_generation_v1",
        "dry_run": bool(args.dry_run),
        "protocol_sha256": sha256_file(protocol_path),
        "input_lock_sha256": sha256_file(Path(args.input_lock).resolve()),
        "datasets": records,
    }
    write_json(root / "corpus_generation.json", report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
