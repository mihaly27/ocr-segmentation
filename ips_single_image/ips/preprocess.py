from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple

import cv2
import numpy as np


@dataclass(frozen=True)
class PreprocessConfig:
    mode: Literal["otsu", "fixed", "adaptive"] = "otsu"
    fixed_tau: float = 0.45
    adaptive_block_size: int = 31
    adaptive_C: int = 5
    morph_kernel: int = 3
    morph_iter: int = 1


def make_mask(gray: np.ndarray, cfg: PreprocessConfig) -> np.ndarray:
    """Return a binary mask (uint8 0/1) from a grayscale image."""
    if gray.ndim != 2:
        raise ValueError("gray must be HxW")

    # Normalize to 0..255 uint8
    if gray.dtype != np.uint8:
        g = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    else:
        g = gray

    if cfg.mode == "otsu":
        _, bin255 = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif cfg.mode == "fixed":
        t = int(np.clip(cfg.fixed_tau, 0.0, 1.0) * 255)
        _, bin255 = cv2.threshold(g, t, 255, cv2.THRESH_BINARY)
    elif cfg.mode == "adaptive":
        b = cfg.adaptive_block_size
        if b % 2 == 0:
            b += 1
        bin255 = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, b, cfg.adaptive_C)
    else:
        raise ValueError(f"Unknown mode: {cfg.mode}")

    # Heuristic: ensure foreground is 1 where characters are dark
    # If more than half is white, invert.
    if np.mean(bin255) > 127:
        bin255 = 255 - bin255

    k = max(1, int(cfg.morph_kernel))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    # Close then open to mend small gaps while suppressing speckles
    bin255 = cv2.morphologyEx(bin255, cv2.MORPH_CLOSE, kernel, iterations=int(cfg.morph_iter))
    bin255 = cv2.morphologyEx(bin255, cv2.MORPH_OPEN, kernel, iterations=max(1, int(cfg.morph_iter)))

    return (bin255 > 0).astype(np.uint8)
