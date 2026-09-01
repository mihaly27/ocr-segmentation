#!/usr/bin/env python3
"""Create a stable SHA-256 manifest for a completed calibration stage."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from recalib_common import sha256_file, write_json


EXCLUDED_PARTS = {
    "cache", "cache_shared", "cache_shared_global", "_tmp_runs", "__pycache__"
}
EXCLUDED_NAMES = {"MANIFEST.sha256", "freeze_summary.json"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--include", nargs="*", default=["."])
    args = parser.parse_args()

    root = Path(args.root).resolve()
    files = set()
    for raw in args.include:
        target = (root / raw).resolve()
        if root not in (target, *target.parents):
            raise SystemExit(f"Include escapes frozen root: {raw}")
        if target.is_file():
            files.add(target)
        elif target.is_dir():
            for path in target.rglob("*"):
                if not path.is_file() or path.name in EXCLUDED_NAMES:
                    continue
                relative = path.relative_to(root)
                if any(part in EXCLUDED_PARTS for part in relative.parts):
                    continue
                files.add(path)
        else:
            raise SystemExit(f"Missing include target: {target}")

    lines = []
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        lines.append(f"{sha256_file(path)}  {relative}")
    manifest = root / "MANIFEST.sha256"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = {
        "root": str(root),
        "file_count": len(lines),
        "manifest": str(manifest),
        "manifest_sha256": sha256_file(manifest),
        "excluded_directory_names": sorted(EXCLUDED_PARTS),
    }
    write_json(root / "freeze_summary.json", report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
