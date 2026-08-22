#!/usr/bin/env python3
"""Run the frozen historical engine with an explicitly injected new W/delta."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

from recalib_common import load_json, load_yaml, sha256_file, write_json


def load_legacy(path: Path):
    spec = importlib.util.spec_from_file_location("frozen_ips_main_experiment", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import historical runner: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ensure_shared_cache(output: Path, shared_cache: Path | None) -> None:
    if shared_cache is None:
        return
    output.mkdir(parents=True, exist_ok=True)
    shared_cache.mkdir(parents=True, exist_ok=True)
    link = output / "cache"
    if link.is_symlink():
        if link.resolve() != shared_cache.resolve():
            raise SystemExit(f"Existing cache symlink points elsewhere: {link}")
        return
    if link.exists():
        raise SystemExit(f"Refusing to replace existing cache path: {link}")
    link.symlink_to(shared_cache.resolve(), target_is_directory=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--w-json", required=True)
    parser.add_argument("--delta", required=True, type=float)
    parser.add_argument("--mode", choices=("delta", "confirmation"), required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--dev-selected", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--shared-cache")
    parser.add_argument("--trajectory-seed", required=True)
    parser.add_argument(
        "--stream-conditions",
        help="Comma-separated frozen stream; required for targeted delta trajectories",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--gate-repeat-n", type=int, default=2)
    parser.add_argument("--bootstrap", type=int, default=500)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    protocol_path = Path(args.protocol).resolve()
    w_path = Path(args.w_json).resolve()
    manifest = Path(args.manifest).resolve()
    dev_selected = Path(args.dev_selected).resolve()
    output = Path(args.output).resolve()
    shared_cache = Path(args.shared_cache).resolve() if args.shared_cache else None
    protocol = load_yaml(protocol_path)
    w_obj = load_json(w_path)

    if output.exists() and (output / "summary.json").exists():
        raise SystemExit(f"Completed output already exists; do not overwrite: {output}")

    historical = float(protocol["provenance"]["historical_delta_W_excluded"])
    if abs(args.delta - historical) <= 1e-12:
        raise SystemExit("Historical delta is prohibited as a recalibration input")
    if args.mode == "delta":
        frozen_grid = [float(x) for x in protocol["delta_calibration"]["delta_grid"]]
        if not any(abs(args.delta - x) <= 1e-12 for x in frozen_grid):
            raise SystemExit(f"Delta {args.delta} is outside the frozen grid")

    legacy_path = repo_root / "mathematical_framework" / "ips_main_experiment.py"
    legacy = load_legacy(legacy_path)
    coordinates = list(protocol["parameter_space"]["coordinates"])
    if tuple(coordinates) != tuple(legacy.COORDS):
        raise SystemExit("Frozen active coordinates differ from the historical engine")
    expected_d = np.asarray(protocol["parameter_space"]["normalization_D_diag"], dtype=float)
    if not np.allclose(expected_d, legacy.H_STEP, atol=0.0, rtol=0.0):
        raise SystemExit("Frozen D differs from the historical engine")

    w_diag = np.asarray(w_obj["W_z_diag"], dtype=float)
    if w_diag.shape != (len(coordinates),) or np.any(w_diag <= 0):
        raise SystemExit("W_z_diag must be positive and match the active dimension")
    p_dim = len(coordinates)
    delta_i = float(args.delta / (float(np.prod(w_diag)) ** (1.0 / (2.0 * p_dim))))

    legacy.W_DIAG = w_diag
    legacy.DELTA_W = float(args.delta)
    legacy.P_DIM = p_dim
    legacy.DELTA_I = delta_i
    legacy.CONTROLLERS = (
        ("B3",) if args.mode == "delta"
        else tuple(protocol["confirmation"]["controllers"])
    )
    if args.mode == "delta":
        if not args.stream_conditions:
            raise SystemExit("--stream-conditions is required in delta mode")
        stream_conditions = tuple(
            item.strip() for item in args.stream_conditions.split(",") if item.strip()
        )
    else:
        stream_conditions = tuple(protocol["confirmation"]["stream_conditions"])
        if args.stream_conditions:
            supplied = tuple(
                item.strip() for item in args.stream_conditions.split(",") if item.strip()
            )
            if supplied != stream_conditions:
                raise SystemExit("Confirmation stream differs from the frozen protocol")
    if len(stream_conditions) < 3 or stream_conditions[0] != "clean":
        raise SystemExit("Invalid frozen stream")
    legacy.STREAM_CONDITIONS = stream_conditions

    ensure_shared_cache(output, shared_cache)
    injection = {
        "mode": args.mode,
        "trajectory_seed": str(args.trajectory_seed),
        "historical_runner": str(legacy_path),
        "historical_runner_sha256": sha256_file(legacy_path),
        "protocol": str(protocol_path),
        "protocol_sha256": sha256_file(protocol_path),
        "W_file": str(w_path),
        "W_file_sha256": sha256_file(w_path),
        "W_z_diag": w_diag.tolist(),
        "delta_W": float(args.delta),
        "delta_I_volume_matched": delta_i,
        "controllers": list(legacy.CONTROLLERS),
        "stream_conditions": list(stream_conditions),
        "manifest": str(manifest),
        "manifest_sha256": sha256_file(manifest),
        "dev_selected": str(dev_selected),
        "dev_selected_sha256": sha256_file(dev_selected),
        "python_executable": sys.executable,
    }
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "recalibration_injection.json", injection)

    old_argv = sys.argv[:]
    sys.argv = [
        str(legacy_path),
        "--repo", str(repo_root / "ips_single_image"),
        "--manifest", str(manifest),
        "--dataset-root", str(manifest.parent),
        "--dev-selected", str(dev_selected),
        "--output", str(output),
        "--reference-clean-n", str(protocol["delta_calibration"]["reference_clean_n"]),
        "--block-size", str(protocol["delta_calibration"]["block_size"]),
        "--workers", str(args.workers),
        "--timeout", str(args.timeout),
        "--python", sys.executable,
        "--gate-repeat-n", str(args.gate_repeat_n),
        "--seed", f"RECAL-TRAJECTORY-{args.trajectory_seed}",
        "--bootstrap", str(args.bootstrap),
    ]
    try:
        result = int(legacy.main())
    finally:
        sys.argv = old_argv
    if result != 0:
        raise SystemExit(result)

    frozen = load_json(output / "frozen_experiment_config.json")
    if not math.isclose(float(frozen["delta_W"]), args.delta, abs_tol=1e-12):
        raise SystemExit("Historical runner did not record the injected delta")
    if not np.allclose(
        [frozen["W_diag"][name] for name in coordinates], w_diag, atol=1e-12, rtol=0
    ):
        raise SystemExit("Historical runner did not record the injected W")

    injection["result"] = "completed"
    injection["frozen_experiment_config_sha256"] = sha256_file(
        output / "frozen_experiment_config.json"
    )
    injection["summary_sha256"] = sha256_file(output / "summary.json")
    write_json(output / "recalibration_injection.json", injection)
    print(json.dumps(injection, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
