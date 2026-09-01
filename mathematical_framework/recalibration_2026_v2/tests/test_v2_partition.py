from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from v2_partition import build_asymmetric_partition  # noqa: E402


def stable_sort(rows, seed):
    del seed
    return sorted(rows, key=lambda row: row["id"])


class V2PartitionTests(unittest.TestCase):
    def setUp(self):
        self.rows = []
        for condition, count in (("clean", 300), ("touch", 100)):
            for index in range(count):
                self.rows.append({
                    "id": f"{condition}-{index:03d}",
                    "perturbation": condition,
                })

    def test_asymmetric_counts_and_disjoint_ids(self):
        reference, blocks, public = build_asymmetric_partition(
            self.rows,
            {"clean-299"},
            100,
            90,
            "TEST",
            stream_conditions=("clean", "touch", "clean"),
            deterministic_sort=stable_sort,
            proposal_n=15,
            gate_n=15,
            evaluation_n=60,
        )
        self.assertEqual(len(reference), 100)
        self.assertEqual(len(blocks), 3)
        all_ids = {row["id"] for row in reference}
        for block in blocks:
            self.assertEqual(len(block["proposal"]), 15)
            self.assertEqual(len(block["gate"]), 15)
            self.assertEqual(len(block["evaluation"]), 60)
            current = {
                row["id"]
                for key in ("proposal", "gate", "evaluation")
                for row in block[key]
            }
            self.assertEqual(len(current), 90)
            self.assertTrue(all_ids.isdisjoint(current))
            all_ids.update(current)
        self.assertEqual(public["partition_counts"]["evaluation_n"], 60)

    def test_rejects_legacy_equal_thirds_total(self):
        with self.assertRaisesRegex(ValueError, "block_size"):
            build_asymmetric_partition(
                self.rows,
                set(),
                100,
                45,
                "TEST",
                stream_conditions=("clean", "touch", "clean"),
                deterministic_sort=stable_sort,
                proposal_n=15,
                gate_n=15,
                evaluation_n=60,
            )


if __name__ == "__main__":
    unittest.main()
