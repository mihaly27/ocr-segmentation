#!/usr/bin/env python3
"""Small dependency-light helpers shared by the recalibration scripts."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml


def delta_trajectory_specs(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand and validate the frozen V2 trajectory groups."""
    config = protocol["delta_calibration"]
    if "trajectory_specs" in config:
        specs = [
            {
                "seed": int(item["seed"]),
                "condition": str(item["condition"]),
                "role": str(item["role"]),
            }
            for item in config["trajectory_specs"]
        ]
    else:
        specs = []
        for group in config["trajectory_groups"]:
            first = int(group["first_seed"])
            count = int(group["count"])
            if count <= 0:
                raise ValueError("trajectory group count must be positive")
            specs.extend({
                "seed": first + offset,
                "condition": str(group["condition"]),
                "role": str(group["role"]),
            } for offset in range(count))
    seeds = [item["seed"] for item in specs]
    if len(seeds) != len(set(seeds)):
        raise ValueError("duplicate delta-calibration trajectory seed")
    expected = config.get("expected_trajectory_count")
    if expected is not None and len(specs) != int(expected):
        raise ValueError(
            f"expanded {len(specs)} trajectories, expected {int(expected)}"
        )
    return specs


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_input_lock(lock_path: Path, protocol_path: Path) -> dict[str, Any]:
    lock = load_json(lock_path)
    if lock.get("status") != "v2_inputs_locked_before_generation":
        raise ValueError("invalid V2 input-lock status")
    protocol_record = lock.get("protocol", {})
    if sha256_file(protocol_path) != str(protocol_record.get("sha256", "")):
        raise ValueError("V2 protocol differs from the locked protocol")
    failures = []
    for record in lock.get("locked_files", []):
        path = Path(str(record["path"])).resolve()
        if not path.is_file():
            failures.append(f"missing: {path}")
        elif sha256_file(path) != str(record["sha256"]):
            failures.append(f"hash mismatch: {path}")
    if failures:
        raise ValueError("V2 input lock failed: " + "; ".join(failures))
    return lock


def load_yaml(path: Path) -> dict[str, Any]:
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"Expected a YAML mapping: {path}")
    return obj


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_bytes(payload)
    temporary.replace(path)


def write_json(path: Path, obj: Any, *, pretty: bool = True) -> None:
    if pretty:
        payload = (
            json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")
    else:
        payload = canonical_json_bytes(obj) + b"\n"
    atomic_write_bytes(path, payload)


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        atomic_write_bytes(path, b"")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(str(key))
                seen.add(str(key))
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def parse_state(raw: str | Sequence[float]) -> tuple[float, ...]:
    if isinstance(raw, str):
        if "=" in raw:
            values = [float(part.split("=", 1)[1]) for part in raw.split(";") if part]
        else:
            values = [float(x) for x in raw.split("|")]
    else:
        values = [float(x) for x in raw]
    return tuple(values)


def state_is_different(a: str | Sequence[float], b: str | Sequence[float],
                       tolerance: float = 1e-9) -> bool:
    aa, bb = parse_state(a), parse_state(b)
    return len(aa) != len(bb) or any(abs(x - y) > tolerance for x, y in zip(aa, bb))


def binomial_cdf(k: int, n: int, p: float) -> float:
    if n < 0 or not 0 <= k <= n:
        raise ValueError("Require 0 <= k <= n")
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k == n else 0.0
    return float(sum(
        math.comb(n, i) * (p ** i) * ((1.0 - p) ** (n - i))
        for i in range(k + 1)
    ))


def clopper_pearson_upper(k: int, n: int, confidence: float = 0.95) -> float:
    """One-sided exact binomial upper confidence limit without SciPy."""
    if n <= 0 or not 0 <= k <= n:
        raise ValueError("Require n > 0 and 0 <= k <= n")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between zero and one")
    if k == n:
        return 1.0
    alpha = 1.0 - confidence
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if binomial_cdf(k, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def iter_files(root: Path, excluded_names: Iterable[str] = ()) -> list[Path]:
    excluded = set(excluded_names)
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.name not in excluded
    )
