R="$HOME/ocr-segmentation"
Q2="$R/mathematical_framework/recalibration_2026_v2"
P2="$Q2/protocol.yaml"
S2="$Q2/scripts"
O2="$Q2/outputs"
L2="$Q2/v2_input_lock.json"
PY="$R/ips_single_image/.venv/bin/python"

"$PY" "$S2/freeze_artifacts.py" \
  --root "$O2" \
  --include \
    preflight.json \
    delta_grid \
    v2_grid_check.json \
    delta_selection
