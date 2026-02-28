from __future__ import annotations

from typing import List, Tuple

import cv2
import numpy as np

from .types import Segment


def draw_segments(image_bgr: np.ndarray, segments: List[Segment]) -> np.ndarray:
    """Draw bounding boxes and indices on a copy of the image."""
    out = image_bgr.copy()
    segs = sorted(segments, key=lambda s: s.sort_key())
    for idx, s in enumerate(segs, start=1):
        x, y, w, h = s.bbox
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(out, f"{idx}", (x, max(0, y - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return out
