from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from recalib_common import clopper_pearson_upper, state_is_different  # noqa: E402


class CommonTests(unittest.TestCase):
    def test_zero_event_exact_upper(self):
        observed = clopper_pearson_upper(0, 60, 0.95)
        expected = 1.0 - 0.05 ** (1.0 / 60.0)
        self.assertAlmostEqual(observed, expected, places=12)
        self.assertLess(observed, 0.05)

    def test_one_harm_does_not_pass_at_sixty(self):
        self.assertGreater(clopper_pearson_upper(1, 60, 0.95), 0.05)

    def test_state_comparison(self):
        state = "rsplit=1.600000;wprior=2.000000;gblock=0.050000"
        self.assertFalse(state_is_different(state, (1.6, 2.0, 0.05)))
        self.assertTrue(state_is_different(state, (1.2, 2.0, 0.05)))


if __name__ == "__main__":
    unittest.main()
