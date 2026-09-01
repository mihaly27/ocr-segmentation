#!/usr/bin/env python3
"""Counterfactual 27-state gate stress map with delayed ground-truth audit."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import yaml

from recalib_common import (
    load_json,
    load_yaml,
    sha256_file,
    verify_input_lock,
    write_csv,
    write_json,
)


def load_legacy(path: Path):
    spec = importlib.util.spec_from_file_location("stress_ips_main_experiment", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def task_metrics(legacy, samples, runs):
    plate, char, dseg, dbox = [], [], [], []
    for sample, run in zip(samples, runs):
        plate.append(legacy.plate_accuracy(sample["gt"], run["pred"]))
        char.append(legacy.char_accuracy(sample["gt"], run["pred"]))
        dseg.append(abs(int(run["segment_count"]) - int(run["expected_count"])))
        box = legacy.box_distance(
            sample.get("gt_boxes", []), run.get("selected_boxes", []),
            int(run.get("expected_count") or 6),
        )
        if box is not None:
            dbox.append(box)
    return {
        "plate_accuracy": float(np.mean(plate)),
        "char_accuracy": float(np.mean(char)),
        "mean_dseg": float(np.mean(dseg)),
        "mean_dbox": float(np.mean(dbox)) if dbox else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--input-lock", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--repeat-n", type=int, default=2)
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    protocol_path = Path(args.protocol).resolve()
    input_lock_path = Path(args.input_lock).resolve()
    run_dir = Path(args.run_dir).resolve()
    manifest = Path(args.manifest).resolve()
    output = Path(args.output).resolve()
    protocol = load_yaml(protocol_path)
    verify_input_lock(input_lock_path, protocol_path)
    conditions = set(protocol["gate_stress"]["conditions"])
    legacy_path = repo / "mathematical_framework" / "ips_main_experiment.py"
    legacy = load_legacy(legacy_path)

    base_cfg = yaml.safe_load(
        (repo / "ips_single_image" / "config.yaml").read_text(encoding="utf-8")
    )
    rows = legacy.normalize_rows(legacy.load_manifest(manifest), manifest.parent, manifest.parent)
    rows_by_id = {row["id"]: row for row in rows}
    partition = load_json(run_dir / "partition_map.json")
    expected_gate_n = int(protocol["confirmation"]["partition"]["gate_n"])
    if any(len(block["gate_ids"]) != expected_gate_n for block in partition["blocks"]):
        raise SystemExit("Gate-stress input does not use the frozen V2 gate size")
    selected_blocks = [
        block for block in partition["blocks"] if block["condition"] in conditions
    ]
    missing = conditions - {block["condition"] for block in selected_blocks}
    if missing:
        raise SystemExit(f"Gate-stress conditions missing from partition: {sorted(missing)}")

    cal_json = load_json(run_dir / "reference_calibration.json")
    calibration = legacy.Calibration(
        env_ref=np.zeros((1, len(legacy.ENV_FEATURE_NAMES))),
        env_edges=[],
        tau_D=float(cal_json["tau_D"]),
        U_max=float(cal_json["U_max"]),
        L_max=float(cal_json["L_max"]),
        epsilon_U=float(cal_json["epsilon_U"]),
        tau_plate=float(cal_json["tau_plate"]),
        tau_char=float(cal_json["tau_char"]),
        tau_dseg=float(cal_json["tau_dseg"]),
        tau_dbox=None if cal_json["tau_dbox"] is None else float(cal_json["tau_dbox"]),
    )
    cache = legacy.ArtifactCache(
        repo=repo / "ips_single_image",
        base_cfg=base_cfg,
        root=run_dir / "cache",
        workers=args.workers,
        timeout=args.timeout,
        python=sys.executable,
    )

    rows_out = []
    for block in selected_blocks:
        samples = [rows_by_id[sid] for sid in block["gate_ids"]]
        current_map = cache.ensure(legacy.REF_STATE, samples)
        current_runs = [current_map[sample["id"]] for sample in samples]
        current_metrics = task_metrics(legacy, samples, current_runs)
        for state in legacy.grid_states():
            candidate_map = cache.ensure(state, samples)
            candidate_runs = [candidate_map[sample["id"]] for sample in samples]
            repeats = cache.rerun_semantic(state, samples[: min(args.repeat_n, len(samples))])
            mismatches = sum(int(a != b) for _, a, b in repeats)
            accepted, gate = legacy.gate_candidate(
                current_runs, candidate_runs, mismatches, calibration
            )
            metrics = task_metrics(legacy, samples, candidate_runs)
            rows_out.append({
                "block_index": block["block_index"],
                "condition": block["condition"],
                "state": legacy.state_label(state),
                "accepted": int(accepted),
                "check_U_absolute": int(gate["checks"]["U_absolute"]),
                "check_latency": int(gate["checks"]["latency"]),
                "check_U_noninferiority": int(gate["checks"]["U_noninferiority"]),
                "check_semantic_repeatability": int(gate["checks"]["semantic_repeatability"]),
                "candidate_mean_U": gate["candidate_mean_U"],
                "current_mean_U": gate["current_mean_U"],
                "candidate_p95_ms": gate["candidate_p95_ms"],
                "semantic_repeat_mismatches": mismatches,
                "candidate_plate_accuracy_delayed_gt": metrics["plate_accuracy"],
                "current_plate_accuracy_delayed_gt": current_metrics["plate_accuracy"],
                "candidate_char_accuracy_delayed_gt": metrics["char_accuracy"],
                "current_char_accuracy_delayed_gt": current_metrics["char_accuracy"],
                "candidate_mean_dseg_delayed_gt": metrics["mean_dseg"],
                "candidate_mean_dbox_delayed_gt": (
                    "" if metrics["mean_dbox"] is None else metrics["mean_dbox"]
                ),
            })

    write_csv(output, rows_out)
    rejected = [row for row in rows_out if int(row["accepted"]) == 0]
    report = {
        "state_environment_pairs": len(rows_out),
        "accepted": len(rows_out) - len(rejected),
        "rejected": len(rejected),
        "selective": bool(rejected and len(rejected) < len(rows_out)),
        "dbox_available": all(row["candidate_mean_dbox_delayed_gt"] != "" for row in rows_out),
        "output": str(output),
        "output_sha256": sha256_file(output),
        "protocol_sha256": sha256_file(protocol_path),
        "input_lock_sha256": sha256_file(input_lock_path),
    }
    write_json(output.with_suffix(".summary.json"), report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
