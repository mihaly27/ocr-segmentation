R="$HOME/ocr-segmentation"
Q2="$R/mathematical_framework/recalibration_2026_v2"
P2="$Q2/protocol.yaml"
S2="$Q2/scripts"
O2="$Q2/outputs"
L2="$Q2/v2_input_lock.json"
PY="$R/ips_single_image/.venv/bin/python"

mkdir -p "$O2/logs"

TS=$(date -u +%Y%m%dT%H%M%SZ)
LOG="$O2/logs/generate_v2_confirmation_${TS}.log"

nohup "$PY" "$S2/prepare_synthetic_corpora.py" \
  --protocol "$P2" \
  --input-lock "$L2" \
  --generator "$GEN" \
  --output-root "$C2" \
  --mode confirmation \
  --selected-delta "$SELECTED" \
  >"$LOG" 2>&1 </dev/null &

PID=$!
echo "$PID" >"$O2/generate_v2_confirmation.pid"
echo "PID: $PID"
echo "LOG: $LOG"
