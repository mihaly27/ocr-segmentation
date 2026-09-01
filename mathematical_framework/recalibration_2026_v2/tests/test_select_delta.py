from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "select_delta.py"


class SelectDeltaTests(unittest.TestCase):
    def test_exact_rule_selects_largest_eligible_value(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            specs = [
                {"seed": 1000 + i, "condition": "touch", "role": "informative_target"}
                for i in range(60)
            ]
            protocol = {
                "delta_calibration": {
                    "trajectory_specs": specs,
                    "delta_grid": [0.0, 0.5],
                    "one_sided_confidence": 0.95,
                    "minimum_informative_events": 60,
                    "minimum_nonzero_commit_coverage": 0.20,
                    "harm_upper_bound": 0.05,
                    "selection_rule": "largest_eligible_grid_value",
                    "partition": {
                        "proposal_n": 15,
                        "gate_n": 15,
                        "evaluation_n": 60,
                        "block_total_n": 90,
                    },
                }
            }
            (root / "protocol.yaml").write_text(yaml.safe_dump(protocol), encoding="utf-8")
            w_obj = {
                "coordinates": ["a", "b", "c"],
                "D_diag": [1, 1, 1],
                "W_z_diag": [1, 1, 1],
                "W_theta_diag": [1, 1, 1],
            }
            (root / "w.json").write_text(json.dumps(w_obj), encoding="utf-8")
            def digest(path):
                return hashlib.sha256(path.read_bytes()).hexdigest()

            lock = {
                "status": "v2_inputs_locked_before_generation",
                "protocol": {
                    "path": str(root / "protocol.yaml"),
                    "sha256": digest(root / "protocol.yaml"),
                },
                "locked_files": [
                    {
                        "role": "test_w",
                        "path": str(root / "w.json"),
                        "sha256": digest(root / "w.json"),
                    }
                ],
            }
            (root / "lock.json").write_text(json.dumps(lock), encoding="utf-8")
            harm_paths = []
            for delta in (0.0, 0.5):
                path = root / f"harm_{delta}.csv"
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=[
                        "trajectory_seed", "delta_W", "block_index",
                        "informative", "committed_nonzero", "H",
                    ])
                    writer.writeheader()
                    for i, spec in enumerate(specs):
                        writer.writerow({
                            "trajectory_seed": spec["seed"],
                            "delta_W": delta,
                            "block_index": 1,
                            "informative": 1,
                            "committed_nonzero": int(delta > 0 and i < 12),
                            "H": 0,
                        })
                path.with_suffix(".summary.json").write_text(json.dumps({
                    "evaluation_n_per_block": 60,
                }), encoding="utf-8")
                harm_paths.append(path)

            command = [
                sys.executable, str(SCRIPT),
                "--protocol", str(root / "protocol.yaml"),
                "--input-lock", str(root / "lock.json"),
                "--w-json", str(root / "w.json"),
                "--harm-csv", *(str(path) for path in harm_paths),
                "--output-dir", str(root / "out"),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            result = json.loads((root / "out" / "selected_delta.json").read_text())
            self.assertEqual(result["selected_delta_W"], 0.5)
            self.assertEqual(result["status"], "positive_delta_selected")


if __name__ == "__main__":
    unittest.main()
