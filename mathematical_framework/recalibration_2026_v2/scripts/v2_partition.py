#!/usr/bin/env python3
"""Pure, testable asymmetric partition builder for the V2 adapter."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any


def build_asymmetric_partition(
    rows: Sequence[dict[str, Any]],
    dev_ids: set[str],
    reference_clean_n: int,
    block_size: int,
    seed: str,
    *,
    stream_conditions: Sequence[str],
    deterministic_sort: Callable[[Sequence[dict[str, Any]], str], list[dict[str, Any]]],
    proposal_n: int,
    gate_n: int,
    evaluation_n: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    total = int(proposal_n) + int(gate_n) + int(evaluation_n)
    if int(block_size) != total:
        raise ValueError("block_size differs from asymmetric partition total")
    if min(proposal_n, gate_n, evaluation_n) <= 0:
        raise ValueError("all asymmetric partition counts must be positive")

    remain = [row for row in rows if row["id"] not in dev_ids]
    by: dict[str, list[dict[str, Any]]] = {}
    for row in remain:
        by.setdefault(str(row["perturbation"]), []).append(row)
    for condition in by:
        by[condition] = deterministic_sort(by[condition], seed + "|" + condition)
    if "clean" not in by:
        raise ValueError("No clean samples found")

    needed_clean = int(reference_clean_n) + stream_conditions.count("clean") * total
    if len(by["clean"]) < needed_clean:
        raise ValueError(
            f"Not enough clean samples: need {needed_clean}, have {len(by['clean'])}"
        )
    reference_clean = by["clean"][:int(reference_clean_n)]
    positions = {"clean": int(reference_clean_n)}
    blocks = []
    for block_index, condition in enumerate(stream_conditions):
        if condition not in by:
            raise ValueError(f"Missing perturbation class: {condition}")
        start = positions.get(condition, 0)
        end = start + total
        if end > len(by[condition]):
            raise ValueError(
                f"Not enough samples for {condition}: need through {end}, "
                f"have {len(by[condition])}"
            )
        chosen = by[condition][start:end]
        positions[condition] = end
        proposal = chosen[:proposal_n]
        gate = chosen[proposal_n:proposal_n + gate_n]
        evaluation = chosen[proposal_n + gate_n:]
        blocks.append({
            "block_index": block_index,
            "condition": condition,
            "proposal_ids": [row["id"] for row in proposal],
            "gate_ids": [row["id"] for row in gate],
            "evaluation_ids": [row["id"] for row in evaluation],
            "proposal": proposal,
            "gate": gate,
            "evaluation": evaluation,
        })

    public = {
        "seed": seed,
        "dev_excluded_count": len(dev_ids),
        "reference_clean_ids": [row["id"] for row in reference_clean],
        "partition_policy": "v2_asymmetric_15_15_60",
        "partition_counts": {
            "proposal_n": proposal_n,
            "gate_n": gate_n,
            "evaluation_n": evaluation_n,
            "block_total_n": total,
        },
        "blocks": [{
            "block_index": block["block_index"],
            "condition": block["condition"],
            "proposal_ids": block["proposal_ids"],
            "gate_ids": block["gate_ids"],
            "evaluation_ids": block["evaluation_ids"],
        } for block in blocks],
    }
    return reference_clean, blocks, public
