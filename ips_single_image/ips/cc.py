from __future__ import annotations

from typing import List, Tuple

import cv2
import numpy as np

from .types import Segment


def connected_components(mask01: np.ndarray) -> Tuple[List[Segment], np.ndarray]:
    """Connected components with deterministic ordering.

    Parameters
    ----------
    mask01: uint8 array with values {0,1}

    Returns
    -------
    segments: list of Segment
    labels: HxW int32 label image
    """
    if mask01.dtype != np.uint8:
        mask01 = mask01.astype(np.uint8)

    num, labels, stats, centroids = cv2.connectedComponentsWithStats(mask01, connectivity=8)

    segs: List[Segment] = []
    for i in range(1, num):  # 0 is background
        x, y, w, h, area = stats[i].tolist()
        cx, cy = centroids[i].tolist()
        segs.append(Segment(id=i, bbox=(int(x), int(y), int(w), int(h)), area=int(area), centroid=(float(cx), float(cy))))

    segs.sort(key=lambda s: s.sort_key())
    return segs, labels
