# Reproduction instructions

## Included evidence check

Run `python3 scripts/verify_included_tables.py` from the `heimdall-replay-study/` directory, or use `py -3` on Windows. All relative commands below use that module directory as their working directory. The script uses only the standard library. The recorded expected output is `notes/INCLUDED_TABLES_CHECK.json`.

The check reconstructs five constant gates and F/A/G, verifies their memberships and weighted winners, compares all recorded lifetime summaries and human-reference counters, and checks the original worksheet and protocol digests. R21–R23/F/A/G reference outcomes are linked back to reconstructed winners. R20 reference checks use its recorded case-output table, because its full observation stream is not included in that table.

The data rows and thresholds are reused from the original audit; this is not a new camera experiment or a fresh independent annotation. The source-frame links remain an assisted visual association recorded in `evidence/manual_r20/visual_mapping.json`.

## Redraw the vector chart

Install the optional plotting dependency and use an output directory outside the frozen evidence:

```bash
python3 -m pip install -r requirements-optional.txt
python3 scripts/plot_controlled_replay.py --notes notes/runs20_23 --output output/controlled_replay
```

The command writes a PDF and PNG. It uses the same observations and trajectories as the included check. `figures/method_diagram.tex` is a manuscript TikZ fragment; its styles and colors are defined in the separate Overleaf project.

## Audits requiring original external archives

Place `prediction-run-20.zip` through `prediction-run-23.zip` in a local `external-inputs/` directory. That directory is ignored by Git. These archives are not distributed with this repository.

With ffprobe available on PATH:

```bash
python3 scripts/audit_runs20_23.py --input-dir external-inputs --output-dir output/runs20_23 --protocol notes/controlled_replay_protocol.json
python3 scripts/audit_manual_r20.py --input-dir external-inputs --output-dir output/manual_r20
```

The manual audit uses the included worksheet and visual mapping. It does not create new human labels. Compare generated outputs with the recorded files under `notes/`; inspect any difference rather than overwriting the frozen evidence.

For source-frame extraction, use the original R20 `video/source.mp4`, with FFmpeg and Pillow available:

```bash
python3 scripts/render_manual_regions.py --source external-inputs/R20/video/source.mp4 --output-dir output/manual_regions --figure-dir output/figures
```

The earlier replay scripts (`audit_replays.py`, `audit_evidence.py`, `extract_replay_crops.py`) require their corresponding original recordings and exports. Run each script with `--help` for its documented arguments. These inputs are external; the scripts were not rerun from raw source archives when this Git-ready package was assembled.

## Included training evidence

The original PaddleOCR log, recovered `training/config.yml` and dictionary, and five dataset list/review files are included with a [descriptive summary](../training/README.md) and [manifest](../training/manifest.json). The completed session reaches 50 epochs and reports its best validation accuracy at epoch 49. The configuration agrees with the final logged settings except for `Global.distributed` (stored `true`, logged `False`). Original machine-specific paths are retained; the YAML is evidence, not a ready-to-run configuration for this repository.

The current lists contain 1,373 training and 241 validation entries. The author reports that the sample missing in the log was deleted as a duplicate. The supplied lists omit it, but do not establish the exact historical validation membership or loader fallback. Nine literal labels occur in both splits, although image paths do not overlap. The log's validation metric has not been independently reproduced.

The supplied checkpoint and optimizer now have recorded hashes, and the dictionary matches the runtime snapshot. Large weights and raw training images remain outside Git. The mapping from the supplied checkpoint to the deployed OCR export remains unverified; no public weight-download location or exact training-source revision has been supplied. The included table-verification script checks the derived replay evidence; it does not rerun training or establish model identity.

## Recorded protocol

The protocol uses a threshold grid of 0.30, 0.50 and 0.80, a maximum step of 0.30, a 5-second update interval and 10-second proposal intervals. Its historical `weight` metadata field is not read by the execution script. The protocol is kept byte-for-byte to preserve its recorded digest; the redundant W parameter was removed from the manuscript.
