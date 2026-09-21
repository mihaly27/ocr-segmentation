# OCR training evidence

`train.log` is the original, unmodified PaddleOCR log supplied on 21 September
2026. `manifest.json` records its SHA-256 and a descriptive extraction with
source-line references. No training, validation or model export was rerun here.

## Recorded run

| Item | Recorded value |
|---|---|
| Log date | 28 August 2026; timezone unspecified |
| Framework | PaddlePaddle 3.3.0, `gpu:0` |
| Model | `PP-OCRv5_mobile_rec`; `SVTR_LCNet`; `PPLCNetV3`, scale 0.95 |
| Initialization | `PP-OCRv5_mobile_rec_pretrained.pdparams` |
| Completed training | 50 epochs; final global step 750 |
| Optimizer | Adam; configured learning rate 0.0005; Cosine schedule; 5 warmup epochs |
| Loader | Configured batch size 128; training uses `MultiScaleSampler`, `fix_bs=False` |
| Recognition image shape | `[3, 48, 320]` |
| Best logged validation | `acc=0.6157024538965928` (61.570245%); epoch 49 |
| Best logged `norm_edit_dis` | `0.9233930242858713` |
| Last-epoch validation | `acc=0.6074379914281821`; epoch 50 |
| Best checkpoint prefix | `./output/hungarian_plate_rec/best_accuracy` |

The configuration is printed inside the log. The exact training YAML,
character dictionary bytes and PaddleOCR training-source revision are not
included. The log identifies the device index, but not the GPU model; the
later inference-platform snapshot does not establish the training hardware.

## Duration and repeated starts

The authors report approximately two hours for the training work. The file
contains four initialization sequences, so it should not be described as a
single uninterrupted two-hour run.

| Sequence | Log lines | First / last timestamp | Maximum logged epoch |
|---|---|---|---:|
| 1 | 1–126 | 16:08:35 / 16:08:36 | No epoch logged |
| 2 | 127–274 | 16:15:38 / 16:21:58 | 6 |
| 3 | 275–442 | 16:23:40 / 16:27:38 | 3 |
| 4 | 443–1163 | 16:31:53 / 17:55:48 | 50 |

The complete log spans **1 h 47 min 13 s**. The final, completed sequence
spans **1 h 23 min 55 s**, including its logged initialization, evaluation and
checkpoint activity. Neither number is a measurement of GPU kernel time.

## Validation provenance

The log reports the same missing input on 53 occasions: three in sequence 3
and 50 in the completed sequence, immediately before its validation results:

`ocr_dataset/unlabeled/plate_20260827_124744_831607_conf0.665.jpg`

Training continues and reaches epoch 50. The log alone does not establish
whether the loader skipped the missing sample, substituted another sample,
or used another fallback. The exact historical `train_list.txt` and
`val_list.txt`, their hashes, and the training-source error handling are needed
to determine the effective validation membership. The 61.57% figure is
therefore a **logged component validation result**, not independently verified
camera-replay accuracy.

The completed sequence also records four pretrained-head shape mismatch
warnings (CTC 38 versus 18385 outputs; NRTR 42 versus 18389), followed by
successful pretrained loading. The original messages are retained in the log.

## Checkpoint and runtime linkage

The [runtime model manifest](../evidence/runtime_snapshot/models/model_hashes.json)
already identifies the deployed OCR export, including `inference.pdiparams`
with SHA-256
`464c97b7fbd6958a96aa11d9affc6992c88b40a48e1844c46105f8b951d57a57`.

The supplied log has no checkpoint hash or export command linking that export
to the epoch-49 `best_accuracy` checkpoint. Record the selected checkpoint,
its hash and the export/deployment mapping when recovered. Training checkpoint
and inference-export files need not have equal hashes; the transformation
between them is the missing provenance link.

The 19 September snapshot's original missing-manifest notes remain historical
records. This addition documents the newly recovered log separately.
