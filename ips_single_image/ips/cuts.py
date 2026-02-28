from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np

from .types import Segment


@dataclass(frozen=True)
class CutConfig:
    max_cuts_per_component: int = 3
    min_rel_width_for_split: float = 1.6  # if w > this * median_w, consider split
    smooth_window: int = 5
    min_cut_margin: int = 2
    max_column_sum_quantile: float = 0.2  # look for low columns


def _smooth_1d(x: np.ndarray, w: int) -> np.ndarray:
    if w <= 1:
        return x
    kernel = np.ones(w, dtype=np.float32) / float(w)
    return np.convolve(x.astype(np.float32), kernel, mode="same")


def propose_vertical_cuts(component_mask01: np.ndarray, cfg: CutConfig) -> List[int]:
    """Return candidate x-cut columns (0..w-1) inside the component bbox.

    Uses minima of vertical projection (column foreground counts).
    """
    h, w = component_mask01.shape
    if w < 4:
        return []

    proj = component_mask01.sum(axis=0)  # length w
    proj_s = _smooth_1d(proj, cfg.smooth_window)

    # Candidate minima: columns in the lowest quantile of proj
    thresh = np.quantile(proj_s, cfg.max_column_sum_quantile)
    candidates = [i for i in range(cfg.min_cut_margin, w - cfg.min_cut_margin) if proj_s[i] <= thresh]
    if not candidates:
        return []

    # Greedy select well-separated cuts with smallest projection values
    candidates.sort(key=lambda i: (proj_s[i], i))
    selected: List[int] = []
    for i in candidates:
        if all(abs(i - j) >= cfg.smooth_window for j in selected):
            selected.append(i)
        if len(selected) >= cfg.max_cuts_per_component:
            break

    selected.sort()
    return selected


def split_mask_by_cut(mask01: np.ndarray, cut_x: int) -> Tuple[np.ndarray, np.ndarray]:
    """Split a local component mask into left/right parts by a vertical cut column."""
    left = mask01.copy()
    right = mask01.copy()
    left[:, cut_x:] = 0
    right[:, :cut_x] = 0
    return left, right


def segment_from_mask(mask01: np.ndarray, offset_xy: Tuple[int, int], seg_id: int) -> Segment | None:
    """Create a Segment from a binary mask (local coords) and an (x,y) offset."""
    ys, xs = np.nonzero(mask01)
    if len(xs) == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    w = x1 - x0 + 1
    h = y1 - y0 + 1
    area = int(mask01.sum())
    cx = float(xs.mean()) + offset_xy[0]
    cy = float(ys.mean()) + offset_xy[1]
    return Segment(id=seg_id, bbox=(offset_xy[0] + x0, offset_xy[1] + y0, w, h), area=area, centroid=(cx, cy))


def refine_segment_with_cuts(labels: np.ndarray, seg: Segment, cut_cfg: CutConfig, next_id_start: int) -> List[List[Segment]]:
    """Generate alternative refinements of a segment via 0 or 1 vertical cut.

    Returns a list of variants; each variant is a list of segments that replace the input segment.
    """
    x, y, w, h = seg.bbox
    local = (labels[y:y+h, x:x+w] == seg.id).astype(np.uint8)

    cuts = propose_vertical_cuts(local, cut_cfg)
    variants: List[List[Segment]] = [[seg]]

    # Only consider single-cut variants (keeps it simple and fast for single-image runs)
    for k, cx in enumerate(cuts):
        left, right = split_mask_by_cut(local, cx)
        s1 = segment_from_mask(left, (x, y), next_id_start + 2*k)
        s2 = segment_from_mask(right, (x, y), next_id_start + 2*k + 1)
        if s1 is None or s2 is None:
            continue
        # enforce deterministic order in the variant
        parts = sorted([s1, s2], key=lambda s: s.sort_key())
        variants.append(parts)

    return variants
