R=$HOME/ocr-segmentation
Q=$R/mathematical_framework/recalibration_2026
O=$Q/outputs
PY=$R/ips_single_image/.venv/bin/python

"$PY" - "$O" <<'PY'
from pathlib import Path
import csv, json, sys

root = Path(sys.argv[1])
selection = json.loads(
    (root / "delta_selection/selected_delta.json").read_text()
)
freeze = json.loads(
    (root / "freeze_summary.json").read_text()
)

harm_csvs = list(root.glob(
    "delta_grid/trajectory_*/delta_*/delta_harm_events.csv"
))
harm_summaries = list(root.glob(
    "delta_grid/trajectory_*/delta_*/delta_harm_events.summary.json"
))
run_summaries = list(root.glob(
    "delta_grid/trajectory_*/delta_*/summary.json"
))

with (root / "delta_selection/delta_calibration_summary.csv").open(
    newline="", encoding="utf-8"
) as f:
    rows = list(csv.DictReader(f))

selected = float(selection["selected_delta_W"])
selected_row = next(
    row for row in rows
    if abs(float(row["delta_W"]) - selected) < 1e-12
)

gate_violations = 0
missing_dbox = 0
for path in harm_csvs:
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gate_violations += int(row["committed_gate_violation"])
            missing_dbox += int(row["dbox_after"] == "")

print("=== COMPLETENESS ===")
print("harm_csv:", len(harm_csvs), "/ 1625")
print("harm_summary:", len(harm_summaries), "/ 1625")
print("experiment_summary:", len(run_summaries), "/ 1625")
print("delta_summary_rows:", len(rows), "/ 25")

print("\n=== DELTA DECISION ===")
print("status:", selection["status"])
print("selected_delta_W:", selection["selected_delta_W"])
print(
    "selected_delta_I:",
    selection["selected_delta_I_volume_matched"]
)
print("eligible_grid_values:", selection["eligible_grid_values"])

print("\n=== SELECTED ROW ===")
for key in (
    "informative_events",
    "harm_events",
    "harm_upper_exact_one_sided",
    "nonzero_commits",
    "update_coverage",
    "eligible",
):
    print(f"{key}:", selected_row[key])

print("\n=== SAFETY / FREEZE ===")
print("committed_gate_violations:", gate_violations)
print("rows_missing_dbox:", missing_dbox)
print("frozen_file_count:", freeze["file_count"])
print("manifest_sha256:", freeze["manifest_sha256"])
PY

(
  cd "$O" &&
  sha256sum --quiet -c MANIFEST.sha256
) && echo "manifest_verification: PASS"
