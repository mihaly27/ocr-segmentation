# OCR Segmentation Research Module

This public research repository contains deterministic OCR-segmentation code,
synthetic data generation, batch evaluation, and the bounded-adaptation
experiments used in related publications. The visual inputs are synthetic and
provide controlled ground truth without using real vehicle identifiers or
personal data.

## Repository map

| Path | Purpose |
|---|---|
| `ips_single_image/` | Minimal inverse-packing segmentation and OCR reference implementation |
| `synthetic-generator/` | Seeded synthetic plate, mask, box, and perturbation generation |
| `batch-runner/` | Batch and ablation runners used by the SISY workflow |
| `mathematical_framework/` | Pilot, calibration, confirmation, gate-stress, and carryover experiments |
| `docs/hardware/` | Experimental compute-platform specification |
| `requirements-node01.lock` | Exact Python package versions used on Node01 |
| `REPRODUCIBILITY.md` | Commit, seed, environment, artifact, and release map |

## Bounded-adaptation evidence

The current parameter-governor study separates three evidence layers:

1. **V2 calibration:** 120 disjoint trajectories and 25 radii, giving 3,000
   stateful runs.
2. **V2 confirmation:** five new trajectories and six frozen controllers.
3. **V2.1 challenge:** 18 new trajectories testing mechanism activation and
   directed carryover across `touch`, `broken`, and `combo` drift.

The frozen protocols, input locks, tests, runbooks, and hash manifests are under
`mathematical_framework/recalibration_2026_v2/`. Generated corpora and large raw
outputs are not duplicated in Git. Compact calibration and audit artifacts are
attached to the tagged archival release as described in
`REPRODUCIBILITY.md`.

## Quick start

```bash
git clone https://github.com/mihaly27/ocr-segmentation.git
cd ocr-segmentation

python3.12 -m venv ips_single_image/.venv
source ips_single_image/.venv/bin/activate
python -m pip install -r requirements-node01.lock

python ips_single_image/main.py \
  --image ips_single_image/test-plates/plate-CJU-784.png \
  --outdir /tmp/ips-example \
  --gt CJU784
```

For the complete V2 and V2.1 procedures, use:

- `mathematical_framework/recalibration_2026_v2/RUNBOOK.md`
- `mathematical_framework/recalibration_2026_v2/challenges/activation_carryover_v1/RUNBOOK_NODE01.md`

## Execution platform

Unless an experiment directory states otherwise, the experiments were executed
on an AMD Ryzen Threadripper PRO 3945WX workstation with 128 GB RAM and Ubuntu
24.04.4 LTS. Four NVIDIA RTX 4000 Ada Generation GPUs were installed, but the
bounded-adaptation V2/V2.1 OpenCV-NumPy-Tesseract workflow used eight CPU
workers and did not use the GPUs. Full details are in
`docs/hardware/HARDWARE.md`.

## Citation and license

Machine-readable citation metadata are provided in `CITATION.cff` and
`codemeta.json`. When the associated journal article receives a DOI, its record
should be added as the preferred citation without changing the software title
or release identity.

Copyright (c) 2025-2026 Mihály Szabó. The repository is publicly readable, but
reuse is governed by the research-use terms in `LICENSE`; public availability
does not by itself grant an open-source license.
