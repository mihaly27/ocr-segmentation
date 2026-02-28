from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Segment:
    """A segment hypothesis represented by its bounding box and basic moments."""

    id: int
    bbox: Tuple[int, int, int, int]  # (x, y, w, h)
    area: int
    centroid: Tuple[float, float]

    def sort_key(self):
        """Deterministic ordering for tie-breaks."""
        x, y, w, h = self.bbox
        return (x, y, -self.area, self.id)
