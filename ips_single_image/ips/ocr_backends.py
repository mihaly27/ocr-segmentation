from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from .types import Segment


@dataclass(frozen=True)
class OCRConfig:
    backend: str = "tesseract"  # tesseract|none|easyocr|paddleocr
    whitelist: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    psm: int = 10
    oem: int = 3
    pad: int = 2
    resize_h: int = 64


def _crop(img: np.ndarray, bbox: Tuple[int,int,int,int], pad: int) -> np.ndarray:
    x, y, w, h = bbox
    H, W = img.shape[:2]
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(W, x + w + pad)
    y1 = min(H, y + h + pad)
    return img[y0:y1, x0:x1].copy()


def ocr_segments(gray_or_bgr: np.ndarray, segments: List[Segment], cfg: OCRConfig) -> Tuple[str, List[str]]:
    """Run OCR on segments left-to-right and return (plate_string, per_segment)."""
    segs = sorted(segments, key=lambda s: s.sort_key())

    if cfg.backend == "none":
        return "", ["" for _ in segs]

    if cfg.backend == "tesseract":
        try:
            import cv2
            import pytesseract
        except Exception:
            return "", ["" for _ in segs]

        out = []
        for s in segs:
            patch = _crop(gray_or_bgr, s.bbox, cfg.pad)
            if patch.ndim == 3:
                patch = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
            # resize to a stable height
            h, w = patch.shape[:2]
            if h > 0 and cfg.resize_h > 0 and h != cfg.resize_h:
                scale = cfg.resize_h / float(h)
                patch = cv2.resize(patch, (max(1, int(w * scale)), cfg.resize_h), interpolation=cv2.INTER_CUBIC)
            patch = cv2.GaussianBlur(patch, (3, 3), 0)
            _, patch = cv2.threshold(patch, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            # invert if needed
            if np.mean(patch) > 127:
                patch = 255 - patch

            tess_cfg = f"--oem {cfg.oem} --psm {cfg.psm} -c tessedit_char_whitelist={cfg.whitelist}"
            txt = pytesseract.image_to_string(patch, config=tess_cfg)
            txt = "".join([c for c in txt.upper() if c.isalnum()])
            out.append(txt[:1] if txt else "")

        plate = "".join(out)
        return plate, out

    if cfg.backend == "easyocr":
        try:
            import cv2
            import easyocr
            reader = easyocr.Reader(["en"], gpu=False)
        except Exception:
            return "", ["" for _ in segs]

        out = []
        for s in segs:
            patch = _crop(gray_or_bgr, s.bbox, cfg.pad)
            if patch.ndim == 2:
                patch = cv2.cvtColor(patch, cv2.COLOR_GRAY2BGR)
            res = reader.readtext(patch, detail=0)
            txt = (res[0] if res else "")
            txt = "".join([c for c in txt.upper() if c.isalnum()])
            out.append(txt[:1] if txt else "")
        return "".join(out), out

    if cfg.backend == "paddleocr":
        try:
            import cv2
            from paddleocr import PaddleOCR
            ocr = PaddleOCR(use_angle_cls=False, lang='en')
        except Exception:
            return "", ["" for _ in segs]

        out = []
        for s in segs:
            patch = _crop(gray_or_bgr, s.bbox, cfg.pad)
            res = ocr.ocr(patch, cls=False)
            txt = ""
            if res and res[0]:
                txt = res[0][0][1][0]
            txt = "".join([c for c in txt.upper() if c.isalnum()])
            out.append(txt[:1] if txt else "")
        return "".join(out), out

    # unknown backend
    return "", ["" for _ in segs]
