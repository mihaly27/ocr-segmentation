#!/usr/bin/env python3
"""Recompute the R17/R18 fixed-gate comparison and R19 diagnostics.

Python standard library only. Reads the original ZIPs without extracting them.
This is a descriptive audit, not an accuracy evaluation or a model rerun.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import re
from zipfile import ZipFile


def csv_rows(archive, name):
    return list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8-sig"))))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect(path):
    with ZipFile(path) as archive:
        run = json.loads(archive.read("run.json"))
        config = json.loads(archive.read("config/pilot_config.json"))
        obs = csv_rows(archive, "results/observations.csv")
        tracks = csv_rows(archive, "results/test.csv")
        log = archive.read("logs/stdout.log").decode("utf-8")
        jrows = [json.loads(line) for line in
                 archive.read("results/plate_observations.jsonl").decode().splitlines()
                 if line.strip()]
        accepted = [o for o in obs if o["accepted_for_vote"] == "True"]
        if any(o["accepted_for_vote"] not in ("True", "False") for o in obs):
            raise ValueError("Unknown acceptance flag")
        source_hash = digest(archive.read("video/source.mp4"))
        reported_hash = re.search(r"^Video SHA256: (\w+)$", log, re.M).group(1)
        if source_hash != reported_hash:
            raise ValueError("Video bytes and log hash disagree")
        if len(jrows) != len(obs) or sum(o["accepted_for_vote"] for o in jrows) != len(accepted):
            raise ValueError("CSV and JSONL counts disagree")
        if Counter(o["rejection_reason"] for o in jrows) != Counter(o["rejection_reason"] for o in obs):
            raise ValueError("CSV and JSONL rejection reasons disagree")
        if sum(int(t["plate_total_observations"]) for t in tracks) != len(accepted):
            raise ValueError("Observation and final-record totals disagree")
        by_track = {t["car_id"]: t for t in tracks}
        for car in {o["car_id"] for o in accepted}:
            group = [o for o in accepted if o["car_id"] == car]
            votes, support = defaultdict(float), Counter()
            for o in group:
                votes[o["normalized_text"]] += float(o["ocr_confidence"])
                support[o["normalized_text"]] += 1
            # The observed winners have strictly highest weight; no tie rule is needed.
            winner = max(votes, key=votes.get)
            if list(votes.values()).count(votes[winner]) != 1:
                raise ValueError("Tied weight requires the implementation tie rule")
            row = by_track[car]
            if winner != row["plate_text"] or support[winner] != int(row["plate_support_count"]):
                raise ValueError("Consensus winner/support mismatch")
            if abs(votes[winner] - float(row["plate_weighted_vote"])) > 1e-10:
                raise ValueError("Consensus weight mismatch")
        summary = {
            "run": run["id"], "source_run": run["replay_source_id"],
            "capture_run_id": run["capture_run_id"], "mode": run["mode"],
            "threshold": config["parameters"]["ocr_threshold"],
            "code_revision": re.search(r"^Code revision: (\w+)$", log, re.M).group(1),
            "source_sha256": source_hash, "archive_sha256": digest(path.read_bytes()),
            "frames": int(re.search(r"Recorded and analyzed (\d+) frames", log).group(1)),
            "finalized_tracks": len(tracks), "logged_observations": len(obs),
            "accepted": len(accepted),
            "rejection_counts": dict(Counter(o["rejection_reason"] for o in obs if o["rejection_reason"])),
            "output_tracks": sum(bool(t["plate_text"]) for t in tracks),
            "outputs": [{k: t[k] for k in ("car_id", "plate_text", "plate_total_observations",
                         "plate_support_count", "plate_weighted_vote", "plate_bbox_frame_number")}
                        for t in tracks if t["plate_text"]],
            "minimum_ocr_score": min(float(o["ocr_confidence"]) for o in obs),
            "maximum_ocr_score": max(float(o["ocr_confidence"]) for o in obs),
            "parameters": config["parameters"],
            "configuration_completeness": config["completeness"],
            "unavailable": config["unavailable"],
        }
    return summary, obs, tracks, run


def comparable(rows):
    ignored = {"run_id", "captured_at", "accepted_for_vote", "rejection_reason"}
    return [{k: v for k, v in o.items() if k not in ignored} for o in rows]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for number in (17, 18, 19):
        parser.add_argument(f"--run{number}", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    data = {n: inspect(getattr(args, f"run{n}")) for n in (17, 18, 19)}
    a, b = data[17], data[18]
    differences = {k: [a[0]["parameters"][k], b[0]["parameters"][k]]
                   for k in a[0]["parameters"]
                   if a[0]["parameters"][k] != b[0]["parameters"][k]}
    vehicle_keys = ("car_id", "tracker_id", "connection_index", "vehicle_class",
                    "vehicle_class_id", "vehicle_confidence", "vehicle_x1", "vehicle_y1",
                    "vehicle_x2", "vehicle_y2", "termination_reason")
    vehicles = lambda rows: [{k: t[k] for k in vehicle_keys} for t in rows]
    accepted17 = [o for o in a[1] if o["accepted_for_vote"] == "True"]
    filtered18 = [o for o in b[1] if o["accepted_for_vote"] == "True"
                  and float(o["ocr_confidence"]) >= a[0]["threshold"]]
    checks = {
        "source_bytes_identical": a[0]["source_sha256"] == b[0]["source_sha256"],
        "reported_code_revision_equal": a[0]["code_revision"] == b[0]["code_revision"],
        "only_recorded_parameter_difference_is_threshold": set(differences) == {"ocr_threshold"},
        "all_ordered_predecision_observations_equal": comparable(a[1]) == comparable(b[1]),
        "final_vehicle_fields_equal_excluding_time_and_plate": vehicles(a[2]) == vehicles(b[2]),
        "filtering_accepted18_at_08_reproduces_accepted17": comparable(accepted17) == comparable(filtered18),
        "r19_all_logged_rows_format_rejected_above_threshold": all(
            o["rejection_reason"] == "unreadable_format" and not o["normalized_text"]
            and o["raw_text"] and float(o["ocr_confidence"]) > data[19][0]["threshold"]
            for o in data[19][1]),
    }
    if not all(checks.values()):
        raise ValueError(f"Observed evidence differs from the reported comparison: {checks}")
    result = {"scope": "Fixed-threshold replay diagnostics; no ground-truth accuracy or governor evaluation",
              "runs": [data[n][0] for n in (17, 18, 19)],
              "paired_parameter_differences": differences, "checks": checks,
              "accepted_count_reduction_percent": 100 * (b[0]["accepted"] - a[0]["accepted"]) / b[0]["accepted"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Saved replay audit: {args.output}; all {len(checks)} checks passed")


if __name__ == "__main__":
    main()
