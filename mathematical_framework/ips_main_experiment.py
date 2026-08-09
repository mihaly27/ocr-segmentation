#!/usr/bin/env python3
"""
Main B0--B3 experiment for the bounded-adaptation IPS case study.

Controllers
-----------
B0     Fixed published reference configuration.
B1     Unbounded (relative to the calibrated trust region): best raw proposal
       inside the hard calibration box is committed whenever triggered.
B2     Bounded only: raw proposal is projected into the calibrated W-ellipsoid
       and committed without a validation gate.
B3     Full controller: drift/risk trigger -> W projection -> label-free gate ->
       commit or deterministic reference fail-safe in recovery mode.
B3-I   Same as B3, but W = I and the radius is volume-matched to the calibrated
       W ellipsoid.
B3-R0  Same as B3, but a rejected recovery candidate leaves the current state
       unchanged (no reference fail-safe).

Ground-truth policy
-------------------
The underlying ips_single_image/main.py is NEVER given --gt.  Ground truth from
the synthetic manifest is used only after a controller decision, by this outer
runner, to compute evaluation metrics.  Proposal selection and commit/reject
decisions are therefore label-free.

Frozen Phase-1 calibration
--------------------------
Adaptive coordinates:
  cut.min_rel_width_for_split : reference 1.6, hard [1.2, 2.0], h = 0.10
  scoring.w_prior             : reference 2.0, hard [0.0, 4.0], h = 0.25
  scoring.blocking_gap_ratio  : reference 0.05, hard [0.0, 0.13], h = 0.01

Combined sensitivity weights from the n=200 local scan and switching scan:
  W = diag(1.10, 0.8036784889951276, 1.901416931827527)

Calibrated radius:
  delta_W = 7.530441831891154 normalized h-units.

For B3-I, delta_I is chosen so that the identity-metric ellipsoid has the same
3-D volume as the W ellipsoid.

Experimental stream
-------------------
A clean reference set is removed first.  From the remaining data a deterministic
17-block stream is constructed:
  clean -> blur -> clean -> glare -> clean -> threshold -> clean ->
  compression -> clean -> perspective -> clean -> touch -> clean ->
  broken -> clean -> combo -> clean

Each block is split disjointly into proposal / gate / evaluation thirds.
Generator perturbation labels are used ONLY to construct and stratify the
controlled experiment, never as runtime trigger inputs.

Outputs
-------
frozen_experiment_config.json
partition_map.json
partition_sha256.txt
controller_events.csv
window_results.csv
sample_results.csv
paired_comparisons.csv
summary.json
cache/                         parsed per-run artifacts
configs/                       generated YAML configurations

Dependencies: Python 3.10+, numpy, opencv-python, pyyaml.
The IPS repository itself supplies its own OCR/runtime dependencies.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import cv2
import numpy as np
import yaml


# ---------------------------------------------------------------------------
# Frozen calibration from Phase 1
# ---------------------------------------------------------------------------

COORDS = (
    "cut.min_rel_width_for_split",
    "scoring.w_prior",
    "scoring.blocking_gap_ratio",
)

REF_STATE = (1.6, 2.0, 0.05)

H_STEP = np.array([0.10, 0.25, 0.01], dtype=float)
LOW = np.array([1.20, 0.00, 0.00], dtype=float)
HIGH = np.array([2.00, 4.00, 0.13], dtype=float)

W_DIAG = np.array(
    [1.10, 0.8036784889951276, 1.901416931827527],
    dtype=float,
)
DELTA_W = 7.530441831891154
P_DIM = 3
DELTA_I = float(
    DELTA_W / (float(np.prod(W_DIAG)) ** (1.0 / (2.0 * P_DIM)))
)

RAW_GRID_LEVELS = (
    (1.20, 1.60, 2.00),
    (0.00, 2.00, 4.00),
    (0.00, 0.05, 0.13),
)

CONTROLLERS = ("B0", "B1", "B2", "B3", "B3-I", "B3-R0")

STREAM_CONDITIONS = (
    "clean",
    "blur",
    "clean",
    "glare",
    "clean",
    "threshold",
    "clean",
    "compression",
    "clean",
    "perspective",
    "clean",
    "touch",
    "clean",
    "broken",
    "clean",
    "combo",
    "clean",
)

IMAGE_KEYS = ("image", "image_path", "path", "filename", "file")
GT_KEYS = ("gt", "text", "plate", "plate_text", "label", "ground_truth")
PERT_KEYS = ("perturbation", "perturbation_type", "condition", "class", "type")
ID_KEYS = ("id", "sample_id", "uid", "name")
BOX_KEYS = (
    "boxes",
    "char_boxes",
    "character_boxes",
    "gt_boxes",
    "boxes_json",
    "bboxes",
)
ANN_KEYS = (
    "annotation",
    "annotation_path",
    "annotations",
    "json_path",
    "meta_path",
)

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

ENV_FEATURE_NAMES = (
    "mean_y",
    "std_y",
    "lap_var",
    "foreground_occupancy",
    "cc_count",
    "median_cc_width",
    "median_cc_height",
)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def qfloat(x: float, digits: int = 8) -> float:
    return round(float(x), digits)


def state_tuple(x: Sequence[float]) -> Tuple[float, float, float]:
    return tuple(qfloat(v) for v in x)  # type: ignore[return-value]


def state_dict(s: Sequence[float]) -> Dict[str, float]:
    return {k: float(v) for k, v in zip(COORDS, s)}


def state_label(s: Sequence[float]) -> str:
    return (
        f"rsplit={float(s[0]):.6f};"
        f"wprior={float(s[1]):.6f};"
        f"gblock={float(s[2]):.6f}"
    )


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


def state_to_config(base_cfg: Dict[str, Any], s: Sequence[float]) -> Dict[str, Any]:
    cfg = deepcopy(base_cfg)
    for dot, val in zip(COORDS, s):
        set_dot(cfg, dot, float(val))
    return cfg


def config_hash(cfg: Mapping[str, Any]) -> str:
    raw = json.dumps(cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def canonicalize(obj: Any, float_digits: int = 12) -> Any:
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
            inp = dict(trace[k])
            inp.pop("image", None)
            inp.pop("gt", None)
            payload[k] = inp
        elif k == "metrics" and isinstance(trace[k], dict):
            # main.py receives no GT, but explicitly remove task metrics anyway.
            m = dict(trace[k])
            m.pop("char_accuracy", None)
            m.pop("full_plate_accuracy", None)
            payload[k] = m
        else:
            payload[k] = trace[k]
    return payload


def semantic_trace_hash(trace: Dict[str, Any]) -> str:
    payload = canonicalize(semantic_trace_payload(trace), 12)
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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


def char_accuracy(gt: str, pred: str) -> float:
    gt = "".join(c for c in str(gt).upper() if c.isalnum())
    pred = "".join(c for c in str(pred).upper() if c.isalnum())
    d = lev(gt, pred)
    return 1.0 - d / float(max(len(gt), len(pred), 1))


def plate_accuracy(gt: str, pred: str) -> float:
    gt = "".join(c for c in str(gt).upper() if c.isalnum())
    pred = "".join(c for c in str(pred).upper() if c.isalnum())
    return float(bool(gt) and gt == pred)


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


def best_iou_sum(a_boxes: Sequence[Sequence[float]],
                 b_boxes: Sequence[Sequence[float]]) -> float:
    a, b = list(a_boxes), list(b_boxes)
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    n, m = len(a), len(b)
    score = [[iou(a[i], b[j]) for j in range(m)] for i in range(n)]
    dp = {0: 0.0}
    for i in range(n):
        nxt: Dict[int, float] = {}
        for mask, val in dp.items():
            nxt[mask] = max(nxt.get(mask, -1.0), val)
            for j in range(m):
                if mask & (1 << j):
                    continue
                nm = mask | (1 << j)
                nxt[nm] = max(nxt.get(nm, -1.0), val + score[i][j])
        dp = nxt
    return max(dp.values())


def box_distance(gt_boxes: Sequence[Sequence[float]],
                 pred_boxes: Sequence[Sequence[float]],
                 expected_count: int = 6) -> Optional[float]:
    if not gt_boxes:
        return None
    denom = max(expected_count, 1)
    return 1.0 - best_iou_sum(gt_boxes, pred_boxes) / float(denom)


def choose_key(row: Mapping[str, Any], candidates: Sequence[str]) -> Optional[str]:
    lower = {str(k).lower(): str(k) for k in row}
    for c in candidates:
        if c in lower:
            return lower[c]
    return None


def load_manifest(path: Path) -> List[Dict[str, Any]]:
    s = path.suffix.lower()
    if s == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as f:
            return [dict(r) for r in csv.DictReader(f)]
    if s in {".jsonl", ".ndjson"}:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if s == ".json":
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, list):
            return [dict(x) for x in obj]
        if isinstance(obj, dict):
            for k in ("samples", "items", "data", "records"):
                if isinstance(obj.get(k), list):
                    return [dict(x) for x in obj[k]]
    raise ValueError(f"Unsupported manifest format: {path}")


def resolve_path(raw: str, dataset_root: Path, manifest_parent: Path) -> Path:
    p = Path(str(raw))
    if p.is_absolute():
        return p
    for q in (dataset_root / p, manifest_parent / p, Path.cwd() / p):
        if q.exists():
            return q.resolve()
    return (dataset_root / p).resolve()


def normalize_bbox_obj(obj: Any) -> List[List[float]]:
    out: List[List[float]] = []
    if obj is None:
        return out
    if isinstance(obj, dict):
        for key in ("boxes", "char_boxes", "character_boxes", "bboxes"):
            if key in obj:
                return normalize_bbox_obj(obj[key])
        if {"x", "y", "w", "h"} <= set(obj):
            return [[float(obj["x"]), float(obj["y"]), float(obj["w"]), float(obj["h"])]]
        if {"x1", "y1", "x2", "y2"} <= set(obj):
            return [[
                float(obj["x1"]),
                float(obj["y1"]),
                float(obj["x2"]) - float(obj["x1"]),
                float(obj["y2"]) - float(obj["y1"]),
            ]]
        if "bbox" in obj:
            return normalize_bbox_obj(obj["bbox"])
        for key in ("characters", "chars", "annotations", "objects"):
            if isinstance(obj.get(key), list):
                for item in obj[key]:
                    out.extend(normalize_bbox_obj(item))
                if out:
                    return out
        return out
    if isinstance(obj, list):
        if len(obj) == 4 and all(isinstance(x, (int, float)) for x in obj):
            return [[float(x) for x in obj]]
        for item in obj:
            out.extend(normalize_bbox_obj(item))
    return out


def parse_boxes_from_row(row: Mapping[str, Any],
                         image_path: Path,
                         dataset_root: Path,
                         manifest_parent: Path) -> List[List[float]]:
    key = choose_key(row, BOX_KEYS)
    if key and str(row.get(key, "")).strip():
        raw = str(row[key]).strip()
        try:
            return normalize_bbox_obj(json.loads(raw))
        except Exception:
            p = resolve_path(raw, dataset_root, manifest_parent)
            if p.exists():
                try:
                    return normalize_bbox_obj(json.loads(p.read_text(encoding="utf-8")))
                except Exception:
                    pass

    akey = choose_key(row, ANN_KEYS)
    if akey and str(row.get(akey, "")).strip():
        p = resolve_path(str(row[akey]), dataset_root, manifest_parent)
        if p.exists():
            try:
                return normalize_bbox_obj(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass

    sidecars = [
        image_path.with_suffix(".json"),
        image_path.parent / f"{image_path.stem}_meta.json",
        image_path.parent / f"{image_path.stem}.annotation.json",
    ]
    for p in sidecars:
        if p.exists():
            try:
                boxes = normalize_bbox_obj(json.loads(p.read_text(encoding="utf-8")))
                if boxes:
                    return boxes
            except Exception:
                continue
    return []


def normalize_rows(rows: List[Dict[str, Any]],
                   dataset_root: Path,
                   manifest_parent: Path) -> List[Dict[str, Any]]:
    if not rows:
        raise ValueError("Manifest is empty")
    ik = choose_key(rows[0], IMAGE_KEYS)
    gk = choose_key(rows[0], GT_KEYS)
    pk = choose_key(rows[0], PERT_KEYS)
    idk = choose_key(rows[0], ID_KEYS)
    if ik is None or gk is None or pk is None:
        raise ValueError(
            "Could not infer image/GT/perturbation columns. "
            f"Columns={list(rows[0])}"
        )
    out = []
    for i, r in enumerate(rows):
        image = resolve_path(str(r[ik]), dataset_root, manifest_parent)
        if not image.exists():
            continue
        sid = (
            str(r[idk]).strip()
            if idk and str(r.get(idk, "")).strip()
            else f"row_{i:06d}"
        )
        out.append(
            {
                "id": sid,
                "image": str(image),
                "gt": str(r[gk]).strip(),
                "perturbation": str(r[pk]).strip().lower(),
                "gt_boxes": parse_boxes_from_row(
                    r, image, dataset_root, manifest_parent
                ),
            }
        )
    return out


def deterministic_sort(rows: Sequence[Dict[str, Any]], seed: str) -> List[Dict[str, Any]]:
    return sorted(
        rows,
        key=lambda r: hashlib.sha256((seed + "|" + str(r["id"])).encode()).hexdigest(),
    )


def load_dev_ids(path: Path) -> set[str]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, list):
        raise ValueError("--dev-selected must be selected_samples.json from Phase 1")
    return {str(x["id"]) for x in obj}


def percentile(vals: Iterable[float], q: float) -> Optional[float]:
    xs = np.array(
        [float(x) for x in vals if x is not None and np.isfinite(float(x))],
        dtype=float,
    )
    if xs.size == 0:
        return None
    return float(np.quantile(xs, q))


def mean(vals: Iterable[float]) -> Optional[float]:
    xs = [float(x) for x in vals if x is not None and np.isfinite(float(x))]
    return float(sum(xs) / len(xs)) if xs else None


def bootstrap_ci(values: Sequence[float],
                 rng: np.random.Generator,
                 n_boot: int = 2000,
                 alpha: float = 0.05) -> Tuple[float, float]:
    a = np.asarray(values, dtype=float)
    if a.size == 0:
        return (float("nan"), float("nan"))
    if a.size == 1:
        return (float(a[0]), float(a[0]))
    means = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        means[i] = float(np.mean(rng.choice(a, size=a.size, replace=True)))
    return (
        float(np.quantile(means, alpha / 2)),
        float(np.quantile(means, 1 - alpha / 2)),
    )


# ---------------------------------------------------------------------------
# Run artifact and cache
# ---------------------------------------------------------------------------

def _single_artifact_task(task: Dict[str, Any]) -> Dict[str, Any]:
    repo = Path(task["repo"])
    cfg_path = Path(task["cfg_path"])
    sample = task["sample"]
    outdir = Path(task["outdir"])
    timeout = float(task["timeout"])
    py = task["python"]

    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Deliberately omit --gt.
    cmd = [
        py,
        str(repo / "main.py"),
        "--image",
        sample["image"],
        "--outdir",
        str(outdir),
        "--config",
        str(cfg_path),
    ]
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "id": sample["id"], "error": "timeout"}

    if cp.returncode != 0:
        return {
            "ok": False,
            "id": sample["id"],
            "error": cp.stderr[-3000:] or f"returncode={cp.returncode}",
        }

    try:
        result = json.loads((outdir / "result.json").read_text(encoding="utf-8"))
        trace = json.loads((outdir / "trace.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "id": sample["id"], "error": f"parse: {exc}"}

    br = trace.get("score_breakdown", {}) or {}
    initial = trace.get("initial_segments", []) or []
    selected = trace.get("selected_segments", []) or []
    metrics = trace.get("metrics", {}) or {}
    timings = trace.get("timings_ms", {}) or {}

    parsed = {
        "ok": True,
        "id": sample["id"],
        "pred": str(result.get("pred", "")),
        "raw_trace_hash": result.get("trace_hash"),
        "semantic_trace_hash": semantic_trace_hash(trace),
        "total_ms": float(result.get("total_ms") or timings.get("total_ms") or 0.0),
        "search_ms": float(timings.get("search_ms") or 0.0),
        "segment_count": int(metrics.get("segment_count") or len(selected)),
        "expected_count": int(metrics.get("expected_count") or 6),
        "initial_segments": initial,
        "selected_boxes": [x.get("bbox", []) for x in selected],
        "fit_pen": float(((br.get("fit") or {}).get("sum")) or 0.0),
        "overlap_pen": float(((br.get("overlap") or {}).get("sum")) or 0.0),
        "density": float(((br.get("prior") or {}).get("density")) or 0.0),
        "density_pen": float(((br.get("prior") or {}).get("density_pen")) or 0.0),
        "blocking": int(((br.get("prior") or {}).get("blocking")) or 0),
    }
    return parsed


class ArtifactCache:
    def __init__(
        self,
        repo: Path,
        base_cfg: Dict[str, Any],
        root: Path,
        workers: int,
        timeout: float,
        python: str,
    ):
        self.repo = repo
        self.base_cfg = base_cfg
        self.root = root
        self.workers = workers
        self.timeout = timeout
        self.python = python
        self.config_dir = root.parent / "configs"
        self.temp_dir = root.parent / "_tmp_runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def cfg_for_state(self, s: Sequence[float]) -> Tuple[Dict[str, Any], str, Path]:
        cfg = state_to_config(self.base_cfg, s)
        h = config_hash(cfg)
        p = self.config_dir / f"{h}.yaml"
        if not p.exists():
            p.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
        return cfg, h, p

    def cache_path(self, cfg_hash: str, sample_id: str) -> Path:
        d = self.root / cfg_hash
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{sample_id}.json"

    def ensure(
        self,
        s: Sequence[float],
        samples: Sequence[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        _, ch, cfgp = self.cfg_for_state(s)
        found: Dict[str, Dict[str, Any]] = {}
        tasks: List[Dict[str, Any]] = []
        for sm in samples:
            cp = self.cache_path(ch, sm["id"])
            if cp.exists():
                found[sm["id"]] = json.loads(cp.read_text(encoding="utf-8"))
                continue
            tasks.append(
                {
                    "repo": str(self.repo),
                    "cfg_path": str(cfgp),
                    "sample": sm,
                    "outdir": str(self.temp_dir / ch / sm["id"]),
                    "timeout": self.timeout,
                    "python": self.python,
                }
            )

        if tasks:
            with ProcessPoolExecutor(max_workers=self.workers) as ex:
                futs = [ex.submit(_single_artifact_task, t) for t in tasks]
                done = 0
                for fut in as_completed(futs):
                    r = fut.result()
                    done += 1
                    if not r.get("ok"):
                        raise RuntimeError(
                            f"Artifact failure for {r.get('id')}: {r.get('error')}"
                        )
                    sid = r["id"]
                    cp = self.cache_path(ch, sid)
                    cp.write_text(json.dumps(r, separators=(",", ":")), encoding="utf-8")
                    found[sid] = r
                    if done % 50 == 0 or done == len(tasks):
                        print(
                            f"  config {ch}: completed {done}/{len(tasks)} new runs",
                            flush=True,
                        )

        return found

    def rerun_semantic(
        self,
        s: Sequence[float],
        samples: Sequence[Dict[str, Any]],
    ) -> List[Tuple[str, str, str]]:
        """Return (id, cached semantic hash, fresh semantic hash)."""
        _, ch, cfgp = self.cfg_for_state(s)
        base = self.ensure(s, samples)
        tasks = []
        for i, sm in enumerate(samples):
            tasks.append(
                {
                    "repo": str(self.repo),
                    "cfg_path": str(cfgp),
                    "sample": sm,
                    "outdir": str(self.temp_dir / f"repeat_{ch}_{i}" / sm["id"]),
                    "timeout": self.timeout,
                    "python": self.python,
                }
            )
        fresh = []
        with ProcessPoolExecutor(max_workers=min(self.workers, max(1, len(tasks)))) as ex:
            futs = [ex.submit(_single_artifact_task, t) for t in tasks]
            for fut in as_completed(futs):
                r = fut.result()
                if not r.get("ok"):
                    raise RuntimeError(
                        f"Repeat artifact failure for {r.get('id')}: {r.get('error')}"
                    )
                fresh.append((r["id"], base[r["id"]]["semantic_trace_hash"],
                              r["semantic_trace_hash"]))
        return sorted(fresh)


# ---------------------------------------------------------------------------
# Environment, risk, trigger, gate
# ---------------------------------------------------------------------------

def env_features(sample: Dict[str, Any], run: Dict[str, Any]) -> np.ndarray:
    img = cv2.imread(sample["image"], cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"Cannot read image: {sample['image']}")
    mean_y = float(np.mean(img))
    std_y = float(np.std(img))
    lap_var = float(cv2.Laplacian(img, cv2.CV_64F).var())

    segs = run.get("initial_segments", []) or []
    H, W = img.shape[:2]
    area = float(sum(float(s.get("area", 0)) for s in segs))
    occ = area / float(max(H * W, 1))
    widths = [float(s.get("bbox", [0, 0, 0, 0])[2]) for s in segs]
    heights = [float(s.get("bbox", [0, 0, 0, 0])[3]) for s in segs]
    return np.array(
        [
            mean_y,
            std_y,
            lap_var,
            occ,
            float(len(segs)),
            float(np.median(widths)) if widths else 0.0,
            float(np.median(heights)) if heights else 0.0,
        ],
        dtype=float,
    )


def risk_components(run: Dict[str, Any]) -> Dict[str, float]:
    k = int(run.get("segment_count") or 0)
    exp = max(int(run.get("expected_count") or 6), 1)
    pred = "".join(c for c in str(run.get("pred", "")).upper() if c.isalnum())

    count = min(1.0, abs(k - exp) / float(exp))
    pred_len = min(1.0, abs(len(pred) - exp) / float(exp))
    fit = min(1.0, float(run.get("fit_pen") or 0.0) / float(max(k, 1)))
    overlap = min(1.0, float(run.get("overlap_pen") or 0.0))
    blocking = min(
        1.0,
        float(run.get("blocking") or 0) / float(max(k - 1, 1)),
    )
    density = min(1.0, max(0.0, float(run.get("density_pen") or 0.0)) / 0.25)
    return {
        "count": count,
        "pred_len": pred_len,
        "fit": fit,
        "overlap": overlap,
        "blocking": blocking,
        "density": density,
    }


def sample_U(run: Dict[str, Any]) -> float:
    c = risk_components(run)
    return float(np.mean(list(c.values())))


def aggregate_runs(runs: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    us = [sample_U(r) for r in runs]
    return {
        "mean_U": float(np.mean(us)) if us else float("nan"),
        "p95_total_ms": float(np.quantile(
            [r["total_ms"] for r in runs], 0.95
        )) if runs else float("nan"),
        "mean_total_ms": float(np.mean(
            [r["total_ms"] for r in runs]
        )) if runs else float("nan"),
        "mean_search_ms": float(np.mean(
            [r["search_ms"] for r in runs]
        )) if runs else float("nan"),
        "mean_count_risk": float(np.mean(
            [risk_components(r)["count"] for r in runs]
        )) if runs else float("nan"),
    }


def psi_from_edges(ref_vals: np.ndarray, cur_vals: np.ndarray, edges: np.ndarray) -> float:
    # Edges already include -inf/+inf.
    ref_counts, _ = np.histogram(ref_vals, bins=edges)
    cur_counts, _ = np.histogram(cur_vals, bins=edges)
    eps = 1e-6
    rp = ref_counts.astype(float) / max(ref_counts.sum(), 1)
    cp = cur_counts.astype(float) / max(cur_counts.sum(), 1)
    rp = np.clip(rp, eps, None)
    cp = np.clip(cp, eps, None)
    rp /= rp.sum()
    cp /= cp.sum()
    return float(np.sum((cp - rp) * np.log(cp / rp)))


@dataclass
class Calibration:
    env_ref: np.ndarray
    env_edges: List[np.ndarray]
    tau_D: float
    U_max: float
    L_max: float
    epsilon_U: float
    tau_plate: float
    tau_char: float
    tau_dseg: float
    tau_dbox: Optional[float]


def make_edges(vals: np.ndarray, n_bins: int = 5) -> np.ndarray:
    qs = np.linspace(0.0, 1.0, n_bins + 1)
    e = np.quantile(vals, qs)
    e = np.unique(e)
    if e.size < 2:
        v = float(vals[0]) if vals.size else 0.0
        e = np.array([v - 0.5, v + 0.5], dtype=float)
    e[0] = -np.inf
    e[-1] = np.inf
    return e


def drift_score(cal: Calibration, cur_env: np.ndarray) -> float:
    vals = []
    for j, edges in enumerate(cal.env_edges):
        vals.append(
            psi_from_edges(cal.env_ref[:, j], cur_env[:, j], edges)
        )
    return float(np.mean(vals))


def calibrate_reference(
    clean_ref_samples: Sequence[Dict[str, Any]],
    clean_ref_runs: Mapping[str, Dict[str, Any]],
    dev_samples: Sequence[Dict[str, Any]],
    dev_runs: Mapping[str, Dict[str, Any]],
    proposal_n: int,
    rng: np.random.Generator,
    n_boot: int = 500,
) -> Calibration:
    """Freeze drift and operational thresholds without final-evaluation leakage.

    * PSI bins and tau_D come only from held-out clean reference samples.
    * U/L/task/segmentation thresholds come from the already-used Phase-1
      development set, bootstrapped *within perturbation class*.  This prevents
      clean-only thresholds from making every supported perturbed regime
      automatically infeasible.
    """
    clean_ordered_runs = [clean_ref_runs[s["id"]] for s in clean_ref_samples]
    env = np.vstack([
        env_features(s, clean_ref_runs[s["id"]]) for s in clean_ref_samples
    ])
    edges = [make_edges(env[:, j], 5) for j in range(env.shape[1])]

    # Clean-to-clean PSI variation only.
    boot_D = []
    n_clean = len(clean_ref_samples)
    for _ in range(n_boot):
        idx = rng.choice(n_clean, size=proposal_n, replace=True)
        cur_env = env[idx, :]
        d = float(np.mean([
            psi_from_edges(env[:, j], cur_env[:, j], edges[j])
            for j in range(env.shape[1])
        ]))
        boot_D.append(d)

    # Development operational/task thresholds, stratified by perturbation.
    by_cond: Dict[str, List[Dict[str, Any]]] = {}
    for s in dev_samples:
        if s["id"] in dev_runs:
            by_cond.setdefault(str(s["perturbation"]), []).append(s)
    if not by_cond:
        raise ValueError("No Phase-1 development samples resolved for calibration")

    boot_U: List[float] = []
    boot_L: List[float] = []
    boot_plate: List[float] = []
    boot_char: List[float] = []
    boot_dseg: List[float] = []
    boot_dbox: List[float] = []
    eps_u_samples: List[float] = []

    per_class_boot = max(100, n_boot // max(len(by_cond), 1))
    for cond, samples in sorted(by_cond.items()):
        n = len(samples)
        if n == 0:
            continue
        win = min(proposal_n, n)
        for _ in range(per_class_boot):
            idx = rng.choice(n, size=win, replace=True)
            chosen = [samples[int(i)] for i in idx]
            rr = [dev_runs[s["id"]] for s in chosen]
            boot_U.append(float(np.mean([sample_U(r) for r in rr])))
            boot_L.append(float(np.quantile([r["total_ms"] for r in rr], 0.95)))

            pa, ca, ds, db = [], [], [], []
            for s, r in zip(chosen, rr):
                pa.append(plate_accuracy(s["gt"], r["pred"]))
                ca.append(char_accuracy(s["gt"], r["pred"]))
                ds.append(abs(int(r["segment_count"]) - int(r["expected_count"])))
                bd = box_distance(
                    s.get("gt_boxes", []),
                    r.get("selected_boxes", []),
                    int(r.get("expected_count") or 6),
                )
                if bd is not None:
                    db.append(bd)
            boot_plate.append(float(np.mean(pa)))
            boot_char.append(float(np.mean(ca)))
            boot_dseg.append(float(np.mean(ds)))
            if db:
                boot_dbox.append(float(np.mean(db)))

            # Same-condition clean statistical tolerance for label-free gate.
            ia = rng.choice(n, size=win, replace=True)
            ib = rng.choice(n, size=win, replace=True)
            ua = np.mean([sample_U(dev_runs[samples[int(i)]["id"]]) for i in ia])
            ub = np.mean([sample_U(dev_runs[samples[int(i)]["id"]]) for i in ib])
            eps_u_samples.append(abs(float(ua - ub)))

    return Calibration(
        env_ref=env,
        env_edges=edges,
        tau_D=float(np.quantile(boot_D, 0.99)),
        U_max=float(np.quantile(boot_U, 0.99)),
        L_max=float(np.quantile(boot_L, 0.99) * 1.10),
        epsilon_U=float(np.quantile(eps_u_samples, 0.95)),
        tau_plate=float(np.quantile(boot_plate, 0.05)),
        tau_char=float(np.quantile(boot_char, 0.05)),
        tau_dseg=float(np.quantile(boot_dseg, 0.95)),
        tau_dbox=(
            float(np.quantile(boot_dbox, 0.95))
            if boot_dbox else None
        ),
    )


def normalized_delta(a: Sequence[float], b: Sequence[float]) -> np.ndarray:
    return (np.asarray(b, dtype=float) - np.asarray(a, dtype=float)) / H_STEP


def weighted_distance(a: Sequence[float], b: Sequence[float],
                      w_diag: np.ndarray) -> float:
    z = normalized_delta(a, b)
    return float(math.sqrt(float(np.sum(w_diag * z * z))))


def project_state(current: Sequence[float],
                  raw: Sequence[float],
                  w_diag: np.ndarray,
                  delta: float) -> Tuple[Tuple[float, float, float], float, bool]:
    c = np.asarray(current, dtype=float)
    r = np.clip(np.asarray(raw, dtype=float), LOW, HIGH)
    z = (r - c) / H_STEP
    norm = float(math.sqrt(float(np.sum(w_diag * z * z))))
    if norm <= delta + 1e-12:
        return state_tuple(r), norm, False
    scale = delta / max(norm, 1e-12)
    projected = c + H_STEP * (z * scale)
    projected = np.clip(projected, LOW, HIGH)
    return state_tuple(projected), norm, True


def grid_states() -> List[Tuple[float, float, float]]:
    out = []
    for a in RAW_GRID_LEVELS[0]:
        for b in RAW_GRID_LEVELS[1]:
            for c in RAW_GRID_LEVELS[2]:
                out.append(state_tuple((a, b, c)))
    return out


# ---------------------------------------------------------------------------
# Partition and stream
# ---------------------------------------------------------------------------

def build_partition(
    rows: Sequence[Dict[str, Any]],
    dev_ids: set[str],
    reference_clean_n: int,
    block_size: int,
    seed: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    remain = [r for r in rows if r["id"] not in dev_ids]
    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in remain:
        by.setdefault(r["perturbation"], []).append(r)
    for k in by:
        by[k] = deterministic_sort(by[k], seed + "|" + k)

    if "clean" not in by:
        raise ValueError("No clean samples found")
    needed_clean = reference_clean_n + STREAM_CONDITIONS.count("clean") * block_size
    if len(by["clean"]) < needed_clean:
        raise ValueError(
            f"Not enough clean samples: need {needed_clean}, have {len(by['clean'])}"
        )

    reference_clean = by["clean"][:reference_clean_n]
    pos = {"clean": reference_clean_n}
    blocks = []
    stream_samples = []

    part_n = block_size // 3
    if block_size % 3 != 0:
        raise ValueError("--block-size must be divisible by 3")

    for bi, cond in enumerate(STREAM_CONDITIONS):
        if cond not in by:
            raise ValueError(f"Missing perturbation class: {cond}")
        start = pos.get(cond, 0)
        end = start + block_size
        if end > len(by[cond]):
            raise ValueError(
                f"Not enough samples for {cond}: need through {end}, have {len(by[cond])}"
            )
        chosen = by[cond][start:end]
        pos[cond] = end

        # Within-class deterministic order is already hashed; no class label is
        # exposed to the runtime controller.
        proposal = chosen[:part_n]
        gate = chosen[part_n:2 * part_n]
        evaluation = chosen[2 * part_n:]

        block = {
            "block_index": bi,
            "condition": cond,
            "proposal_ids": [x["id"] for x in proposal],
            "gate_ids": [x["id"] for x in gate],
            "evaluation_ids": [x["id"] for x in evaluation],
            "proposal": proposal,
            "gate": gate,
            "evaluation": evaluation,
        }
        blocks.append(block)
        stream_samples.extend(chosen)

    partition_public = {
        "seed": seed,
        "dev_excluded_count": len(dev_ids),
        "reference_clean_ids": [r["id"] for r in reference_clean],
        "blocks": [
            {
                "block_index": b["block_index"],
                "condition": b["condition"],
                "proposal_ids": b["proposal_ids"],
                "gate_ids": b["gate_ids"],
                "evaluation_ids": b["evaluation_ids"],
            }
            for b in blocks
        ],
    }
    return reference_clean, blocks, partition_public


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

@dataclass
class ControllerState:
    name: str
    theta: Tuple[float, float, float]


def proposal_objective(runs: Sequence[Dict[str, Any]], L_max: float) -> float:
    agg = aggregate_runs(runs)
    latency_excess = max(0.0, agg["p95_total_ms"] / max(L_max, 1e-9) - 1.0)
    return float(agg["mean_U"] + latency_excess)


def select_raw_candidate(
    current: Sequence[float],
    candidates: Sequence[Tuple[float, float, float]],
    candidate_runs: Mapping[Tuple[float, float, float], Sequence[Dict[str, Any]]],
    L_max: float,
) -> Tuple[Tuple[float, float, float], float]:
    scored = []
    for s in candidates:
        obj = proposal_objective(candidate_runs[s], L_max)
        d = float(np.linalg.norm(normalized_delta(current, s)))
        scored.append((obj, d, state_label(s), s))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return scored[0][3], float(scored[0][0])


def gate_candidate(
    current_runs: Sequence[Dict[str, Any]],
    candidate_runs: Sequence[Dict[str, Any]],
    semantic_repeat_mismatches: int,
    cal: Calibration,
) -> Tuple[bool, Dict[str, Any]]:
    cur = aggregate_runs(current_runs)
    cand = aggregate_runs(candidate_runs)
    checks = {
        "U_absolute": cand["mean_U"] <= cal.U_max,
        "latency": cand["p95_total_ms"] <= cal.L_max,
        "U_noninferiority": cand["mean_U"] <= cur["mean_U"] + cal.epsilon_U,
        "semantic_repeatability": semantic_repeat_mismatches == 0,
    }
    accepted = all(checks.values())
    return accepted, {
        "accepted": accepted,
        "checks": checks,
        "current_mean_U": cur["mean_U"],
        "candidate_mean_U": cand["mean_U"],
        "candidate_p95_ms": cand["p95_total_ms"],
        "U_max": cal.U_max,
        "L_max": cal.L_max,
        "epsilon_U": cal.epsilon_U,
        "semantic_repeat_mismatches": semantic_repeat_mismatches,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--dataset-root", required=True)
    ap.add_argument(
        "--dev-selected",
        required=True,
        help="Phase-1 selected_samples.json; these samples are excluded",
    )
    ap.add_argument("--output", default="mathematical_framework/main_experiment")
    ap.add_argument("--reference-clean-n", type=int, default=100)
    ap.add_argument("--block-size", type=int, default=45)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--gate-repeat-n", type=int, default=2)
    ap.add_argument(
        "--seed",
        default="IPS-MATH-FRAMEWORK-MAIN-2026-08-09",
    )
    ap.add_argument("--bootstrap", type=int, default=2000)
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    manifest = Path(args.manifest).resolve()
    dataset_root = Path(args.dataset_root).resolve()
    dev_selected = Path(args.dev_selected).resolve()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)

    if not (repo / "main.py").exists() or not (repo / "config.yaml").exists():
        raise SystemExit("--repo must point to ips_single_image")
    for p in (manifest, dev_selected):
        if not p.exists():
            raise SystemExit(f"Missing input: {p}")

    base_cfg = yaml.safe_load((repo / "config.yaml").read_text(encoding="utf-8"))
    # Verify the three calibrated reference values match the repository state.
    actual_ref = tuple(float(get_dot(base_cfg, c)) for c in COORDS)
    if any(abs(a - b) > 1e-9 for a, b in zip(actual_ref, REF_STATE)):
        raise SystemExit(
            f"Reference config mismatch. Expected {REF_STATE}, repo has {actual_ref}. "
            "Do not run the frozen experiment on a changed config."
        )

    rows = normalize_rows(
        load_manifest(manifest),
        dataset_root,
        manifest.parent,
    )
    dev_ids = load_dev_ids(dev_selected)

    reference_clean, blocks, partition = build_partition(
        rows,
        dev_ids,
        args.reference_clean_n,
        args.block_size,
        args.seed,
    )

    partition_path = out / "partition_map.json"
    partition_path.write_text(
        json.dumps(partition, indent=2),
        encoding="utf-8",
    )
    partition_hash = hashlib.sha256(partition_path.read_bytes()).hexdigest()
    (out / "partition_sha256.txt").write_text(partition_hash + "\n", encoding="utf-8")

    exp_cfg = {
        "adaptive_coordinates": list(COORDS),
        "reference_state": state_dict(REF_STATE),
        "base_steps": dict(zip(COORDS, H_STEP.tolist())),
        "hard_lower": dict(zip(COORDS, LOW.tolist())),
        "hard_upper": dict(zip(COORDS, HIGH.tolist())),
        "W_diag": dict(zip(COORDS, W_DIAG.tolist())),
        "delta_W": DELTA_W,
        "delta_I_volume_matched": DELTA_I,
        "raw_grid_levels": {
            COORDS[i]: list(RAW_GRID_LEVELS[i]) for i in range(3)
        },
        "controllers": list(CONTROLLERS),
        "stream_conditions": list(STREAM_CONDITIONS),
        "reference_clean_n": args.reference_clean_n,
        "block_size": args.block_size,
        "proposal_gate_eval_each": args.block_size // 3,
        "gate_repeat_n": args.gate_repeat_n,
        "partition_sha256": partition_hash,
        "ground_truth_policy": (
            "Never passed to ips_single_image/main.py; used only by outer evaluator."
        ),
    }
    frozen_path = out / "frozen_experiment_config.json"
    frozen_path.write_text(json.dumps(exp_cfg, indent=2), encoding="utf-8")
    exp_cfg_hash = hashlib.sha256(frozen_path.read_bytes()).hexdigest()
    (out / "frozen_experiment_config.sha256").write_text(
        exp_cfg_hash + "\n", encoding="utf-8"
    )

    cache = ArtifactCache(
        repo=repo,
        base_cfg=base_cfg,
        root=out / "cache",
        workers=args.workers,
        timeout=args.timeout,
        python=args.python,
    )

    print("Phase A: clean drift reference + Phase-1 development calibration", flush=True)
    ref_map = cache.ensure(REF_STATE, reference_clean)
    dev_samples = [r for r in rows if r["id"] in dev_ids]
    if len(dev_samples) != len(dev_ids):
        print(
            f"WARNING: resolved {len(dev_samples)}/{len(dev_ids)} Phase-1 dev IDs",
            file=sys.stderr,
        )
    dev_map = cache.ensure(REF_STATE, dev_samples)
    rng = np.random.default_rng(27081986)
    cal = calibrate_reference(
        reference_clean,
        ref_map,
        dev_samples,
        dev_map,
        proposal_n=args.block_size // 3,
        rng=rng,
        n_boot=500,
    )
    cal_json = {
        "tau_D": cal.tau_D,
        "U_max": cal.U_max,
        "L_max": cal.L_max,
        "epsilon_U": cal.epsilon_U,
        "tau_plate": cal.tau_plate,
        "tau_char": cal.tau_char,
        "tau_dseg": cal.tau_dseg,
        "tau_dbox": cal.tau_dbox,
        "env_feature_names": list(ENV_FEATURE_NAMES),
    }
    (out / "reference_calibration.json").write_text(
        json.dumps(cal_json, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(cal_json, indent=2), flush=True)

    states = {
        name: ControllerState(name=name, theta=REF_STATE)
        for name in CONTROLLERS
    }
    grid = grid_states()

    event_rows: List[Dict[str, Any]] = []
    sample_rows: List[Dict[str, Any]] = []
    window_rows: List[Dict[str, Any]] = []

    for block in blocks:
        bi = int(block["block_index"])
        cond = str(block["condition"])
        proposal = block["proposal"]
        gate = block["gate"]
        evaluation = block["evaluation"]

        print(f"\n=== block {bi:02d} condition={cond} ===", flush=True)

        # Environment drift is measured using the fixed reference front end.
        ref_prop = cache.ensure(REF_STATE, proposal)
        cur_env = np.vstack(
            [env_features(s, ref_prop[s["id"]]) for s in proposal]
        )
        D = drift_score(cal, cur_env)
        env_trigger = D > cal.tau_D

        # Current-state proposal diagnostics determine risk-trigger status.
        unique_current = sorted(set(st.theta for st in states.values()))
        current_prop_runs: Dict[Tuple[float, float, float], List[Dict[str, Any]]] = {}
        for s in unique_current:
            mp = cache.ensure(s, proposal)
            current_prop_runs[s] = [mp[x["id"]] for x in proposal]

        triggers: Dict[str, bool] = {}
        current_prop_aggs: Dict[str, Dict[str, float]] = {}
        for name, st in states.items():
            agg = aggregate_runs(current_prop_runs[st.theta])
            current_prop_aggs[name] = agg
            triggers[name] = (
                False if name == "B0"
                else bool(
                    env_trigger
                    or agg["mean_U"] > cal.U_max
                    or agg["p95_total_ms"] > cal.L_max
                )
            )

        candidate_runs: Dict[Tuple[float, float, float], Sequence[Dict[str, Any]]] = {}
        if any(triggers.values()):
            print("  trigger present -> evaluating 27-state raw grid on proposal window",
                  flush=True)
            for gs in grid:
                m = cache.ensure(gs, proposal)
                candidate_runs[gs] = [m[x["id"]] for x in proposal]

        for name in CONTROLLERS:
            st = states[name]
            before = st.theta
            trigger = triggers[name]
            raw = before
            raw_obj = None
            projected = before
            projected_from_raw_norm = 0.0
            projection_active = False
            gate_result: Optional[Dict[str, Any]] = None
            decision = "hold"
            rollback = False
            fail_safe = False

            if name != "B0" and trigger:
                raw, raw_obj = select_raw_candidate(
                    before,
                    grid,
                    candidate_runs,
                    cal.L_max,
                )

                if name == "B1":
                    projected = raw
                    decision = "commit_raw"
                    st.theta = raw

                elif name in ("B2", "B3", "B3-R0"):
                    projected, projected_from_raw_norm, projection_active = project_state(
                        before, raw, W_DIAG, DELTA_W
                    )
                    if name == "B2":
                        st.theta = projected
                        decision = "commit_bounded"
                    else:
                        cur_gate_map = cache.ensure(before, gate)
                        cand_gate_map = cache.ensure(projected, gate)
                        cur_gate = [cur_gate_map[x["id"]] for x in gate]
                        cand_gate = [cand_gate_map[x["id"]] for x in gate]

                        rep = cache.rerun_semantic(
                            projected,
                            gate[: min(args.gate_repeat_n, len(gate))],
                        )
                        mismatches = sum(int(a != b) for _, a, b in rep)
                        accepted, gate_result = gate_candidate(
                            cur_gate, cand_gate, mismatches, cal
                        )
                        if accepted:
                            st.theta = projected
                            decision = "commit_gated"
                        else:
                            cur_gate_agg = aggregate_runs(cur_gate)
                            recovery_mode = (
                                cur_gate_agg["mean_U"] > cal.U_max
                                or cur_gate_agg["p95_total_ms"] > cal.L_max
                            )
                            if name == "B3" and recovery_mode:
                                st.theta = REF_STATE
                                decision = "reject_fail_safe_reference"
                                rollback = True
                                fail_safe = True
                            else:
                                decision = "reject_hold"

                elif name == "B3-I":
                    projected, projected_from_raw_norm, projection_active = project_state(
                        before,
                        raw,
                        np.ones(3, dtype=float),
                        DELTA_I,
                    )
                    cur_gate_map = cache.ensure(before, gate)
                    cand_gate_map = cache.ensure(projected, gate)
                    cur_gate = [cur_gate_map[x["id"]] for x in gate]
                    cand_gate = [cand_gate_map[x["id"]] for x in gate]
                    rep = cache.rerun_semantic(
                        projected,
                        gate[: min(args.gate_repeat_n, len(gate))],
                    )
                    mismatches = sum(int(a != b) for _, a, b in rep)
                    accepted, gate_result = gate_candidate(
                        cur_gate, cand_gate, mismatches, cal
                    )
                    if accepted:
                        st.theta = projected
                        decision = "commit_gated_identity"
                    else:
                        cur_gate_agg = aggregate_runs(cur_gate)
                        recovery_mode = (
                            cur_gate_agg["mean_U"] > cal.U_max
                            or cur_gate_agg["p95_total_ms"] > cal.L_max
                        )
                        if recovery_mode:
                            st.theta = REF_STATE
                            decision = "reject_fail_safe_reference"
                            rollback = True
                            fail_safe = True
                        else:
                            decision = "reject_hold"

            after = st.theta
            W_for_log = np.ones(3, dtype=float) if name == "B3-I" else W_DIAG
            update_norm = weighted_distance(before, after, W_for_log)

            ev = {
                "block_index": bi,
                "condition": cond,
                "controller": name,
                "D": D,
                "tau_D": cal.tau_D,
                "env_trigger": int(env_trigger),
                "trigger": int(trigger),
                "current_mean_U_proposal": current_prop_aggs[name]["mean_U"],
                "U_max": cal.U_max,
                "state_before": state_label(before),
                "raw_candidate": state_label(raw),
                "raw_objective": raw_obj,
                "projected_candidate": state_label(projected),
                "projection_active": int(projection_active),
                "raw_weighted_norm": projected_from_raw_norm,
                "state_after": state_label(after),
                "committed_update_norm": update_norm,
                "decision": decision,
                "rollback": int(rollback),
                "fail_safe": int(fail_safe),
                "gate_accepted": (
                    "" if gate_result is None else int(bool(gate_result["accepted"]))
                ),
                "gate_candidate_U": (
                    "" if gate_result is None else gate_result["candidate_mean_U"]
                ),
                "gate_current_U": (
                    "" if gate_result is None else gate_result["current_mean_U"]
                ),
                "gate_p95_ms": (
                    "" if gate_result is None else gate_result["candidate_p95_ms"]
                ),
                "gate_semantic_mismatches": (
                    "" if gate_result is None else gate_result["semantic_repeat_mismatches"]
                ),
            }
            event_rows.append(ev)

        # Evaluate all six controllers on the disjoint evaluation third.
        for name in CONTROLLERS:
            st = states[name]
            emap = cache.ensure(st.theta, evaluation)
            eruns = [emap[x["id"]] for x in evaluation]
            agg = aggregate_runs(eruns)

            pa_list = []
            ca_list = []
            dseg_list = []
            dbox_list = []
            for sm in evaluation:
                r = emap[sm["id"]]
                pa = plate_accuracy(sm["gt"], r["pred"])
                ca = char_accuracy(sm["gt"], r["pred"])
                dseg = abs(int(r["segment_count"]) - int(r["expected_count"]))
                db = box_distance(
                    sm.get("gt_boxes", []),
                    r.get("selected_boxes", []),
                    int(r.get("expected_count") or 6),
                )
                pa_list.append(pa)
                ca_list.append(ca)
                dseg_list.append(float(dseg))
                if db is not None:
                    dbox_list.append(float(db))

                sample_rows.append(
                    {
                        "block_index": bi,
                        "condition": cond,
                        "controller": name,
                        "sample_id": sm["id"],
                        "state": state_label(st.theta),
                        "gt": sm["gt"],
                        "pred": r["pred"],
                        "plate_accuracy": pa,
                        "char_accuracy": ca,
                        "dseg": dseg,
                        "dbox": "" if db is None else db,
                        "U": sample_U(r),
                        "total_ms": r["total_ms"],
                        "search_ms": r["search_ms"],
                        "semantic_trace_hash": r["semantic_trace_hash"],
                    }
                )

            mean_pa = float(np.mean(pa_list))
            mean_ca = float(np.mean(ca_list))
            mean_ds = float(np.mean(dseg_list))
            mean_db = float(np.mean(dbox_list)) if dbox_list else None

            # Stable-region membership is evaluated with GT after the controller
            # decision; task metrics do not feed back into the controller.
            outside_reasons = []
            if mean_pa < cal.tau_plate:
                outside_reasons.append("plate")
            if mean_ca < cal.tau_char:
                outside_reasons.append("char")
            if mean_ds > cal.tau_dseg:
                outside_reasons.append("dseg")
            if cal.tau_dbox is not None and mean_db is not None and mean_db > cal.tau_dbox:
                outside_reasons.append("dbox")
            if agg["mean_U"] > cal.U_max:
                outside_reasons.append("U")
            if agg["p95_total_ms"] > cal.L_max:
                outside_reasons.append("latency")

            window_rows.append(
                {
                    "block_index": bi,
                    "condition": cond,
                    "controller": name,
                    "state": state_label(st.theta),
                    "plate_accuracy": mean_pa,
                    "char_accuracy": mean_ca,
                    "mean_dseg": mean_ds,
                    "mean_dbox": "" if mean_db is None else mean_db,
                    "mean_U": agg["mean_U"],
                    "mean_total_ms": agg["mean_total_ms"],
                    "p95_total_ms": agg["p95_total_ms"],
                    "mean_search_ms": agg["mean_search_ms"],
                    "outside_stable_region": int(bool(outside_reasons)),
                    "outside_reasons": "|".join(outside_reasons),
                }
            )

    # -----------------------------------------------------------------------
    # Write detailed CSVs
    # -----------------------------------------------------------------------
    def write_rows(path: Path, rows_: Sequence[Dict[str, Any]]) -> None:
        if not rows_:
            return
        fields = list(rows_[0].keys())
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows_)

    write_rows(out / "controller_events.csv", event_rows)
    write_rows(out / "window_results.csv", window_rows)
    write_rows(out / "sample_results.csv", sample_rows)

    # -----------------------------------------------------------------------
    # Aggregate summaries
    # -----------------------------------------------------------------------
    summary: Dict[str, Any] = {
        "partition_sha256": partition_hash,
        "frozen_config_sha256": exp_cfg_hash,
        "calibration": cal_json,
        "controllers": {},
        "ground_truth_boxes_detected": any(bool(r.get("gt_boxes")) for r in rows),
    }

    rng_summary = np.random.default_rng(314159)
    for name in CONTROLLERS:
        sr = [r for r in sample_rows if r["controller"] == name]
        wr = [r for r in window_rows if r["controller"] == name]
        evr = [r for r in event_rows if r["controller"] == name]

        pa = [float(r["plate_accuracy"]) for r in sr]
        ca = [float(r["char_accuracy"]) for r in sr]
        outside = [float(r["outside_stable_region"]) for r in wr]
        pa_ci = bootstrap_ci(pa, rng_summary, args.bootstrap)
        ca_ci = bootstrap_ci(ca, rng_summary, args.bootstrap)
        out_ci = bootstrap_ci(outside, rng_summary, args.bootstrap)

        summary["controllers"][name] = {
            "n_eval_samples": len(sr),
            "n_eval_windows": len(wr),
            "plate_accuracy": mean(pa),
            "plate_accuracy_ci95": pa_ci,
            "char_accuracy": mean(ca),
            "char_accuracy_ci95": ca_ci,
            "outside_stable_region_rate": mean(outside),
            "outside_stable_region_rate_ci95": out_ci,
            "mean_total_ms": mean(float(r["total_ms"]) for r in sr),
            "p95_total_ms": percentile((float(r["total_ms"]) for r in sr), 0.95),
            "mean_dseg": mean(float(r["dseg"]) for r in sr),
            "mean_dbox": mean(
                float(r["dbox"]) for r in sr if str(r["dbox"]) != ""
            ),
            "trigger_count": sum(int(r["trigger"]) for r in evr),
            "commit_count": sum(
                str(r["decision"]).startswith("commit") for r in evr
            ),
            "rollback_count": sum(int(r["rollback"]) for r in evr),
            "fail_safe_count": sum(int(r["fail_safe"]) for r in evr),
        }

    # Paired sample-level controller comparisons versus B3 and B0/B1/B2.
    by_sample: Dict[Tuple[int, str], Dict[str, Dict[str, Any]]] = {}
    for r in sample_rows:
        key = (int(r["block_index"]), str(r["sample_id"]))
        by_sample.setdefault(key, {})[str(r["controller"])] = r

    comparisons = []
    for a, b in (
        ("B3", "B0"),
        ("B3", "B1"),
        ("B3", "B2"),
        ("B3", "B3-I"),
        ("B3", "B3-R0"),
    ):
        dpa, dca = [], []
        for group in by_sample.values():
            if a not in group or b not in group:
                continue
            dpa.append(
                float(group[a]["plate_accuracy"]) - float(group[b]["plate_accuracy"])
            )
            dca.append(
                float(group[a]["char_accuracy"]) - float(group[b]["char_accuracy"])
            )
        pa_ci = bootstrap_ci(dpa, rng_summary, args.bootstrap)
        ca_ci = bootstrap_ci(dca, rng_summary, args.bootstrap)
        comparisons.append(
            {
                "controller_a": a,
                "controller_b": b,
                "n_paired_samples": len(dpa),
                "delta_plate_accuracy": mean(dpa),
                "delta_plate_accuracy_ci95_low": pa_ci[0],
                "delta_plate_accuracy_ci95_high": pa_ci[1],
                "delta_char_accuracy": mean(dca),
                "delta_char_accuracy_ci95_low": ca_ci[0],
                "delta_char_accuracy_ci95_high": ca_ci[1],
            }
        )

    write_rows(out / "paired_comparisons.csv", comparisons)

    (out / "summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print("\n=== FINAL SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"\nOutputs written to: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
