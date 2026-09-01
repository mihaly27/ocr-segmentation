# Node01 bounded-adaptation recalibration V2

This protocol is a new, fixed-sample calibration. It does not modify or pool
the 1,625 V1 runs. V1 remains an integrity-verified, inconclusive pilot with 45
informative events per radius. V2 reuses only the independently recalibrated
W, locked by SHA-256 before any V2 corpus is generated.

## 0. Repository checkpoint and V2 branch

Complete the V1 virtual-environment cleanup and push it before branching:

```bash
cd "$HOME/ocr-segmentation"
git status --short
git switch -c research/bounded-adaptation-recalibration-v2
```

Unpack the V2 overlay into the repository root, then commit it:

```bash
sha256sum -c mathematical_framework/recalibration_2026_v2/PACKAGE_CONTENTS.sha256

git add mathematical_framework/recalibration_2026_v2
git commit -m "add preregistered bounded-adaptation recalibration V2"
git push -u origin HEAD
```

Set paths. V1 and V2 must remain separate:

```bash
R=$HOME/ocr-segmentation
Q1=$R/mathematical_framework/recalibration_2026
Q2=$R/mathematical_framework/recalibration_2026_v2
P2=$Q2/protocol.yaml
S2=$Q2/scripts
C2=$Q2/corpora
O2=$Q2/outputs
L2=$Q2/v2_input_lock.json
PY=$R/ips_single_image/.venv/bin/python
GEN=$R/synthetic-generator/synthetic_plate_generator_fixed_v2.py
W1=$Q1/outputs/w_calibration.json
PHASE1=$Q1/outputs/w_phase1_local/selected_samples.json
W1DATA=$Q1/corpora/w_calibration
```

## 1. Lock every V2 input before generation

The working tree must be clean and the current branch must be the V2 branch.
The lock verifies the complete frozen V1 manifest, checks that V1 ended with 45
informative events and no selected delta, and hashes the V2 code, historical
engine, generator, W and Phase-1 inputs.

```bash
"$PY" "$S2/lock_v2_inputs.py" \
  --repo-root "$R" \
  --v1-root "$Q1" \
  --v2-root "$Q2" \
  --generator "$GEN" \
  --output "$L2"

git add "$L2"
git commit -m "freeze bounded-adaptation V2 inputs"
git push

"$PY" "$S2/verify_v2_inputs.py" \
  --repo-root "$R" \
  --protocol "$P2" \
  --input-lock "$L2" \
  --output "$O2/preflight.json"
```

Stop unless `preflight.json` contains `"ok": true`.

## 2. Generate 120 new disjoint calibration corpora

The fixed V2 design uses 40 touch, 40 broken and 40 combo seeds. Each corpus
contains 800 images split evenly between clean and its declared condition.

Review the plan:

```bash
"$PY" "$S2/prepare_synthetic_corpora.py" \
  --protocol "$P2" --input-lock "$L2" \
  --generator "$GEN" --output-root "$C2" \
  --mode delta --dry-run
```

Then generate under nohup:

```bash
mkdir -p "$O2/logs"
TS=$(date -u +%Y%m%dT%H%M%SZ)
LOG=$O2/logs/generate_v2_delta_${TS}.log

nohup "$PY" "$S2/prepare_synthetic_corpora.py" \
  --protocol "$P2" --input-lock "$L2" \
  --generator "$GEN" --output-root "$C2" \
  --mode delta \
  >"$LOG" 2>&1 </dev/null &

echo $! > "$O2/generate_v2_delta.pid"
echo "LOG: $LOG"
```

## 3. Plan and run the 15/15/60 V2 delta grid

Render the complete 3,000-run plan without execution:

```bash
"$PY" "$S2/run_delta_grid.py" \
  --repo-root "$R" --protocol "$P2" --input-lock "$L2" \
  --w-json "$W1" --phase1-selected "$PHASE1" \
  --w-dataset-root "$W1DATA" \
  --corpora-root "$C2" --output-root "$O2/delta_grid"
```

Run a three-condition, three-radius smoke slice:

```bash
"$PY" "$S2/run_delta_grid.py" \
  --repo-root "$R" --protocol "$P2" --input-lock "$L2" \
  --w-json "$W1" --phase1-selected "$PHASE1" \
  --w-dataset-root "$W1DATA" \
  --corpora-root "$C2" --output-root "$O2/delta_grid" \
  --only-seed 86082601 --only-seed 86082641 --only-seed 86082681 \
  --only-delta 0 --only-delta 6 --only-delta 12 \
  --workers 8 --timeout 180 --max-new-runs 9 --execute
```

Every smoke harm summary must contain:

```text
evaluation_n_per_block: 60
dbox_available: true
```

Start or resume the complete grid under nohup:

```bash
mkdir -p "$O2/logs"
TS=$(date -u +%Y%m%dT%H%M%SZ)
LOG=$O2/logs/run_v2_delta_grid_${TS}.log

nohup "$PY" "$S2/run_delta_grid.py" \
  --repo-root "$R" --protocol "$P2" --input-lock "$L2" \
  --w-json "$W1" --phase1-selected "$PHASE1" \
  --w-dataset-root "$W1DATA" \
  --corpora-root "$C2" --output-root "$O2/delta_grid" \
  --workers 8 --timeout 180 --execute \
  >"$LOG" 2>&1 </dev/null &

echo $! > "$O2/run_v2_delta_grid.pid"
echo "LOG: $LOG"
```

Progress:

```bash
"$PY" "$S2/progress_v2.py" \
  --protocol "$P2" --grid-root "$O2/delta_grid"
```

The runner is resumable. It skips only a delta directory containing the
experiment summary, atomic harm CSV and atomic harm summary.

## 4. Validate, select and freeze V2 delta

After all 3,000 runs:

```bash
"$PY" "$S2/check_v2_grid.py" \
  --protocol "$P2" --input-lock "$L2" \
  --grid-root "$O2/delta_grid" \
  --output "$O2/v2_grid_check.json"
```

Stop unless the check reports `"ok": true`, 3,000/3,000 for every file class,
60 evaluation samples, zero committed gate violations and no missing d_box.

```bash
mapfile -d '' HARM_FILES < <(
  find "$O2/delta_grid" -name delta_harm_events.csv -print0 | sort -z
)

"$PY" "$S2/select_delta.py" \
  --protocol "$P2" --input-lock "$L2" \
  --w-json "$W1" \
  --harm-csv "${HARM_FILES[@]}" \
  --output-dir "$O2/delta_selection"

"$PY" "$S2/show_v2_selection.py" \
  --selection-dir "$O2/delta_selection"
```

The selector is unchanged in substance: largest eligible grid value, at least
60 independent informative events, exact one-sided 95% harm upper bound at
most 5%, and non-zero commit coverage at least 20%.

Freeze the V2 calibration evidence, excluding caches:

```bash
"$PY" "$S2/freeze_artifacts.py" --root "$O2" \
  --include preflight.json delta_grid v2_grid_check.json delta_selection
```

## 5. Confirmation remains blocked until a positive V2 delta exists

Do not generate confirmation data before V2 selection. If and only if
`selected_delta.json` reports `positive_delta_selected`, generate the five new
confirmation corpora. No V1 delta result may be used as a confirmation input.

```bash
"$PY" "$S2/prepare_synthetic_corpora.py" \
  --protocol "$P2" --input-lock "$L2" \
  --generator "$GEN" --output-root "$C2" \
  --mode confirmation \
  --selected-delta "$O2/delta_selection/selected_delta.json"

"$PY" "$S2/run_confirmation.py" \
  --repo-root "$R" --protocol "$P2" --input-lock "$L2" \
  --w-json "$W1" \
  --selected-delta "$O2/delta_selection/selected_delta.json" \
  --phase1-selected "$PHASE1" --w-dataset-root "$W1DATA" \
  --corpora-root "$C2" --output-root "$O2/confirmation"
```

Review `confirmation_plan.json`, then rerun the last command with `--execute`.
The five confirmatory trajectories use new seeds, a 10,000-image corpus each,
the same 15/15/60 partitions and all six frozen controllers.

After confirmation, run gate stress and the deterministic safety challenge on
the first trajectory:

```bash
T=$O2/confirmation/trajectory_86082721

"$PY" "$S2/run_gate_stress.py" \
  --repo-root "$R" --protocol "$P2" --input-lock "$L2" \
  --run-dir "$T/confirmatory_main" \
  --manifest "$T/composite_manifest.jsonl" \
  --output "$T/gate_stress.csv" \
  --workers 8 --timeout 180

"$PY" "$S2/run_safety_challenge.py" \
  --repo-root "$R" \
  --reference-calibration "$T/confirmatory_main/reference_calibration.json" \
  --output "$T/safety_challenge.csv"
```

## 6. Tests

```bash
"$PY" -m unittest discover -s "$Q2/tests" -v
"$PY" -m compileall -q "$S2" "$Q2/tests"
```
