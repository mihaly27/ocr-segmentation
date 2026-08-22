#!/usr/bin/env python3
"""Construct the confirmatory three-coordinate W from two new Phase-1 scans."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from recalib_common import load_json, load_yaml, sha256_file, write_json


def selected_sensitivity(summary: dict[str, Any], coordinate: str) -> float:
    try:
        value = summary["finite_difference"]["coordinates"][coordinate][
            "selected_response_sensitivity"
        ]
    except KeyError as exc:
        raise ValueError(f"Coordinate absent from Phase-1 summary: {coordinate}") from exc
    return float(value or 0.0)


def selected_ids(path: Path) -> list[str]:
    obj = load_json(path)
    if not isinstance(obj, list):
        raise ValueError(f"Expected a list in {path}")
    return [str(row["id"]) for row in obj]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--local-summary", required=True)
    parser.add_argument("--switch-summary", required=True)
    parser.add_argument("--local-selected", required=True)
    parser.add_argument("--switch-selected", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    protocol_path = Path(args.protocol).resolve()
    local_path = Path(args.local_summary).resolve()
    switch_path = Path(args.switch_summary).resolve()
    local_selected_path = Path(args.local_selected).resolve()
    switch_selected_path = Path(args.switch_selected).resolve()

    protocol = load_yaml(protocol_path)
    local = load_json(local_path)
    switching = load_json(switch_path)
    active = list(protocol["parameter_space"]["coordinates"])
    d_diag = [float(x) for x in protocol["parameter_space"]["normalization_D_diag"]]
    lam = float(protocol["w_calibration"]["regularization_lambda"])

    local_ids = selected_ids(local_selected_path)
    switch_ids = selected_ids(switch_selected_path)
    if local_ids != switch_ids:
        raise SystemExit(
            "Local and switching scans did not use the identical frozen sample order"
        )
    expected_n = int(protocol["w_calibration"]["sample_n"])
    if len(local_ids) != expected_n:
        raise SystemExit(f"Phase-1 sample count {len(local_ids)} != frozen {expected_n}")

    coordinate_rows = []
    active_sensitivities = []
    all_coordinates = sorted(set(
        local["finite_difference"]["coordinates"]
    ) | set(switching["finite_difference"]["coordinates"]))
    for coordinate in all_coordinates:
        s_local = selected_sensitivity(local, coordinate)
        s_switch = selected_sensitivity(switching, coordinate)
        selected = max(s_local, s_switch)
        is_active = coordinate in active
        if is_active:
            if selected <= 0.0:
                raise SystemExit(
                    f"Frozen active coordinate has zero new sensitivity: {coordinate}"
                )
            active_sensitivities.append(selected)
        coordinate_rows.append({
            "coordinate": coordinate,
            "in_frozen_active_set": is_active,
            "local_selected_response_sensitivity": s_local,
            "switching_selected_response_sensitivity": s_switch,
            "combined_sensitivity": selected,
        })

    scale_reference = float(statistics.median(active_sensitivities))
    combined_by_name = {row["coordinate"]: row["combined_sensitivity"]
                        for row in coordinate_rows}
    w_diag = [lam + float(combined_by_name[name]) / scale_reference for name in active]
    w_theta_diag = [w / (d * d) for w, d in zip(w_diag, d_diag)]

    result = {
        "version": "recalibration_W_v1",
        "active_set_policy": protocol["parameter_space"]["active_set_policy"],
        "coordinates": active,
        "D_diag": d_diag,
        "aggregation_rule": protocol["w_calibration"]["aggregation"],
        "regularization_lambda": lam,
        "scale_reference": scale_reference,
        "W_z_diag": w_diag,
        "W_theta_diag": w_theta_diag,
        "coordinate_diagnostics": coordinate_rows,
        "sample_count": len(local_ids),
        "sample_ids_sha256": __import__("hashlib").sha256(
            ("\n".join(local_ids) + "\n").encode("utf-8")
        ).hexdigest(),
        "inputs": {
            "protocol": {"path": str(protocol_path), "sha256": sha256_file(protocol_path)},
            "local_summary": {"path": str(local_path), "sha256": sha256_file(local_path)},
            "switch_summary": {"path": str(switch_path), "sha256": sha256_file(switch_path)},
            "local_selected": {
                "path": str(local_selected_path), "sha256": sha256_file(local_selected_path)
            },
            "switch_selected": {
                "path": str(switch_selected_path), "sha256": sha256_file(switch_selected_path)
            },
        },
    }
    output = Path(args.output).resolve()
    write_json(output, result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

