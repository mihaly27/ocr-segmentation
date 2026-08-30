# Node01 runbook

Run from the repository root. The commands are intentionally shown as single lines.

```bash
cd "$HOME/ocr-segmentation"
```

Set paths:

```bash
R="$HOME/ocr-segmentation"; V1="$R/mathematical_framework/recalibration_2026"; V2="$R/mathematical_framework/recalibration_2026_v2"; Q="$V2/challenges/activation_carryover_v1"; P="$Q/protocol.yaml"; S="$Q/scripts"; L="$Q/input_lock.json"; C="$Q/corpora"; O="$Q/outputs"; PY="$R/ips_single_image/.venv/bin/python"; GEN="$R/synthetic-generator/synthetic_plate_generator_fixed_v2.py"
```

Lock inputs before generation:

```bash
"$PY" "$S/lock_inputs.py" --repo-root "$R" --generator "$GEN" --protocol "$P" --output "$L"
```

Dry-run and generate the 18 corpora:

```bash
"$PY" "$S/generate_corpora.py" --protocol "$P" --input-lock "$L" --generator "$GEN" --output-root "$C" --python "$PY" --dry-run
```

```bash
mkdir -p "$O/logs"; TS=$(date -u +%Y%m%dT%H%M%SZ); LOG="$O/logs/generate_${TS}.log"; nohup "$PY" "$S/generate_corpora.py" --protocol "$P" --input-lock "$L" --generator "$GEN" --output-root "$C" --python "$PY" >"$LOG" 2>&1 </dev/null & echo $! >"$O/generate.pid"; echo "PID=$! LOG=$LOG"
```

Plan all trajectories:

```bash
"$PY" "$S/run_all.py" --repo-root "$R" --protocol "$P" --input-lock "$L" --phase1-selected "$V1/outputs/w_phase1_local/selected_samples.json" --w-dataset-root "$V1/corpora/w_calibration" --corpora-root "$C" --output-root "$O/challenge" --workers 8 --timeout 180
```

Run one-seed smoke test first:

```bash
"$PY" "$S/run_all.py" --repo-root "$R" --protocol "$P" --input-lock "$L" --phase1-selected "$V1/outputs/w_phase1_local/selected_samples.json" --w-dataset-root "$V1/corpora/w_calibration" --corpora-root "$C" --output-root "$O/challenge" --only-seed 86082801 --workers 8 --timeout 180 --execute
```

The smoke summary must contain counts 7 blocks, 42 controller events, 42 window
rows, 10 carryover rows, and 81 stress rows. Then start/resume all 18:

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ); LOG="$O/logs/run_${TS}.log"; nohup "$PY" "$S/run_all.py" --repo-root "$R" --protocol "$P" --input-lock "$L" --phase1-selected "$V1/outputs/w_phase1_local/selected_samples.json" --w-dataset-root "$V1/corpora/w_calibration" --corpora-root "$C" --output-root "$O/challenge" --workers 8 --timeout 180 --execute >"$LOG" 2>&1 </dev/null & echo $! >"$O/run.pid"; echo "PID=$! LOG=$LOG"
```

Progress:

```bash
"$PY" "$S/progress.py" --protocol "$P" --output-root "$O/challenge" --pid-file "$O/run.pid"
```

Final audit:

```bash
"$PY" "$S/audit_challenge.py" --protocol "$P" --input-lock "$L" --output-root "$O/challenge" --output "$O/challenge_audit.json"
```

Freeze only after the audit is technically green:

```bash
"$PY" "$S/freeze_results.py" --root "$O"
```

Verify the frozen manifest:

```bash
cd "$O" && sha256sum -c MANIFEST.sha256
```
