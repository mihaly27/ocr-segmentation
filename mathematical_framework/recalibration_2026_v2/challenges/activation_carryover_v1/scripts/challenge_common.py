#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(str(key))
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def sequence_by_seed(protocol: Mapping[str, Any]) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    for group in protocol["design"]["sequences"]:
        first = int(group["first_seed"])
        for offset in range(int(group["count"])):
            seed = first + offset
            if seed in result:
                raise ValueError(f"Duplicate seed {seed}")
            result[seed] = [str(x) for x in group["order"]]
    expected = [int(x) for x in protocol["design"]["trajectory_seeds"]]
    if sorted(result) != sorted(expected):
        raise ValueError("Expanded challenge seeds differ from trajectory_seeds")
    return result


def stream_from_order(order: Sequence[str]) -> list[str]:
    stream = ["clean"]
    for condition in order:
        stream.extend([str(condition), "clean"])
    return stream


def verify_package_manifest(path: Path) -> None:
    failures: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split(None, 1)
        target = (path.parent / relative.strip()).resolve()
        if not target.is_file():
            failures.append(f"missing: {target}")
        elif sha256_file(target) != digest:
            failures.append(f"hash mismatch: {target}")
    if failures:
        raise ValueError("Challenge package manifest failed: " + "; ".join(failures))


def verify_lock(lock_path: Path, protocol_path: Path) -> dict[str, Any]:
    lock = load_json(lock_path)
    if lock.get("status") != "v21_inputs_locked_before_generation":
        raise ValueError("Invalid V2.1 input lock status")
    if lock.get("protocol", {}).get("sha256") != sha256_file(protocol_path):
        raise ValueError("V2.1 protocol differs from input lock")
    failures = []
    for row in lock.get("locked_files", []):
        path = Path(str(row["path"])).resolve()
        if not path.is_file():
            failures.append(f"missing: {path}")
        elif sha256_file(path) != str(row["sha256"]):
            failures.append(f"hash mismatch: {path}")
    if failures:
        raise ValueError("V2.1 input lock failed: " + "; ".join(failures))
    package_rows = [row for row in lock.get("locked_files", []) if row.get("role") == "challenge_package_manifest"]
    if len(package_rows) != 1:
        raise ValueError("Input lock must contain exactly one challenge package manifest")
    verify_package_manifest(Path(str(package_rows[0]["path"])).resolve())
    return lock


def state_different(a: Sequence[float], b: Sequence[float], tol: float = 1e-9) -> bool:
    return len(a) != len(b) or any(abs(float(x) - float(y)) > tol for x, y in zip(a, b))
