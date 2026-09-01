#!/usr/bin/env python3
"""Deterministic threshold-level challenge of every operational gate check."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

from recalib_common import load_json, sha256_file, write_csv, write_json


def load_legacy(path: Path):
    spec = importlib.util.spec_from_file_location("challenge_ips_main_experiment", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fake_run(mean_u: float, latency: float) -> dict:
    # With all other components zero, density_pen / 1.5 equals sample_U.
    if not 0.0 <= mean_u <= 1.0 / 6.0:
        raise ValueError("Synthetic mean_u must be in [0, 1/6]")
    return {
        "segment_count": 6,
        "expected_count": 6,
        "pred": "ABC123",
        "fit_pen": 0.0,
        "overlap_pen": 0.0,
        "blocking": 0,
        "density_pen": 1.5 * mean_u,
        "total_ms": latency,
        "search_ms": latency * 0.5,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--reference-calibration", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    calibration_path = Path(args.reference_calibration).resolve()
    cal_json = load_json(calibration_path)
    legacy_path = repo / "mathematical_framework" / "ips_main_experiment.py"
    legacy = load_legacy(legacy_path)
    cal = legacy.Calibration(
        env_ref=np.zeros((1, len(legacy.ENV_FEATURE_NAMES))),
        env_edges=[],
        tau_D=float(cal_json["tau_D"]),
        U_max=float(cal_json["U_max"]),
        L_max=float(cal_json["L_max"]),
        epsilon_U=float(cal_json["epsilon_U"]),
        tau_plate=float(cal_json["tau_plate"]),
        tau_char=float(cal_json["tau_char"]),
        tau_dseg=float(cal_json["tau_dseg"]),
        tau_dbox=None,
    )

    low_latency = max(1.0, 0.5 * cal.L_max)
    current_u = min(0.01, 0.25 * cal.U_max)
    absolute_bad_u = min(1.0 / 6.0, max(cal.U_max + 0.01, cal.U_max * 1.1))
    noninferior_bad_u = min(1.0 / 6.0, current_u + cal.epsilon_U + 0.005)
    scenarios = [
        ("accepted_baseline", current_u, low_latency, 0),
        ("reject_U_absolute", absolute_bad_u, low_latency, 0),
        ("reject_latency", current_u, cal.L_max * 1.10 + 1.0, 0),
        ("reject_semantic_repeatability", current_u, low_latency, 1),
    ]
    if noninferior_bad_u < cal.U_max:
        scenarios.append(("reject_U_noninferiority", noninferior_bad_u, low_latency, 0))

    current = [fake_run(current_u, low_latency) for _ in range(15)]
    rows = []
    for name, candidate_u, latency, mismatches in scenarios:
        candidate = [fake_run(candidate_u, latency) for _ in range(15)]
        accepted, result = legacy.gate_candidate(current, candidate, mismatches, cal)
        rows.append({
            "scenario": name,
            "accepted": int(accepted),
            "U_absolute": int(result["checks"]["U_absolute"]),
            "latency": int(result["checks"]["latency"]),
            "U_noninferiority": int(result["checks"]["U_noninferiority"]),
            "semantic_repeatability": int(result["checks"]["semantic_repeatability"]),
            "candidate_mean_U": result["candidate_mean_U"],
            "candidate_p95_ms": result["candidate_p95_ms"],
            "semantic_repeat_mismatches": mismatches,
        })

    expected = {
        "accepted_baseline": True,
        "reject_U_absolute": False,
        "reject_latency": False,
        "reject_semantic_repeatability": False,
        "reject_U_noninferiority": False,
    }
    failures = [
        row["scenario"] for row in rows
        if bool(row["accepted"]) != expected[row["scenario"]]
    ]
    output = Path(args.output).resolve()
    write_csv(output, rows)
    report = {
        "ok": not failures,
        "scenario_count": len(rows),
        "failed_scenarios": failures,
        "reference_calibration": str(calibration_path),
        "reference_calibration_sha256": sha256_file(calibration_path),
        "output_sha256": sha256_file(output),
        "scope_note": (
            "Threshold-level branch challenge. Real-output selectivity is assessed "
            "separately by run_gate_stress.py."
        ),
    }
    write_json(output.with_suffix(".summary.json"), report)
    print(json.dumps(report, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())

