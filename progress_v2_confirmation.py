#!/usr/bin/env python3
"""Report progress and a rough ETA for the V2 confirmation run on Node01.

The script is read-only.  By default it expects the repository at
~/ocr-segmentation and reads the frozen confirmation plan, PID file, latest
nohup log, and per-trajectory output directories.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SEEDS = [86082721, 86082722, 86082723, 86082724, 86082725]
TOTAL_BLOCKS = 17
SEED_RE = re.compile(r"--trajectory-seed(?:=|\s+)(\d+)")
BLOCK_RE = re.compile(r"=== block\s+(\d+)\s+condition=([^\s=]+)\s+===")
CONFIG_RE = re.compile(r"config\s+([^:]+):\s+completed\s+(\d+)/(\d+)\s+new runs")


def duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "unknown"
    seconds_i = int(round(seconds))
    days, rem = divmod(seconds_i, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def utc_stamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def read_pid(path: Path) -> int | None:
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def process_info(pid: int | None) -> tuple[bool, float | None, str]:
    if pid is None:
        return False, None, "PID file missing or invalid"
    proc = Path("/proc") / str(pid)
    try:
        cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", errors="replace"
        ).strip()
        stat_text = (proc / "stat").read_text(encoding="utf-8")
        uptime = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        right_paren = stat_text.rfind(")")
        fields_after_comm = stat_text[right_paren + 2 :].split()
        start_ticks = int(fields_after_comm[19])
        ticks_per_second = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        elapsed = max(0.0, uptime - start_ticks / ticks_per_second)
    except (OSError, ValueError, IndexError):
        return False, None, f"PID {pid} is not running"
    if "run_confirmation.py" not in cmdline:
        return False, None, f"PID {pid} belongs to another process: {cmdline[:120]}"
    return True, elapsed, cmdline


def latest_log(log_dir: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_file() else None
    logs = list(log_dir.glob("run_v2_confirmation_*.log"))
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def parse_log(path: Path | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "seed": None,
        "block_index": None,
        "condition": None,
        "config_progress": None,
        "final_summary_seen": False,
        "mtime": None,
        "size": 0,
        "tail": [],
    }
    if path is None:
        return result
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        stat = path.stat()
    except OSError:
        return result
    result["mtime"] = stat.st_mtime
    result["size"] = stat.st_size
    result["tail"] = [line for line in text.splitlines() if line.strip()][-10:]
    seed_matches = list(SEED_RE.finditer(text))
    if not seed_matches:
        return result
    last_seed = seed_matches[-1]
    result["seed"] = int(last_seed.group(1))
    segment = text[last_seed.end() :]
    blocks = list(BLOCK_RE.finditer(segment))
    if blocks:
        block = blocks[-1]
        result["block_index"] = int(block.group(1))
        result["condition"] = block.group(2)
    configs = list(CONFIG_RE.finditer(segment))
    if configs:
        cfg = configs[-1]
        result["config_progress"] = (cfg.group(1), int(cfg.group(2)), int(cfg.group(3)))
    result["final_summary_seen"] = "=== FINAL SUMMARY ===" in segment
    return result


def get_seeds(plan_path: Path) -> list[int]:
    plan = load_json(plan_path)
    if plan and isinstance(plan.get("seeds"), list):
        try:
            seeds = [int(seed) for seed in plan["seeds"]]
        except (TypeError, ValueError):
            seeds = []
        if seeds:
            return seeds
    return DEFAULT_SEEDS[:]


def trajectory_state(root: Path, seed: int, current_seed: int | None, alive: bool) -> dict[str, Any]:
    trajectory = root / f"trajectory_{seed}"
    run_dir = trajectory / "confirmatory_main"
    summary = run_dir / "summary.json"
    partition = run_dir / "partition_map.json"
    injection = run_dir / "recalibration_injection.json"
    composed = trajectory / "composite_manifest.jsonl"
    dev_selected = trajectory / "dev_selected.json"

    if summary.is_file():
        status = "COMPLETED"
    elif current_seed == seed and alive:
        status = "RUNNING"
    elif injection.is_file() or partition.is_file():
        status = "INTERRUPTED"
    elif composed.is_file() and dev_selected.is_file():
        status = "PREPARED"
    else:
        status = "PENDING"

    runtime = None
    if summary.is_file() and partition.is_file():
        runtime = max(0.0, summary.stat().st_mtime - partition.stat().st_mtime)
    elif status == "RUNNING" and partition.is_file():
        runtime = max(0.0, time.time() - partition.stat().st_mtime)

    return {
        "seed": seed,
        "status": status,
        "runtime": runtime,
        "summary": summary,
    }


def render(args: argparse.Namespace) -> int:
    repo = args.repo_root.expanduser().resolve()
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root
        else repo / "mathematical_framework" / "recalibration_2026_v2" / "outputs"
    )
    confirmation_root = output_root / "confirmation"
    pid_path = args.pid_file or output_root / "run_v2_confirmation.pid"
    pid = read_pid(pid_path)
    alive, process_elapsed, process_detail = process_info(pid)
    log_path = latest_log(output_root / "logs", args.log)
    log = parse_log(log_path)
    seeds = get_seeds(confirmation_root / "confirmation_plan.json")
    states = [trajectory_state(confirmation_root, seed, log["seed"], alive) for seed in seeds]
    completed = sum(item["status"] == "COMPLETED" for item in states)

    current_fraction = 0.0
    if alive and log["seed"] in seeds:
        if log["final_summary_seen"]:
            current_fraction = 0.99
        elif log["block_index"] is not None:
            current_fraction = min(0.98, (float(log["block_index"]) + 0.5) / TOTAL_BLOCKS)
        elif any(item["seed"] == log["seed"] and item["status"] == "RUNNING" for item in states):
            current_fraction = 0.02

    work_units = min(float(len(seeds)), completed + current_fraction)
    percent = 100.0 * work_units / len(seeds) if seeds else 0.0
    completed_runtimes = [
        float(item["runtime"])
        for item in states
        if item["status"] == "COMPLETED" and item["runtime"] is not None
    ]
    eta = None
    basis = ""
    if completed_runtimes:
        typical = statistics.median(completed_runtimes)
        eta = typical * max(0.0, len(seeds) - work_units)
        basis = f"median completed trajectory {duration(typical)}"
    elif alive and process_elapsed is not None and current_fraction >= 0.12:
        typical = process_elapsed / max(current_fraction, 0.01)
        eta = typical * max(0.0, len(seeds) - work_units)
        basis = "current partial trajectory extrapolation"

    now = time.time()
    print("V2 CONFIRMATION PROGRESS")
    print("checked:", utc_stamp(now))
    if alive:
        print(f"process: RUNNING  pid={pid}  elapsed={duration(process_elapsed)}")
    elif completed == len(seeds) and seeds:
        print(f"process: FINISHED  pid_file={pid_path}")
    else:
        print(f"process: NOT RUNNING  {process_detail}")
    print(f"completed: {completed}/{len(seeds)}")
    print(f"estimated_work: {work_units:.2f}/{len(seeds)} ({percent:.1f}%)")
    if eta is None:
        print("estimated_remaining: pending; reliable after the first completed trajectory")
    else:
        print(f"estimated_remaining: {duration(eta)} ({basis})")

    if log_path is None:
        print("log: not found")
    else:
        age = None if log["mtime"] is None else max(0.0, now - float(log["mtime"]))
        print(f"log: {log_path}")
        print(f"log_activity_age: {duration(age)}  size={int(log['size'])} bytes")

    if alive and log["seed"] is not None:
        if log["block_index"] is None:
            print(f"current: seed={log['seed']} phase=setup/reference-calibration")
        else:
            print(
                f"current: seed={log['seed']} "
                f"block={int(log['block_index']) + 1}/{TOTAL_BLOCKS} "
                f"condition={log['condition']}"
            )
        if log["config_progress"]:
            cfg, done, total = log["config_progress"]
            print(f"latest_config_progress: {cfg} {done}/{total} new runs")

    print("trajectories:")
    for item in states:
        runtime_text = "" if item["runtime"] is None else f" runtime={duration(item['runtime'])}"
        print(f"  {item['seed']}: {item['status']}{runtime_text}")

    if not alive and completed < len(seeds) and log["tail"]:
        print("latest_nonempty_log_lines:")
        for line in log["tail"]:
            print("  " + line[-240:])

    if completed == len(seeds) and seeds:
        print("confirmation_status: COMPLETE")
        return 0
    if not alive:
        print("confirmation_status: INCOMPLETE_AND_NOT_RUNNING")
        return 2
    print("confirmation_status: RUNNING")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.home() / "ocr-segmentation",
        help="Repository root (default: ~/ocr-segmentation)",
    )
    parser.add_argument("--output-root", type=Path, help="Override V2 outputs directory")
    parser.add_argument("--pid-file", type=Path, help="Override confirmation PID file")
    parser.add_argument("--log", type=Path, help="Inspect one explicit confirmation log")
    parser.add_argument(
        "--watch",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="Refresh continuously at this interval; Ctrl+C stops only the monitor",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.watch < 0:
        raise SystemExit("--watch must be non-negative")
    if args.watch == 0:
        return render(args)
    try:
        while True:
            print("\033[2J\033[H", end="")
            render(args)
            sys.stdout.flush()
            time.sleep(max(1.0, args.watch))
    except KeyboardInterrupt:
        print("\nmonitor stopped; confirmation process was not interrupted")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

