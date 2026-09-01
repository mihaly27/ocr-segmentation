R=$HOME/ocr-segmentation
Q1=$R/mathematical_framework/recalibration_2026
Q2=$R/mathematical_framework/recalibration_2026_v2
P2=$Q2/protocol.yaml
S2=$Q2/scripts
O2=$Q2/outputs
L2=$Q2/v2_input_lock.json
PY=$R/ips_single_image/.venv/bin/python
W1=$Q1/outputs/w_calibration.json

"$PY" "$S2/check_v2_grid.py" \
  --protocol "$P2" \
  --input-lock "$L2" \
  --grid-root "$O2/delta_grid" \
  --output "$O2/v2_grid_check.json"
