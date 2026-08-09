#!/usr/bin/env python3
"""Phase-1 calibration for the IPS bounded-adaptation case study.

Runs the existing ips_single_image/main.py artifact on a deterministic subset
under the reference config, repeated reference runs, and +/- one-step changes of
six operational coordinates.  It estimates a dimensionless diagonal
finite-difference sensitivity W and writes machine-readable outputs for the
paper's calibration stage.

This script intentionally does NOT implement the final B0--B3 controller.  Its
purpose is to obtain evidence needed to freeze W, hard ranges, determinism, and
candidate step sizes before the final controller comparison.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import yaml

# Coordinates are normalized by one development-calibrated step.  These are
# deliberately modest starting increments around the published/reference state;
# override with --steps-json if development inspection justifies other values.
DEFAULT_STEPS: Dict[str, float] = {
    "cut.min_rel_width_for_split": 0.10,
    "cut.max_column_sum_quantile": 0.025,
    "scoring.w_overlap": 1.0,
    "scoring.w_prior": 0.25,
    "scoring.rho_max": 0.025,
    "scoring.blocking_gap_ratio": 0.01,
}

NATURAL_BOUNDS: Dict[str, Tuple[float, float]] = {
    "cut.min_rel_width_for_split": (0.50, 4.00),
    "cut.max_column_sum_quantile": (0.001, 0.499),
    "scoring.w_overlap": (0.0, 50.0),
    "scoring.w_prior": (0.0, 20.0),
    "scoring.rho_max": (0.05, 0.99),
    "scoring.blocking_gap_ratio": (0.0, 0.50),
}

IMAGE_KEYS = ("image", "image_path", "path", "filename", "file")
GT_KEYS = ("gt", "text", "plate", "plate_text", "label", "ground_truth")
PERT_KEYS = ("perturbation", "perturbation_type", "condition", "class", "type")
ID_KEYS = ("id", "sample_id", "uid", "name")


def lev(a: str, b: str) -> int:
    a, b = str(a), str(b)
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            cur = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (ca != cb))
            prev = cur
    return dp[-1]


def norm_str_distance(a: str, b: str) -> float:
    return lev(a, b) / float(max(len(a), len(b), 1))


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax, ay, aw, ah = map(float, a)
    bx, by, bw, bh = map(float, b)
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    union = max(1e-12, aw * ah + bw * bh - inter)
    return inter / union


def best_iou_sum(a_boxes: Sequence[Sequence[float]], b_boxes: Sequence[Sequence[float]]) -> float:
    """Exact maximum matching by DP over bitmasks; suitable for ~6-char plates."""
    a = list(a_boxes)
    b = list(b_boxes)
    if not a or not b:
        return 0.0
    # Put smaller list on rows; unmatched boxes contribute zero.
    if len(a) > len(b):
        a, b = b, a
    n, m = len(a), len(b)
    scores = [[iou(a[i], b[j]) for j in range(m)] for i in range(n)]
    dp = {0: 0.0}
    for i in range(n):
        nxt: Dict[int, float] = {}
        for mask, val in dp.items():
            # Allow an unmatched row.
            nxt[mask] = max(nxt.get(mask, -1.0), val)
            for j in range(m):
                if mask & (1 << j):
                    continue
                nm = mask | (1 << j)
                nxt[nm] = max(nxt.get(nm, -1.0), val + scores[i][j])
        dp = nxt
    return max(dp.values())


def box_set_distance(a_boxes: Sequence[Sequence[float]], b_boxes: Sequence[Sequence[float]]) -> float:
    denom = max(len(a_boxes), len(b_boxes), 1)
    return 1.0 - best_iou_sum(a_boxes, b_boxes) / float(denom)


def get_dot(cfg: Dict[str, Any], dot: str) -> Any:
    cur: Any = cfg
    for p in dot.split("."):
        cur = cur[p]
    return cur


def set_dot(cfg: Dict[str, Any], dot: str, value: Any) -> None:
    cur: Any = cfg
    parts = dot.split(".")
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def choose_key(row: Dict[str, Any], candidates: Sequence[str]) -> str | None:
    lower = {str(k).lower(): str(k) for k in row}
    for c in candidates:
        if c in lower:
            return lower[c]
    return None


def load_manifest(path: Path) -> List[Dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as f:
            return [dict(r) for r in csv.DictReader(f)]
    if suffix in {".jsonl", ".ndjson"}:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if suffix == ".json":
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, list):
            return [dict(x) for x in obj]
        for key in ("samples", "items", "data", "records"):
            if isinstance(obj, dict) and isinstance(obj.get(key), list):
                return [dict(x) for x in obj[key]]
    raise ValueError(f"Unsupported/unknown manifest format: {path}")


def normalize_rows(rows: List[Dict[str, Any]], root: Path) -> List[Dict[str, Any]]:
    if not rows:
        raise ValueError("Manifest is empty")
    ik = choose_key(rows[0], IMAGE_KEYS)
    gk = choose_key(rows[0], GT_KEYS)
    pk = choose_key(rows[0], PERT_KEYS)
    idk = choose_key(rows[0], ID_KEYS)
    if ik is None or gk is None:
        raise ValueError(f"Could not infer image/GT columns. Columns: {list(rows[0])}")
    out = []
    for i, r in enumerate(rows):
        img = Path(str(r[ik]))
        if not img.is_absolute():
            img = root / img
        sid = str(r[idk]) if idk and str(r.get(idk, "")).strip() else f"row_{i:06d}"
        out.append({
            "id": sid,
            "image": str(img),
            "gt": str(r[gk]).strip(),
            "perturbation": str(r.get(pk, "unknown")).strip() if pk else "unknown",
        })
    return out


def deterministic_balanced_sample(rows: List[Dict[str, Any]], n: int, seed: str) -> List[Dict[str, Any]]:
    # Stable pseudo-random order from SHA256; approximately balance available classes.
    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["perturbation"], []).append(r)
    for cls in by:
        by[cls].sort(key=lambda r: hashlib.sha256((seed + "|" + r["id"]).encode()).hexdigest())
    classes = sorted(by)
    picked: List[Dict[str, Any]] = []
    indices = {c: 0 for c in classes}
    while len(picked) < min(n, len(rows)):
        progressed = False
        for c in classes:
            i = indices[c]
            if i < len(by[c]):
                picked.append(by[c][i])
                indices[c] += 1
                progressed = True
                if len(picked) >= n:
                    break
        if not progressed:
            break
    return picked


def write_yaml(path: Path, cfg: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


def run_artifact(task: Dict[str, Any]) -> Dict[str, Any]:
    repo = Path(task["repo"])
    sample = task["sample"]
    cfg_path = Path(task["cfg_path"])
    work = Path(task["work"])
    keep = bool(task["keep"])
    tag = task["tag"]
    outdir = work / tag / sample["id"]
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        task["python"], str(repo / "main.py"),
        "--image", sample["image"],
        "--outdir", str(outdir),
        "--config", str(cfg_path),
        "--gt", sample["gt"],
    ]
    cp = subprocess.run(cmd, cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, timeout=float(task["timeout"]))
    if cp.returncode != 0:
        return {"ok": False, "id": sample["id"], "tag": tag, "stderr": cp.stderr[-2000:]}
    try:
        res = json.loads((outdir / "result.json").read_text(encoding="utf-8"))
        tr = json.loads((outdir / "trace.json").read_text(encoding="utf-8"))
        selected = [x["bbox"] for x in tr.get("selected_segments", [])]
        initial = [x["bbox"] for x in tr.get("initial_segments", [])]
        br = tr.get("score_breakdown", {}) or {}
        row = {
            "ok": True,
            "id": sample["id"],
            "tag": tag,
            "perturbation": sample["perturbation"],
            "gt": sample["gt"],
            "pred": res.get("pred", ""),
            "char_accuracy": res.get("char_accuracy"),
            "plate_accuracy": res.get("full_plate_accuracy"),
            "trace_hash": res.get("trace_hash"),
            "total_ms": res.get("total_ms"),
            "search_ms": (tr.get("timings_ms", {}) or {}).get("search_ms"),
            "segment_count": (tr.get("metrics", {}) or {}).get("segment_count"),
            "expected_count": (tr.get("metrics", {}) or {}).get("expected_count"),
            "selected_boxes": selected,
            "initial_boxes": initial,
            "overlap_pen": ((br.get("overlap", {}) or {}).get("sum")),
            "density": ((br.get("prior", {}) or {}).get("density")),
            "density_pen": ((br.get("prior", {}) or {}).get("density_pen")),
            "blocking": ((br.get("prior", {}) or {}).get("blocking")),
        }
    except Exception as e:
        return {"ok": False, "id": sample["id"], "tag": tag, "stderr": f"parse: {e}"}
    if not keep:
        shutil.rmtree(outdir, ignore_errors=True)
    return row


def run_batch(tasks: List[Dict[str, Any]], workers: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run_artifact, t) for t in tasks]
        for i, f in enumerate(as_completed(futs), 1):
            out.append(f.result())
            if i % 50 == 0 or i == len(futs):
                print(f"completed {i}/{len(futs)}", flush=True)
    return out


def mean(xs: Iterable[float]) -> float | None:
    vals = [float(x) for x in xs if x is not None and math.isfinite(float(x))]
    return sum(vals) / len(vals) if vals else None


def percentile(xs: Iterable[float], q: float) -> float | None:
    vals = sorted(float(x) for x in xs if x is not None and math.isfinite(float(x)))
    if not vals:
        return None
    pos = (len(vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return vals[lo]
    return vals[lo] * (hi - pos) + vals[hi] * (pos - lo)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="Path to ocr-segmentation/ips_single_image")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--dataset-root", default=".")
    ap.add_argument("--output", default="phase1_calibration")
    ap.add_argument("--n", type=int, default=200, help="Balanced calibration sample count")
    ap.add_argument("--repeat-n", type=int, default=50, help="Reference samples rerun for hash identity")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--steps-json", default="", help="Optional JSON object overriding finite-difference steps")
    ap.add_argument("--keep-traces", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    base_cfg_path = repo / "config.yaml"
    if not (repo / "main.py").exists() or not base_cfg_path.exists():
        raise SystemExit("--repo must point to the directory containing main.py and config.yaml")
    base_cfg = yaml.safe_load(base_cfg_path.read_text(encoding="utf-8"))
    steps = dict(DEFAULT_STEPS)
    if args.steps_json:
        steps.update({k: float(v) for k, v in json.loads(args.steps_json).items()})

    rows = normalize_rows(load_manifest(Path(args.manifest)), Path(args.dataset_root).resolve())
    rows = [r for r in rows if Path(r["image"]).exists()]
    if not rows:
        raise SystemExit("No manifest images resolved on disk")
    chosen = deterministic_balanced_sample(rows, args.n, seed="IPS-FRAMEWORK-PHASE1-2026")

    out = Path(args.output).resolve()
    cfgdir, work = out / "configs", out / "runs"
    out.mkdir(parents=True, exist_ok=True)
    write_yaml(cfgdir / "reference.yaml", base_cfg)

    variants: Dict[str, Dict[str, Any]] = {"reference": base_cfg}
    for dot, h in steps.items():
        base = float(get_dot(base_cfg, dot))
        lo, hi = NATURAL_BOUNDS[dot]
        for sign, suffix in [(-1, "minus"), (1, "plus")]:
            val = min(hi, max(lo, base + sign * h))
            c = deepcopy(base_cfg)
            set_dot(c, dot, val)
            tag = dot.replace(".", "__") + "__" + suffix
            variants[tag] = c
            write_yaml(cfgdir / f"{tag}.yaml", c)

    tasks: List[Dict[str, Any]] = []
    for tag in variants:
        for sample in chosen:
            tasks.append({"repo": str(repo), "sample": sample, "cfg_path": str(cfgdir / f"{tag}.yaml" if tag != "reference" else cfgdir / "reference.yaml"),
                          "work": str(work), "keep": args.keep_traces, "tag": tag,
                          "python": args.python, "timeout": args.timeout})
    # Repeated reference executions use a distinct tag and a deterministic prefix.
    for sample in chosen[: min(args.repeat_n, len(chosen))]:
        tasks.append({"repo": str(repo), "sample": sample, "cfg_path": str(cfgdir / "reference.yaml"),
                      "work": str(work), "keep": args.keep_traces, "tag": "reference_repeat",
                      "python": args.python, "timeout": args.timeout})

    print(f"Running {len(tasks)} artifact executions on {len(chosen)} samples with {args.workers} workers")
    results = run_batch(tasks, args.workers)
    failed = [r for r in results if not r.get("ok")]
    if failed:
        (out / "failures.json").write_text(json.dumps(failed, indent=2), encoding="utf-8")
        print(f"WARNING: {len(failed)} executions failed; see failures.json", file=sys.stderr)
    ok = [r for r in results if r.get("ok")]

    # Machine-readable run table (selected_boxes serialized as JSON strings).
    fields = ["id","tag","perturbation","gt","pred","char_accuracy","plate_accuracy","trace_hash","total_ms","search_ms","segment_count","expected_count","overlap_pen","density","density_pen","blocking","selected_boxes"]
    with (out / "phase1_runs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in sorted(ok, key=lambda z: (z["id"], z["tag"])):
            rr = {k: r.get(k) for k in fields}
            rr["selected_boxes"] = json.dumps(rr["selected_boxes"], separators=(",", ":"))
            w.writerow(rr)

    by_key = {(r["id"], r["tag"]): r for r in ok}
    sensitivities: Dict[str, Dict[str, Any]] = {}
    for dot, h in steps.items():
        minus = dot.replace(".", "__") + "__minus"
        plus = dot.replace(".", "__") + "__plus"
        dy_vals = []
        for s in chosen:
            rm = by_key.get((s["id"], minus))
            rp = by_key.get((s["id"], plus))
            if not rm or not rp:
                continue
            ds = norm_str_distance(rm["pred"], rp["pred"])
            db = box_set_distance(rm["selected_boxes"], rp["selected_boxes"])
            kc = abs(int(rm["segment_count"] or 0) - int(rp["segment_count"] or 0)) / 6.0
            dy = 0.50 * ds + 0.35 * db + 0.15 * kc
            dy_vals.append(dy)
        # Coordinates are normalized in units of one configured step, so +/- is +/-1.
        s_j = mean((d / 2.0) ** 2 for d in dy_vals) or 0.0
        sensitivities[dot] = {"step": h, "n": len(dy_vals), "mean_output_discrepancy": mean(dy_vals), "step_normalized_sensitivity": s_j}

    nz = [v["step_normalized_sensitivity"] for v in sensitivities.values() if v["step_normalized_sensitivity"] > 0]
    scale = percentile(nz, 0.5) or 1.0
    lambda0 = 0.10
    W_diag = {k: lambda0 + v["step_normalized_sensitivity"] / scale for k, v in sensitivities.items()}

    refs = [r for r in ok if r["tag"] == "reference"]
    reps = [r for r in ok if r["tag"] == "reference_repeat"]
    repeat_map = {r["id"]: r for r in reps}
    mismatches = []
    for r in refs:
        q = repeat_map.get(r["id"])
        if q is not None:
            mismatches.append(int(r["trace_hash"] != q["trace_hash"]))

    summary = {
        "source_reference_config": str(base_cfg_path),
        "sample_count": len(chosen),
        "perturbation_counts": {c: sum(r["perturbation"] == c for r in chosen) for c in sorted({r["perturbation"] for r in chosen})},
        "reference": {
            "plate_accuracy_mean": mean(r["plate_accuracy"] for r in refs),
            "char_accuracy_mean": mean(r["char_accuracy"] for r in refs),
            "total_ms_mean": mean(r["total_ms"] for r in refs),
            "total_ms_p95": percentile((r["total_ms"] for r in refs), 0.95),
            "search_ms_mean": mean(r["search_ms"] for r in refs),
            "trace_repeat_n": len(mismatches),
            "trace_hash_mismatch_rate": mean(mismatches),
        },
        "finite_difference": sensitivities,
        "W_construction": {
            "coordinate_normalization": "one finite-difference step = 1 normalized unit",
            "lambda": lambda0,
            "median_nonzero_sensitivity": scale,
            "W_diag": W_diag,
        },
        "note": "Phase-1 calibration only. Freeze reviewed steps/ranges/W before running B0-B3 final trajectories.",
    }
    (out / "phase1_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "selected_samples.json").write_text(json.dumps(chosen, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
