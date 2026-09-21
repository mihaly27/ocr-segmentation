# Heimdall Camera Replay Study

Supplementary data and analysis code for **Bounded Threshold Updates for Through-Glass License Plate Recognition: A Camera-Replay Study**, by Mihály Szabó, Attila Kovari, and Gábor Kertész.

This module contains the evidence and calculations supporting a one-camera replay case study. It reconstructs fixed OCR confidence gates and fixed/direct/step-bounded threshold trajectories over a frozen observation stream, including weighted consensus and comparison with a small joint human reference.

**Current status:** preparation for the first Heimdall release. The original PaddleOCR log, recovered configuration and dictionary, current dataset lists and review tables, and hashes of the external checkpoint files are documented under [`training/`](training/README.md). The historical validation membership and checkpoint-to-export link remain unverified. No Heimdall release version or Zenodo DOI has been assigned; archive-specific access and reuse terms remain to be finalized.

## Run the included check

From the `heimdall-replay-study/` directory:

```bash
python3 scripts/verify_included_tables.py
```

On Windows, if Python is invoked through the launcher:

```powershell
py -3 scripts/verify_included_tables.py
```

The core check uses only the Python standard library. It should end with `"result": "PASS"`. It reads the included files and prints its report without modifying the evidence.

| Calculation | Accepted observations | Nonempty lifetime outputs |
|---|---:|---:|
| Constant gate 0.30 | 193 | 20 |
| Constant gate 0.46 | 192 | 20 |
| Constant gate 0.77 | 160 | 19 |
| Calculated constant gate 0.50 | 191 | 20 |
| Calculated constant gate 0.80 | 156 | 19 |
| F fixed threshold | 193 | 20 |
| A direct switching | 164 | 19 |
| G bounded updates | 166 | 19 |

The calculation uses 319 logged observations and 121 application lifetimes. A and G produce identical final strings. Six of eight confident human-reference cases have at least one matching replay output; 10 of 13 linked replay lifetime outputs match. These are descriptive, conditional reference results, not general recognition accuracy or independent held-out performance.

## Repository contents

| Path | Contents |
|---|---|
| `scripts/` | Table verification, original export audits, plotting and crop extraction |
| `notes/runs20_23/` | Frozen observation, threshold, lifetime and decision tables with recorded audits |
| `notes/manual_r20/` | Reference categories, linked case outcomes and winning regions |
| `notes/controlled_replay_protocol.json` | Recorded 10-second proposal intervals and 5-second update opportunities |
| `evidence/manual_r20/` | Original joint-reference worksheet and visual mappings |
| `evidence/runtime_snapshot/` | Model/source digests, configurations and the 19 September environment snapshot |
| `evidence/ui/` | Interface screenshots underlying the source-path audit |
| [`training/`](training/README.md) | Original PaddleOCR log, recovered YAML and dictionary, dataset lists and review tables, checkpoint digests, metrics and provenance |
| `figures/` | Camera images, crops, vector chart and manuscript diagram fragment |
| `docs/REPRODUCTION.md` | Scope, dependencies and extended reproduction commands |
| `docs/PROVENANCE.md` | Evidence preservation and limitations |
| `docs/RELEASE.md` | Steps to complete the first citable release |
| `CITATION.cff` | Citation metadata for this research package |
| `SHA256SUMS.json` | Checksums for the current repository files |

The existing `notes/` paths are retained because the audit scripts use them. This directory now contains machine-readable research evidence, without internal reviewer correspondence or editorial task histories.

## Training evidence

The unmodified [`train.log`](training/train.log) records four initialization sequences on 28 August 2026. The final session completed 50 epochs with PaddlePaddle 3.3.0 on `gpu:0`, using `PP-OCRv5_mobile_rec` (`SVTR_LCNet`, `PPLCNetV3`). Its best logged validation accuracy is 61.570245% at epoch 49. These are training-time component metrics.

The authors report approximately two hours for the training work. The complete log spans 1 h 47 min 13 s; the final completed session spans 1 h 23 min 55 s. The current lists contain 1,373 training and 241 validation entries. The author reports that the sample repeatedly missing during logged validation was deleted as a duplicate; it is absent from the current splits but remains in `labels.txt`. These files do not establish the effective historical validation membership.

The recovered dictionary exactly matches the runtime dictionary digest. The supplied checkpoint and optimizer have recorded hashes; static optimizer metadata is consistent with the logged best epoch. The checkpoint-to-deployed-export mapping remains unverified. See the [training summary](training/README.md) and [manifest](training/manifest.json) for the configuration comparison, dataset audit and limits of these links.

## Reproduction scope

The included check recomputes the constant gates and F/A/G variants, their admissions and weighted winners, all 121 lifetime outcomes, the step bound, the human-reference summaries, and the original worksheet checksum.

Full source videos, original prediction-run archives, model weights, the proprietary CV engine, and training images are not included. Current dataset lists are included, with their historical limitations documented above. The package therefore does not rerun neural inference or independently verify all upstream detections, video-to-vehicle links, or historical checkpoint identity. Extended scripts remain available for use with the original external inputs; see [reproduction instructions](docs/REPRODUCTION.md).

## Citation and release status

Citation metadata is in `CITATION.cff`. The recovered training evidence has been integrated. The first completed Heimdall release will receive its version and separate Zenodo DOI after its scope, provenance limitations and access/reuse terms are finalized. Until then, refer to a specific Git commit and this module path. The planned Zenodo record will archive this module separately from the other studies in `ocr-segmentation`; see the [release instructions](docs/RELEASE.md).

The authors still need to select the reuse license and finalize the access arrangements for vehicle identifiers/images before the public archived release. This packaging step neither anonymizes those materials nor assigns new permissions.
