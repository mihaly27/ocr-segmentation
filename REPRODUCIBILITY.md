# Reproducibility record: bounded adaptation V2/V2.1

This file maps the manuscript evidence to source revisions, environments,
frozen inputs, random seeds, and compact release artifacts. Large generated
corpora and raw per-sample outputs are distributed as release evidence bundles,
not duplicated in Git.

## Canonical revisions

| Role | Git revision |
|---|---|
| V2/V2.1 evidence and hardware checkpoint | `faca0c392caa5b731172928a7594fe089c57a28f` |
| Research branch after figure-sample extraction helper | `496c96450a8cda4fef710089c27eba4c52cba292` |
| Archival release tag to create after merge | `bounded-adaptation-v2.1.0` |

The release tag, rather than a moving branch name, is the canonical software
identifier after the research branch has been merged into `main`.

## Software environment

- Ubuntu 24.04.4 LTS; Linux kernel 6.8.0-111-generic; glibc 2.39.
- Python 3.12.3; Tesseract 5.3.4.
- NumPy 2.4.4; OpenCV-Python 4.13.0.92; Pillow 12.2.0;
  pytesseract 0.3.13; PyYAML 6.0.3; packaging 26.1.
- Exact Python pins: `requirements-node01.lock`.
- Captured environment record:
  `mathematical_framework/recalibration_2026/environment_lock.json`.
- Compute platform: `docs/hardware/HARDWARE.md`.

Create the matching Python environment with:

```bash
python3.12 -m venv ips_single_image/.venv
source ips_single_image/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-node01.lock
tesseract --version
```

## Frozen protocols and random seeds

| Layer | Protocol/lock | Seeds |
|---|---|---|
| V2 calibration | `mathematical_framework/recalibration_2026_v2/protocol.yaml`; `v2_input_lock.json` | touch 86082601-86082640; broken 86082641-86082680; combo 86082681-86082720 |
| V2 confirmation | same V2 protocol and lock | 86082721-86082725 |
| V2.1 activation/carryover | `mathematical_framework/recalibration_2026_v2/challenges/activation_carryover_v1/protocol.yaml`; `input_lock.json` | 86082801-86082818 |

The V2 protocol fixes the active coordinates, reference state, scaling matrix
`D`, weighted metric `W`, hard bounds, 27-state proposal grid, radius grid,
selection rule, non-inferiority margins, partitions, and stop rules. The lock
files record SHA-256 values for the protocol, generator, pipeline configuration,
historical engine, and inherited W-calibration inputs.

## Calibration and evidence artifacts

The repository already tracks the historical Phase-1 CSV/JSON files under:

- `mathematical_framework/phase1_200/`
- `mathematical_framework/phase1_switchscan200/`

The V2 input lock also depends on compact files under ignored `outputs/`
directories. Before tagging the archival release, run
`scripts/prepare_bounded_adaptation_v2_1_release.sh` on Node01. It copies the
following small, result-defining artifacts into the tracked release directory:

- independently recalibrated `w_calibration.json`;
- W-calibration Phase-1 `selected_samples.json`;
- V2 `selected_delta.json` and `delta_calibration_summary.csv`;
- V2 preflight, grid-check, confirmation-plan, and confirmation-audit JSON;
- V2.1 challenge audit, freeze summary, and manifest;
- an exact software/environment record and a SHA-256 release manifest.

The script stops rather than creating an incomplete release if any required file
is absent. Large frozen evidence bundles should be attached to the GitHub release
for tag `bounded-adaptation-v2.1.0`; their filenames and SHA-256 values should be
copied into `release/bounded_adaptation_v2_1/EVIDENCE_BUNDLES.sha256`.

## Verification

```bash
python -m unittest discover -s mathematical_framework/recalibration_2026_v2/tests -v
python -m compileall -q \
  mathematical_framework/recalibration_2026_v2/scripts \
  mathematical_framework/recalibration_2026_v2/tests

sha256sum -c mathematical_framework/recalibration_2026_v2/PACKAGE_CONTENTS.sha256
sha256sum -c release/bounded_adaptation_v2_1/ARTIFACTS.sha256
```

The full execution commands are in the V2 and V2.1 runbooks. A successful hash
check establishes file identity; the runbooks, environment pins, seeds, input
locks, and compact calibration artifacts establish the information needed to
repeat the calibration logic.
