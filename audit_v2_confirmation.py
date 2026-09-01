#!/usr/bin/env python3
"""Fail-closed integrity audit and descriptive summary for V2 confirmation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import yaml


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return obj


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def as_int(value: Any) -> int:
    return int(float(str(value)))


def as_float(value: Any) -> float:
    return float(str(value))


def mean(values: Iterable[float]) -> float | None:
    data = list(values)
    return sum(data) / len(data) if data else None


def percentile(values: Iterable[float], probability: float) -> float | None:
    data = sorted(values)
    if not data:
        return None
    position = (len(data) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return data[lower]
    weight = position - lower
    return data[lower] * (1.0 - weight) + data[upper] * weight


def fmt_float(value: float | None) -> str:
    return "       NA" if value is None else f"{value:9.6f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.home() / "ocr-segmentation",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    repo = args.repo_root.expanduser().resolve()
    v2 = repo / "mathematical_framework" / "recalibration_2026_v2"
    protocol_path = v2 / "protocol.yaml"
    input_lock_path = v2 / "v2_input_lock.json"
    outputs = v2 / "outputs"
    confirmation = outputs / "confirmation"
    selection_path = outputs / "delta_selection" / "selected_delta.json"
    output = args.output or confirmation / "confirmation_audit.json"

    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    selection = load_json(selection_path)
    expected_seeds = [int(seed) for seed in protocol["confirmation"]["trajectory_generator_seeds"]]
    expected_controllers = [str(name) for name in protocol["confirmation"]["controllers"]]
    expected_conditions = [str(name) for name in protocol["confirmation"]["stream_conditions"]]
    partition_cfg = protocol["confirmation"]["partition"]
    proposal_n = int(partition_cfg["proposal_n"])
    gate_n = int(partition_cfg["gate_n"])
    evaluation_n = int(partition_cfg["evaluation_n"])
    expected_blocks = len(expected_conditions)
    expected_samples_per_controller = expected_blocks * evaluation_n
    expected_event_rows = expected_blocks * len(expected_controllers)
    selected_delta = selection.get("selected_delta_W")

    errors: list[str] = []
    controller_sample_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    controller_window_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    controller_event_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    b3_condition_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    paired_samples: dict[tuple[int, int, str], dict[str, dict[str, str]]] = defaultdict(dict)
    trajectory_reports: list[dict[str, Any]] = []
    rows_missing_dbox = 0
    committed_gate_violations = 0

    required_names = [
        "summary.json",
        "partition_map.json",
        "frozen_experiment_config.json",
        "recalibration_injection.json",
        "controller_events.csv",
        "window_results.csv",
        "sample_results.csv",
        "paired_comparisons.csv",
        "reference_calibration.json",
    ]

    for seed in expected_seeds:
        trajectory = confirmation / f"trajectory_{seed}"
        run_dir = trajectory / "confirmatory_main"
        missing = [name for name in required_names if not (run_dir / name).is_file()]
        if not (trajectory / "composite_manifest.jsonl").is_file():
            missing.append("../composite_manifest.jsonl")
        if not (trajectory / "dev_selected.json").is_file():
            missing.append("../dev_selected.json")
        if missing:
            errors.append(f"seed {seed}: missing files: {', '.join(missing)}")
            continue

        summary = load_json(run_dir / "summary.json")
        partition = load_json(run_dir / "partition_map.json")
        frozen = load_json(run_dir / "frozen_experiment_config.json")
        injection = load_json(run_dir / "recalibration_injection.json")
        events = load_csv(run_dir / "controller_events.csv")
        windows = load_csv(run_dir / "window_results.csv")
        samples = load_csv(run_dir / "sample_results.csv")
        comparisons = load_csv(run_dir / "paired_comparisons.csv")

        blocks = partition.get("blocks", [])
        actual_conditions = [str(block.get("condition")) for block in blocks]
        if actual_conditions != expected_conditions:
            errors.append(f"seed {seed}: stream conditions differ from protocol")
        for block in blocks:
            counts = (
                len(block.get("proposal_ids", [])),
                len(block.get("gate_ids", [])),
                len(block.get("evaluation_ids", [])),
            )
            if counts != (proposal_n, gate_n, evaluation_n):
                errors.append(
                    f"seed {seed}: block {block.get('block_index')} partition {counts} "
                    f"!= {(proposal_n, gate_n, evaluation_n)}"
                )

        if injection.get("result") != "completed":
            errors.append(f"seed {seed}: injection result is not completed")
        if str(injection.get("trajectory_seed")) != str(seed):
            errors.append(f"seed {seed}: trajectory seed mismatch")
        if not math.isclose(as_float(injection.get("delta_W")), as_float(selected_delta), abs_tol=1e-12):
            errors.append(f"seed {seed}: injected delta differs from selection")
        if not math.isclose(as_float(frozen.get("delta_W")), as_float(selected_delta), abs_tol=1e-12):
            errors.append(f"seed {seed}: frozen delta differs from selection")
        if list(frozen.get("controllers", [])) != expected_controllers:
            errors.append(f"seed {seed}: frozen controllers differ from protocol")
        if list(frozen.get("stream_conditions", [])) != expected_conditions:
            errors.append(f"seed {seed}: frozen stream differs from protocol")
        if summary.get("ground_truth_boxes_detected") is not True:
            errors.append(f"seed {seed}: ground-truth boxes were not detected")

        summary_controllers = summary.get("controllers", {})
        if list(summary_controllers.keys()) != expected_controllers:
            errors.append(f"seed {seed}: summary controllers differ from protocol")
        for controller in expected_controllers:
            row = summary_controllers.get(controller, {})
            if int(row.get("n_eval_samples", -1)) != expected_samples_per_controller:
                errors.append(f"seed {seed}: {controller} evaluation sample count mismatch")
            if int(row.get("n_eval_windows", -1)) != expected_blocks:
                errors.append(f"seed {seed}: {controller} evaluation window count mismatch")

        expected_counts = {
            "controller_events.csv": expected_event_rows,
            "window_results.csv": expected_event_rows,
            "sample_results.csv": expected_samples_per_controller * len(expected_controllers),
            "paired_comparisons.csv": len(expected_controllers) - 1,
        }
        actual_counts = {
            "controller_events.csv": len(events),
            "window_results.csv": len(windows),
            "sample_results.csv": len(samples),
            "paired_comparisons.csv": len(comparisons),
        }
        for name, expected in expected_counts.items():
            if actual_counts[name] != expected:
                errors.append(f"seed {seed}: {name} rows {actual_counts[name]} != {expected}")

        for row in events:
            controller = row["controller"]
            row["trajectory_seed"] = str(seed)
            controller_event_rows[controller].append(row)
            decision = row.get("decision", "")
            if controller in {"B3", "B3-I", "B3-R0"} and decision.startswith("commit_gated"):
                if row.get("gate_accepted") != "1":
                    committed_gate_violations += 1

        for row in windows:
            controller = row["controller"]
            row["trajectory_seed"] = str(seed)
            controller_window_rows[controller].append(row)

        for row in samples:
            controller = row["controller"]
            row["trajectory_seed"] = str(seed)
            controller_sample_rows[controller].append(row)
            if row.get("dbox", "") == "":
                rows_missing_dbox += 1
            key = (seed, as_int(row["block_index"]), row["sample_id"])
            paired_samples[key][controller] = row
            if controller == "B3":
                b3_condition_rows[row["condition"]].append(row)

        trajectory_reports.append(
            {
                "seed": seed,
                "blocks": len(blocks),
                "event_rows": len(events),
                "window_rows": len(windows),
                "sample_rows": len(samples),
                "summary_sha256": sha256_file(run_dir / "summary.json"),
                "partition_sha256": sha256_file(run_dir / "partition_map.json"),
            }
        )

    if committed_gate_violations:
        errors.append(f"committed gate violations: {committed_gate_violations}")
    if rows_missing_dbox:
        errors.append(f"sample rows missing d_box: {rows_missing_dbox}")

    gate_summary_path = confirmation / "trajectory_86082721" / "gate_stress.summary.json"
    safety_summary_path = confirmation / "trajectory_86082721" / "safety_challenge.summary.json"
    gate_summary = load_json(gate_summary_path) if gate_summary_path.is_file() else None
    safety_summary = load_json(safety_summary_path) if safety_summary_path.is_file() else None
    if gate_summary is None:
        errors.append("gate-stress summary missing")
    else:
        gate_csv = gate_summary_path.with_name("gate_stress.csv")
        expected_pairs = len(protocol["gate_stress"]["conditions"]) * 27
        if int(gate_summary.get("state_environment_pairs", -1)) != expected_pairs:
            errors.append("gate-stress pair count mismatch")
        if gate_summary.get("selective") is not True:
            errors.append("gate stress is not selective")
        if gate_summary.get("dbox_available") is not True:
            errors.append("gate-stress d_box unavailable")
        if not gate_csv.is_file() or sha256_file(gate_csv) != gate_summary.get("output_sha256"):
            errors.append("gate-stress CSV hash mismatch")
    if safety_summary is None:
        errors.append("safety-challenge summary missing")
    elif safety_summary.get("ok") is not True or safety_summary.get("failed_scenarios"):
        errors.append("safety challenge failed")
    else:
        safety_csv = safety_summary_path.with_name("safety_challenge.csv")
        if not safety_csv.is_file() or sha256_file(safety_csv) != safety_summary.get("output_sha256"):
            errors.append("safety-challenge CSV hash mismatch")

    controller_summary: list[dict[str, Any]] = []
    for controller in expected_controllers:
        samples = controller_sample_rows.get(controller, [])
        windows = controller_window_rows.get(controller, [])
        events = controller_event_rows.get(controller, [])
        dboxes = [as_float(row["dbox"]) for row in samples if row.get("dbox", "") != ""]
        controller_summary.append(
            {
                "controller": controller,
                "evaluation_samples": len(samples),
                "evaluation_windows": len(windows),
                "plate_accuracy": mean(as_float(row["plate_accuracy"]) for row in samples),
                "char_accuracy": mean(as_float(row["char_accuracy"]) for row in samples),
                "mean_dseg": mean(as_float(row["dseg"]) for row in samples),
                "mean_dbox": mean(dboxes),
                "outside_stable_region_windows": sum(as_int(row["outside_stable_region"]) for row in windows),
                "outside_stable_region_rate": mean(as_float(row["outside_stable_region"]) for row in windows),
                "mean_total_ms": mean(as_float(row["total_ms"]) for row in samples),
                "p95_total_ms": percentile((as_float(row["total_ms"]) for row in samples), 0.95),
                "triggers": sum(as_int(row["trigger"]) for row in events),
                "commits": sum(str(row.get("decision", "")).startswith("commit") for row in events),
                "rollbacks": sum(as_int(row["rollback"]) for row in events),
                "fail_safes": sum(as_int(row["fail_safe"]) for row in events),
            }
        )

    b3_by_condition: list[dict[str, Any]] = []
    for condition in expected_conditions:
        if condition == "clean" or condition in {row["condition"] for row in b3_by_condition}:
            continue
        rows = b3_condition_rows.get(condition, [])
        b3_by_condition.append(
            {
                "condition": condition,
                "evaluation_samples": len(rows),
                "plate_accuracy": mean(as_float(row["plate_accuracy"]) for row in rows),
                "char_accuracy": mean(as_float(row["char_accuracy"]) for row in rows),
                "mean_dseg": mean(as_float(row["dseg"]) for row in rows),
                "mean_dbox": mean(as_float(row["dbox"]) for row in rows if row.get("dbox", "") != ""),
            }
        )

    paired_b3: list[dict[str, Any]] = []
    for comparator in expected_controllers:
        if comparator == "B3":
            continue
        plate_deltas: list[float] = []
        char_deltas: list[float] = []
        for rows in paired_samples.values():
            if "B3" not in rows or comparator not in rows:
                continue
            plate_deltas.append(
                as_float(rows["B3"]["plate_accuracy"])
                - as_float(rows[comparator]["plate_accuracy"])
            )
            char_deltas.append(
                as_float(rows["B3"]["char_accuracy"])
                - as_float(rows[comparator]["char_accuracy"])
            )
        paired_b3.append(
            {
                "controller_a": "B3",
                "controller_b": comparator,
                "paired_samples": len(plate_deltas),
                "delta_plate_accuracy": mean(plate_deltas),
                "delta_char_accuracy": mean(char_deltas),
            }
        )

    report = {
        "version": "v2_confirmation_audit_v1",
        "ok": not errors,
        "errors": errors,
        "scope": (
            "Integrity, frozen-design conformance, descriptive endpoints, and "
            "operational gate consistency. No post-hoc endpoint success threshold is imposed."
        ),
        "protocol_sha256": sha256_file(protocol_path),
        "input_lock_sha256": sha256_file(input_lock_path),
        "selected_delta_W": selected_delta,
        "expected_trajectories": len(expected_seeds),
        "completed_trajectories": len(trajectory_reports),
        "partition": {
            "blocks_per_trajectory": expected_blocks,
            "proposal_n": proposal_n,
            "gate_n": gate_n,
            "evaluation_n": evaluation_n,
        },
        "rows_missing_dbox": rows_missing_dbox,
        "committed_gate_violations": committed_gate_violations,
        "trajectory_reports": trajectory_reports,
        "controller_summary": controller_summary,
        "B3_by_condition": b3_by_condition,
        "paired_B3_comparisons": paired_b3,
        "gate_stress": gate_summary,
        "safety_challenge": safety_summary,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("V2 CONFIRMATION AUDIT")
    print("ok:", report["ok"])
    print("completed_trajectories:", f"{len(trajectory_reports)}/{len(expected_seeds)}")
    print("selected_delta_W:", selected_delta)
    print("rows_missing_dbox:", rows_missing_dbox)
    print("committed_gate_violations:", committed_gate_violations)
    print()
    print(
        f"{'controller':<8} {'samples':>8} {'plate':>9} {'char':>9} "
        f"{'dseg':>9} {'dbox':>9} {'outside':>9} {'commit':>8} {'rollback':>9} {'fail_safe':>10}"
    )
    for row in controller_summary:
        print(
            f"{row['controller']:<8} {row['evaluation_samples']:8d} "
            f"{fmt_float(row['plate_accuracy'])} {fmt_float(row['char_accuracy'])} "
            f"{fmt_float(row['mean_dseg'])} {fmt_float(row['mean_dbox'])} "
            f"{row['outside_stable_region_windows']:9d} "
            f"{row['commits']:8d} {row['rollbacks']:9d} {row['fail_safes']:10d}"
        )
    print()
    print("B3 by non-clean condition")
    for row in b3_by_condition:
        print(
            f"  {row['condition']:<12} n={row['evaluation_samples']:4d} "
            f"plate={fmt_float(row['plate_accuracy']).strip()} "
            f"char={fmt_float(row['char_accuracy']).strip()} "
            f"dseg={fmt_float(row['mean_dseg']).strip()} "
            f"dbox={fmt_float(row['mean_dbox']).strip()}"
        )
    print()
    print("Paired B3 differences")
    for row in paired_b3:
        print(
            f"  B3 - {row['controller_b']:<5} n={row['paired_samples']:5d} "
            f"delta_plate={row['delta_plate_accuracy']:+.6f} "
            f"delta_char={row['delta_char_accuracy']:+.6f}"
        )
    print()
    print("output:", output)
    if errors:
        print("errors:")
        for error in errors:
            print("  -", error)
    print("confirmation_audit:", "PASS" if not errors else "FAIL")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
 
