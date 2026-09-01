#!/usr/bin/env python3
"""Independent read-only audit of the frozen V2 recalibration evidence bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.stats import binomtest, spearmanr
from sklearn.metrics import average_precision_score, roc_auc_score


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_state(label: str) -> np.ndarray:
    parts = {}
    for item in str(label).split(";"):
        key, value = item.split("=", 1)
        parts[key] = float(value)
    return np.asarray([parts["rsplit"], parts["wprior"], parts["gblock"]])


def finite_or_none(value: float) -> float | None:
    return None if not math.isfinite(float(value)) else float(value)


def cluster_bootstrap(values: list[float], seed: int = 20260830, n_boot: int = 100000):
    values_arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    draws = rng.choice(values_arr, size=(n_boot, len(values_arr)), replace=True).mean(axis=1)
    return [float(x) for x in np.quantile(draws, [0.025, 0.975])]


def cp_upper_zero(n: int, alpha: float = 0.05) -> float | None:
    return None if n <= 0 else float(1.0 - alpha ** (1.0 / n))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    output = Path(args.output).resolve()
    v2 = repo / "mathematical_framework" / "recalibration_2026_v2"
    conf_root = v2 / "outputs" / "confirmation"
    protocol_path = v2 / "protocol.yaml"
    w_path = repo / "mathematical_framework" / "recalibration_2026" / "outputs" / "w_calibration.json"
    selection_path = v2 / "outputs" / "delta_selection" / "selected_delta.json"
    grid_summary_path = v2 / "outputs" / "delta_selection" / "delta_calibration_summary.csv"
    grid_condition_path = v2 / "outputs" / "delta_selection" / "delta_calibration_by_condition.csv"

    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    w_obj = json.loads(w_path.read_text(encoding="utf-8"))
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    seeds = [str(x) for x in protocol["confirmation"]["trajectory_generator_seeds"]]
    controllers = list(protocol["confirmation"]["controllers"])
    margins = protocol["noninferiority_margins"]
    delta = float(selection["selected_delta_W"])
    delta_i = float(selection["selected_delta_I_volume_matched"])
    w = np.asarray(w_obj["W_z_diag"], dtype=float)
    d = np.asarray(w_obj["D_diag"], dtype=float)

    sample_frames = []
    window_frames = []
    event_frames = []
    reference_calibrations = {}
    for seed in seeds:
        main_dir = conf_root / f"trajectory_{seed}" / "confirmatory_main"
        for name, target in (
            ("sample_results.csv", sample_frames),
            ("window_results.csv", window_frames),
            ("controller_events.csv", event_frames),
        ):
            frame = pd.read_csv(main_dir / name)
            frame.insert(0, "trajectory_seed", seed)
            target.append(frame)
        reference_calibrations[seed] = json.loads(
            (main_dir / "reference_calibration.json").read_text(encoding="utf-8")
        )

    samples = pd.concat(sample_frames, ignore_index=True)
    windows = pd.concat(window_frames, ignore_index=True)
    events = pd.concat(event_frames, ignore_index=True)
    for col in ("plate_accuracy", "char_accuracy", "dseg", "dbox", "U", "total_ms", "search_ms"):
        samples[col] = pd.to_numeric(samples[col], errors="coerce")
    for col in ("plate_accuracy", "char_accuracy", "mean_dseg", "mean_dbox", "mean_U", "mean_total_ms", "p95_total_ms", "outside_stable_region"):
        windows[col] = pd.to_numeric(windows[col], errors="coerce")
    for col in ("trigger", "projection_active", "raw_weighted_norm", "committed_update_norm", "rollback", "fail_safe", "gate_accepted"):
        events[col] = pd.to_numeric(events[col], errors="coerce")

    result: dict[str, object] = {
        "version": "independent_v2_evidence_audit_v1",
        "inputs": {
            "repo_root": str(repo),
            "protocol_sha256": sha256(protocol_path),
            "W_sha256": sha256(w_path),
            "selected_delta_sha256": sha256(selection_path),
        },
        "selected_geometry": {
            "coordinates": w_obj["coordinates"],
            "D_diag": d.tolist(),
            "W_z_diag": w.tolist(),
            "W_theta_diag": w_obj["W_theta_diag"],
            "delta_W": delta,
            "delta_I": delta_i,
            "delta_I_recomputed": float(delta / (np.prod(w) ** (1.0 / (2.0 * len(w))))),
        },
    }

    # Radius relative to the full frozen raw grid.
    levels = [np.asarray(x, dtype=float) for x in protocol["parameter_space"]["raw_grid_levels"]]
    grid = np.asarray(np.meshgrid(*levels, indexing="ij")).reshape(3, -1).T
    ref = np.asarray(protocol["parameter_space"]["reference_state"], dtype=float)
    dist = lambda a, b, weights: float(np.sqrt(np.sum(weights * ((b - a) / d) ** 2)))
    result["selected_geometry"].update({
        "max_W_distance_reference_to_raw_grid": max(dist(ref, x, w) for x in grid),
        "max_W_distance_between_raw_grid_states": max(dist(a, b, w) for a in grid for b in grid),
        "raw_grid_states_outside_selected_radius_from_reference": int(sum(dist(ref, x, w) > delta + 1e-12 for x in grid)),
        "raw_grid_state_count": int(len(grid)),
    })

    # Delta calibration, including condition-specific exact bounds.
    grid_summary = pd.read_csv(grid_summary_path)
    grid_conditions = pd.read_csv(grid_condition_path)
    selected_row = grid_summary[np.isclose(grid_summary["delta_W"], delta)].iloc[0]
    selected_conditions = grid_conditions[np.isclose(grid_conditions["delta_W"], delta)]
    condition_calibration = {}
    for row in selected_conditions.to_dict("records"):
        n = int(row["informative_events"])
        h = int(row["harm_events"])
        condition_calibration[str(row["condition"])] = {
            "trajectory_count": int(row["trajectory_count"]),
            "informative_events": n,
            "harm_events": h,
            "nonzero_commits": int(row["nonzero_commits"]),
            "update_coverage": float(row["update_coverage"]),
            "one_sided_upper95": cp_upper_zero(n) if h == 0 else None,
        }
    result["delta_calibration"] = {
        "selected_row": {
            "informative_events": int(selected_row["informative_events"]),
            "harm_events": int(selected_row["harm_events"]),
            "one_sided_upper95": float(selected_row["harm_upper_exact_one_sided"]),
            "nonzero_commits": int(selected_row["nonzero_commits"]),
            "update_coverage": float(selected_row["update_coverage"]),
        },
        "eligible_grid_values": selection["eligible_grid_values"],
        "condition_specific": condition_calibration,
    }

    # Per-trajectory means and paired B3-B0 effect estimates.
    metric_cols = ["plate_accuracy", "char_accuracy", "dseg", "dbox"]
    trajectory_means = (
        samples.groupby(["trajectory_seed", "controller"], sort=True)[metric_cols]
        .mean()
        .reset_index()
    )
    paired = []
    effect_summary = {}
    for seed in seeds:
        seed_means = trajectory_means[trajectory_means["trajectory_seed"] == seed].set_index("controller")
        row = {"trajectory_seed": seed}
        for metric in metric_cols:
            row[f"B3_minus_B0_{metric}"] = float(seed_means.loc["B3", metric] - seed_means.loc["B0", metric])
        paired.append(row)
    for metric in metric_cols:
        values = [float(x[f"B3_minus_B0_{metric}"]) for x in paired]
        nonzero = [x for x in values if abs(x) > 1e-15]
        positive = sum(x > 0 for x in nonzero)
        negative = sum(x < 0 for x in nonzero)
        effect_summary[metric] = {
            "trajectory_differences": values,
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "sd": float(np.std(values, ddof=1)),
            "min": float(np.min(values)),
            "max": float(np.max(values)),
            "trajectory_cluster_bootstrap_percentile95": cluster_bootstrap(values),
            "positive": positive,
            "negative": negative,
            "ties": len(values) - len(nonzero),
            "exact_sign_test_two_sided_p": (
                float(binomtest(positive, len(nonzero), 0.5, alternative="two-sided").pvalue)
                if nonzero else None
            ),
        }
    result["confirmation_paired_B3_minus_B0"] = {
        "trajectory_count": len(seeds),
        "per_trajectory": paired,
        "summary": effect_summary,
        "bootstrap_caution": "Only five independent trajectory clusters; intervals are descriptive and unstable.",
    }

    # Exact output equivalence of B3 and each adaptive ablation.
    key = ["trajectory_seed", "block_index", "sample_id"]
    compare_cols = ["state", "pred", "plate_accuracy", "char_accuracy", "dseg", "dbox", "U", "semantic_trace_hash"]
    b3 = samples[samples["controller"] == "B3"][key + compare_cols].copy()
    equality = {}
    for controller in ["B1", "B2", "B3-I", "B3-R0"]:
        other = samples[samples["controller"] == controller][key + compare_cols].copy()
        merged = b3.merge(other, on=key, suffixes=("_B3", "_other"), how="outer", indicator=True)
        mismatches = 0
        mismatch_by_col = {}
        for col in compare_cols:
            a = merged[f"{col}_B3"]
            b = merged[f"{col}_other"]
            if pd.api.types.is_numeric_dtype(a):
                bad = ~(np.isclose(a.astype(float), b.astype(float), equal_nan=True, atol=1e-12, rtol=0))
            else:
                bad = ~(a.fillna("<NA>").astype(str) == b.fillna("<NA>").astype(str))
            mismatch_by_col[col] = int(bad.sum())
            mismatches += int(bad.sum())
        equality[controller] = {
            "joined_rows": int(len(merged)),
            "nonmatching_keys": int((merged["_merge"] != "both").sum()),
            "field_mismatches_total": mismatches,
            "field_mismatches": mismatch_by_col,
            "exactly_equal_on_compared_outputs": bool(mismatches == 0 and (merged["_merge"] == "both").all()),
        }
    result["adaptive_controller_output_equivalence_to_B3"] = equality

    # Event-level trigger, proposal, projection, gate, and state behavior.
    event_summary = {}
    for controller in controllers:
        sub = events[events["controller"] == controller].copy()
        raw_dist_w = []
        raw_dist_controller = []
        nonzero_state_changes = 0
        for _, row in sub.iterrows():
            before = parse_state(row["state_before"])
            raw = parse_state(row["raw_candidate"])
            after = parse_state(row["state_after"])
            raw_dist_w.append(dist(before, raw, w))
            weights = np.ones(3) if controller == "B3-I" else w
            raw_dist_controller.append(dist(before, raw, weights))
            nonzero_state_changes += int(not np.allclose(before, after, atol=1e-12, rtol=0))
        decisions = Counter(sub["decision"].astype(str))
        gate_rows = sub[sub["gate_accepted"].notna()]
        event_summary[controller] = {
            "events": int(len(sub)),
            "triggers": int((sub["trigger"] == 1).sum()),
            "decisions": dict(sorted((str(k), int(v)) for k, v in decisions.items())),
            "decision_labels_starting_with_commit": int(sub["decision"].astype(str).str.startswith("commit").sum()),
            "nonzero_state_changes": int(nonzero_state_changes),
            "noop_commit_labels": int(sub["decision"].astype(str).str.startswith("commit").sum() - nonzero_state_changes),
            "projection_active": int((sub["projection_active"] == 1).sum()),
            "max_raw_distance_W_recomputed": float(max(raw_dist_w)),
            "max_raw_distance_controller_geometry_recomputed": float(max(raw_dist_controller)),
            "raw_proposals_over_controller_radius": int(sum(x > (delta_i if controller == "B3-I" else delta) + 1e-12 for x in raw_dist_controller)),
            "gate_evaluations": int(len(gate_rows)),
            "gate_rejections": int((gate_rows["gate_accepted"] == 0).sum()),
            "rollbacks": int((sub["rollback"] == 1).sum()),
            "fail_safe": int((sub["fail_safe"] == 1).sum()),
            "unique_final_states": sorted(sub["state_after"].astype(str).unique().tolist()),
        }
    result["confirmation_controller_events"] = event_summary

    # Exact B3/B0 per-window differences and post-hoc margin audit.
    b0w = windows[windows["controller"] == "B0"].copy()
    b3w = windows[windows["controller"] == "B3"].copy()
    wmerge = b3w.merge(
        b0w,
        on=["trajectory_seed", "block_index", "condition"],
        suffixes=("_B3", "_B0"),
        validate="one_to_one",
    )
    wmerge["delta_plate"] = wmerge["plate_accuracy_B3"] - wmerge["plate_accuracy_B0"]
    wmerge["delta_char"] = wmerge["char_accuracy_B3"] - wmerge["char_accuracy_B0"]
    wmerge["delta_dseg"] = wmerge["mean_dseg_B3"] - wmerge["mean_dseg_B0"]
    wmerge["plate_margin_violation"] = -wmerge["delta_plate"] > float(margins["full_plate_accuracy_drop"]) + 1e-12
    wmerge["char_margin_violation"] = -wmerge["delta_char"] > float(margins["character_accuracy_drop"]) + 1e-12
    wmerge["dseg_margin_violation"] = wmerge["delta_dseg"] > float(margins["mean_dseg_increase"]) + 1e-12
    wmerge["any_accuracy_or_dseg_margin_violation"] = wmerge[["plate_margin_violation", "char_margin_violation", "dseg_margin_violation"]].any(axis=1)
    condition_window = (
        wmerge.groupby("condition")[["delta_plate", "delta_char", "delta_dseg"]]
        .agg(["mean", "min", "max"])
    )
    condition_window.columns = ["_".join(x) for x in condition_window.columns]
    result["posthoc_window_B3_minus_B0"] = {
        "window_count": int(len(wmerge)),
        "plate_margin_violations": int(wmerge["plate_margin_violation"].sum()),
        "char_margin_violations": int(wmerge["char_margin_violation"].sum()),
        "dseg_margin_violations": int(wmerge["dseg_margin_violation"].sum()),
        "any_margin_violations": int(wmerge["any_accuracy_or_dseg_margin_violation"].sum()),
        "violating_windows": wmerge.loc[
            wmerge["any_accuracy_or_dseg_margin_violation"],
            ["trajectory_seed", "block_index", "condition", "delta_plate", "delta_char", "delta_dseg"],
        ].to_dict("records"),
        "by_condition": condition_window.reset_index().to_dict("records"),
        "scope_note": "Post-hoc B3-versus-B0 window comparison; not the preregistered before/after committed-update harm endpoint.",
    }

    # Stable-region flags and frozen latency thresholds.
    outside = windows[windows["outside_stable_region"] == 1].copy()
    outside_cols = ["trajectory_seed", "block_index", "condition", "controller", "state", "outside_reasons", "mean_U", "p95_total_ms", "plate_accuracy", "char_accuracy", "mean_dseg", "mean_dbox"]
    result["outside_stable_region"] = {
        "count": int(len(outside)),
        "rows": outside[outside_cols].to_dict("records"),
        "reference_thresholds_by_seed": {
            seed: {
                "U_max": reference_calibrations[seed]["U_max"],
                "L_max": reference_calibrations[seed]["L_max"],
                "tau_plate": reference_calibrations[seed]["tau_plate"],
                "tau_char": reference_calibrations[seed]["tau_char"],
                "tau_dseg": reference_calibrations[seed]["tau_dseg"],
                "tau_dbox": reference_calibrations[seed].get("tau_dbox"),
            }
            for seed in seeds
        },
    }

    # Label-free risk score construct validity, using B3 only and trajectory as cluster.
    b3s = samples[samples["controller"] == "B3"].copy()
    b3s["plate_error"] = 1.0 - b3s["plate_accuracy"]
    b3s["char_error"] = 1.0 - b3s["char_accuracy"]
    risk_rows = []
    for seed in seeds:
        sub = b3s[b3s["trajectory_seed"] == seed]
        auc = roc_auc_score(sub["plate_error"], sub["U"])
        ap = average_precision_score(sub["plate_error"], sub["U"])
        rho_plate = spearmanr(sub["U"], sub["plate_error"], nan_policy="omit").statistic
        rho_char = spearmanr(sub["U"], sub["char_error"], nan_policy="omit").statistic
        risk_rows.append({
            "trajectory_seed": seed,
            "roc_auc_plate_error": float(auc),
            "average_precision_plate_error": float(ap),
            "plate_error_prevalence": float(sub["plate_error"].mean()),
            "spearman_U_plate_error": finite_or_none(rho_plate),
            "spearman_U_char_error": finite_or_none(rho_char),
        })
    pooled_auc = roc_auc_score(b3s["plate_error"], b3s["U"])
    pooled_ap = average_precision_score(b3s["plate_error"], b3s["U"])
    coverage_rows = []
    for coverage in (0.2, 0.4, 0.6, 0.8, 1.0):
        retained = []
        for seed in seeds:
            sub = b3s[b3s["trajectory_seed"] == seed].sort_values(["U", "sample_id"], kind="stable")
            retained.append(sub.iloc[: int(round(len(sub) * coverage))])
        kept = pd.concat(retained, ignore_index=True)
        coverage_rows.append({
            "coverage": coverage,
            "n": int(len(kept)),
            "plate_error": float(kept["plate_error"].mean()),
            "char_error": float(kept["char_error"].mean()),
            "mean_U": float(kept["U"].mean()),
        })
    result["U_construct_validity_B3"] = {
        "per_trajectory": risk_rows,
        "mean_trajectory_roc_auc": float(np.mean([x["roc_auc_plate_error"] for x in risk_rows])),
        "min_trajectory_roc_auc": float(np.min([x["roc_auc_plate_error"] for x in risk_rows])),
        "max_trajectory_roc_auc": float(np.max([x["roc_auc_plate_error"] for x in risk_rows])),
        "pooled_roc_auc_descriptive": float(pooled_auc),
        "pooled_average_precision_descriptive": float(pooled_ap),
        "coverage_risk_lowest_U_retained": coverage_rows,
    }

    # Gate stress is deliberately separate and available for the first trajectory only.
    gate_path = conf_root / f"trajectory_{seeds[0]}" / "gate_stress.csv"
    gate = pd.read_csv(gate_path)
    bool_cols = ["accepted", "check_U_absolute", "check_latency", "check_U_noninferiority", "check_semantic_repeatability"]
    for col in bool_cols:
        gate[col] = pd.to_numeric(gate[col], errors="coerce").astype(int)
    gate["delta_plate"] = gate["candidate_plate_accuracy_delayed_gt"] - gate["current_plate_accuracy_delayed_gt"]
    gate["delta_char"] = gate["candidate_char_accuracy_delayed_gt"] - gate["current_char_accuracy_delayed_gt"]
    gate["delayed_accuracy_harm"] = (
        (-gate["delta_plate"] > float(margins["full_plate_accuracy_drop"]) + 1e-12)
        | (-gate["delta_char"] > float(margins["character_accuracy_drop"]) + 1e-12)
    )
    gate["rejected"] = gate["accepted"] == 0
    tp = int((gate["rejected"] & gate["delayed_accuracy_harm"]).sum())
    fp = int((gate["rejected"] & ~gate["delayed_accuracy_harm"]).sum())
    fn = int((~gate["rejected"] & gate["delayed_accuracy_harm"]).sum())
    tn = int((~gate["rejected"] & ~gate["delayed_accuracy_harm"]).sum())
    failure_combinations = Counter()
    for _, row in gate[gate["rejected"]].iterrows():
        failed = [col.removeprefix("check_") for col in bool_cols[1:] if int(row[col]) == 0]
        failure_combinations["+".join(failed) or "none"] += 1
    by_accept = gate.groupby("accepted")[["delta_plate", "delta_char"]].agg(["count", "mean", "min", "max"])
    by_accept.columns = ["_".join(x) for x in by_accept.columns]
    result["gate_stress"] = {
        "trajectory_seed": seeds[0],
        "rows": int(len(gate)),
        "accepted": int(gate["accepted"].sum()),
        "rejected": int((gate["accepted"] == 0).sum()),
        "by_condition": gate.groupby("condition")["accepted"].agg(["count", "sum"]).rename(columns={"sum": "accepted"}).reset_index().to_dict("records"),
        "rejection_failure_combinations": dict(sorted(failure_combinations.items())),
        "delayed_accuracy_harm_definition": "candidate-current plate drop > 0.05 OR character drop > 0.02; dseg cannot be paired because current dseg is absent",
        "rejection_vs_delayed_accuracy_harm": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "true_negative": tn,
            "sensitivity": None if tp + fn == 0 else tp / (tp + fn),
            "specificity": None if tn + fp == 0 else tn / (tn + fp),
            "positive_predictive_value": None if tp + fp == 0 else tp / (tp + fp),
        },
        "delayed_outcome_differences_by_acceptance": by_accept.reset_index().to_dict("records"),
        "rejected_but_nonworse_on_both_accuracy_metrics": int(((gate["rejected"]) & (gate["delta_plate"] >= -1e-12) & (gate["delta_char"] >= -1e-12)).sum()),
        "scope_note": "Single-trajectory, repeated-state stress audit; 81 rows are not 81 independent experimental units.",
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output), "sha256": sha256(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

