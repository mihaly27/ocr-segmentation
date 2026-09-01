#!/usr/bin/env python3
"""Independent aggregate audit; harm is a result, not an integrity failure."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from challenge_common import load_json, load_yaml, sequence_by_seed, sha256_file, verify_lock, write_json


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def truth(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--protocol", required=True); ap.add_argument("--input-lock", required=True)
    ap.add_argument("--output-root", required=True); ap.add_argument("--output", required=True)
    args = ap.parse_args()
    protocol_path = Path(args.protocol).resolve(); lock_path = Path(args.input_lock).resolve()
    protocol = load_yaml(protocol_path); verify_lock(lock_path, protocol_path)
    root = Path(args.output_root).resolve(); errors: list[str] = []
    seeds = sorted(sequence_by_seed(protocol)); all_events=[]; all_carry=[]; all_stress=[]
    expected = {"controller_events.csv": 42, "window_results.csv": 42,
                "carryover_events.csv": 10, "projection_gate_stress.csv": 81}
    completed = 0
    for seed in seeds:
        d = root / f"trajectory_{seed}"; sp = d / "summary.json"
        if not sp.is_file(): errors.append(f"missing summary seed={seed}"); continue
        summary = load_json(sp)
        if not summary.get("ok") or int(summary.get("seed", -1)) != seed:
            errors.append(f"invalid summary seed={seed}"); continue
        completed += 1
        for name, count in expected.items():
            p = d / name
            if not p.is_file(): errors.append(f"missing {name} seed={seed}"); continue
            rr = rows(p)
            if len(rr) != count: errors.append(f"{name} seed={seed}: {len(rr)} != {count}")
            if name == "controller_events.csv": all_events.extend(rr)
            elif name == "carryover_events.csv": all_carry.extend(rr)
            elif name == "projection_gate_stress.csv": all_stress.extend(rr)

    pair_controller = Counter((r["ordered_pair"], r["controller"]) for r in all_carry)
    for pair in protocol["challenge_layers"]["carryover"]["ordered_pairs"]:
        for controller in protocol["design"]["controllers"]:
            if controller == "B0": continue
            n = pair_controller[(pair, controller)]
            if n != int(protocol["design"]["expected_ordered_pair_replicates"]):
                errors.append(f"ordered pair {pair}/{controller}: {n} != 6")
    carry_groups: dict[str, Any] = {}
    grouped = defaultdict(list)
    for r in all_carry: grouped[(r["ordered_pair"], r["controller"])].append(r)
    for (pair, controller), rr in sorted(grouped.items()):
        carry_groups[f"{pair}/{controller}"] = {
            "n": len(rr), "state_differs_from_reference": sum(truth(r["state_differs_from_reference"]) for r in rr),
            "any_harm": sum(truth(r["any_harm"]) for r in rr),
            "plate_harm": sum(truth(r["plate_harm"]) for r in rr),
            "char_harm": sum(truth(r["char_harm"]) for r in rr),
            "dseg_harm": sum(truth(r["dseg_harm"]) for r in rr),
            "latency_violation": sum(truth(r["latency_violation"]) for r in rr),
        }
    projection_selected = sum(truth(r["projection_active"]) for r in all_events)
    nonzero_changes = sum(truth(r["nonzero_state_change"]) for r in all_events)
    gate_events = [r for r in all_events if r.get("gate_accepted", "") not in ("", "None")]
    stress_projected = [r for r in all_stress if truth(r["projection_active"])]
    accepted = [r for r in all_stress if truth(r["gate_accepted"])]
    rejected = [r for r in all_stress if not truth(r["gate_accepted"])]
    report = {
        "version": "v21_activation_carryover_audit_v1", "technical_ok": not errors,
        "technical_errors": errors, "completed_trajectories": completed, "expected_trajectories": len(seeds),
        "scientific_result": {
            "selected_path": {"projection_active_events": projection_selected, "nonzero_state_changes": nonzero_changes,
                              "gate_events": len(gate_events), "gate_rejections": sum(not truth(r["gate_accepted"]) for r in gate_events)},
            "counterfactual_stress": {"rows": len(all_stress), "projection_active": len(stress_projected),
                "accepted": len(accepted), "rejected": len(rejected),
                "accepted_harm_vs_current": sum(truth(r["harm_vs_current"]) for r in accepted),
                "rejected_harm_vs_current": sum(truth(r["harm_vs_current"]) for r in rejected),
                "accepted_harm_vs_reference": sum(truth(r["harm_vs_reference"]) for r in accepted),
                "rejected_harm_vs_reference": sum(truth(r["harm_vs_reference"]) for r in rejected)},
            "carryover_by_pair_and_controller": carry_groups,
            "carryover_total": {"rows": len(all_carry), "state_differs_from_reference": sum(truth(r["state_differs_from_reference"]) for r in all_carry),
                                "any_harm": sum(truth(r["any_harm"]) for r in all_carry)},
        },
        "interpretation": "technical_ok covers completeness and provenance only; scientific results may be adverse",
        "protocol_sha256": sha256_file(protocol_path), "input_lock_sha256": sha256_file(lock_path),
    }
    write_json(Path(args.output).resolve(), report)
    print(json.dumps(report, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
