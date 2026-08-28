R="$HOME/ocr-segmentation"
Q1="$R/mathematical_framework/recalibration_2026"
Q2="$R/mathematical_framework/recalibration_2026_v2"
P2="$Q2/protocol.yaml"
S2="$Q2/scripts"
C2="$Q2/corpora"
O2="$Q2/outputs"
L2="$Q2/v2_input_lock.json"
PY="$R/ips_single_image/.venv/bin/python"
W1="$Q1/outputs/w_calibration.json"
PHASE1="$Q1/outputs/w_phase1_local/selected_samples.json"
W1DATA="$Q1/corpora/w_calibration"
SELECTED="$O2/delta_selection/selected_delta.json"

"$PY" - "$O2/confirmation/confirmation_plan.json" <<'PY'
import json
import sys

plan = json.load(open(sys.argv[1], encoding="utf-8"))
expected_seeds = [86082721, 86082722, 86082723, 86082724, 86082725]

confirmation_jobs = sum(
    item["kind"] == "confirmation" for item in plan["items"]
)

print("execute:", plan["execute"])
print("selected_delta_W:", plan["selected_delta_W"])
print("seeds:", plan["seeds"])
print("confirmation_jobs:", confirmation_jobs)

assert plan["execute"] is False
assert plan["selected_delta_W"] == 12.0
assert plan["seeds"] == expected_seeds
assert confirmation_jobs == 5

print("confirmation_plan: PASS")
PY
