#!/usr/bin/env python3
"""Run one frozen V2.1 activation/carryover trajectory."""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import yaml

from challenge_common import (
    load_json, load_yaml, sequence_by_seed, sha256_file, state_different,
    stream_from_order, verify_lock, write_csv, write_json,
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def metrics(legacy, samples, runs):
    ordered = [runs[s["id"]] for s in samples]
    plate = [legacy.plate_accuracy(s["gt"], r["pred"]) for s, r in zip(samples, ordered)]
    char = [legacy.char_accuracy(s["gt"], r["pred"]) for s, r in zip(samples, ordered)]
    dseg = [abs(int(r["segment_count"]) - int(r["expected_count"])) for r in ordered]
    dbox = [
        legacy.box_distance(s.get("gt_boxes", []), r.get("selected_boxes", []), int(r.get("expected_count") or 6))
        for s, r in zip(samples, ordered)
    ]
    dbox = [x for x in dbox if x is not None]
    agg = legacy.aggregate_runs(ordered)
    return {
        "n": len(samples), "plate": float(np.mean(plate)), "char": float(np.mean(char)),
        "dseg": float(np.mean(dseg)), "dbox": float(np.mean(dbox)) if dbox else None,
        "mean_U": agg["mean_U"], "p95_ms": agg["p95_total_ms"],
    }


def add_metric_fields(row: dict[str, Any], prefix: str, value: dict[str, Any]) -> None:
    for key, val in value.items():
        row[f"{prefix}_{key}"] = val


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--protocol", required=True)
    ap.add_argument("--input-lock", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--dev-selected", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--trajectory-seed", required=True, type=int)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    started = time.time()
    repo = Path(args.repo_root).resolve()
    protocol_path = Path(args.protocol).resolve()
    lock_path = Path(args.input_lock).resolve()
    manifest = Path(args.manifest).resolve()
    dev_selected = Path(args.dev_selected).resolve()
    output = Path(args.output).resolve()
    protocol = load_yaml(protocol_path)
    lock = verify_lock(lock_path, protocol_path)
    sequences = sequence_by_seed(protocol)
    if args.trajectory_seed not in sequences:
        raise SystemExit("Trajectory seed is outside the frozen design")
    if (output / "summary.json").exists():
        raise SystemExit(f"Completed output exists; refusing overwrite: {output}")

    roles = {row["role"]: Path(row["path"]).resolve() for row in lock["locked_files"]}
    legacy = load_module("v21_frozen_legacy", roles["historical_engine"])
    partition_mod = load_module("v21_frozen_partition", roles["v2_partition_adapter"])
    frozen = protocol["frozen_inputs"]
    legacy.W_DIAG = np.asarray(frozen["W_z_diag"], dtype=float)
    legacy.DELTA_W = float(frozen["selected_delta_W"])
    legacy.DELTA_I = float(frozen["selected_delta_I"])
    legacy.H_STEP = np.asarray(frozen["D_diag"], dtype=float)
    legacy.LOW = np.asarray(frozen["hard_lower"], dtype=float)
    legacy.HIGH = np.asarray(frozen["hard_upper"], dtype=float)
    legacy.RAW_GRID_LEVELS = tuple(tuple(float(x) for x in level) for level in frozen["raw_grid_levels"])
    ref = legacy.state_tuple(frozen["reference_state"])

    stream = tuple(stream_from_order(sequences[args.trajectory_seed]))
    rows = legacy.normalize_rows(legacy.load_manifest(manifest), manifest.parent, manifest.parent)
    dev_ids = legacy.load_dev_ids(dev_selected)
    part = protocol["design"]["partition"]
    reference, blocks, public = partition_mod.build_asymmetric_partition(
        rows, dev_ids, int(protocol["design"]["reference_clean_n"]), int(part["block_total_n"]),
        f"V21-{args.trajectory_seed}", stream_conditions=stream,
        deterministic_sort=legacy.deterministic_sort, proposal_n=int(part["proposal_n"]),
        gate_n=int(part["gate_n"]), evaluation_n=int(part["evaluation_n"]),
    )
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "partition_map.json", public)

    base_cfg = yaml.safe_load(roles["base_pipeline_config"].read_text(encoding="utf-8"))
    cache = legacy.ArtifactCache(repo / "ips_single_image", base_cfg, output / "cache", args.workers, args.timeout, sys.executable)
    gate_obj = load_json(roles["frozen_gate_thresholds"])
    cal = legacy.Calibration(
        env_ref=np.zeros((1, 1)), env_edges=[np.array([-np.inf, np.inf])],
        tau_D=float(gate_obj["tau_D"]), U_max=float(gate_obj["U_max"]),
        L_max=float(gate_obj["L_max"]), epsilon_U=float(gate_obj["epsilon_U"]),
        tau_plate=float(gate_obj["tau_plate"]), tau_char=float(gate_obj["tau_char"]),
        tau_dseg=float(gate_obj["tau_dseg"]), tau_dbox=gate_obj.get("tau_dbox"),
    )
    controllers = [str(x) for x in protocol["design"]["controllers"]]
    states = {name: ref for name in controllers}
    candidates = legacy.grid_states()
    margins = protocol["noninferiority_margins"]
    events: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []
    carry: list[dict[str, Any]] = []
    stress: list[dict[str, Any]] = []
    previous_nonclean: str | None = None

    # Warm the reference cache and retain proof that GT never enters the IPS command.
    cache.ensure(ref, reference)
    for block in blocks:
        bi, condition = int(block["block_index"]), str(block["condition"])
        proposal, gate, evaluation = block["proposal"], block["gate"], block["evaluation"]
        nonclean = condition != "clean"
        print(f"seed={args.trajectory_seed} block={bi + 1}/{len(blocks)} condition={condition}", flush=True)

        if nonclean and previous_nonclean is not None:
            baseline = metrics(legacy, evaluation, cache.ensure(ref, evaluation))
            for name in controllers:
                if name == "B0":
                    continue
                observed = metrics(legacy, evaluation, cache.ensure(states[name], evaluation))
                row = {"seed": args.trajectory_seed, "source": previous_nonclean, "target": condition,
                       "ordered_pair": f"{previous_nonclean}_to_{condition}", "controller": name,
                       "state": legacy.state_label(states[name]), "state_differs_from_reference": state_different(states[name], ref)}
                add_metric_fields(row, "reference", baseline); add_metric_fields(row, "carry", observed)
                row.update({
                    "plate_drop": baseline["plate"] - observed["plate"],
                    "char_drop": baseline["char"] - observed["char"],
                    "dseg_increase": observed["dseg"] - baseline["dseg"],
                    "dbox_increase": None if baseline["dbox"] is None or observed["dbox"] is None else observed["dbox"] - baseline["dbox"],
                    "plate_harm": baseline["plate"] - observed["plate"] > float(margins["full_plate_accuracy_drop"]) + 1e-12,
                    "char_harm": baseline["char"] - observed["char"] > float(margins["character_accuracy_drop"]) + 1e-12,
                    "dseg_harm": observed["dseg"] - baseline["dseg"] > float(margins["mean_dseg_increase"]) + 1e-12,
                    "latency_violation": observed["p95_ms"] > cal.L_max,
                })
                row["any_harm"] = any(row[k] for k in ("plate_harm", "char_harm", "dseg_harm", "latency_violation"))
                carry.append(row)

        # Counterfactual layer is anchored to the B3 state entering the block.
        if nonclean:
            entering = states["B3"]
            current_gate_runs = cache.ensure(entering, gate)
            current_eval = metrics(legacy, evaluation, cache.ensure(entering, evaluation))
            ref_eval = metrics(legacy, evaluation, cache.ensure(ref, evaluation))
            stress_cache: dict[tuple[float, float, float], tuple[dict[str, Any], int, bool, dict[str, Any]]] = {}
            for raw in candidates:
                projected, raw_norm, projection_active = legacy.project_state(entering, raw, legacy.W_DIAG, legacy.DELTA_W)
                if projected not in stress_cache:
                    projected_gate = cache.ensure(projected, gate)
                    mismatches = sum(a != b for _, a, b in cache.rerun_semantic(projected, gate))
                    accepted, gd = legacy.gate_candidate(
                        [current_gate_runs[s["id"]] for s in gate], [projected_gate[s["id"]] for s in gate], mismatches, cal)
                    projected_eval = metrics(legacy, evaluation, cache.ensure(projected, evaluation))
                    stress_cache[projected] = (projected_eval, mismatches, accepted, gd)
                projected_eval, mismatches, accepted, gd = stress_cache[projected]
                row = {"seed": args.trajectory_seed, "block_index": bi, "condition": condition,
                       "entering_state": legacy.state_label(entering), "raw_state": legacy.state_label(raw),
                       "projected_state": legacy.state_label(projected), "raw_weighted_norm": raw_norm,
                       "projection_active": projection_active, "gate_accepted": accepted,
                       "semantic_repeat_mismatches": mismatches}
                add_metric_fields(row, "current", current_eval); add_metric_fields(row, "reference", ref_eval); add_metric_fields(row, "projected", projected_eval)
                row["harm_vs_current"] = (current_eval["plate"] - projected_eval["plate"] > float(margins["full_plate_accuracy_drop"]) or current_eval["char"] - projected_eval["char"] > float(margins["character_accuracy_drop"]) or projected_eval["dseg"] - current_eval["dseg"] > float(margins["mean_dseg_increase"]) or projected_eval["p95_ms"] > cal.L_max)
                row["harm_vs_reference"] = (ref_eval["plate"] - projected_eval["plate"] > float(margins["full_plate_accuracy_drop"]) or ref_eval["char"] - projected_eval["char"] > float(margins["character_accuracy_drop"]) or projected_eval["dseg"] - ref_eval["dseg"] > float(margins["mean_dseg_increase"]) or projected_eval["p95_ms"] > cal.L_max)
                row.update({f"gate_{k}": v for k, v in gd["checks"].items()})
                stress.append(row)

        proposal_runs = {s: [cache.ensure(s, proposal)[x["id"]] for x in proposal] for s in candidates} if nonclean else {}
        for name in controllers:
            before = states[name]
            raw, selected, projection_active = before, before, False
            gate_accepted: bool | None = None
            mismatches = 0
            decision = "hold_clean" if not nonclean else "hold"
            raw_obj: float | None = None
            if nonclean and name != "B0":
                raw, raw_obj = legacy.select_raw_candidate(before, candidates, proposal_runs, cal.L_max)
                if name == "B1":
                    selected, decision = raw, "commit_raw"
                elif name == "B2":
                    selected, _, projection_active = legacy.project_state(before, raw, legacy.W_DIAG, legacy.DELTA_W)
                    decision = "commit_projected"
                else:
                    w = np.ones(3) if name == "B3-I" else legacy.W_DIAG
                    delta = legacy.DELTA_I if name == "B3-I" else legacy.DELTA_W
                    selected, _, projection_active = legacy.project_state(before, raw, w, delta)
                    cur_map, cand_map = cache.ensure(before, gate), cache.ensure(selected, gate)
                    mismatches = sum(a != b for _, a, b in cache.rerun_semantic(selected, gate))
                    gate_accepted, gd = legacy.gate_candidate([cur_map[x["id"]] for x in gate], [cand_map[x["id"]] for x in gate], mismatches, cal)
                    if gate_accepted:
                        decision = "commit_gated"
                    elif name == "B3-R0":
                        selected, decision = before, "reject_hold"
                    else:
                        curagg = legacy.aggregate_runs([cur_map[x["id"]] for x in gate])
                        recovery = curagg["mean_U"] > cal.U_max or curagg["p95_total_ms"] > cal.L_max
                        selected, decision = (ref, "reject_fail_safe") if recovery else (before, "reject_hold")
            states[name] = selected
            observed = metrics(legacy, evaluation, cache.ensure(selected, evaluation))
            erow = {"seed": args.trajectory_seed, "block_index": bi, "condition": condition, "controller": name,
                    "forced_opportunity": nonclean, "state_before": legacy.state_label(before), "raw_candidate": legacy.state_label(raw),
                    "state_after": legacy.state_label(selected), "raw_objective": raw_obj,
                    "raw_weighted_norm": legacy.weighted_distance(before, raw, legacy.W_DIAG),
                    "projection_active": projection_active, "gate_accepted": gate_accepted,
                    "semantic_repeat_mismatches": mismatches, "decision": decision,
                    "nonzero_state_change": state_different(before, selected)}
            events.append(erow)
            wrow = {"seed": args.trajectory_seed, "block_index": bi, "condition": condition,
                    "controller": name, "state": legacy.state_label(selected)}
            add_metric_fields(wrow, "eval", observed); windows.append(wrow)
        if nonclean:
            previous_nonclean = condition

    write_csv(output / "controller_events.csv", events)
    write_csv(output / "window_results.csv", windows)
    write_csv(output / "carryover_events.csv", carry)
    write_csv(output / "projection_gate_stress.csv", stress)
    summary = {
        "version": "v21_activation_carryover_trajectory_v1", "ok": True,
        "seed": args.trajectory_seed, "order": sequences[args.trajectory_seed], "stream": list(stream),
        "counts": {"blocks": len(blocks), "controller_events": len(events), "window_results": len(windows),
                   "carryover_events": len(carry), "projection_gate_stress": len(stress)},
        "selected_delta_W": legacy.DELTA_W, "selected_delta_I": legacy.DELTA_I,
        "runtime_seconds": time.time() - started,
        "protocol_sha256": sha256_file(protocol_path), "input_lock_sha256": sha256_file(lock_path),
        "manifest_sha256": sha256_file(manifest), "dev_selected_sha256": sha256_file(dev_selected),
        "scientific_interpretation_deferred_to_audit": True,
    }
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
