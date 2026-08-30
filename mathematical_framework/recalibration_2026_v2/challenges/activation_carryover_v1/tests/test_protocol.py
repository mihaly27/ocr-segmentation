#!/usr/bin/env python3
from __future__ import annotations
import sys, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"scripts"))
from challenge_common import load_yaml, sequence_by_seed, stream_from_order

class ProtocolTests(unittest.TestCase):
    def setUp(self): self.p=load_yaml(ROOT/"protocol.yaml")
    def test_design(self):
        seq=sequence_by_seed(self.p); self.assertEqual(len(seq),18)
        self.assertEqual(set(map(tuple,seq.values())),set(__import__('itertools').permutations(("touch","broken","combo"))))
        counts={pair:0 for pair in self.p["challenge_layers"]["carryover"]["ordered_pairs"]}
        for order in seq.values():
            for a,b in zip(order,order[1:]): counts[f"{a}_to_{b}"]+=1
        self.assertEqual(set(counts.values()),{6})
    def test_stream(self):
        self.assertEqual(stream_from_order(["touch","broken","combo"]),["clean","touch","clean","broken","clean","combo","clean"])
    def test_partition_counts(self):
        x=self.p["design"]["partition"]; self.assertEqual(x["proposal_n"]+x["gate_n"]+x["evaluation_n"],x["block_total_n"])

if __name__=="__main__": unittest.main()
