R="$HOME/ocr-segmentation"
Q2="$R/mathematical_framework/recalibration_2026_v2"
P2="$Q2/protocol.yaml"
S2="$Q2/scripts"
O2="$Q2/outputs"
L2="$Q2/v2_input_lock.json"
PY="$R/ips_single_image/.venv/bin/python"

find "$C2" \
  -maxdepth 2 \
  -path "$C2/confirmation_*/dataset_config.json" \
  -type f | wc -l
