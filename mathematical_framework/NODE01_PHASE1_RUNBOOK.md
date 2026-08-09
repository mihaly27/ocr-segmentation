# IPS framework — Phase 1 calibration on Revival27 Node01

This is the first empirical run required by the bounded-adaptation paper. It does **not** yet produce B0–B3 Results. It calibrates and verifies the quantities that must be frozen before the final comparison: finite-difference step sizes, diagonal sensitivity metric `W`, reference latency, and repeated-run trace-hash determinism.

## 1. Environment

Run on the same `r27node01` host used for the prior IPS experiment. Use the existing repository environment and Tesseract installation; do not change OCR backend or preprocessing defaults for Phase 1.

```bash
cd /path/to/ocr-segmentation/ips_single_image
source .venv/bin/activate   # if that is how the prior experiment was run
python --version
tesseract --version
```

The paper's platform record is: AMD Ryzen Threadripper PRO 3945WX (12c/24t), 128 GB RAM, Ubuntu 24.04.4 LTS; the host also has 4× RTX 4000 Ada GPUs, but the default Tesseract IPS run is CPU-oriented.

## 2. Locate the existing synthetic manifest

Use the same manifest/dataset generated for the 5,000-sample / 25,000-run ablation. The calibration script accepts CSV, JSON, or JSONL and tries to infer the image and GT columns. It also uses the perturbation column when present to construct an approximately balanced deterministic sample.

## 3. Dry run (20 samples)

Copy `ips_phase1_calibration.py` anywhere on Node01, then run:

```bash
python /path/to/ips_phase1_calibration.py \
  --repo /path/to/ocr-segmentation/ips_single_image \
  --manifest /path/to/synthetic/manifest.csv \
  --dataset-root /path/to/synthetic \
  --output phase1_smoke \
  --n 20 \
  --repeat-n 10 \
  --workers 8
```

Expected outputs:

- `phase1_smoke/phase1_summary.json`
- `phase1_smoke/phase1_runs.csv`
- `phase1_smoke/selected_samples.json`
- `phase1_smoke/configs/*.yaml`
- `phase1_smoke/failures.json` only if any artifact execution failed.

## 4. Calibration run (recommended first full pass: 200 samples)

```bash
python /path/to/ips_phase1_calibration.py \
  --repo /path/to/ocr-segmentation/ips_single_image \
  --manifest /path/to/synthetic/manifest.csv \
  --dataset-root /path/to/synthetic \
  --output phase1_200 \
  --n 200 \
  --repeat-n 50 \
  --workers 8 \
  --timeout 180
```

The run evaluates the reference state and ± one step for these six actual repository coordinates:

- `cut.min_rel_width_for_split` (reference 1.6)
- `cut.max_column_sum_quantile` (reference 0.20)
- `scoring.w_overlap` (reference 10)
- `scoring.w_prior` (reference 2)
- `scoring.rho_max` (reference 0.75)
- `scoring.blocking_gap_ratio` (reference 0.05)

Default Phase-1 increments are modest engineering probes, not paper constants. They can be overridden via `--steps-json` after the smoke run.

## 5. What to send back

Upload **only** `phase1_summary.json` and `phase1_runs.csv` (plus `failures.json` if created). From those we can freeze:

1. the empirical diagonal `W`;
2. whether any coordinate is effectively inactive and should be removed;
3. suitable hard ranges / next finite-difference increments;
4. repeated-run trace-hash determinism;
5. reference mean/p95 latency;
6. the next calibration for the stable-region thresholds and trust radius `delta`.

After that, the final B0/B1/B2/B3/B3-I/B3-R0 trajectory runner can be fixed without tuning on the final evaluation data.
