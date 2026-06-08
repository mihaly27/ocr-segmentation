#!/usr/bin/env python3
"""
Batch runner for SISY 2026 IPS ablation experiments.

Reads the synthetic generator's manifest.csv, runs the OCR/IPS software for
multiple ablation variants, and writes one normalized CSV row per
(sample, variant).

The runner is intentionally CLI-template based because different IPS builds may
use different flag names. You only need to adjust variants.json and/or
--cmd-template.

Expected synthetic manifest columns:
    sample_id, plate, split, perturbation, image_path, mask_path, width, height, n_chars

Default command template:
    python main.py -image {image} -outdir {outdir} -gt {gt} {variant_args}

Placeholders usable in --cmd-template:
    {image}         absolute image path
    {mask}          absolute mask path
    {gt}            ground-truth plate string
    {sample_id}
    {variant}
    {variant_args}
    {outdir}        per-sample per-variant output directory
    {dataset_root}
    {software_dir}

Typical usage:
    python batch_runner.py \
      --manifest synthetic_plates_sisy2026/manifest.csv \
      --dataset-root synthetic_plates_sisy2026 \
      --software-dir /home/mszabo/ocr-segmentation \
      --variants variants_sisy2026.template.json \
      --out runs/sisy2026_batch \
      --workers 4 \
      --limit 100

Then full run:
    python batch_runner.py ... --workers 12
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_CMD_TEMPLATE = "python main.py -image {image} -outdir {outdir} -gt {gt} {variant_args}"


def load_variants(path: Optional[Path]) -> List[Dict[str, str]]:
    if path is None:
        return [{"name": "default", "args": ""}]
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "variants" in data:
        data = data["variants"]
    if not isinstance(data, list):
        raise ValueError("Variants file must contain a list or {'variants': [...]}")

    variants: List[Dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict) or "name" not in item:
            raise ValueError("Each variant must be an object with at least a 'name'")
        variants.append({"name": str(item["name"]), "args": str(item.get("args", ""))})
    return variants


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(path: Path, dataset_root: Path, split: str, limit: Optional[int]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if split != "all" and row.get("split") != split:
                continue
            row["abs_image"] = str((dataset_root / row["image_path"]).resolve())
            row["abs_mask"] = str((dataset_root / row["mask_path"]).resolve())
            rows.append(row)
            if limit is not None and len(rows) >= limit:
                break
    return rows


def load_json_if_exists(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_result_json(outdir: Path) -> Dict[str, Any]:
    """
    Try common result file names. If multiple exist, prefer result.json.
    """
    candidates = [
        outdir / "result.json",
        outdir / "results.json",
        outdir / "metrics.json",
        outdir / "trace_summary.json",
    ]
    for c in candidates:
        data = load_json_if_exists(c)
        if data:
            data["_result_json_path"] = str(c)
            return data

    # Fallback: first small JSON file in output directory.
    if outdir.exists():
        for c in sorted(outdir.glob("*.json")):
            if c.name == "trace.json":
                continue
            data = load_json_if_exists(c)
            if data:
                data["_result_json_path"] = str(c)
                return data
    return {}


def find_trace_hash(outdir: Path, result: Dict[str, Any]) -> str:
    for key in ["trace_hash", "hash", "sha256", "trace_sha256"]:
        val = result.get(key)
        if val:
            return str(val)

    trace_json = outdir / "trace.json"
    if trace_json.exists():
        try:
            return file_sha256(trace_json)
        except Exception:
            return ""

    return ""


def dig(obj: Dict[str, Any], *keys: str) -> Any:
    """
    Return the first existing key from a dict, supporting shallow alternatives.
    """
    for key in keys:
        if key in obj:
            return obj[key]
    return ""


def normalize_result(result: Dict[str, Any], outdir: Path) -> Dict[str, Any]:
    """
    Extract common metric names without assuming one exact schema.
    Missing values stay empty, so the CSV remains usable even if the software
    exports only a subset.
    """
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), dict) else {}

    normalized = {
        "pred": dig(result, "pred", "prediction", "predicted", "predicted_plate", "text", "ocr_text"),
        "char_acc": dig(result, "char_acc", "character_accuracy", "char_accuracy"),
        "plate_acc": dig(result, "plate_acc", "full_plate_accuracy", "plate_accuracy", "string_accuracy"),
        "seg_edit_dist": dig(result, "seg_edit_dist", "segmentation_edit_distance", "seg_edit"),
        "latency_ms": dig(result, "latency_ms", "runtime_ms", "elapsed_ms"),
        "latency_s": dig(result, "latency_s", "runtime_s", "elapsed_s"),
        "search_ms": dig(result, "search_ms", "search_time_ms"),
        "ocr_ms": dig(result, "ocr_ms", "ocr_time_ms"),
        "n_segments": dig(result, "n_segments", "segment_count", "num_segments"),
        "n_candidates": dig(result, "n_candidates", "candidate_count", "num_candidates"),
        "rejected_density": dig(result, "rejected_density", "density_rejects"),
        "rejected_blocking": dig(result, "rejected_blocking", "blocking_rejects"),
        "rejected_overlap": dig(result, "rejected_overlap", "overlap_rejects"),
        "trace_hash": find_trace_hash(outdir, result),
        "result_json_path": result.get("_result_json_path", ""),
    }

    # Also check nested metrics.
    for k in list(normalized.keys()):
        if normalized[k] == "" and k in metrics:
            normalized[k] = metrics[k]

    # Derive latency_s/ms when only one is present.
    if normalized["latency_ms"] == "" and normalized["latency_s"] != "":
        try:
            normalized["latency_ms"] = float(normalized["latency_s"]) * 1000.0
        except Exception:
            pass
    if normalized["latency_s"] == "" and normalized["latency_ms"] != "":
        try:
            normalized["latency_s"] = float(normalized["latency_ms"]) / 1000.0
        except Exception:
            pass

    return normalized


def build_command(
    cmd_template: str,
    row: Dict[str, str],
    variant: Dict[str, str],
    dataset_root: Path,
    software_dir: Path,
    outdir: Path,
) -> str:
    values = {
        "image": row["abs_image"],
        "mask": row["abs_mask"],
        "gt": row["plate"],
        "sample_id": row["sample_id"],
        "variant": variant["name"],
        "variant_args": variant.get("args", ""),
        "outdir": str(outdir),
        "dataset_root": str(dataset_root.resolve()),
        "software_dir": str(software_dir.resolve()),
    }
    return cmd_template.format(**values)


def run_one(
    row: Dict[str, str],
    variant: Dict[str, str],
    args: argparse.Namespace,
) -> Dict[str, Any]:
    dataset_root = Path(args.dataset_root)
    software_dir = Path(args.software_dir)
    out_root = Path(args.out)

    variant_name = safe_name(variant["name"])
    sample_name = safe_name(row["sample_id"])
    outdir = out_root / "outputs" / variant_name / sample_name
    outdir.mkdir(parents=True, exist_ok=True)

    cmd = build_command(args.cmd_template, row, variant, dataset_root, software_dir, outdir)

    started = time.perf_counter()
    completed = subprocess.run(
        cmd,
        cwd=str(software_dir),
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=args.timeout,
    )
    elapsed = time.perf_counter() - started

    # Store raw logs for auditability.
    (outdir / "stdout.txt").write_text(completed.stdout or "", encoding="utf-8", errors="replace")
    (outdir / "stderr.txt").write_text(completed.stderr or "", encoding="utf-8", errors="replace")
    (outdir / "command.txt").write_text(cmd + "\n", encoding="utf-8")

    result = find_result_json(outdir)
    metrics = normalize_result(result, outdir)

    rec: Dict[str, Any] = {
        "sample_id": row["sample_id"],
        "plate": row["plate"],
        "split": row.get("split", ""),
        "perturbation": row.get("perturbation", ""),
        "image_path": row.get("image_path", ""),
        "variant": variant["name"],
        "variant_args": variant.get("args", ""),
        "returncode": completed.returncode,
        "runner_elapsed_s": round(elapsed, 6),
        "outdir": str(outdir),
        "cmd": cmd,
        "stdout_tail": (completed.stdout or "")[-500:].replace("\n", "\\n"),
        "stderr_tail": (completed.stderr or "")[-500:].replace("\n", "\\n"),
        **metrics,
    }

    return rec


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: List[str] = []
    preferred = [
        "sample_id", "plate", "split", "perturbation", "variant", "returncode",
        "pred", "char_acc", "plate_acc", "seg_edit_dist", "n_segments",
        "n_candidates", "rejected_density", "rejected_blocking", "rejected_overlap",
        "latency_ms", "latency_s", "search_ms", "ocr_ms",
        "trace_hash", "runner_elapsed_s", "outdir", "result_json_path",
        "image_path", "variant_args", "cmd", "stdout_tail", "stderr_tail",
    ]
    for k in preferred:
        if any(k in r for r in rows):
            fieldnames.append(k)
    for r in rows:
        for k in r:
            if k not in fieldnames:
                fieldnames.append(k)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True, help="Path to manifest.csv")
    p.add_argument("--dataset-root", required=True, help="Root dir of generated dataset")
    p.add_argument("--software-dir", required=True, help="Root dir of OCR/IPS software")
    p.add_argument("--variants", default=None, help="JSON file with ablation variants")
    p.add_argument("--out", required=True, help="Output directory for batch run")
    p.add_argument("--cmd-template", default=DEFAULT_CMD_TEMPLATE, help="Command template")
    p.add_argument("--split", default="all", choices=["all", "train", "test"])
    p.add_argument("--limit", type=int, default=None, help="Limit number of manifest rows")
    p.add_argument("--workers", type=int, default=1, help="Parallel worker processes")
    p.add_argument("--timeout", type=float, default=120.0, help="Timeout per command in seconds")
    p.add_argument("--fail-fast", action="store_true", help="Stop after first failed command")
    args = p.parse_args()

    manifest = Path(args.manifest)
    dataset_root = Path(args.dataset_root)
    variants = load_variants(Path(args.variants) if args.variants else None)
    rows = read_manifest(manifest, dataset_root, args.split, args.limit)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    run_config = {
        "manifest": str(manifest),
        "dataset_root": str(dataset_root),
        "software_dir": str(Path(args.software_dir)),
        "variants": variants,
        "cmd_template": args.cmd_template,
        "split": args.split,
        "limit": args.limit,
        "workers": args.workers,
        "timeout": args.timeout,
        "n_manifest_rows": len(rows),
        "n_commands": len(rows) * len(variants),
    }
    (out / "batch_config.json").write_text(json.dumps(run_config, indent=2, ensure_ascii=False), encoding="utf-8")

    tasks: List[Tuple[Dict[str, str], Dict[str, str]]] = [
        (row, variant) for row in rows for variant in variants
    ]

    print(f"Rows: {len(rows)} | Variants: {len(variants)} | Commands: {len(tasks)}")
    print(f"Output: {out}")

    results: List[Dict[str, Any]] = []
    results_csv = out / "results.csv"

    if args.workers <= 1:
        for i, (row, variant) in enumerate(tasks, start=1):
            print(f"[{i}/{len(tasks)}] {row['sample_id']} :: {variant['name']}")
            rec = run_one(row, variant, args)
            results.append(rec)
            write_csv(results_csv, results)
            if args.fail_fast and rec["returncode"] != 0:
                print(f"FAILED: {rec['sample_id']} :: {rec['variant']}", file=sys.stderr)
                return int(rec["returncode"]) or 1
    else:
        with cf.ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(run_one, row, variant, args) for row, variant in tasks]
            for i, fut in enumerate(cf.as_completed(futs), start=1):
                rec = fut.result()
                results.append(rec)
                status = "OK" if rec["returncode"] == 0 else f"ERR {rec['returncode']}"
                print(f"[{i}/{len(tasks)}] {status} {rec['sample_id']} :: {rec['variant']}")
                if i % 10 == 0 or i == len(tasks):
                    write_csv(results_csv, results)
                if args.fail_fast and rec["returncode"] != 0:
                    write_csv(results_csv, results)
                    return int(rec["returncode"]) or 1

    write_csv(results_csv, results)

    # Simple summary by variant.
    summary_path = out / "summary_by_variant.csv"
    try:
        import statistics
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for r in results:
            groups.setdefault(str(r["variant"]), []).append(r)

        summary_rows: List[Dict[str, Any]] = []
        for variant, rs in sorted(groups.items()):
            def mean_float(key: str) -> str:
                vals = []
                for r in rs:
                    try:
                        if r.get(key) not in ("", None):
                            vals.append(float(r[key]))
                    except Exception:
                        pass
                return "" if not vals else str(round(statistics.mean(vals), 6))

            summary_rows.append({
                "variant": variant,
                "n": len(rs),
                "failures": sum(1 for r in rs if int(r.get("returncode", 1)) != 0),
                "mean_char_acc": mean_float("char_acc"),
                "mean_plate_acc": mean_float("plate_acc"),
                "mean_seg_edit_dist": mean_float("seg_edit_dist"),
                "mean_latency_ms": mean_float("latency_ms"),
                "mean_runner_elapsed_s": mean_float("runner_elapsed_s"),
                "stable_trace_hash_count": len(set(r.get("trace_hash", "") for r in rs if r.get("trace_hash", ""))),
            })
        write_csv(summary_path, summary_rows)
    except Exception as exc:
        print(f"Warning: failed to write summary: {exc}", file=sys.stderr)

    print(f"Done. Results: {results_csv}")
    print(f"Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
