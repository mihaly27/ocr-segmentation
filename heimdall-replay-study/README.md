# Heimdall Camera Replay Study

Supplementary data and analysis code for **Bounded Threshold Updates for Through-Glass License Plate Recognition: A Camera-Replay Study**, by Mihály Szabó, Attila Kovari, and Gábor Kertész.

This repository contains the evidence and calculations supporting a one-camera replay case study. It reconstructs fixed OCR confidence gates and fixed/direct/step-bounded threshold trajectories over a frozen observation stream, including weighted consensus and comparison with a small joint human reference.

**Current status:** preparation for the first release. Training logs and their links to the evaluated checkpoints are still being assembled. No release version, Zenodo DOI, or reuse license has been assigned to this working snapshot.

## Run the included check

From the repository root:

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
| `figures/` | Camera images, crops, vector chart and manuscript diagram fragment |
| `docs/REPRODUCTION.md` | Scope, dependencies and extended reproduction commands |
| `docs/PROVENANCE.md` | Evidence preservation and limitations |
| `docs/RELEASE.md` | Steps to complete the first citable release |
| `CITATION.cff` | Citation metadata for this research package |
| `SHA256SUMS.json` | Checksums for the current repository files |

The existing `notes/` paths are retained because the audit scripts use them. This directory now contains machine-readable research evidence, without internal reviewer correspondence or editorial task histories.

## Reproduction scope

The included check recomputes the constant gates and F/A/G variants, their admissions and weighted winners, all 121 lifetime outcomes, the step bound, the human-reference summaries, and the original worksheet checksum.

Full source videos, original prediction-run archives, model weights, the proprietary CV engine, and training images/manifests are not included. The package therefore does not rerun neural inference or independently verify all upstream detections, video-to-vehicle links, or historical checkpoint identity. Extended scripts remain available for use with the original external inputs; see [reproduction instructions](docs/REPRODUCTION.md).

## Citation and release status

Citation metadata is in `CITATION.cff`. The first completed release will receive its version and archive DOI after the training evidence is integrated. Until then, refer to a specific Git commit when identifying this working snapshot. Add the actual repository URL and version-specific DOI when they are available; no placeholder identifier has been inserted.

The authors still need to select the reuse license and finalize the access arrangements for vehicle identifiers/images before the public archived release. This packaging step neither anonymizes those materials nor assigns new permissions.
