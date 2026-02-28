from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np

from .cuts import CutConfig, refine_segment_with_cuts
from .priors import ScoringConfig, score_partition
from .types import Segment


@dataclass
class SearchConfig:
    beam_size: int = 50
    max_steps: int = 12
    expected_count: int = 6


def _segments_signature(segs: List[Segment]) -> Tuple[Tuple[int,int,int,int,int], ...]:
    # deterministic signature for tie-breaks
    out = []
    for s in sorted(segs, key=lambda s: s.sort_key()):
        x,y,w,h = s.bbox
        out.append((x,y,w,h,s.area))
    return tuple(out)


@dataclass
class Hypothesis:
    segments: List[Segment]
    score: float
    breakdown: Dict[str, Any]
    history: List[Dict[str, Any]]

    def sort_key(self):
        # lower score better; then prefer closer to expected count; then stable signature
        return (
            float(self.score),
            abs(len(self.segments) - int(self.breakdown.get("expected_count", 0))),
            _segments_signature(self.segments),
        )


def beam_search(labels: np.ndarray,
                init_segments: List[Segment],
                image_shape_hw: Tuple[int,int],
                search_cfg: SearchConfig,
                cut_cfg: CutConfig,
                scoring_cfg: ScoringConfig) -> Hypothesis:
    """Beam search over split proposals; designed for single-image runs."""
    # Initialize
    base_score, base_breakdown = score_partition(init_segments, image_shape_hw, scoring_cfg)
    base_breakdown["expected_count"] = int(search_cfg.expected_count)

    beam: List[Hypothesis] = [Hypothesis(
        segments=sorted(init_segments, key=lambda s: s.sort_key()),
        score=base_score,
        breakdown=base_breakdown,
        history=[{"step": 0, "action": "init", "score": float(base_score), "n": len(init_segments)}],
    )]

    next_id = max([s.id for s in init_segments] + [0]) + 1

    for step in range(1, int(search_cfg.max_steps) + 1):
        candidates: List[Hypothesis] = []

        for hyp in beam:
            segs = sorted(hyp.segments, key=lambda s: s.sort_key())
            widths = [s.bbox[2] for s in segs]
            med_w = float(np.median(widths)) if widths else 1.0

            # Deterministic expansion order: left-to-right
            for idx, seg in enumerate(segs):
                x,y,w,h = seg.bbox
                if med_w > 0 and w < cut_cfg.min_rel_width_for_split * med_w:
                    continue

                variants = refine_segment_with_cuts(labels, seg, cut_cfg, next_id_start=next_id)

                # First variant is identity; skip to avoid duplicates
                for v in variants[1:]:
                    new_segs = [s for s in segs if s.id != seg.id] + v
                    new_segs = sorted(new_segs, key=lambda s: s.sort_key())

                    sc, br = score_partition(new_segs, image_shape_hw, scoring_cfg)
                    br["expected_count"] = int(search_cfg.expected_count)
                    br["count_pen"] = float(abs(len(new_segs) - int(search_cfg.expected_count)))

                    hist = hyp.history + [{
                        "step": step,
                        "action": "split",
                        "target_id": int(seg.id),
                        "variant": [int(s.id) for s in v],
                        "score": float(sc),
                        "n": len(new_segs),
                    }]
                    candidates.append(Hypothesis(new_segs, sc, br, hist))

                # Advance id budget deterministically even if no variant used
                next_id += 2 * max(1, cut_cfg.max_cuts_per_component)

        # Always keep the previous hypotheses as candidates as well (allows early stop)
        candidates.extend(beam)

        # Deduplicate by signature (keep best score)
        best_by_sig: Dict[Tuple[Tuple[int,int,int,int,int], ...], Hypothesis] = {}
        for h in candidates:
            sig = _segments_signature(h.segments)
            prev = best_by_sig.get(sig)
            if prev is None or h.score < prev.score:
                best_by_sig[sig] = h

        new_beam = sorted(best_by_sig.values(), key=lambda h: (h.score, h.breakdown.get("count_pen", 0.0), _segments_signature(h.segments)))
        beam = new_beam[: int(search_cfg.beam_size)]

    # Final selection: best score; if ties, prefer closest to expected count
    best = sorted(beam, key=lambda h: (h.score, abs(len(h.segments) - search_cfg.expected_count), _segments_signature(h.segments)))[0]
    return best
