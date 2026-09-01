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

with (root / "delta_selection/delta_calibration_summary.csv").open(
    newline="", encoding="utf-8"
) as f:
    rows = list(csv.DictReader(f))

print("status:", selection["status"])
print("selected_delta_W:", selection["selected_delta_W"])
print("eligible_grid_values:", selection["eligible_grid_values"])

print()
print(
    f"{'delta':>5} {'info':>5} {'harm':>5} "
    f"{'upper95':>10} {'commit':>7} {'coverage':>10} {'eligible':>8}"
)
for r in rows:
    print(
        f"{float(r['delta_W']):5.1f} "
        f"{int(r['informative_events']):5d} "
        f"{int(r['harm_events']):5d} "
        f"{float(r['harm_upper_exact_one_sided']):10.6f} "
        f"{int(r['nonzero_commits']):7d} "
        f"{float(r['update_coverage']):10.6f} "
        f"{int(r['eligible']):8d}"
    )
PY
