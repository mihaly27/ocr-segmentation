from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aggregate_w.py"


class AggregateWTests(unittest.TestCase):
    def test_coordinatewise_max_median_normalization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            protocol = {
                "parameter_space": {
                    "coordinates": ["a", "b", "c"],
                    "normalization_D_diag": [1.0, 2.0, 4.0],
                    "active_set_policy": "fixture",
                },
                "w_calibration": {
                    "regularization_lambda": 0.1,
                    "sample_n": 2,
                    "aggregation": "fixture-max",
                },
            }
            local_s = {"a": 1.0, "b": 0.0, "c": 2.0}
            switch_s = {"a": 0.5, "b": 3.0, "c": 1.0}

            def summary(values):
                return {
                    "finite_difference": {
                        "coordinates": {
                            key: {"selected_response_sensitivity": value}
                            for key, value in values.items()
                        }
                    }
                }

            (root / "protocol.yaml").write_text(yaml.safe_dump(protocol), encoding="utf-8")
            (root / "local.json").write_text(json.dumps(summary(local_s)), encoding="utf-8")
            (root / "switch.json").write_text(json.dumps(summary(switch_s)), encoding="utf-8")
            selected = [{"id": "x"}, {"id": "y"}]
            (root / "local_selected.json").write_text(json.dumps(selected), encoding="utf-8")
            (root / "switch_selected.json").write_text(json.dumps(selected), encoding="utf-8")
            output = root / "w.json"

            subprocess.run([
                sys.executable, str(SCRIPT),
                "--protocol", str(root / "protocol.yaml"),
                "--local-summary", str(root / "local.json"),
                "--switch-summary", str(root / "switch.json"),
                "--local-selected", str(root / "local_selected.json"),
                "--switch-selected", str(root / "switch_selected.json"),
                "--output", str(output),
            ], check=True, capture_output=True, text=True)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["W_z_diag"], [0.6, 1.6, 1.1])
            self.assertEqual(result["W_theta_diag"], [0.6, 0.4, 0.06875])


if __name__ == "__main__":
    unittest.main()

