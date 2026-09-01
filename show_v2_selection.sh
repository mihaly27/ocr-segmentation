cd "$HOME/ocr-segmentation"

export R="$HOME/ocr-segmentation"
export Q1="$R/mathematical_framework/recalibration_2026"
export Q2="$R/mathematical_framework/recalibration_2026_v2"
export P2="$Q2/protocol.yaml"
export S2="$Q2/scripts"
export O2="$Q2/outputs"
export L2="$Q2/v2_input_lock.json"
export PY="$R/ips_single_image/.venv/bin/python"
export W1="$Q1/outputs/w_calibration.json"

printf 'PY=%s\nS2=%s\nO2=%s\n' "$PY" "$S2" "$O2"

mkdir -p "$O2/logs"

mapfile -d '' HARM_FILES < <(
  find "$O2/delta_grid" \
    -name delta_harm_events.csv \
    -print0 | sort -z
)

echo "harm_files: ${#HARM_FILES[@]}"

"$PY" "$S2/select_delta.py" \
  --protocol "$P2" \
  --input-lock "$L2" \
  --w-json "$W1" \
  --harm-csv "${HARM_FILES[@]}" \
  --output-dir "$O2/delta_selection" \
  >"$O2/logs/v2_select_delta.log" 2>&1

SELECT_RC=$?
echo "selector_exit_code: $SELECT_RC"

if [[ "$SELECT_RC" -eq 0 || "$SELECT_RC" -eq 3 ]]; then
  "$PY" "$S2/show_v2_selection.py" \
    --selection-dir "$O2/delta_selection"
else
  tail -n 80 "$O2/logs/v2_select_delta.log"
fi
