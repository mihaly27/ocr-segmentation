# Node01 — Main B0–B3 IPS Experiment

From the repository root:

```bash
cd ~/ocr-segmentation
```

Copy `ips_main_experiment.py` into:

```text
~/ocr-segmentation/mathematical_framework/
```

## 1. Verify the Phase-1 development selection exists

The main experiment must exclude the 200 samples used for calibration.

Expected path from the previous run:

```bash
ls -lh mathematical_framework/phase1_v2_200/selected_samples.json
```

If the directory name differs:

```bash
find mathematical_framework -name selected_samples.json -print
```

Use the `selected_samples.json` belonging to the successful n=200 Phase-1 v2 run.

## 2. Main experiment

```bash
python3 mathematical_framework/ips_main_experiment.py \
  --repo ips_single_image \
  --manifest synthetic-generator/data/synthetic_plates_sisy2026/manifest.csv \
  --dataset-root synthetic-generator/data/synthetic_plates_sisy2026 \
  --dev-selected mathematical_framework/phase1_v2_200/selected_samples.json \
  --output mathematical_framework/main_experiment \
  --reference-clean-n 100 \
  --block-size 45 \
  --gate-repeat-n 2 \
  --workers 8 \
  --timeout 180
```

The script checks that the repository reference configuration still contains:

- `cut.min_rel_width_for_split = 1.6`
- `scoring.w_prior = 2.0`
- `scoring.blocking_gap_ratio = 0.05`

and aborts if those frozen starting values changed.

## 3. What is frozen

Active state:

\[
\Theta_A=(r_{\rm split},w_{\rm prior},g_{\rm block})
\]

with hard ranges:

- `r_split`: [1.2, 2.0]
- `w_prior`: [0.0, 4.0]
- `g_block`: [0.0, 0.13]

Calibration:

```text
W = diag(
  1.10,
  0.8036784889951276,
  1.901416931827527
)

delta_W = 7.530441831891154
delta_I = volume-matched automatically
```

The inactive Phase-1 coordinates remain fixed at the repository reference values.

## 4. Ground truth policy

The runner does **not** pass `--gt` to `ips_single_image/main.py`.

Ground truth is used by the outer experiment script only for final evaluation
of the disjoint evaluation third of each block. Proposal and gate decisions use
only observable image/trace/runtime information.

## 5. Controlled stream

The final stream is deterministic:

```text
clean
blur
clean
glare
clean
threshold
clean
compression
clean
perspective
clean
touch
clean
broken
clean
combo
clean
```

Each 45-image block is split into:

```text
15 proposal
15 gate
15 evaluation
```

A separate 100-image clean set is used to freeze PSI reference bins and the
drift threshold. The 200 Phase-1 calibration samples are excluded from this
stream.

## 6. Controllers

- `B0`: fixed
- `B1`: raw proposal / no trust-region bound
- `B2`: W-bounded / no gate
- `B3`: W-bounded + label-free gate + reference fail-safe
- `B3-I`: identity metric with volume-matched radius
- `B3-R0`: B3 without recovery rollback/fail-safe

## 7. Outputs

Expected output directory:

```text
mathematical_framework/main_experiment/
```

Important files:

```text
frozen_experiment_config.json
frozen_experiment_config.sha256
reference_calibration.json
partition_map.json
partition_sha256.txt
controller_events.csv
window_results.csv
sample_results.csv
paired_comparisons.csv
summary.json
```

The `cache/` directory stores parsed deterministic artifact executions, so a
restart can reuse already completed runs.

## 8. After completion

Package only the result files first:

```bash
cd ~/ocr-segmentation/mathematical_framework

zip -j main_experiment_results.zip \
  main_experiment/frozen_experiment_config.json \
  main_experiment/frozen_experiment_config.sha256 \
  main_experiment/reference_calibration.json \
  main_experiment/partition_map.json \
  main_experiment/partition_sha256.txt \
  main_experiment/controller_events.csv \
  main_experiment/window_results.csv \
  main_experiment/sample_results.csv \
  main_experiment/paired_comparisons.csv \
  main_experiment/summary.json
```

Upload `main_experiment_results.zip`.

There is no need to upload the full cache unless a result needs forensic
inspection.
