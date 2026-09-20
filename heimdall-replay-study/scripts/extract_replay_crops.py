#!/usr/bin/env python3
"""Extract the three diagnostic crops from original replay ZIPs.

Requires FFmpeg and Pillow; not needed to compile the Overleaf project.
No sharpening, reconstruction, or generative enhancement is applied.
"""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run18", type=Path, required=True)
    parser.add_argument("--run19", type=Path, required=True)
    parser.add_argument("--figures", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    args.figures.mkdir(parents=True, exist_ok=True)
    specs = [(18, 79, "2", "NWL-335", "replay_plate_crop.png"),
             (18, 745, "36", "NTE-446", "replay_nonplate_crop.png"),
             (19, 19, "1", "KP-4", "replay_format_crop.png")]
    manifest = []
    with TemporaryDirectory() as tmp:
        cache = {}
        for run, frame, car, raw_text, filename in specs:
            if run not in cache:
                with ZipFile(getattr(args, f"run{run}")) as archive:
                    data = archive.read("video/source.mp4")
                    video = Path(tmp) / f"run{run}.mp4"
                    video.write_bytes(data)
                    rows = list(csv.DictReader(io.StringIO(archive.read("results/observations.csv").decode())))
                    cache[run] = video, rows, hashlib.sha256(data).hexdigest()
            video, rows, source_hash = cache[run]
            matched = [r for r in rows if int(r["frame_id"]) == frame
                       and r["car_id"] == car and r["raw_text"] == raw_text]
            if len(matched) != 1:
                raise ValueError("Expected one observation for the declared frame and track")
            row = matched[0]
            full = Path(tmp) / f"frame{run}_{frame}.png"
            subprocess.run(["ffmpeg", "-v", "error", "-threads", "2", "-i", str(video),
                            "-vf", f"select=eq(n\\,{frame})", "-vsync", "0", "-frames:v", "1",
                            "-y", str(full)], check=True)
            with Image.open(full) as im:
                bbox = [float(row[k]) for k in ("plate_x1", "plate_y1", "plate_x2", "plate_y2")]
                crop = [max(0, math.floor(bbox[0]) - 8), max(0, math.floor(bbox[1]) - 8),
                        min(im.width, math.ceil(bbox[2]) + 8), min(im.height, math.ceil(bbox[3]) + 8)]
                path = args.figures / filename
                im.crop(crop).save(path)
            manifest.append({"figure": filename, "source_run": run, "frame_index_zero_based": frame,
                             "car_id": car, "logged_bbox_xyxy": bbox, "crop_xyxy": crop,
                             "margin_pixels": 8, "raw_text": row["raw_text"],
                             "ocr_confidence": float(row["ocr_confidence"]),
                             "source_video_sha256": source_hash,
                             "figure_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                             "processing": "FFmpeg decode; pixel crop with 8-pixel margin; no enhancement"})
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Saved {len(manifest)} source-frame crops and their manifest")


if __name__ == "__main__":
    main()
