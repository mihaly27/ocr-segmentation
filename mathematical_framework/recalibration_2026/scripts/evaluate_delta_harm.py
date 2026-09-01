#!/usr/bin/env python3
"""Offline, delayed-GT harm audit for one stateful B3 delta trajectory."""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import yaml

from recalib_common import (
    load_json,
    load_yaml,
    parse_state,
    sha256_file,
    state_is_different,
    write_csv,
    write_json,
)


def load_legacy(path: Path):
    spec = importlib.util.spec_from_file_location("harm_ips_main_experiment", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def mean(values: Sequence[float]) -> float:
    return float(np.mean(np.asarray(values, dtype=float)))


def evaluate_state(legacy, cache, state: tuple[float, ...],
                   samples: list[dict[str, Any]]) -> dict[str, Any]:
    result_map = cache.ensure(state, samples)
    runs = [result_map[row["id"]] for row in samples]
    plate, char, dseg, dbox = [], [], [], []
    for sample, run in zip(samples, runs):
        plate.append(legacy.plate_accuracy(sample["gt"], run["pred"]))
        char.append(legacy.char_accuracy(sample["gt"], run["pred"]))
        dseg.append(abs(int(run["segment_count"]) - int(run["expected_count"])))
        box = legacy.box_distance(
            sample.get("gt_boxes", []),
            run.get("selected_boxes", []),
            int(run.get("expected_count") or 6),
        )
        if box is not None:
            dbox.append(float(box))
    aggregate = legacy.aggregate_runs(runs)
    return {
        "plate_accuracy": mean(plate),
        "char_accuracy": mean(char),
        "mean_dseg": mean(dseg),
        "mean_dbox": mean(dbox) if dbox else None,
        "mean_U": float(aggregate["mean_U"]),
        "p95_total_ms": float(aggregate["p95_total_ms"]),
    }


def truthy_csv(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    protocol_path = Path(args.protocol).resolve()
    run_dir = Path(args.run_dir).resolve()
    manifest = Path(args.manifest).resolve()
    output = Path(args.output).resolve()
    protocol = load_yaml(protocol_path)
    margins = protocol["noninferiority_margins"]

    legacy_path = repo_root / "mathematical_framework" / "ips_main_experiment.py"
    legacy = load_legacy(legacy_path)
    base_cfg = yaml.safe_load(
        (repo_root / "ips_single_image" / "config.yaml").read_text(encoding="utf-8")
    )
    rows = legacy.normalize_rows(
        legacy.load_manifest(manifest), manifest.parent, manifest.parent
    )
    rows_by_id = {row["id"]: row for row in rows}
    partition = load_json(run_dir / "partition_map.json")
    blocks = {int(row["block_index"]): row for row in partition["blocks"]}
    calibration = load_json(run_dir / "reference_calibration.json")
    injection = load_json(run_dir / "recalibration_injection.json")

    cache = legacy.ArtifactCache(
        repo=repo_root / "ips_single_image",
        base_cfg=base_cfg,
        root=run_dir / "cache",
        workers=args.workers,
        timeout=args.timeout,
        python=sys.executable,
    )

    with (run_dir / "controller_events.csv").open(newline="", encoding="utf-8") as handle:
        events = [row for row in csv.DictReader(handle) if row["controller"] == "B3"]

    audit_rows = []
    for event in events:
        block_index = int(event["block_index"])
        block = blocks[block_index]
        samples = [rows_by_id[sid] for sid in block["evaluation_ids"]]
        before_state = parse_state(event["state_before"])
        after_state = parse_state(event["state_after"])
        before = evaluate_state(legacy, cache, before_state, samples)
        after = before if not state_is_different(before_state, after_state) else evaluate_state(
            legacy, cache, after_state, samples
        )

        non_clean = str(event["condition"]) != "clean"
        informative = bool(
            non_clean
            and truthy_csv(event["trigger"])
            and state_is_different(event["raw_candidate"], event["state_before"])
        )
        committed_nonzero = bool(
            str(event["decision"]).startswith("commit")
            and state_is_different(event["state_before"], event["state_after"])
        )

        plate_drop = before["plate_accuracy"] - after["plate_accuracy"]
        char_drop = before["char_accuracy"] - after["char_accuracy"]
        dseg_increase = after["mean_dseg"] - before["mean_dseg"]
        dbox_increase = (
            None if before["mean_dbox"] is None or after["mean_dbox"] is None
            else after["mean_dbox"] - before["mean_dbox"]
        )
        plate_harm = committed_nonzero and plate_drop > float(
            margins["full_plate_accuracy_drop"]
        ) + 1e-12
        char_harm = committed_nonzero and char_drop > float(
            margins["character_accuracy_drop"]
        ) + 1e-12
        dseg_harm = committed_nonzero and dseg_increase > float(
            margins["mean_dseg_increase"]
        ) + 1e-12
        latency_harm = committed_nonzero and after["p95_total_ms"] > float(
            calibration["L_max"]
        ) + 1e-12

        gate_accepted = str(event["gate_accepted"]).strip()
        gate_violation = committed_nonzero and (
            gate_accepted != "1"
            or int(float(event["gate_semantic_mismatches"] or 0))
                > int(margins["semantic_repeat_mismatches"])
            or float(event["gate_candidate_U"] or 0) > float(calibration["U_max"]) + 1e-12
            or float(event["gate_p95_ms"] or 0) > float(calibration["L_max"]) + 1e-12
        )
        harm = bool(informative and (
            plate_harm or char_harm or dseg_harm or latency_harm or gate_violation
        ))

        audit_rows.append({
            "trajectory_seed": injection["trajectory_seed"],
            "delta_W": injection["delta_W"],
            "block_index": block_index,
            "condition": event["condition"],
            "informative": int(informative),
            "committed_nonzero": int(committed_nonzero),
            "decision": event["decision"],
            "state_before": event["state_before"],
            "raw_candidate": event["raw_candidate"],
            "state_after": event["state_after"],
            "plate_before": before["plate_accuracy"],
            "plate_after": after["plate_accuracy"],
            "plate_drop": plate_drop,
            "char_before": before["char_accuracy"],
            "char_after": after["char_accuracy"],
            "char_drop": char_drop,
            "dseg_before": before["mean_dseg"],
            "dseg_after": after["mean_dseg"],
            "dseg_increase": dseg_increase,
            "dbox_before": "" if before["mean_dbox"] is None else before["mean_dbox"],
            "dbox_after": "" if after["mean_dbox"] is None else after["mean_dbox"],
            "dbox_increase": "" if dbox_increase is None else dbox_increase,
            "after_p95_total_ms": after["p95_total_ms"],
            "frozen_L_max": calibration["L_max"],
            "plate_harm": int(plate_harm),
            "char_harm": int(char_harm),
            "dseg_harm": int(dseg_harm),
            "latency_harm": int(latency_harm),
            "committed_gate_violation": int(gate_violation),
            "H": int(harm),
        })

    write_csv(output, audit_rows)
    informative_rows = [row for row in audit_rows if int(row["informative"]) == 1]
    summary = {
        "trajectory_seed": injection["trajectory_seed"],
        "delta_W": injection["delta_W"],
        "informative_events": len(informative_rows),
        "harm_events": sum(int(row["H"]) for row in informative_rows),
        "nonzero_commits": sum(int(row["committed_nonzero"]) for row in informative_rows),
        "dbox_available": all(row["dbox_after"] != "" for row in audit_rows),
        "harm_csv": str(output),
        "harm_csv_sha256": sha256_file(output),
        "protocol_sha256": sha256_file(protocol_path),
    }
    write_json(output.with_suffix(".summary.json"), summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

