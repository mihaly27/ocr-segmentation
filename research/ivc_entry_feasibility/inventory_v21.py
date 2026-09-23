#!/usr/bin/env python3
"""Read-only inventory of naturally reached V2.1 transition-entry states.

This is a feasibility check, not a test of a new entry controller. In particular,
different trajectory seeds have different target images; the script does not
interpret across-seed performance contrasts as state effects.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"seed", "source", "target", "controller", "state", "state_differs_from_reference"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing {sorted(missing)} in {path}")
        return list(reader)


def inventory(root: Path) -> dict:
    if not root.is_dir():
        raise ValueError(f"V2.1 challenge output directory is missing: {root}")
    trajectory_dirs = sorted(root.glob("trajectory_*"))
    if not trajectory_dirs:
        raise ValueError(f"No trajectory_* directories found in {root}")

    records = []
    source_states: dict[str, set[str]] = defaultdict(set)
    pair_states: dict[tuple[str, str], set[str]] = defaultdict(set)
    pair_blocks: dict[tuple[str, str], set[str]] = defaultdict(set)
    target_block_states: dict[str, set[str]] = defaultdict(set)
    target_signatures: dict[str, str] = {}
    input_sha256: dict[str, str] = {}
    seeds: set[int] = set()

    for directory in trajectory_dirs:
        if not directory.is_dir():
            continue
        try:
            seed = int(directory.name.removeprefix("trajectory_"))
        except ValueError as exc:
            raise ValueError(f"Unexpected trajectory directory name: {directory}") from exc
        if seed in seeds:
            raise ValueError(f"Duplicate trajectory seed {seed}")
        seeds.add(seed)
        summary_path = directory / "summary.json"
        carry_path = directory / "carryover_events.csv"
        partition_path = directory / "partition_map.json"
        summary = read_json(summary_path)
        partition = read_json(partition_path)
        if not summary.get("ok") or int(summary.get("seed", -1)) != seed:
            raise ValueError(f"Incomplete or mismatched trajectory summary: {summary_path}")
        rows = [r for r in read_csv(carry_path) if r["controller"] == "B3"]
        if len(rows) != 2:
            raise ValueError(f"Expected two B3 carryover rows for seed {seed}; found {len(rows)}")

        blocks = partition.get("blocks")
        if not isinstance(blocks, list):
            raise ValueError(f"Missing blocks in {partition_path}")
        entering = []
        previous_nonclean = None
        for block in blocks:
            condition = str(block["condition"])
            if condition != "clean":
                if previous_nonclean is not None:
                    entering.append((previous_nonclean, condition, block))
                previous_nonclean = condition
        if len(entering) != 2:
            raise ValueError(f"Expected two directed non-clean entries for seed {seed}")

        for row, (source, target, block) in zip(rows, entering):
            if int(row["seed"]) != seed or row["source"] != source or row["target"] != target:
                raise ValueError(f"Carryover order disagrees with partition for seed {seed}")
            state = row["state"].strip()
            ids = block.get("evaluation_ids")
            if not state or not isinstance(ids, list) or len(ids) != 60:
                raise ValueError(f"Missing state or 60 evaluation IDs for seed {seed}, target {target}")
            block_hash = hashlib.sha256(
                json.dumps(ids, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            signature = json.dumps(ids, separators=(",", ":"), ensure_ascii=False)
            if block_hash in target_signatures and target_signatures[block_hash] != signature:
                raise ValueError("Target-block fingerprint collision")
            target_signatures[block_hash] = signature
            pair = (source, target)
            source_states[source].add(state)
            pair_states[pair].add(state)
            pair_blocks[pair].add(block_hash)
            target_block_states[block_hash].add(state)
            reference_flag = row["state_differs_from_reference"].strip().lower()
            if reference_flag not in {"true", "false"}:
                raise ValueError(f"Invalid state_differs_from_reference for seed {seed}")
            records.append({
                "seed": seed, "source": source, "target": target,
                "inherited_state": state,
                "differs_from_reference": reference_flag == "true",
                "target_eval_block_sha256": block_hash,
            })
        for path in (summary_path, carry_path, partition_path):
            input_sha256[str(path.relative_to(root))] = sha256_file(path)

    audit_path = root.parent / "challenge_audit.json"
    audit = read_json(audit_path) if audit_path.is_file() else None
    if audit is not None and not audit.get("technical_ok"):
        raise ValueError(f"V2.1 challenge audit is not technically complete: {audit_path}")
    if audit is not None and len(seeds) != int(audit.get("completed_trajectories", -1)):
        raise ValueError("Trajectory count differs from the V2.1 challenge audit")
    same_block_comparisons = sum(len(states) > 1 for states in target_block_states.values())
    return {
        "purpose": "Exploratory inventory only; no causal or deployment claim",
        "challenge_root": str(root.resolve()),
        "audit": {"path": str(audit_path), "technical_ok": audit.get("technical_ok")} if audit else None,
        "trajectory_count": len(seeds),
        "b3_directed_entry_count": len(records),
        "unique_target_eval_blocks": len(target_block_states),
        "target_blocks_already_crossed_with_different_states": same_block_comparisons,
        "distinct_inherited_states_by_source": {key: len(states) for key, states in sorted(source_states.items())},
        "by_ordered_pair": [
            {"source": source, "target": target,
             "distinct_inherited_states": len(states), "distinct_target_blocks": len(pair_blocks[(source, target)]),
             "entry_count": sum(r["source"] == source and r["target"] == target for r in records)}
            for (source, target), states in sorted(pair_states.items())
        ],
        "has_pair_with_multiple_natural_states": any(len(s) > 1 for s in pair_states.values()),
        "input_sha256": dict(sorted(input_sha256.items())),
        "entries": records,
        "next_step": "Replay naturally reached states on the SAME held-out target blocks only if state diversity is adequate; no gate or GPU run is authorized by this inventory.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--challenge-root", type=Path, required=True,
                        help="Existing V2.1 outputs/challenge directory containing trajectory_* folders")
    args = parser.parse_args()
    print(json.dumps(inventory(args.challenge_root), indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
