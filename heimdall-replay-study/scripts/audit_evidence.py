#!/usr/bin/env python3
"""Recompute descriptive file diagnostics; this does not measure accuracy.

Python standard library only. FFprobe must be on PATH for video metadata.
Usage: python3 scripts/audit_evidence.py --legacy-csv OLD/test.csv \
    --event-csv NEW/test.csv --video NEW/capture_RUNID.mp4 --output audit.json
"""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import subprocess


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    if not rows:
        raise ValueError(f"Empty CSV: {path}")
    return rows, reader.fieldnames


def file_info(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return {"name": path.name, "size_bytes": path.stat().st_size,
            "sha256": sha.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-csv", required=True, type=Path)
    parser.add_argument("--event-csv", required=True, type=Path)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    old, old_fields = read_csv(args.legacy_csv)
    new, new_fields = read_csv(args.event_csv)
    frames = {int(row["frame_nmr"]) for row in old}
    strings = collections.defaultdict(set)
    for row in old:
        strings[row["car_id"]].add(row["license_number"])
    pairs = collections.Counter((r["frame_nmr"], r["car_id"]) for r in old)
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate,nb_frames,duration",
        "-of", "json", str(args.video)], text=True))["streams"][0]
    n_frames = int(probe["nb_frames"])
    indices = [int(r["plate_bbox_frame_number"]) for r in new
               if r["plate_bbox_frame_number"]]
    audit = {
        "scope": "Descriptive file audit; no independent ground truth or accuracy estimate",
        "legacy_observations": {
            **file_info(args.legacy_csv), "columns": len(old_fields), "rows": len(old),
            "distinct_frames": len(frames), "min_frame": min(frames), "max_frame": max(frames),
            "distinct_ids": len(strings),
            "ids_with_multiple_strings": sum(len(v) > 1 for v in strings.values()),
            "frame_id_pairs_with_two_rows": sum(n == 2 for n in pairs.values())},
        "lifetime_records": {
            **file_info(args.event_csv), "columns": len(new_fields), "rows": len(new),
            "distinct_car_ids": len({r["car_id"] for r in new}),
            "run_ids": sorted({r["run_id"] for r in new}),
            "status_counts": dict(collections.Counter(r["plate_status"] for r in new)),
            "termination_counts": dict(collections.Counter(r["termination_reason"] for r in new)),
            "rows_with_plate_text": sum(bool(r["plate_text"]) for r in new),
            "representative_indices_present": len(indices),
            "representative_indices_in_range": all(0 <= i < n_frames for i in indices),
            "video_name_matches_all_run_ids": all(args.video.stem == "capture_" + r["run_id"] for r in new)},
        "video": {**file_info(args.video), **probe}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved descriptive audit: {args.output}")


if __name__ == "__main__":
    main()
