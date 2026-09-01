from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compose_manifest.py"


class ComposeManifestTests(unittest.TestCase):
    def test_prefixes_ids_preserves_boxes_and_excludes_plate_overlap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            phase_root = root / "phase"
            trajectory_root = root / "trajectory"
            phase_root.mkdir()
            trajectory_root.mkdir()
            (phase_root / "a.png").write_bytes(b"fixture")
            (phase_root / "b.png").write_bytes(b"fixture")
            (trajectory_root / "c.png").write_bytes(b"fixture")
            (trajectory_root / "d.png").write_bytes(b"fixture")

            phase_rows = [
                {"sample_id": "a", "plate": "ABC123", "perturbation": "clean",
                 "image_path": "a.png", "char_boxes": [{"x": 1, "y": 2, "w": 3, "h": 4}]},
                {"sample_id": "b", "plate": "DEF456", "perturbation": "touch",
                 "image_path": "b.png", "char_boxes": []},
            ]
            trajectory_rows = [
                {"sample_id": "c", "plate": "ABC123", "perturbation": "clean",
                 "image_path": "c.png", "char_boxes": []},
                {"sample_id": "d", "plate": "GHI789", "perturbation": "touch",
                 "image_path": "d.png", "char_boxes": []},
            ]
            phase_manifest = phase_root / "annotations.jsonl"
            trajectory_manifest = trajectory_root / "annotations.jsonl"
            phase_manifest.write_text(
                "".join(json.dumps(row) + "\n" for row in phase_rows), encoding="utf-8"
            )
            trajectory_manifest.write_text(
                "".join(json.dumps(row) + "\n" for row in trajectory_rows), encoding="utf-8"
            )
            selected = root / "selected.json"
            selected.write_text(json.dumps([{"id": "a"}]), encoding="utf-8")
            output_manifest = root / "combined.jsonl"
            output_selected = root / "dev.json"

            subprocess.run([
                sys.executable, str(SCRIPT),
                "--phase1-selected", str(selected),
                "--phase1-manifest", str(phase_manifest),
                "--phase1-root", str(phase_root),
                "--trajectory-manifest", str(trajectory_manifest),
                "--trajectory-root", str(trajectory_root),
                "--trajectory-label", "fixture",
                "--output-manifest", str(output_manifest),
                "--output-dev-selected", str(output_selected),
            ], check=True, capture_output=True, text=True)
            combined = [json.loads(line) for line in output_manifest.read_text().splitlines()]
            self.assertEqual([row["sample_id"] for row in combined], ["wdev:a", "traj-fixture:d"])
            self.assertEqual(json.loads(combined[0]["char_boxes"])[0]["x"], 1)
            report = json.loads(output_manifest.with_suffix(".composition.json").read_text())
            self.assertEqual(report["plate_identity_overlap_count"], 1)


if __name__ == "__main__":
    unittest.main()
