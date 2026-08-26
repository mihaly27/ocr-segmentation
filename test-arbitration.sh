R=$HOME/ocr-segmentation
Q=$R/mathematical_framework/recalibration_2026
P=$Q/protocol.yaml
O=$Q/outputs
PY=$R/ips_single_image/.venv/bin/python

"$PY" - "$P" "$O/delta_grid" <<'PY'
from pathlib import Path
from collections import Counter, defaultdict
import csv, sys, yaml

protocol = yaml.safe_load(Path(sys.argv[1]).read_text())
root = Path(sys.argv[2])

specs = {
    str(x["seed"]): x
    for x in protocol["delta_calibration"]["trajectory_specs"]
}

# A 0.5-ös delta informatív mintáinak bontása.
records = []
for path in root.glob("trajectory_*/delta_*/delta_harm_events.csv"):
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows or abs(float(rows[0]["delta_W"]) - 0.5) > 1e-12:
        continue

    seed = str(rows[0]["trajectory_seed"])
    spec = specs[seed]
    event = next(
        row for row in rows
        if row["condition"] == str(spec["condition"])
    )
    records.append((seed, spec, event))

print("=== INFORMATIVITY AT DELTA 0.5 ===")
groups = defaultdict(list)
for seed, spec, event in records:
    groups[(spec["role"], spec["condition"])].append((seed, event))

for (role, condition), items in sorted(groups.items()):
    info = sum(int(event["informative"]) for _, event in items)
    decisions = Counter(event["decision"] for _, event in items)
    print(
        f"{role:18} {condition:12} "
        f"total={len(items):2d} informative={info:2d} "
        f"decisions={dict(decisions)}"
    )

print("\n=== NON-INFORMATIVE SEEDS ===")
for seed, spec, event in records:
    if int(event["informative"]) == 0:
        print(
            f"seed={seed} role={spec['role']} "
            f"condition={spec['condition']} decision={event['decision']}"
        )

print("\n=== ALL HARM EVENTS ===")
harm_count = 0
for path in sorted(root.glob(
    "trajectory_*/delta_*/delta_harm_events.csv"
)):
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row["H"]) != 1:
                continue
            harm_count += 1
            flags = [
                name for name in (
                    "plate_harm",
                    "char_harm",
                    "dseg_harm",
                    "latency_harm",
                    "committed_gate_violation",
                )
                if int(row[name]) == 1
            ]
            print(
                f"delta={float(row['delta_W']):4.1f} "
                f"seed={row['trajectory_seed']} "
                f"condition={row['condition']} "
                f"flags={','.join(flags)} "
                f"plate_drop={row['plate_drop']} "
                f"char_drop={row['char_drop']} "
                f"dseg_increase={row['dseg_increase']}"
            )

print("harm_rows_total:", harm_count)
PY
