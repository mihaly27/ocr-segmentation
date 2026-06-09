#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_CMD_TEMPLATE = "python3 main.py --image {image} --outdir {outdir} --gt {gt} {variant_args}"


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_variants(path: Path) -> List[Dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    data = data["variants"] if isinstance(data, dict) and "variants" in data else data
    return [{"name": str(v["name"]), "args": str(v.get("args", ""))} for v in data]


def read_manifest(path: Path, dataset_root: Path, split: str, limit: Optional[int]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if split != "all" and row.get("split") != split:
                continue
            row["abs_image"] = str((dataset_root / row["image_path"]).resolve())
            row["abs_mask"] = str((dataset_root / row["mask_path"]).resolve())
            rows.append(row)
            if limit is not None and len(rows) >= limit:
                break
    return rows


def first(*vals: Any) -> Any:
    for v in vals:
        if v is not None and v != "":
            return v
    return ""


def normalize(outdir: Path, elapsed_s: float) -> Dict[str, Any]:
    result = read_json(outdir / "result.json")
    trace = read_json(outdir / "trace.json")
    metrics = trace.get("metrics", {}) if isinstance(trace.get("metrics"), dict) else {}
    timings = trace.get("timings_ms", {}) if isinstance(trace.get("timings_ms"), dict) else {}
    breakdown = trace.get("score_breakdown", {}) if isinstance(trace.get("score_breakdown"), dict) else {}
    prior = breakdown.get("prior", {}) if isinstance(breakdown.get("prior"), dict) else {}
    overlap = breakdown.get("overlap", {}) if isinstance(breakdown.get("overlap"), dict) else {}
    fit = breakdown.get("fit", {}) if isinstance(breakdown.get("fit"), dict) else {}
    search_history = trace.get("search_history", [])
    initial_segments = trace.get("initial_segments", [])
    selected_segments = trace.get("selected_segments", [])

    trace_hash = first(result.get("trace_hash"), trace.get("trace_hash"))
    if not trace_hash and (outdir / "trace.json").exists():
        trace_hash = file_sha256(outdir / "trace.json")

    expected_count = first(metrics.get("expected_count"), "")
    segment_count = first(metrics.get("segment_count"), "")
    seg_count_edit = ""
    try:
        seg_count_edit = abs(int(segment_count) - int(expected_count))
    except Exception:
        pass

    try:
        split_actions = sum(1 for h in search_history if isinstance(h, dict) and h.get("action") == "split")
    except Exception:
        split_actions = ""

    return {
        "pred": result.get("pred", ""),
        "gt": result.get("gt", ""),
        "char_acc": first(result.get("char_accuracy"), metrics.get("char_accuracy")),
        "plate_acc": first(result.get("full_plate_accuracy"), metrics.get("full_plate_accuracy")),
        "seg_edit_dist": seg_count_edit,
        "segment_count": segment_count,
        "expected_count": expected_count,
        "initial_segment_count": len(initial_segments) if isinstance(initial_segments, list) else "",
        "selected_segment_count": len(selected_segments) if isinstance(selected_segments, list) else "",
        "split_actions": split_actions,
        "total_ms": first(result.get("total_ms"), timings.get("total_ms")),
        "load_ms": timings.get("load_ms", ""),
        "preprocess_ms": timings.get("preprocess_ms", ""),
        "cc_ms": timings.get("cc_ms", ""),
        "search_ms": timings.get("search_ms", ""),
        "ocr_ms": timings.get("ocr_ms", ""),
        "runner_elapsed_s": round(elapsed_s, 6),
        "trace_hash": trace_hash,
        "score_total": breakdown.get("total", ""),
        "fit_sum": fit.get("sum", ""),
        "overlap_sum": overlap.get("sum", ""),
        "overlap_pairs": len(overlap.get("pairs", [])) if isinstance(overlap.get("pairs", []), list) else "",
        "density": prior.get("density", ""),
        "density_pen": prior.get("density_pen", ""),
        "density_weighted": prior.get("density_weighted", ""),
        "blocking": prior.get("blocking", ""),
        "blocking_weighted": prior.get("blocking_weighted", ""),
        "blocking_pairs": len(prior.get("blocking_pairs", [])) if isinstance(prior.get("blocking_pairs", []), list) else "",
    }


def build_command(template: str, row: Dict[str, str], variant: Dict[str, str], dataset_root: Path, software_dir: Path, outdir: Path) -> str:
    return template.format(
        image=row["abs_image"],
        mask=row["abs_mask"],
        gt=row["plate"],
        sample_id=row["sample_id"],
        variant=variant["name"],
        variant_args=variant.get("args", ""),
        outdir=str(outdir),
        dataset_root=str(dataset_root.resolve()),
        software_dir=str(software_dir.resolve()),
    )


def run_one(row: Dict[str, str], variant: Dict[str, str], args: argparse.Namespace) -> Dict[str, Any]:
    dataset_root = Path(args.dataset_root)
    software_dir = Path(args.software_dir)
    outdir = Path(args.out) / "outputs" / safe_name(variant["name"]) / safe_name(row["sample_id"])
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = build_command(args.cmd_template, row, variant, dataset_root, software_dir, outdir)

    t0 = time.perf_counter()
    p = subprocess.run(cmd, cwd=str(software_dir), shell=True, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=args.timeout)
    elapsed = time.perf_counter() - t0

    (outdir / "command.txt").write_text(cmd + "\n", encoding="utf-8")
    (outdir / "stdout.txt").write_text(p.stdout or "", encoding="utf-8", errors="replace")
    (outdir / "stderr.txt").write_text(p.stderr or "", encoding="utf-8", errors="replace")

    rec = {
        "sample_id": row["sample_id"],
        "plate": row["plate"],
        "split": row.get("split", ""),
        "perturbation": row.get("perturbation", ""),
        "variant": variant["name"],
        "returncode": p.returncode,
        "image_path": row.get("image_path", ""),
        "outdir": str(outdir),
        "cmd": cmd,
        "stderr_tail": (p.stderr or "")[-500:].replace("\n", "\\n"),
    }
    rec.update(normalize(outdir, elapsed))
    return rec


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    preferred = [
        "sample_id", "plate", "split", "perturbation", "variant", "returncode",
        "pred", "gt", "char_acc", "plate_acc", "seg_edit_dist",
        "segment_count", "expected_count", "initial_segment_count", "selected_segment_count",
        "split_actions", "density", "density_pen", "density_weighted",
        "blocking", "blocking_weighted", "blocking_pairs", "overlap_sum", "overlap_pairs",
        "score_total", "total_ms", "load_ms", "preprocess_ms", "cc_ms", "search_ms", "ocr_ms",
        "runner_elapsed_s", "trace_hash", "outdir", "image_path", "stderr_tail", "cmd",
    ]
    fields = [k for k in preferred if any(k in r for r in rows)]
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def make_summary(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((str(r.get("variant", "")), str(r.get("perturbation", ""))), []).append(r)

    def mean(rs: List[Dict[str, Any]], key: str) -> Any:
        vals = []
        for r in rs:
            try:
                v = r.get(key, "")
                if v != "" and v is not None:
                    vals.append(float(v))
            except Exception:
                pass
        return "" if not vals else round(sum(vals) / len(vals), 6)

    out = []
    for (variant, perturb), rs in sorted(groups.items()):
        out.append({
            "variant": variant,
            "perturbation": perturb,
            "n": len(rs),
            "failures": sum(1 for r in rs if int(r.get("returncode", 1)) != 0),
            "mean_char_acc": mean(rs, "char_acc"),
            "mean_plate_acc": mean(rs, "plate_acc"),
            "mean_seg_edit_dist": mean(rs, "seg_edit_dist"),
            "mean_total_ms": mean(rs, "total_ms"),
            "mean_search_ms": mean(rs, "search_ms"),
            "mean_ocr_ms": mean(rs, "ocr_ms"),
            "mean_density_pen": mean(rs, "density_pen"),
            "mean_blocking": mean(rs, "blocking"),
            "mean_overlap_sum": mean(rs, "overlap_sum"),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--dataset-root", required=True)
    ap.add_argument("--software-dir", required=True)
    ap.add_argument("--variants", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cmd-template", default=DEFAULT_CMD_TEMPLATE)
    ap.add_argument("--split", default="all", choices=["all", "train", "test"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--fail-fast", action="store_true")
    args = ap.parse_args()

    rows = read_manifest(Path(args.manifest), Path(args.dataset_root), args.split, args.limit)
    variants = load_variants(Path(args.variants))
    tasks = [(row, var) for row in rows for var in variants]
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    (outdir / "batch_config.json").write_text(json.dumps({
        "manifest": args.manifest,
        "dataset_root": args.dataset_root,
        "software_dir": args.software_dir,
        "variants": variants,
        "cmd_template": args.cmd_template,
        "split": args.split,
        "limit": args.limit,
        "workers": args.workers,
        "timeout": args.timeout,
        "n_commands": len(tasks),
    }, indent=2), encoding="utf-8")

    print(f"Rows={len(rows)} Variants={len(variants)} Commands={len(tasks)} Out={outdir}")
    results: List[Dict[str, Any]] = []
    if args.workers <= 1:
        for i, (row, var) in enumerate(tasks, 1):
            print(f"[{i}/{len(tasks)}] {row['sample_id']} :: {var['name']}")
            rec = run_one(row, var, args)
            results.append(rec)
            write_csv(outdir / "results.csv", results)
            if args.fail_fast and rec["returncode"] != 0:
                return int(rec["returncode"]) or 1
    else:
        with cf.ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = [ex.submit(run_one, row, var, args) for row, var in tasks]
            for i, fut in enumerate(cf.as_completed(futures), 1):
                rec = fut.result()
                results.append(rec)
                print(f"[{i}/{len(tasks)}] rc={rec['returncode']} {rec['sample_id']} :: {rec['variant']}")
                if i % 10 == 0:
                    write_csv(outdir / "results.csv", results)
                if args.fail_fast and rec["returncode"] != 0:
                    write_csv(outdir / "results.csv", results)
                    return int(rec["returncode"]) or 1

    write_csv(outdir / "results.csv", results)
    write_csv(outdir / "summary_by_variant_perturbation.csv", make_summary(results))
    print(f"Done: {outdir / 'results.csv'}")
    print(f"Summary: {outdir / 'summary_by_variant_perturbation.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
