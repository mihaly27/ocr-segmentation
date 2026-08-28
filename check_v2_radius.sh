R="$HOME/ocr-segmentation"
Q2="$R/mathematical_framework/recalibration_2026_v2"
P2="$Q2/protocol.yaml"
S2="$Q2/scripts"
O2="$Q2/outputs"
L2="$Q2/v2_input_lock.json"
PY="$R/ips_single_image/.venv/bin/python"

"$PY" - "$O2/delta_selection/delta_calibration_by_condition.csv" <<'PY'
import csv
import sys

with open(sys.argv[1], newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

for row in rows:
    if float(row["delta_W"]) == 12.0:
        print(
            row["condition"],
            "trajectories=", row["trajectory_count"],
            "informative=", row["informative_events"],
            "harm=", row["harm_events"],
            "commits=", row["nonzero_commits"],
            "coverage=", row["update_coverage"],
        )
PY
