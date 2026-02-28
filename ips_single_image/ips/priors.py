from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np

from .types import Segment


@dataclass(frozen=True)
class ScoringConfig:
    # weights
    w_fit: float = 1.0
    w_overlap: float = 10.0
    w_prior: float = 2.0

    # overlap
    overlap_eps: float = 0.02  # allowed normalized intersection

    # density
    rho_max: float = 0.75

    # blocking
    blocking_gap_ratio: float = 0.05

    # fast fit proxies
    aspect_min: float = 0.25
    aspect_max: float = 4.0
    extent_min: float = 0.05
    extent_max: float = 0.95


def _bbox_intersection(a: Tuple[int,int,int,int], b: Tuple[int,int,int,int]) -> int:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    inter_w = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    inter_h = max(0, min(ay + ah, by + bh) - max(ay, by))
    return int(inter_w * inter_h)


def score_partition(segments: List[Segment], image_shape_hw: Tuple[int,int], cfg: ScoringConfig) -> Tuple[float, Dict[str, Any]]:
    """Compute a scalar score (lower is better) and a structured breakdown."""
    H, W = image_shape_hw
    container_area = float(max(1, H * W))

    # --- fit proxy term ---
    fit_pen = 0.0
    fit_details = []
    for s in segments:
        x, y, w, h = s.bbox
        aspect = (w / max(1.0, float(h)))
        extent = (s.area / max(1.0, float(w * h)))
        p = 0.0
        if aspect < cfg.aspect_min:
            p += (cfg.aspect_min - aspect)
        if aspect > cfg.aspect_max:
            p += (aspect - cfg.aspect_max)
        if extent < cfg.extent_min:
            p += (cfg.extent_min - extent)
        if extent > cfg.extent_max:
            p += (extent - cfg.extent_max)
        fit_pen += p
        fit_details.append({
            "id": s.id,
            "aspect": float(aspect),
            "extent": float(extent),
            "pen": float(p),
        })

    # --- overlap term ---
    overlap_pen = 0.0
    overlap_pairs = []
    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            inter = _bbox_intersection(segments[i].bbox, segments[j].bbox)
            if inter <= 0:
                continue
            denom = float(max(1, min(segments[i].bbox[2] * segments[i].bbox[3],
                                     segments[j].bbox[2] * segments[j].bbox[3])))
            r = inter / denom
            if r > cfg.overlap_eps:
                overlap_pen += r
                overlap_pairs.append({
                    "i": segments[i].id,
                    "j": segments[j].id,
                    "inter_norm": float(r),
                })

    # --- density prior ---
    density = float(sum(s.area for s in segments) / container_area)
    density_pen = max(0.0, density - cfg.rho_max)

    # --- blocking prior (1D order in x) ---
    blocking = 0
    blocking_pairs = []
    seg_sorted = sorted(segments, key=lambda s: (s.bbox[0], s.bbox[1], s.id))
    for a, b in zip(seg_sorted, seg_sorted[1:]):
        xa, ya, wa, ha = a.bbox
        xb, yb, wb, hb = b.bbox
        gap = xb - (xa + wa)
        thresh = cfg.blocking_gap_ratio * float(min(wa, wb))
        if gap < thresh:
            blocking += 1
            blocking_pairs.append({
                "a": a.id,
                "b": b.id,
                "gap": float(gap),
                "thresh": float(thresh),
            })

    prior_pen = density_pen + float(blocking)

    total = cfg.w_fit * fit_pen + cfg.w_overlap * overlap_pen + cfg.w_prior * prior_pen

    breakdown: Dict[str, Any] = {
        "fit": {"sum": float(fit_pen), "per_segment": fit_details},
        "overlap": {"sum": float(overlap_pen), "pairs": overlap_pairs, "eps": float(cfg.overlap_eps)},
        "prior": {
            "sum": float(prior_pen),
            "density": density,
            "density_pen": float(density_pen),
            "rho_max": float(cfg.rho_max),
            "blocking": int(blocking),
            "blocking_pairs": blocking_pairs,
            "blocking_gap_ratio": float(cfg.blocking_gap_ratio),
        },
        "weights": {"w_fit": cfg.w_fit, "w_overlap": cfg.w_overlap, "w_prior": cfg.w_prior},
        "total": float(total),
    }
    return float(total), breakdown
