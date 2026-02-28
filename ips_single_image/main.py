from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

import cv2
import numpy as np
import yaml

from ips import (
    CutConfig,
    OCRConfig,
    PreprocessConfig,
    ScoringConfig,
    SearchConfig,
    beam_search,
    connected_components,
    draw_segments,
    hash_trace,
    make_mask,
    ocr_segments,
)


def edit_distance(a: str, b: str) -> int:
    """Levenshtein edit distance (DP, O(nm)) for short strings."""
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, m + 1):
            cur = dp[j]
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
            prev = cur
    return dp[m]


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> int:
    parser = argparse.ArgumentParser(description="IPS single-image segmentation + trace")
    parser.add_argument("--image", required=True, help="Path to a single plate crop image")
    parser.add_argument("--outdir", default="out", help="Output directory")
    parser.add_argument("--config", default="config.yaml", help="YAML config path")
    parser.add_argument("--gt", default="", help="Optional ground-truth plate string")
    args = parser.parse_args()

    cv2.setNumThreads(1)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(Path(args.config))

    pre_cfg = PreprocessConfig(**(cfg.get("preprocess", {}) or {}))
    cut_cfg = CutConfig(**(cfg.get("cut", {}) or {}))
    search_cfg = SearchConfig(**(cfg.get("search", {}) or {}))
    score_cfg = ScoringConfig(**(cfg.get("scoring", {}) or {}))
    ocr_cfg = OCRConfig(**(cfg.get("ocr", {}) or {}))

    timings: Dict[str, float] = {}

    t0 = time.perf_counter()
    img = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"Failed to read image: {args.image}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    timings["load_ms"] = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    mask01 = make_mask(gray, pre_cfg)
    timings["preprocess_ms"] = (time.perf_counter() - t1) * 1000.0

    t2 = time.perf_counter()
    segs, labels = connected_components(mask01)
    timings["cc_ms"] = (time.perf_counter() - t2) * 1000.0

    t3 = time.perf_counter()
    best = beam_search(labels, segs, (gray.shape[0], gray.shape[1]), search_cfg, cut_cfg, score_cfg)
    timings["search_ms"] = (time.perf_counter() - t3) * 1000.0

    t4 = time.perf_counter()
    pred, per_seg = ocr_segments(img, best.segments, ocr_cfg)
    timings["ocr_ms"] = (time.perf_counter() - t4) * 1000.0

    timings["total_ms"] = sum(timings.values())

    # Metrics (single image)
    gt = "".join([c for c in args.gt.upper() if c.isalnum()])
    full_plate_acc = 1.0 if (gt and pred == gt) else 0.0 if gt else None
    char_acc = None
    if gt:
        dist = edit_distance(pred, gt)
        denom = max(len(gt), len(pred), 1)
        char_acc = 1.0 - (dist / float(denom))

    # Trace
    trace: Dict[str, Any] = {
        "input": {
            "image": os.path.abspath(args.image),
            "H": int(gray.shape[0]),
            "W": int(gray.shape[1]),
            "gt": gt,
        },
        "config": {
            "preprocess": asdict(pre_cfg),
            "cut": asdict(cut_cfg),
            "search": asdict(search_cfg),
            "scoring": asdict(score_cfg),
            "ocr": asdict(ocr_cfg),
        },
        "timings_ms": {k: float(v) for k, v in timings.items()},
        "initial_segments": [
            {"id": int(s.id), "bbox": list(map(int, s.bbox)), "area": int(s.area)} for s in segs
        ],
        "selected_segments": [
            {"id": int(s.id), "bbox": list(map(int, s.bbox)), "area": int(s.area)} for s in best.segments
        ],
        "search_history": best.history,
        "score_breakdown": best.breakdown,
        "ocr": {
            "pred": pred,
            "per_segment": per_seg,
        },
        "metrics": {
            "char_accuracy": char_acc,
            "full_plate_accuracy": full_plate_acc,
            "segment_count": int(len(best.segments)),
            "expected_count": int(search_cfg.expected_count),
        },
    }
    trace["trace_hash"] = hash_trace(trace)

    # Save outputs
    vis = draw_segments(img, best.segments)
    cv2.imwrite(str(outdir / "segments.png"), vis)

    (outdir / "trace.json").write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")

    result = {
        "pred": pred,
        "gt": gt,
        "char_accuracy": char_acc,
        "full_plate_accuracy": full_plate_acc,
        "trace_hash": trace["trace_hash"],
        "total_ms": timings["total_ms"],
    }
    (outdir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
