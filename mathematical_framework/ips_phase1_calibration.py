#!/usr/bin/env python3
"""Phase-1 calibration v2 for the IPS bounded-adaptation case study.

Changes relative to v1
----------------------
1. Computes a semantic trace hash that excludes runtime/timing fields while
   retaining the processing semantics (config, ordered candidates/search
   history, score decomposition, selected segments, OCR output and metrics).
2. Uses multi-scale finite perturbations h, 2h, 4h by default.
3. Detects one-sided and symmetric output changes relative to the reference,
   which is important for piecewise-constant / non-differentiable pipelines.
4. Selects, for each coordinate, the smallest perturbation scale that produces
   an observable end-to-end response.
5. Reports both raw artifact-hash repeatability and semantic-hash repeatability.

This script intentionally does NOT implement the final B0--B3 controller. Its
purpose is to obtain evidence needed to freeze W, hard ranges, determinism and
candidate step sizes before the final controller comparison.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import yaml


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

# Deliberately excludes timings_ms and the repository's own trace_hash.
SEMANTIC_TRACE_KEYS = (
    "input",
    "config",
    "initial_segments",
    "selected_segments",
    "search_history",
    "score_breakdown",
    "ocr",
    "metrics",
)


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


def best_iou_sum(
    a_boxes: Sequence[Sequence[float]],
    b_boxes: Sequence[Sequence[float]],
) -> float:
    """Exact maximum matching by DP over bitmasks; suitable for ~6-char plates."""
    a = list(a_boxes)
    b = list(b_boxes)
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    n, m = len(a), len(b)
    scores = [[iou(a[i], b[j]) for j in range(m)] for i in range(n)]
    dp = {0: 0.0}
    for i in range(n):
        nxt: Dict[int, float] = {}
        for mask, val in dp.items():
            nxt[mask] = max(nxt.get(mask, -1.0), val)  # unmatched row
            for j in range(m):
                if mask & (1 << j):
                    continue
                nm = mask | (1 << j)
                nxt[nm] = max(nxt.get(nm, -1.0), val + scores[i][j])
        dp = nxt
    return max(dp.values())


def box_set_distance(
    a_boxes: Sequence[Sequence[float]],
    b_boxes: Sequence[Sequence[float]],
) -> float:
    denom = max(len(a_boxes), len(b_boxes), 1)
    return 1.0 - best_iou_sum(a_boxes, b_boxes) / float(denom)


def output_distance(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """End-to-end output discrepancy used for finite perturbation response.

    We retain the same transparent decomposition used in phase-1 v1:
      50% OCR-string discrepancy
      35% selected-box discrepancy
      15% segment-count discrepancy

    The count term is normalized by the configured expected character count.
    """
    ds = norm_str_distance(a.get("pred", ""), b.get("pred", ""))
    db = box_set_distance(a.get("selected_boxes", []), b.get("selected_boxes", []))
    exp = max(
        int(a.get("expected_count") or 0),
        int(b.get("expected_count") or 0),
        1,
    )
    kc = abs(
        int(a.get("segment_count") or 0) - int(b.get("segment_count") or 0)
    ) / float(exp)
    return 0.50 * ds + 0.35 * db + 0.15 * kc


def canonicalize(obj: Any, float_digits: int = 12) -> Any:
    """Recursively canonicalize JSON-compatible data for semantic hashing."""
    if isinstance(obj, dict):
        return {
            str(k): canonicalize(v, float_digits)
            for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(obj, list):
        return [canonicalize(v, float_digits) for v in obj]
    if isinstance(obj, tuple):
        return [canonicalize(v, float_digits) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj):
            return "NaN"
        if math.isinf(obj):
            return "Infinity" if obj > 0 else "-Infinity"
        return round(obj, float_digits)
    return obj


def semantic_trace_payload(trace: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for k in SEMANTIC_TRACE_KEYS:
        if k not in trace:
            continue
        if k == "input" and isinstance(trace[k], dict):
            # Absolute filesystem location is not part of processing semantics.
            inp = dict(trace[k])
            inp.pop("image", None)
            payload[k] = inp
        else:
            payload[k] = trace[k]
    return payload


def semantic_trace_hash(trace: Dict[str, Any], float_digits: int = 12) -> str:
    payload = canonicalize(semantic_trace_payload(trace), float_digits)
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if suffix == ".json":
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, list):
            return [dict(x) for x in obj]
        for key in ("samples", "items", "data", "records"):
            if isinstance(obj, dict) and isinstance(obj.get(key), list):
                return [dict(x) for x in obj[key]]
    raise ValueError(f"Unsupported/unknown manifest format: {path}")


def resolve_image_path(raw: str, root: Path, manifest_parent: Path) -> Path:
    p = Path(str(raw))
    if p.is_absolute():
        return p

    # Explicit dataset root has priority. Manifest-relative and CWD-relative
    # fallbacks make the runner robust to the two common manifest conventions.
    candidates = [
        root / p,
        manifest_parent / p,
        Path.cwd() / p,
    ]
    for q in candidates:
        if q.exists():
            return q.resolve()
    return candidates[0].resolve()


def normalize_rows(
    rows: List[Dict[str, Any]],
    root: Path,
    manifest_parent: Path,
) -> List[Dict[str, Any]]:
    if not rows:
        raise ValueError("Manifest is empty")
    ik = choose_key(rows[0], IMAGE_KEYS)
    gk = choose_key(rows[0], GT_KEYS)
    pk = choose_key(rows[0], PERT_KEYS)
    idk = choose_key(rows[0], ID_KEYS)
    if ik is None or gk is None:
        raise ValueError(
            f"Could not infer image/GT columns. Columns: {list(rows[0])}"
        )

    out = []
    for i, r in enumerate(rows):
        img = resolve_image_path(str(r[ik]), root, manifest_parent)
        sid = (
            str(r[idk])
            if idk and str(r.get(idk, "")).strip()
            else f"row_{i:06d}"
        )
        out.append(
            {
                "id": sid,
                "image": str(img),
                "gt": str(r[gk]).strip(),
                "perturbation": (
                    str(r.get(pk, "unknown")).strip() if pk else "unknown"
                ),
            }
        )
    return out


def deterministic_balanced_sample(
    rows: List[Dict[str, Any]],
    n: int,
    seed: str,
) -> List[Dict[str, Any]]:
    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["perturbation"], []).append(r)

    for cls in by:
        by[cls].sort(
            key=lambda r: hashlib.sha256(
                (seed + "|" + r["id"]).encode()
            ).hexdigest()
        )

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
    float_digits = int(task.get("semantic_float_digits", 12))

    outdir = work / tag / sample["id"]
    outdir.mkdir(parents=True, exist_ok=True)

    cmd = [
        task["python"],
        str(repo / "main.py"),
        "--image",
        sample["image"],
        "--outdir",
        str(outdir),
        "--config",
        str(cfg_path),
        "--gt",
        sample["gt"],
    ]

    cp = subprocess.run(
        cmd,
        cwd=str(repo),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=float(task["timeout"]),
    )

    if cp.returncode != 0:
        return {
            "ok": False,
            "id": sample["id"],
            "tag": tag,
            "stderr": cp.stderr[-2000:],
        }

    try:
        res = json.loads(
            (outdir / "result.json").read_text(encoding="utf-8")
        )
        tr = json.loads(
            (outdir / "trace.json").read_text(encoding="utf-8")
        )

        selected = [
            x["bbox"] for x in tr.get("selected_segments", [])
        ]
        initial = [
            x["bbox"] for x in tr.get("initial_segments", [])
        ]
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
            "semantic_trace_hash": semantic_trace_hash(
                tr, float_digits=float_digits
            ),
            "total_ms": res.get("total_ms"),
            "search_ms": (
                (tr.get("timings_ms", {}) or {}).get("search_ms")
            ),
            "segment_count": (
                (tr.get("metrics", {}) or {}).get("segment_count")
            ),
            "expected_count": (
                (tr.get("metrics", {}) or {}).get("expected_count")
            ),
            "selected_boxes": selected,
            "initial_boxes": initial,
            "overlap_pen": (
                ((br.get("overlap", {}) or {}).get("sum"))
            ),
            "density": (
                ((br.get("prior", {}) or {}).get("density"))
            ),
            "density_pen": (
                ((br.get("prior", {}) or {}).get("density_pen"))
            ),
            "blocking": (
                ((br.get("prior", {}) or {}).get("blocking"))
            ),
        }
    except Exception as e:
        return {
            "ok": False,
            "id": sample["id"],
            "tag": tag,
            "stderr": f"parse: {e}",
        }

    if not keep:
        shutil.rmtree(outdir, ignore_errors=True)
    return row


def run_batch(
    tasks: List[Dict[str, Any]],
    workers: int,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run_artifact, t) for t in tasks]
        for i, f in enumerate(as_completed(futs), 1):
            out.append(f.result())
            if i % 50 == 0 or i == len(futs):
                print(f"completed {i}/{len(futs)}", flush=True)
    return out


def mean(xs: Iterable[float]) -> float | None:
    vals = [
        float(x)
        for x in xs
        if x is not None and math.isfinite(float(x))
    ]
    return sum(vals) / len(vals) if vals else None


def percentile(xs: Iterable[float], q: float) -> float | None:
    vals = sorted(
        float(x)
        for x in xs
        if x is not None and math.isfinite(float(x))
    )
    if not vals:
        return None
    pos = (len(vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return vals[lo]
    return vals[lo] * (hi - pos) + vals[hi] * (pos - lo)


def parse_scales(raw: str) -> List[float]:
    vals = []
    for x in raw.split(","):
        x = x.strip()
        if not x:
            continue
        v = float(x)
        if v <= 0:
            raise ValueError("All finite-difference scales must be > 0")
        vals.append(v)
    if not vals:
        raise ValueError("At least one finite-difference scale is required")
    return sorted(set(vals))


def scale_label(v: float) -> str:
    if float(v).is_integer():
        return str(int(v))
    return str(v).replace(".", "p")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--repo",
        required=True,
        help="Path to ocr-segmentation/ips_single_image",
    )
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--dataset-root", default=".")
    ap.add_argument("--output", default="phase1_calibration_v2")
    ap.add_argument(
        "--n",
        type=int,
        default=200,
        help="Balanced calibration sample count",
    )
    ap.add_argument(
        "--repeat-n",
        type=int,
        default=50,
        help="Reference samples rerun for raw/semantic hash identity",
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument(
        "--steps-json",
        default="",
        help="Optional JSON object overriding base finite-difference steps",
    )
    ap.add_argument(
        "--scales",
        default="1,2,4",
        help="Comma-separated perturbation scale factors; default: 1,2,4",
    )
    ap.add_argument(
        "--activity-eps",
        type=float,
        default=1e-12,
        help="Output-distance threshold above which a response is active",
    )
    ap.add_argument(
        "--semantic-float-digits",
        type=int,
        default=12,
        help="Float digits retained in semantic trace canonicalization",
    )
    ap.add_argument(
        "--keep-traces",
        action="store_true",
        help="Keep per-run artifact directories instead of removing them",
    )
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    manifest = Path(args.manifest).resolve()
    dataset_root = Path(args.dataset_root).resolve()
    out = Path(args.output).resolve()

    base_cfg_path = repo / "config.yaml"
    if not (repo / "main.py").exists() or not base_cfg_path.exists():
        raise SystemExit(
            "--repo must point to the directory containing main.py and config.yaml"
        )
    if not manifest.exists():
        raise SystemExit(f"Manifest not found: {manifest}")

    base_cfg = yaml.safe_load(
        base_cfg_path.read_text(encoding="utf-8")
    )

    steps = dict(DEFAULT_STEPS)
    if args.steps_json:
        steps.update(
            {k: float(v) for k, v in json.loads(args.steps_json).items()}
        )

    scales = parse_scales(args.scales)

    rows = normalize_rows(
        load_manifest(manifest),
        dataset_root,
        manifest.parent,
    )
    resolved_n = sum(Path(r["image"]).exists() for r in rows)
    rows = [r for r in rows if Path(r["image"]).exists()]
    if not rows:
        raise SystemExit(
            "No manifest images resolved on disk. "
            f"dataset_root={dataset_root}, manifest_parent={manifest.parent}"
        )

    print(
        f"Resolved {resolved_n}/{len(load_manifest(manifest))} manifest images",
        flush=True,
    )

    chosen = deterministic_balanced_sample(
        rows,
        args.n,
        seed="IPS-FRAMEWORK-PHASE1-V2-2026",
    )

    cfgdir = out / "configs"
    work = out / "runs"
    out.mkdir(parents=True, exist_ok=True)

    write_yaml(cfgdir / "reference.yaml", base_cfg)

    # variant_meta carries actual values and normalized radii after clamping.
    variants: Dict[str, Dict[str, Any]] = {"reference": base_cfg}
    variant_meta: Dict[str, Dict[str, Any]] = {}

    for dot, h in steps.items():
        base = float(get_dot(base_cfg, dot))
        lo, hi = NATURAL_BOUNDS[dot]

        for scale in scales:
            sval = scale_label(scale)
            minus_val = min(hi, max(lo, base - scale * h))
            plus_val = min(hi, max(lo, base + scale * h))

            for suffix, val in (
                ("minus", minus_val),
                ("plus", plus_val),
            ):
                c = deepcopy(base_cfg)
                set_dot(c, dot, val)
                tag = (
                    dot.replace(".", "__")
                    + f"__s{sval}__{suffix}"
                )
                variants[tag] = c
                variant_meta[tag] = {
                    "coordinate": dot,
                    "base_value": base,
                    "base_step": h,
                    "scale": scale,
                    "side": suffix,
                    "value": val,
                    "normalized_radius": abs(val - base) / h
                    if h > 0
                    else 0.0,
                }
                write_yaml(cfgdir / f"{tag}.yaml", c)

    tasks: List[Dict[str, Any]] = []

    for tag in variants:
        cfg_path = (
            cfgdir / "reference.yaml"
            if tag == "reference"
            else cfgdir / f"{tag}.yaml"
        )
        for sample in chosen:
            tasks.append(
                {
                    "repo": str(repo),
                    "sample": sample,
                    "cfg_path": str(cfg_path),
                    "work": str(work),
                    "keep": args.keep_traces,
                    "tag": tag,
                    "python": args.python,
                    "timeout": args.timeout,
                    "semantic_float_digits": args.semantic_float_digits,
                }
            )

    for sample in chosen[: min(args.repeat_n, len(chosen))]:
        tasks.append(
            {
                "repo": str(repo),
                "sample": sample,
                "cfg_path": str(cfgdir / "reference.yaml"),
                "work": str(work),
                "keep": args.keep_traces,
                "tag": "reference_repeat",
                "python": args.python,
                "timeout": args.timeout,
                "semantic_float_digits": args.semantic_float_digits,
            }
        )

    print(
        f"Running {len(tasks)} artifact executions on "
        f"{len(chosen)} samples with {args.workers} workers",
        flush=True,
    )

    results = run_batch(tasks, args.workers)

    failed = [r for r in results if not r.get("ok")]
    if failed:
        (out / "failures.json").write_text(
            json.dumps(failed, indent=2),
            encoding="utf-8",
        )
        print(
            f"WARNING: {len(failed)} executions failed; see failures.json",
            file=sys.stderr,
        )

    ok = [r for r in results if r.get("ok")]

    fields = [
        "id",
        "tag",
        "perturbation",
        "gt",
        "pred",
        "char_accuracy",
        "plate_accuracy",
        "trace_hash",
        "semantic_trace_hash",
        "total_ms",
        "search_ms",
        "segment_count",
        "expected_count",
        "overlap_pen",
        "density",
        "density_pen",
        "blocking",
        "selected_boxes",
    ]

    with (out / "phase1_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in sorted(ok, key=lambda z: (z["id"], z["tag"])):
            rr = {k: r.get(k) for k in fields}
            rr["selected_boxes"] = json.dumps(
                rr["selected_boxes"],
                separators=(",", ":"),
            )
            w.writerow(rr)

    by_key = {(r["id"], r["tag"]): r for r in ok}

    # Multi-scale sensitivity analysis.
    sensitivities: Dict[str, Dict[str, Any]] = {}
    sensitivity_rows: List[Dict[str, Any]] = []

    for dot, h in steps.items():
        base = float(get_dot(base_cfg, dot))
        scale_results: List[Dict[str, Any]] = []

        for scale in scales:
            sval = scale_label(scale)
            minus_tag = (
                dot.replace(".", "__") + f"__s{sval}__minus"
            )
            plus_tag = (
                dot.replace(".", "__") + f"__s{sval}__plus"
            )

            minus_val = float(
                variant_meta[minus_tag]["value"]
            )
            plus_val = float(
                variant_meta[plus_tag]["value"]
            )

            minus_radius = (
                abs(base - minus_val) / h if h > 0 else 0.0
            )
            plus_radius = (
                abs(plus_val - base) / h if h > 0 else 0.0
            )
            central_span = minus_radius + plus_radius

            response_rates = []
            central_rates = []
            response_discrepancies = []
            central_discrepancies = []
            active_flags = []
            d_ref_plus_vals = []
            d_ref_minus_vals = []

            for s in chosen:
                r0 = by_key.get((s["id"], "reference"))
                rm = by_key.get((s["id"], minus_tag))
                rp = by_key.get((s["id"], plus_tag))

                if not r0 or not rm or not rp:
                    continue

                d0p = output_distance(r0, rp)
                d0m = output_distance(r0, rm)
                dmp = output_distance(rm, rp)

                rates = []
                if plus_radius > 0:
                    rates.append(d0p / plus_radius)
                if minus_radius > 0:
                    rates.append(d0m / minus_radius)
                if central_span > 0:
                    rates.append(dmp / central_span)

                response_rate = max(rates) if rates else 0.0
                central_rate = (
                    dmp / central_span
                    if central_span > 0
                    else 0.0
                )

                response_discrepancy = max(
                    d0p,
                    d0m,
                    0.5 * dmp,
                )

                active = (
                    max(d0p, d0m, dmp) > args.activity_eps
                )

                response_rates.append(response_rate)
                central_rates.append(central_rate)
                response_discrepancies.append(
                    response_discrepancy
                )
                central_discrepancies.append(dmp)
                active_flags.append(int(active))
                d_ref_plus_vals.append(d0p)
                d_ref_minus_vals.append(d0m)

            response_sensitivity = (
                mean(v * v for v in response_rates) or 0.0
            )
            central_sensitivity = (
                mean(v * v for v in central_rates) or 0.0
            )
            active_fraction = mean(active_flags) or 0.0

            sr = {
                "coordinate": dot,
                "base_value": base,
                "base_step": h,
                "scale": scale,
                "minus_value": minus_val,
                "plus_value": plus_val,
                "minus_normalized_radius": minus_radius,
                "plus_normalized_radius": plus_radius,
                "n": len(response_rates),
                "active_fraction": active_fraction,
                "mean_ref_plus_discrepancy": (
                    mean(d_ref_plus_vals) or 0.0
                ),
                "mean_ref_minus_discrepancy": (
                    mean(d_ref_minus_vals) or 0.0
                ),
                "mean_central_discrepancy": (
                    mean(central_discrepancies) or 0.0
                ),
                "mean_response_discrepancy": (
                    mean(response_discrepancies) or 0.0
                ),
                "max_response_discrepancy": (
                    max(response_discrepancies)
                    if response_discrepancies
                    else 0.0
                ),
                "central_sensitivity": central_sensitivity,
                "response_sensitivity": response_sensitivity,
                "informative": bool(
                    active_fraction > 0
                    and response_sensitivity > 0
                ),
            }

            scale_results.append(sr)
            sensitivity_rows.append(sr)

        informative = [
            x for x in scale_results if x["informative"]
        ]
        selected = informative[0] if informative else None

        sensitivities[dot] = {
            "base_value": base,
            "base_step": h,
            "scales": scale_results,
            "selected_scale": (
                selected["scale"] if selected else None
            ),
            "selected_minus_value": (
                selected["minus_value"] if selected else None
            ),
            "selected_plus_value": (
                selected["plus_value"] if selected else None
            ),
            "selected_active_fraction": (
                selected["active_fraction"] if selected else 0.0
            ),
            "selected_response_sensitivity": (
                selected["response_sensitivity"]
                if selected
                else 0.0
            ),
            "locally_inactive_over_tested_scales": (
                selected is None
            ),
        }

    with (out / "phase1_sensitivity.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        sf = [
            "coordinate",
            "base_value",
            "base_step",
            "scale",
            "minus_value",
            "plus_value",
            "minus_normalized_radius",
            "plus_normalized_radius",
            "n",
            "active_fraction",
            "mean_ref_plus_discrepancy",
            "mean_ref_minus_discrepancy",
            "mean_central_discrepancy",
            "mean_response_discrepancy",
            "max_response_discrepancy",
            "central_sensitivity",
            "response_sensitivity",
            "informative",
        ]
        w = csv.DictWriter(f, fieldnames=sf)
        w.writeheader()
        for r in sensitivity_rows:
            w.writerow({k: r.get(k) for k in sf})

    selected_nonzero = [
        v["selected_response_sensitivity"]
        for v in sensitivities.values()
        if v["selected_response_sensitivity"] > 0
    ]

    scale_ref = percentile(selected_nonzero, 0.5) or 1.0
    lambda0 = 0.10

    W_diag = {
        k: (
            lambda0
            + v["selected_response_sensitivity"] / scale_ref
        )
        for k, v in sensitivities.items()
    }

    refs = [r for r in ok if r["tag"] == "reference"]
    reps = [
        r for r in ok if r["tag"] == "reference_repeat"
    ]
    repeat_map = {r["id"]: r for r in reps}

    raw_hash_mismatches = []
    semantic_hash_mismatches = []
    prediction_mismatches = []
    segment_count_mismatches = []
    selected_box_mismatches = []
    repeat_details = []

    for r in refs:
        q = repeat_map.get(r["id"])
        if q is None:
            continue

        raw_m = int(r["trace_hash"] != q["trace_hash"])
        sem_m = int(
            r["semantic_trace_hash"]
            != q["semantic_trace_hash"]
        )
        pred_m = int(r["pred"] != q["pred"])
        seg_m = int(
            int(r["segment_count"] or 0)
            != int(q["segment_count"] or 0)
        )
        box_m = int(
            r["selected_boxes"] != q["selected_boxes"]
        )

        raw_hash_mismatches.append(raw_m)
        semantic_hash_mismatches.append(sem_m)
        prediction_mismatches.append(pred_m)
        segment_count_mismatches.append(seg_m)
        selected_box_mismatches.append(box_m)

        repeat_details.append(
            {
                "id": r["id"],
                "raw_hash_mismatch": raw_m,
                "semantic_hash_mismatch": sem_m,
                "prediction_mismatch": pred_m,
                "segment_count_mismatch": seg_m,
                "selected_boxes_mismatch": box_m,
            }
        )

    (out / "repeat_identity.csv").write_text(
        "",
        encoding="utf-8",
    )
    with (out / "repeat_identity.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        rf = [
            "id",
            "raw_hash_mismatch",
            "semantic_hash_mismatch",
            "prediction_mismatch",
            "segment_count_mismatch",
            "selected_boxes_mismatch",
        ]
        w = csv.DictWriter(f, fieldnames=rf)
        w.writeheader()
        w.writerows(repeat_details)

    summary = {
        "version": "phase1_calibration_v2",
        "source_reference_config": str(base_cfg_path),
        "manifest": str(manifest),
        "dataset_root": str(dataset_root),
        "sample_count": len(chosen),
        "perturbation_counts": {
            c: sum(
                r["perturbation"] == c for r in chosen
            )
            for c in sorted(
                {r["perturbation"] for r in chosen}
            )
        },
        "reference": {
            "plate_accuracy_mean": mean(
                r["plate_accuracy"] for r in refs
            ),
            "char_accuracy_mean": mean(
                r["char_accuracy"] for r in refs
            ),
            "total_ms_mean": mean(
                r["total_ms"] for r in refs
            ),
            "total_ms_p95": percentile(
                (r["total_ms"] for r in refs),
                0.95,
            ),
            "search_ms_mean": mean(
                r["search_ms"] for r in refs
            ),
        },
        "repeat_identity": {
            "repeat_n": len(raw_hash_mismatches),
            "raw_trace_hash_mismatch_rate": mean(
                raw_hash_mismatches
            ),
            "semantic_trace_hash_mismatch_rate": mean(
                semantic_hash_mismatches
            ),
            "prediction_mismatch_rate": mean(
                prediction_mismatches
            ),
            "segment_count_mismatch_rate": mean(
                segment_count_mismatches
            ),
            "selected_boxes_mismatch_rate": mean(
                selected_box_mismatches
            ),
            "semantic_hash_definition": {
                "included_top_level_fields": list(
                    SEMANTIC_TRACE_KEYS
                ),
                "excluded": [
                    "timings_ms",
                    "trace_hash",
                    "input.image absolute path",
                ],
                "float_digits": args.semantic_float_digits,
            },
        },
        "finite_difference": {
            "scales": scales,
            "activity_eps": args.activity_eps,
            "selection_rule": (
                "smallest tested scale with nonzero "
                "end-to-end response"
            ),
            "response_definition": (
                "max(one-sided reference response rates, "
                "symmetric plus/minus response rate); "
                "string/box/count output metric"
            ),
            "coordinates": sensitivities,
        },
        "W_construction": {
            "coordinate_normalization": (
                "one base finite-difference step = "
                "1 normalized coordinate unit"
            ),
            "lambda": lambda0,
            "median_selected_nonzero_response_sensitivity": (
                scale_ref
            ),
            "W_diag": W_diag,
            "inactive_coordinate_policy": (
                "retain lambda only if no tested scale "
                "is informative"
            ),
        },
        "note": (
            "Phase-1 calibration only. Review the selected "
            "scales and W before running the final "
            "B0/B1/B2/B3 trajectories."
        ),
    }

    (out / "phase1_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    (out / "selected_samples.json").write_text(
        json.dumps(chosen, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2))

    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
