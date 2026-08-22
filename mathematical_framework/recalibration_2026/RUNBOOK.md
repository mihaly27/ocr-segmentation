# Node01 recalibration and confirmation runbook

## 0. Create the branch and activate the captured environment

From the repository root:

```bash
cd ~/ocr-segmentation
git status --short
git switch -c research/bounded-adaptation-recalibration-2026 \
  5641bb3dce90696072bf54f7afb62aa29e492190
source ips_single_image/.venv/bin/activate
```

Unpack the overlay into the repository root, then commit it before any research
execution:

```bash
git add requirements-node01.lock mathematical_framework/recalibration_2026
git commit -m "add preregistered bounded-adaptation recalibration workflow"
```

Set short path variables for the commands below:

```bash
R=~/ocr-segmentation
Q=$R/mathematical_framework/recalibration_2026
P=$Q/protocol.yaml
S=$Q/scripts
C=$Q/corpora
O=$Q/outputs
```

Verify the exact virtualenv, repository commit, clean tree and Tesseract state:

```bash
python "$S/verify_protocol.py" \
  --repo-root "$R" \
  --protocol "$P" \
  --environment-lock "$Q/environment_lock.json" \
  --output "$O/preflight.json"
```

`preflight.json` must contain `"ok": true`. Do not install or upgrade packages
after this point.

## 1. Generate only the new W-calibration corpus

The new corpus uses generator seed `86082301`, not the historical dataset.

```bash
python "$S/prepare_synthetic_corpora.py" \
  --protocol "$P" \
  --generator "$R/synthetic-generator/synthetic_plate_generator_fixed_v2.py" \
  --output-root "$C" \
  --mode w
```

Run the two preregistered scans on the identical 300-sample selection:

```bash
python "$R/mathematical_framework/ips_phase1_calibration.py" \
  --repo "$R/ips_single_image" \
  --manifest "$C/w_calibration/annotations.jsonl" \
  --dataset-root "$C/w_calibration" \
  --output "$O/w_phase1_local" \
  --n 300 --repeat-n 60 --workers 8 --timeout 180 \
  --scales 1,2,4

python "$R/mathematical_framework/ips_phase1_calibration.py" \
  --repo "$R/ips_single_image" \
  --manifest "$C/w_calibration/annotations.jsonl" \
  --dataset-root "$C/w_calibration" \
  --output "$O/w_phase1_switch" \
  --n 300 --repeat-n 0 --workers 8 --timeout 180 \
  --scales 8,16
```

Both runs must have no `failures.json`, and both `selected_samples.json` files
must describe the identical ordered sample set. Construct the new metric:

```bash
python "$S/aggregate_w.py" \
  --protocol "$P" \
  --local-summary "$O/w_phase1_local/phase1_summary.json" \
  --switch-summary "$O/w_phase1_switch/phase1_summary.json" \
  --local-selected "$O/w_phase1_local/selected_samples.json" \
  --switch-selected "$O/w_phase1_switch/selected_samples.json" \
  --output "$O/w_calibration.json"
```

Stop if any frozen active coordinate has zero sensitivity. Do not promote a
historically inactive diagnostic coordinate on the basis of these new data.

## 2. Generate the delta-calibration corpora

Do not generate the confirmation corpora yet.

This creates 60 independent targeted corpora (20 touch, 20 broken and 20
combo), each with its own generator seed and a single non-clean drift block,
plus five independent negative controls. Each targeted corpus has only 400
images; its stream is `clean -> declared condition -> clean`. Thus no two
binomial event units share a stateful trajectory.

```bash
python "$S/prepare_synthetic_corpora.py" \
  --protocol "$P" \
  --generator "$R/synthetic-generator/synthetic_plate_generator_fixed_v2.py" \
  --output-root "$C" \
  --mode delta
```

First render a non-executing plan:

```bash
python "$S/run_delta_grid.py" \
  --repo-root "$R" --protocol "$P" \
  --w-json "$O/w_calibration.json" \
  --phase1-selected "$O/w_phase1_local/selected_samples.json" \
  --corpora-root "$C" --output-root "$O/delta_grid"
```

Then run a three-point integration slice on one trajectory from each primary
condition:

```bash
python "$S/run_delta_grid.py" \
  --repo-root "$R" --protocol "$P" \
  --w-json "$O/w_calibration.json" \
  --phase1-selected "$O/w_phase1_local/selected_samples.json" \
  --corpora-root "$C" --output-root "$O/delta_grid" \
  --only-seed 86082311 --only-seed 86082331 --only-seed 86082351 \
  --only-delta 0 --only-delta 6 --only-delta 12 \
  --workers 8 --timeout 180 --max-new-runs 9 --execute
```

Inspect the nine `delta_harm_events.csv` files. Required smoke conditions:

- 15 evaluation rows per block;
- `dbox_available=true` in each harm summary;
- no committed operational-gate violation;
- identical `partition_sha256.txt` for the three radii within each seed;
- no artifact failure or semantic mismatch on a committed candidate.

If the slice is clean, resume the complete 25 × 65 grid. Existing completed
runs and the global content-addressed artifact cache are reused:

```bash
python "$S/run_delta_grid.py" \
  --repo-root "$R" --protocol "$P" \
  --w-json "$O/w_calibration.json" \
  --phase1-selected "$O/w_phase1_local/selected_samples.json" \
  --corpora-root "$C" --output-root "$O/delta_grid" \
  --workers 8 --timeout 180 --execute
```

Use `--max-new-runs N`, `--only-seed` and `--only-delta` to execute this in
bounded batches. A radius is always replayed statefully from the start of its
trajectory; outputs from one radius are never truncated post hoc.

## 3. Select and freeze delta

After all 1,625 harm CSVs exist:

```bash
mapfile -d '' HARM_FILES < <(
  find "$O/delta_grid" -name delta_harm_events.csv -print0 | sort -z
)

python "$S/select_delta.py" \
  --protocol "$P" \
  --w-json "$O/w_calibration.json" \
  --harm-csv "${HARM_FILES[@]}" \
  --output-dir "$O/delta_selection"
```

The decision is automatic: the largest grid value with at least 60 informative
events, exact one-sided 95% harm upper bound at most 5%, and at least 20%
non-zero commit coverage. If no positive radius qualifies, do not modify the
rule or inspect confirmation data to relax it.

Freeze the completed calibration evidence, excluding caches:

```bash
python "$S/freeze_artifacts.py" --root "$O" \
  --include w_calibration.json w_phase1_local w_phase1_switch \
  delta_grid delta_selection
```

Commit the protocol, code and small freeze metadata. Large result files may be
kept in the research archive instead of Git.

## 4. Only now generate and run confirmation

```bash
python "$S/prepare_synthetic_corpora.py" \
  --protocol "$P" \
  --generator "$R/synthetic-generator/synthetic_plate_generator_fixed_v2.py" \
  --output-root "$C" \
  --mode confirmation \
  --selected-delta "$O/delta_selection/selected_delta.json"

python "$S/run_confirmation.py" \
  --repo-root "$R" --protocol "$P" \
  --w-json "$O/w_calibration.json" \
  --selected-delta "$O/delta_selection/selected_delta.json" \
  --phase1-selected "$O/w_phase1_local/selected_samples.json" \
  --corpora-root "$C" --output-root "$O/confirmation"
```

Review the plan and repeat with `--execute`. The five confirmation seeds run all
six controllers and are untouched by radius selection.

## 5. Gate and safety challenge

Run the real-output 27-state map on at least the first confirmation trajectory:

```bash
T=$O/confirmation/trajectory_86082421

python "$S/run_gate_stress.py" \
  --repo-root "$R" --protocol "$P" \
  --run-dir "$T/confirmatory_main" \
  --manifest "$T/composite_manifest.jsonl" \
  --output "$T/gate_stress.csv" \
  --workers 8 --timeout 180

python "$S/run_safety_challenge.py" \
  --repo-root "$R" \
  --reference-calibration "$T/confirmatory_main/reference_calibration.json" \
  --output "$T/safety_challenge.csv"
```

`run_gate_stress.py` answers whether the real gate is selective and whether its
rejections align with delayed ground truth. `run_safety_challenge.py` separately
verifies every threshold branch deterministically; it is not presented as
real-data evidence.

## 6. Stop rules

Stop and preserve all artifacts without tuning if:

- the environment or Git preflight fails;
- either Phase-1 scan fails or selects a different sample list;
- an active W sensitivity is zero;
- fewer than 60 informative delta events are obtained;
- only `delta_W=0` qualifies;
- `d_box` cannot be reconstructed from `annotations.jsonl`;
- a committed candidate violates its frozen operational gate;
- confirmation contradicts the calibration result.

These are scientific outcomes, not software errors to be hidden by changing
seeds or thresholds.

## 7. Local tests

```bash
python -m unittest discover -s "$Q/tests" -v
python -m compileall -q "$Q/scripts" "$Q/tests"
```
