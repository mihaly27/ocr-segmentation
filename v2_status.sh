#!/usr/bin/env bash
set -euo pipefail

R="$HOME/ocr-segmentation"
Q2="$R/mathematical_framework/recalibration_2026_v2"

"$R/ips_single_image/.venv/bin/python" \
  "$Q2/scripts/progress_v2.py" \
  --protocol "$Q2/protocol.yaml" \
  --grid-root "$Q2/outputs/delta_grid"
