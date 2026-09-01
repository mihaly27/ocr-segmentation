#!/usr/bin/env python3
"""Export one reproducible real corpus image for clean/touch/broken/combo.

The script uses an existing frozen V2.1 corpus.  For each condition it chooses
the test-set sample whose recorded severity is closest to the within-condition
median (ties are resolved by sample_id).  It copies the four untouched PNGs,
creates a labelled 2x2 montage, and records paths and SHA-256 hashes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import statistics
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


CONDITIONS = ("clean", "touch", "broken", "combo")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_records(dataset: Path) -> list[dict]:
    annotations = dataset / "annotations.jsonl"
    if annotations.is_file():
        rows = []
        for line in annotations.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            row["severity"] = float(row.get("params", {}).get("severity", 0.0))
            rows.append(row)
        return rows

    manifest = dataset / "manifest.csv"
    with manifest.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row["severity"] = 0.0
    return rows


def resolve_dataset(corpus_root: Path, seed: int) -> Path:
    direct = corpus_root / f"challenge_{seed}"
    if (direct / "manifest.csv").is_file():
        return direct.resolve()
    if (corpus_root / "manifest.csv").is_file():
        return corpus_root.resolve()

    candidates = []
    for manifest in corpus_root.rglob("manifest.csv"):
        dataset = manifest.parent
        records = load_records(dataset)
        present = {str(row.get("perturbation", "")) for row in records}
        if set(CONDITIONS).issubset(present):
            candidates.append(dataset)
    if not candidates:
        raise SystemExit(f"No corpus containing {CONDITIONS} found below {corpus_root}")
    preferred = [p for p in candidates if str(seed) in p.name]
    return sorted(preferred or candidates)[0].resolve()


def choose(rows: list[dict], condition: str) -> dict:
    pool = [r for r in rows if r.get("perturbation") == condition and r.get("split") == "test"]
    if not pool:
        pool = [r for r in rows if r.get("perturbation") == condition]
    if not pool:
        raise SystemExit(f"No samples for condition: {condition}")
    median = statistics.median(float(r["severity"]) for r in pool)
    return min(pool, key=lambda r: (abs(float(r["severity"]) - median), str(r["sample_id"])))


def make_montage(images: list[tuple[str, Path]], output: Path) -> None:
    opened = [(name, Image.open(path).convert("RGB")) for name, path in images]
    panel_w = max(im.width for _, im in opened)
    panel_h = max(im.height for _, im in opened)
    gap, header, margin = 28, 42, 18
    canvas = Image.new("RGB", (2 * panel_w + gap + 2 * margin,
                                2 * (panel_h + header) + gap + 2 * margin), "white")
    draw = ImageDraw.Draw(canvas)
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    font_path = next((p for p in font_candidates if Path(p).is_file()), None)
    font = ImageFont.truetype(font_path, 24) if font_path else ImageFont.load_default()
    for index, (condition, im) in enumerate(opened):
        col, row = index % 2, index // 2
        x = margin + col * (panel_w + gap)
        y = margin + row * (panel_h + header + gap)
        draw.text((x + panel_w / 2, y + header / 2), condition.capitalize(),
                  fill="#1F2A33", font=font, anchor="mm")
        canvas.paste(im, (x + (panel_w - im.width) // 2, y + header))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, dpi=(300, 300))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(Path.home() / "ocr-segmentation"))
    parser.add_argument("--corpus-root", help="Defaults to the frozen V2.1 corpus directory")
    parser.add_argument("--seed", type=int, default=86082801)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    repo = Path(args.repo_root).expanduser().resolve()
    corpus_root = Path(args.corpus_root).expanduser().resolve() if args.corpus_root else (
        repo / "mathematical_framework/recalibration_2026_v2/challenges/"
               "activation_carryover_v1/corpora"
    )
    dataset = resolve_dataset(corpus_root, args.seed)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    records = load_records(dataset)

    exported = []
    montage_inputs = []
    for condition in CONDITIONS:
        row = choose(records, condition)
        source = (dataset / str(row["image_path"])).resolve()
        source.relative_to(dataset)
        if not source.is_file():
            raise SystemExit(f"Missing source image: {source}")
        destination = output_dir / f"real_{condition}.png"
        shutil.copy2(source, destination)
        montage_inputs.append((condition, destination))
        exported.append({
            "condition": condition,
            "sample_id": row["sample_id"],
            "plate": row.get("plate"),
            "split": row.get("split"),
            "severity": float(row["severity"]),
            "source": str(source),
            "source_sha256": sha256(source),
            "export": str(destination),
            "export_sha256": sha256(destination),
        })

    montage = output_dir / "fig_real_corpus_examples.png"
    make_montage(montage_inputs, montage)
    report = {
        "version": "v21_real_corpus_examples_v1",
        "selection_rule": "test-split sample nearest within-condition median severity; sample_id tie-break",
        "dataset": str(dataset),
        "dataset_config_sha256": sha256(dataset / "dataset_config.json"),
        "seed_requested": args.seed,
        "samples": exported,
        "montage": str(montage),
        "montage_sha256": sha256(montage),
    }
    manifest = output_dir / "real_corpus_examples.json"
    manifest.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

