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

mkdir -p "$O2/logs"

"$PY" "$S2/run_confirmation.py" \
  --repo-root "$R" \
  --protocol "$P2" \
  --input-lock "$L2" \
  --w-json "$W1" \
  --selected-delta "$SELECTED" \
  --phase1-selected "$PHASE1" \
  --w-dataset-root "$W1DATA" \
  --corpora-root "$C2" \
  --output-root "$O2/confirmation" \
  --workers 8 \
  --timeout 180 \
  >"$O2/logs/v2_confirmation_plan.log" 2>&1
