from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from recalib_common import delta_trajectory_specs, load_yaml  # noqa: E402


class V2ProtocolTests(unittest.TestCase):
    def test_fixed_seed_groups_are_disjoint_and_balanced(self):
        protocol = load_yaml(ROOT / "protocol.yaml")
        specs = delta_trajectory_specs(protocol)
        self.assertEqual(len(specs), 120)
        self.assertEqual(len({item["seed"] for item in specs}), 120)
        counts = {
            condition: sum(item["condition"] == condition for item in specs)
            for condition in ("touch", "broken", "combo")
        }
        self.assertEqual(counts, {"touch": 40, "broken": 40, "combo": 40})

    def test_v2_partition_and_accepted_margins_are_frozen(self):
        protocol = load_yaml(ROOT / "protocol.yaml")
        partition = protocol["delta_calibration"]["partition"]
        self.assertEqual(
            (
                partition["proposal_n"],
                partition["gate_n"],
                partition["evaluation_n"],
                partition["block_total_n"],
            ),
            (15, 15, 60, 90),
        )
        margins = protocol["noninferiority_margins"]
        self.assertEqual(margins["full_plate_accuracy_drop"], 0.05)
        self.assertEqual(margins["character_accuracy_drop"], 0.02)
        self.assertEqual(margins["mean_dseg_increase"], 0.25)

    def test_generator_counts_cover_every_frozen_partition(self):
        protocol = load_yaml(ROOT / "protocol.yaml")
        delta = protocol["delta_calibration"]
        per_class = int(delta["generator_n_each"]) // 2
        clean_needed = int(delta["reference_clean_n"]) + 2 * int(
            delta["partition"]["block_total_n"]
        )
        self.assertGreaterEqual(per_class, clean_needed)
        self.assertGreaterEqual(per_class, delta["partition"]["block_total_n"])

        confirmation = protocol["confirmation"]
        perturbation_class_count = 9
        per_class = int(confirmation["generator_n_each"]) // perturbation_class_count
        clean_needed = int(confirmation["reference_clean_n"]) + 9 * int(
            confirmation["partition"]["block_total_n"]
        )
        self.assertGreaterEqual(per_class, clean_needed)


if __name__ == "__main__":
    unittest.main()
