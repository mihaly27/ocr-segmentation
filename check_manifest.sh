R="$HOME/ocr-segmentation"
Q2="$R/mathematical_framework/recalibration_2026_v2"
P2="$Q2/protocol.yaml"
S2="$Q2/scripts"
O2="$Q2/outputs"
L2="$Q2/v2_input_lock.json"
PY="$R/ips_single_image/.venv/bin/python"

if (
  cd "$O2" &&
  sha256sum -c MANIFEST.sha256 \
    >logs/v2_manifest_verify.log 2>&1
); then
  echo "v2_calibration_freeze: PASS"
else
  echo "v2_calibration_freeze: FAIL"
  tail -n 80 "$O2/logs/v2_manifest_verify.log"
fi

sha256sum \
  "$O2/MANIFEST.sha256" \
  "$O2/freeze_summary.json"
