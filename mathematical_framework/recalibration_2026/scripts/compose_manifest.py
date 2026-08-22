#!/usr/bin/env python3
"""Compose Phase-1 dev rows and one trajectory into a collision-safe manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from recalib_common import load_json, sha256_file, write_json


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def image_path(row: dict[str, Any], root: Path) -> Path:
    raw = row.get("image_path", row.get("image"))
    if raw is None:
        raise ValueError("Manifest row has no image path")
    path = Path(str(raw))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def row_id(row: dict[str, Any]) -> str:
    for key in ("sample_id", "id", "uid", "name"):
        if row.get(key) not in (None, ""):
            return str(row[key])
    raise ValueError("Manifest row has no sample identifier")


def normalized(row: dict[str, Any], root: Path, prefix: str) -> dict[str, Any]:
    path = image_path(row, root)
    if not path.exists():
        raise FileNotFoundError(path)
    plate = row.get("plate", row.get("gt", row.get("text")))
    perturbation = row.get("perturbation", row.get("condition"))
    if plate is None or perturbation is None:
        raise ValueError("Manifest row lacks plate or perturbation")
    return {
        "sample_id": f"{prefix}:{row_id(row)}",
        "plate": str(plate),
        "perturbation": str(perturbation).lower(),
        "image_path": str(path),
        "char_boxes": row.get("char_boxes", row.get("boxes", [])),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase1-selected", required=True)
    parser.add_argument("--phase1-manifest", required=True)
    parser.add_argument("--phase1-root", required=True)
    parser.add_argument("--trajectory-manifest", required=True)
    parser.add_argument("--trajectory-root", required=True)
    parser.add_argument("--trajectory-label", required=True)
    parser.add_argument("--output-manifest", required=True)
    parser.add_argument("--output-dev-selected", required=True)
    args = parser.parse_args()

    selected_path = Path(args.phase1_selected).resolve()
    phase1_manifest_path = Path(args.phase1_manifest).resolve()
    trajectory_manifest_path = Path(args.trajectory_manifest).resolve()
    phase1_root = Path(args.phase1_root).resolve()
    trajectory_root = Path(args.trajectory_root).resolve()

    selected = load_json(selected_path)
    selected_ids = [str(row["id"]) for row in selected]
    if len(selected_ids) != len(set(selected_ids)):
        raise SystemExit("Duplicate IDs in Phase-1 selected_samples.json")

    phase_rows = load_jsonl(phase1_manifest_path)
    phase_by_id = {row_id(row): row for row in phase_rows}
    missing = [sid for sid in selected_ids if sid not in phase_by_id]
    if missing:
        raise SystemExit(f"Selected Phase-1 IDs missing from annotation manifest: {missing[:5]}")

    dev_rows = [normalized(phase_by_id[sid], phase1_root, "wdev") for sid in selected_ids]
    trajectory_rows_all = [
        normalized(row, trajectory_root, f"traj-{args.trajectory_label}")
        for row in load_jsonl(trajectory_manifest_path)
    ]

    dev_plates = {row["plate"] for row in dev_rows}
    trajectory_plates = {row["plate"] for row in trajectory_rows_all}
    overlap = sorted(dev_plates & trajectory_plates)
    overlap_set = set(overlap)
    trajectory_rows = [
        row for row in trajectory_rows_all if row["plate"] not in overlap_set
    ]

    output_manifest = Path(args.output_manifest).resolve()
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    with output_manifest.open("w", encoding="utf-8") as handle:
        for row in dev_rows + trajectory_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    output_selected = Path(args.output_dev_selected).resolve()
    write_json(output_selected, [{"id": row["sample_id"]} for row in dev_rows])
    report = {
        "phase1_selected_count": len(dev_rows),
        "trajectory_count_before_identity_filter": len(trajectory_rows_all),
        "trajectory_count": len(trajectory_rows),
        "plate_identity_overlap_count": len(overlap),
        "excluded_plate_identities": overlap,
        "output_manifest": str(output_manifest),
        "output_manifest_sha256": sha256_file(output_manifest),
        "output_dev_selected": str(output_selected),
        "output_dev_selected_sha256": sha256_file(output_selected),
    }
    write_json(output_manifest.with_suffix(".composition.json"), report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
