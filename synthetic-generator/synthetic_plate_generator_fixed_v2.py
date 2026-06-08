#!/usr/bin/env python3
"""
Synthetic license-plate crop generator for traceable OCR segmentation experiments.

Purpose:
- Generate controlled plate crops with known ground-truth string and character boxes.
- Provide perturbation levels for OCR segmentation ablation:
  clean, blur, glare, touch, broken, threshold, perspective, compression, combo.
- Export JSONL and CSV manifests for reproducible benchmark runs.

Dependencies:
    pip install pillow numpy opencv-python

Example:
    python synthetic_plate_generator.py --out synthetic_plates --n 1000 --seed 27 --perturb all
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import string
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

try:
    import cv2
except ImportError as exc:
    raise SystemExit("This script requires opencv-python. Install with: pip install opencv-python") from exc


@dataclass
class CharBox:
    char: str
    x: int
    y: int
    w: int
    h: int
    index: int


@dataclass
class SampleRecord:
    sample_id: str
    plate: str
    split: str
    perturbation: str
    image_path: str
    mask_path: str
    width: int
    height: int
    char_boxes: List[Dict]
    params: Dict


def to_jsonable(obj):
    """Convert NumPy scalar/container values to standard Python JSON values."""
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, tuple):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def find_font(font_size: int) -> ImageFont.FreeTypeFont:
    """Find a bold sans-serif font available on most Linux/Windows systems."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, font_size)

    # Fallback: default bitmap font. This is less realistic but keeps the script runnable.
    return ImageFont.load_default()


def random_plate(rng: random.Random) -> str:
    """Legacy HU-style synthetic plate: 3 uppercase letters + 3 digits."""
    letters = "".join(rng.choice(string.ascii_uppercase) for _ in range(3))
    digits = "".join(rng.choice(string.digits) for _ in range(3))
    return letters + digits


def draw_base_plate(
    plate: str,
    width: int,
    height: int,
    rng: random.Random,
    touching_level: float = 0.0,
) -> Tuple[Image.Image, Image.Image, List[CharBox], Dict]:
    """
    Render a clean plate crop and binary foreground mask.

    touching_level:
        0.0 = normal spacing
        1.0 = very tight spacing, likely touching after morphology/blur
    """
    bg = int(rng.uniform(220, 250))
    fg = int(rng.uniform(5, 35))

    img = Image.new("L", (width, height), color=bg)
    mask = Image.new("L", (width, height), color=0)

    draw = ImageDraw.Draw(img)
    mask_draw = ImageDraw.Draw(mask)

    # Border and mild plate rectangle.
    border = max(2, width // 140)
    draw.rounded_rectangle(
        [border, border, width - border - 1, height - border - 1],
        radius=max(4, height // 12),
        outline=int(rng.uniform(90, 150)),
        width=max(1, border),
        fill=bg,
    )

    # Choose a font size that actually fits into the crop.
    # The previous version could render too wide strings for small crops or
    # fallback fonts, which later produced invalid crop coordinates.
    font_size = int(height * rng.uniform(0.54, 0.68))

    # Normal gap, then reduce by touching level.
    normal_gap = width * rng.uniform(0.035, 0.055)
    tight_gap = -width * rng.uniform(0.005, 0.018)
    gap = int((1.0 - touching_level) * normal_gap + touching_level * tight_gap)

    # Slight group gap between letters and numbers.
    group_gap = int(width * rng.uniform(0.035, 0.055) * (1.0 - 0.7 * touching_level))

    char_metrics = []
    total_width = width + 1
    for _ in range(25):
        font = find_font(font_size)
        char_metrics = []
        for ch in plate:
            bbox = draw.textbbox((0, 0), ch, font=font)
            cw = max(1, bbox[2] - bbox[0])
            chh = max(1, bbox[3] - bbox[1])
            char_metrics.append((cw, chh))
        total_char_width = sum(w for w, _ in char_metrics)
        total_width = total_char_width + gap * 4 + group_gap

        # Keep a small margin; if the text does not fit, reduce font size.
        if total_width <= 0.88 * width or font_size <= 10:
            break
        font_size = max(10, int(font_size * 0.92))

    # If the text is still too wide, compress the gaps first.
    if total_width > 0.92 * width:
        gap = min(gap, 1)
        group_gap = max(2, int(group_gap * 0.5))
        total_char_width = sum(w for w, _ in char_metrics)
        total_width = total_char_width + gap * 4 + group_gap

    x = max(2, int((width - total_width) / 2))
    y_base = int(height * rng.uniform(0.11, 0.20))

    char_boxes: List[CharBox] = []

    for idx, ch in enumerate(plate):
        if idx == 3:
            x += group_gap

        w, h = char_metrics[idx]
        y = y_base + int(rng.uniform(-height * 0.025, height * 0.025))

        # Draw text on image and mask.
        draw.text((x, y), ch, font=font, fill=fg)
        mask_draw.text((x, y), ch, font=font, fill=255)

        # Tight box from local mask crop for more useful annotation.
        # Coordinates must be clamped carefully; otherwise PIL raises
        # "right is less than left" if a rendered string exceeds the crop.
        left = max(0, min(width, x - 3))
        top = max(0, min(height, y - 3))
        right = max(0, min(width, x + w + 6))
        bottom = max(0, min(height, y + h + 8))

        if right > left and bottom > top:
            local = np.array(mask.crop((left, top, right, bottom)))
            ys, xs = np.where(local > 0)
        else:
            local = np.zeros((0, 0), dtype=np.uint8)
            ys, xs = np.array([]), np.array([])

        if len(xs) > 0:
            bx0 = left + int(xs.min())
            by0 = top + int(ys.min())
            bx1 = left + int(xs.max()) + 1
            by1 = top + int(ys.max()) + 1
        else:
            bx0 = max(0, min(width - 1, x))
            by0 = max(0, min(height - 1, y))
            bx1 = max(bx0 + 1, min(width, x + w))
            by1 = max(by0 + 1, min(height, y + h))

        char_boxes.append(CharBox(ch, bx0, by0, bx1 - bx0, by1 - by0, idx))

        x += w + gap

    params = {
        "font_size": font_size,
        "gap": gap,
        "group_gap": group_gap,
        "touching_level": touching_level,
        "bg": bg,
        "fg": fg,
    }
    return img, mask, char_boxes, params


def apply_blur(img: Image.Image, mask: Image.Image, rng: random.Random, severity: float) -> Tuple[Image.Image, Image.Image, Dict]:
    radius = float(np.interp(severity, [0, 1], [0.8, 2.8]))
    return img.filter(ImageFilter.GaussianBlur(radius=radius)), mask, {"blur_radius": radius}


def apply_glare(img: Image.Image, mask: Image.Image, rng: random.Random, severity: float) -> Tuple[Image.Image, Image.Image, Dict]:
    arr = np.array(img).astype(np.float32)
    h, w = arr.shape
    cx = rng.uniform(0.15 * w, 0.85 * w)
    cy = rng.uniform(0.15 * h, 0.85 * h)
    sigma = rng.uniform(0.10, 0.25) * max(w, h)
    yy, xx = np.mgrid[0:h, 0:w]
    spot = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))
    strength = np.interp(severity, [0, 1], [45, 115])
    arr = np.clip(arr + strength * spot, 0, 255)
    return Image.fromarray(arr.astype(np.uint8)), mask, {"glare_strength": float(strength), "glare_sigma": float(sigma)}


def apply_broken_strokes(img: Image.Image, mask: Image.Image, rng: random.Random, severity: float) -> Tuple[Image.Image, Image.Image, Dict]:
    """
    Remove small random vertical/horizontal gaps from foreground.
    This simulates thresholding artifacts and broken strokes.
    """
    img_arr = np.array(img).copy()
    mask_arr = np.array(mask).copy()

    h, w = mask_arr.shape
    n_cuts = int(np.interp(severity, [0, 1], [3, 12]))
    bg_est = int(np.percentile(img_arr, 95))

    for _ in range(n_cuts):
        x = rng.randint(int(0.05 * w), int(0.95 * w))
        y = rng.randint(int(0.15 * h), int(0.85 * h))
        cut_w = rng.randint(1, max(2, int(1 + severity * 4)))
        cut_h = rng.randint(max(4, int(0.12 * h)), max(6, int(0.45 * h)))
        x0, x1 = max(0, x - cut_w), min(w, x + cut_w)
        y0, y1 = max(0, y - cut_h // 2), min(h, y + cut_h // 2)
        img_arr[y0:y1, x0:x1] = bg_est
        mask_arr[y0:y1, x0:x1] = 0

    return Image.fromarray(img_arr), Image.fromarray(mask_arr), {"broken_cuts": n_cuts}


def apply_threshold_shift(img: Image.Image, mask: Image.Image, rng: random.Random, severity: float) -> Tuple[Image.Image, Image.Image, Dict]:
    """
    Re-threshold with contrast/gamma perturbation to simulate binarization instability.
    """
    arr = np.array(img).astype(np.float32)
    alpha = rng.uniform(0.75, 1.35)
    beta = rng.uniform(-35, 35) * severity
    arr = np.clip(alpha * arr + beta, 0, 255).astype(np.uint8)
    # New mask from threshold.
    thr = int(np.interp(severity, [0, 1], [150, 205]))
    new_mask = (arr < thr).astype(np.uint8) * 255
    return Image.fromarray(arr), Image.fromarray(new_mask), {"contrast_alpha": alpha, "brightness_beta": beta, "threshold": thr}


def apply_perspective(img: Image.Image, mask: Image.Image, rng: random.Random, severity: float, boxes: List[CharBox]) -> Tuple[Image.Image, Image.Image, List[CharBox], Dict]:
    """
    Apply a mild perspective transform. For speed and simplicity, boxes are transformed
    as enclosing rectangles of their four transformed corners.
    """
    img_arr = np.array(img)
    mask_arr = np.array(mask)
    h, w = img_arr.shape

    max_dx = severity * 0.08 * w
    max_dy = severity * 0.12 * h

    src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    dst = np.float32([
        [rng.uniform(0, max_dx), rng.uniform(0, max_dy)],
        [w - 1 - rng.uniform(0, max_dx), rng.uniform(0, max_dy)],
        [w - 1 - rng.uniform(0, max_dx), h - 1 - rng.uniform(0, max_dy)],
        [rng.uniform(0, max_dx), h - 1 - rng.uniform(0, max_dy)],
    ])

    M = cv2.getPerspectiveTransform(src, dst)
    warped_img = cv2.warpPerspective(img_arr, M, (w, h), borderValue=int(np.percentile(img_arr, 95)))
    warped_mask = cv2.warpPerspective(mask_arr, M, (w, h), borderValue=0)

    new_boxes: List[CharBox] = []
    for b in boxes:
        pts = np.float32([
            [b.x, b.y],
            [b.x + b.w, b.y],
            [b.x + b.w, b.y + b.h],
            [b.x, b.y + b.h],
        ]).reshape(-1, 1, 2)
        t = cv2.perspectiveTransform(pts, M).reshape(-1, 2)
        x0, y0 = np.floor(t.min(axis=0)).astype(int)
        x1, y1 = np.ceil(t.max(axis=0)).astype(int)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        new_boxes.append(CharBox(b.char, x0, y0, max(0, x1 - x0), max(0, y1 - y0), b.index))

    return Image.fromarray(warped_img), Image.fromarray(warped_mask), new_boxes, {"perspective_severity": severity}


def apply_compression(img: Image.Image, mask: Image.Image, rng: random.Random, severity: float) -> Tuple[Image.Image, Image.Image, Dict]:
    """
    JPEG roundtrip compression.
    """
    import io

    quality = int(np.interp(severity, [0, 1], [75, 28]))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    out = Image.open(buf).convert("L")
    return out, mask, {"jpeg_quality": quality}


def apply_morph_touch(img: Image.Image, mask: Image.Image, rng: random.Random, severity: float) -> Tuple[Image.Image, Image.Image, Dict]:
    """
    Morphologically dilate foreground to create touching characters.
    """
    img_arr = np.array(img).copy()
    mask_arr = np.array(mask).copy()
    k = int(np.interp(severity, [0, 1], [2, 5]))
    kernel = np.ones((k, k), dtype=np.uint8)
    dil = cv2.dilate(mask_arr, kernel, iterations=1)

    bg = int(np.percentile(img_arr, 95))
    fg = int(np.percentile(img_arr[mask_arr > 0], 10)) if np.any(mask_arr > 0) else 20
    img_arr[dil > 0] = fg
    # Preserve the plate background elsewhere.
    return Image.fromarray(img_arr), Image.fromarray(dil), {"morph_kernel": k}


def generate_sample(
    sample_idx: int,
    rng: random.Random,
    width: int,
    height: int,
    perturbation: str,
    split: str,
) -> Tuple[str, Image.Image, Image.Image, List[CharBox], Dict]:
    plate = random_plate(rng)

    touching_level = 0.0
    if perturbation in {"touch", "combo"}:
        touching_level = rng.uniform(0.35, 0.90)

    img, mask, boxes, params = draw_base_plate(plate, width, height, rng, touching_level=touching_level)
    params["base"] = dict(params)

    severity = rng.uniform(0.45, 0.95)

    if perturbation == "clean":
        params.update({"perturbation": "clean", "severity": 0.0})

    elif perturbation == "blur":
        img, mask, p = apply_blur(img, mask, rng, severity)
        params.update({"perturbation": "blur", "severity": severity, **p})

    elif perturbation == "glare":
        img, mask, p = apply_glare(img, mask, rng, severity)
        params.update({"perturbation": "glare", "severity": severity, **p})

    elif perturbation == "touch":
        img, mask, p = apply_morph_touch(img, mask, rng, severity)
        params.update({"perturbation": "touch", "severity": severity, **p})

    elif perturbation == "broken":
        img, mask, p = apply_broken_strokes(img, mask, rng, severity)
        params.update({"perturbation": "broken", "severity": severity, **p})

    elif perturbation == "threshold":
        img, mask, p = apply_threshold_shift(img, mask, rng, severity)
        params.update({"perturbation": "threshold", "severity": severity, **p})

    elif perturbation == "perspective":
        img, mask, boxes, p = apply_perspective(img, mask, rng, severity, boxes)
        params.update({"perturbation": "perspective", "severity": severity, **p})

    elif perturbation == "compression":
        img, mask, p = apply_compression(img, mask, rng, severity)
        params.update({"perturbation": "compression", "severity": severity, **p})

    elif perturbation == "combo":
        # Keep it deterministic through explicit sequence and log all subparameters.
        combo_params = {}
        img, mask, p = apply_morph_touch(img, mask, rng, severity * 0.75)
        combo_params.update({f"touch_{k}": v for k, v in p.items()})
        img, mask, boxes, p = apply_perspective(img, mask, rng, severity * 0.70, boxes)
        combo_params.update({f"perspective_{k}": v for k, v in p.items()})
        img, mask, p = apply_blur(img, mask, rng, severity * 0.65)
        combo_params.update({f"blur_{k}": v for k, v in p.items()})
        img, mask, p = apply_glare(img, mask, rng, severity * 0.55)
        combo_params.update({f"glare_{k}": v for k, v in p.items()})
        img, mask, p = apply_compression(img, mask, rng, severity * 0.65)
        combo_params.update({f"compression_{k}": v for k, v in p.items()})
        params.update({"perturbation": "combo", "severity": severity, **combo_params})

    else:
        raise ValueError(f"Unknown perturbation: {perturbation}")

    sample_id = f"{split}_{sample_idx:06d}_{perturbation}_{plate}"
    return plate, img, mask, boxes, params


def create_dataset(args: argparse.Namespace) -> None:
    out = Path(args.out)
    img_dir = out / "images"
    mask_dir = out / "masks"
    img_dir.mkdir(parents=True, exist_ok=True)
    mask_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)

    perturbations = ["clean", "blur", "glare", "touch", "broken", "threshold", "perspective", "compression", "combo"]
    if args.perturb != "all":
        perturbations = [p.strip() for p in args.perturb.split(",") if p.strip()]

    jsonl_path = out / "annotations.jsonl"
    csv_path = out / "manifest.csv"

    records: List[SampleRecord] = []

    for i in range(args.n):
        split = "train" if i < int(args.n * args.train_ratio) else "test"
        perturbation = perturbations[i % len(perturbations)]

        plate, img, mask, boxes, params = generate_sample(
            sample_idx=i,
            rng=rng,
            width=args.width,
            height=args.height,
            perturbation=perturbation,
            split=split,
        )

        sample_id = f"{split}_{i:06d}_{perturbation}_{plate}"
        img_path = img_dir / f"{sample_id}.png"
        mask_path = mask_dir / f"{sample_id}_mask.png"

        img.save(img_path)
        mask.save(mask_path)

        rec = SampleRecord(
            sample_id=sample_id,
            plate=plate,
            split=split,
            perturbation=perturbation,
            image_path=str(img_path.relative_to(out)),
            mask_path=str(mask_path.relative_to(out)),
            width=args.width,
            height=args.height,
            char_boxes=[asdict(b) for b in boxes],
            params=params,
        )
        records.append(rec)

    with jsonl_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(to_jsonable(asdict(rec)), ensure_ascii=False, sort_keys=True) + "\n")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "sample_id",
                "plate",
                "split",
                "perturbation",
                "image_path",
                "mask_path",
                "width",
                "height",
                "n_chars",
            ],
        )
        writer.writeheader()
        for rec in records:
            writer.writerow({
                "sample_id": rec.sample_id,
                "plate": rec.plate,
                "split": rec.split,
                "perturbation": rec.perturbation,
                "image_path": rec.image_path,
                "mask_path": rec.mask_path,
                "width": rec.width,
                "height": rec.height,
                "n_chars": len(rec.char_boxes),
            })

    config = {
        "n": args.n,
        "seed": args.seed,
        "width": args.width,
        "height": args.height,
        "perturbations": perturbations,
        "train_ratio": args.train_ratio,
        "format": "legacy_hu_synthetic_AAA999",
        "outputs": {
            "images": "images/",
            "masks": "masks/",
            "annotations": "annotations.jsonl",
            "manifest": "manifest.csv",
        },
    }
    (out / "dataset_config.json").write_text(json.dumps(to_jsonable(config), indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Generated {len(records)} synthetic plate crops in: {out}")
    print(f"Manifest: {csv_path}")
    print(f"Annotations: {jsonl_path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=str, default="synthetic_plates", help="Output dataset directory")
    p.add_argument("--n", type=int, default=1000, help="Number of generated samples")
    p.add_argument("--seed", type=int, default=27, help="Random seed")
    p.add_argument("--width", type=int, default=240, help="Plate crop width")
    p.add_argument("--height", type=int, default=80, help="Plate crop height")
    p.add_argument(
        "--perturb",
        type=str,
        default="all",
        help="Comma-separated perturbations or 'all'. Options: clean,blur,glare,touch,broken,threshold,perspective,compression,combo",
    )
    p.add_argument("--train-ratio", type=float, default=0.8, help="Train/test split ratio for manifest only")
    return p.parse_args()


if __name__ == "__main__":
    create_dataset(parse_args())
