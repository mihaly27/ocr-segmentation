R=$HOME/ocr-segmentation
Q=$R/mathematical_framework/recalibration_2026
P=$Q/protocol.yaml
S=$Q/scripts
C=$Q/corpora
O=$Q/outputs
PY=$R/ips_single_image/.venv/bin/python

cd "$R" || exit 1
mkdir -p "$O/delta_grid"

TS=$(date -u +%Y%m%dT%H%M%SZ)
LOG=$O/delta_grid/run_delta_grid_${TS}.log
PIDFILE=$O/delta_grid/run_delta_grid.pid

nohup "$PY" "$S/run_delta_grid.py" \
  --repo-root "$R" \
  --protocol "$P" \
  --w-json "$O/w_calibration.json" \
  --phase1-selected "$O/w_phase1_local/selected_samples.json" \
  --corpora-root "$C" \
  --output-root "$O/delta_grid" \
  --workers 8 \
  --timeout 180 \
  --execute \
  >"$LOG" 2>&1 </dev/null &

RUN_PID=$!
echo "$RUN_PID" > "$PIDFILE"
disown "$RUN_PID"

echo "PID: $RUN_PID"
echo "LOG: $LOG"
