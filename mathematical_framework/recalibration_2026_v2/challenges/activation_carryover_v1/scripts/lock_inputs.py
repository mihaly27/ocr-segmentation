#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from challenge_common import load_json, load_yaml, sha256_file, verify_package_manifest, write_json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--generator", required=True)
    ap.add_argument("--protocol", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    repo = Path(args.repo_root).resolve()
    generator = Path(args.generator).resolve()
    protocol_path = Path(args.protocol).resolve()
    output = Path(args.output).resolve()
    protocol = load_yaml(protocol_path)
    challenge_root = protocol_path.parent
    v2 = repo / "mathematical_framework" / "recalibration_2026_v2"
    v1 = repo / "mathematical_framework" / "recalibration_2026"
    selection_path = v2 / "outputs" / "delta_selection" / "selected_delta.json"
    w_path = v1 / "outputs" / "w_calibration.json"
    selection = load_json(selection_path)
    w_obj = load_json(w_path)
    expected = protocol["frozen_inputs"]
    if float(selection.get("selected_delta_W", -1)) != float(expected["selected_delta_W"]):
        raise SystemExit("Selected V2 delta differs from challenge protocol")
    if [float(x) for x in w_obj["W_z_diag"]] != [float(x) for x in expected["W_z_diag"]]:
        raise SystemExit("V2 W differs from challenge protocol")
    files = [
        ("v2_protocol", v2 / "protocol.yaml"),
        ("v2_input_lock", v2 / "v2_input_lock.json"),
        ("v2_selected_delta", selection_path),
        ("v1_independent_W", w_path),
        ("v1_phase1_selected", v1 / "outputs" / "w_phase1_local" / "selected_samples.json"),
        ("v1_W_annotations", v1 / "corpora" / "w_calibration" / "annotations.jsonl"),
        ("frozen_gate_thresholds", v2 / "outputs" / "confirmation" / "trajectory_86082721" / "confirmatory_main" / "reference_calibration.json"),
        ("historical_engine", repo / "mathematical_framework" / "ips_main_experiment.py"),
        ("base_pipeline_config", repo / "ips_single_image" / "config.yaml"),
        ("synthetic_generator", generator),
        ("v2_compose_manifest", v2 / "scripts" / "compose_manifest.py"),
        ("v2_partition_adapter", v2 / "scripts" / "v2_partition.py"),
        ("challenge_package_manifest", challenge_root / "PACKAGE_CONTENTS.sha256"),
    ]
    missing = [str(path) for _, path in files if not path.is_file()]
    if missing:
        raise SystemExit("Missing locked inputs: " + ", ".join(missing))
    verify_package_manifest(challenge_root / "PACKAGE_CONTENTS.sha256")
    result = {
        "version": "v21_activation_carryover_input_lock_v1",
        "status": "v21_inputs_locked_before_generation",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo),
        "protocol": {"path": str(protocol_path), "sha256": sha256_file(protocol_path)},
        "locked_files": [
            {"role": role, "path": str(path.resolve()), "sha256": sha256_file(path)}
            for role, path in files
        ],
    }
    if output.exists():
        old = load_json(output)
        comparable_old = {k: v for k, v in old.items() if k != "created_at_utc"}
        comparable_new = {k: v for k, v in result.items() if k != "created_at_utc"}
        if comparable_old != comparable_new:
            raise SystemExit("Existing V2.1 input lock differs; refusing overwrite")
        print(json.dumps(old, indent=2))
        return 0
    write_json(output, result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
