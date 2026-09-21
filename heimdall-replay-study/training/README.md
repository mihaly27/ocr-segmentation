# OCR training evidence

The original `train.log`, recovered `config.yml` and character dictionary, and
five supplied dataset text files are preserved byte-for-byte. They were supplied
on 21 September 2026. [`manifest.json`](manifest.json) records their hashes,
the log extraction, the dataset audit and the hashes of the external model files.
No training, validation or model export was rerun for this package.

## Included and externally retained files

| Path | Contents |
|---|---|
| [`train.log`](train.log) | Original log, including repeated starts and missing-image errors |
| [`config.yml`](config.yml) | Recovered training configuration; original machine paths retained |
| [`ppocrv5_dict.txt`](ppocrv5_dict.txt) | 37 characters: digits, uppercase Latin letters and hyphen |
| [`dataset/train_list.txt`](dataset/train_list.txt) | 1,373 current training entries |
| [`dataset/val_list.txt`](dataset/val_list.txt) | 241 current validation entries |
| [`dataset/labels.txt`](dataset/labels.txt) | 1,615 label entries, including the subsequently reported deleted sample |
| [`dataset/labels_review.tsv`](dataset/labels_review.tsv) | Original review table: 2,534 data rows |
| [`dataset/labels_review_ocr_corrected.tsv`](dataset/labels_review_ocr_corrected.tsv) | Corrected review table: 2,533 data rows, including 1,614 approved entries |

The supplied `ocr_extract.zip` also contains `best_model/model.pdparams`
(68,648,052 bytes) and `best_model/model.pdopt` (121,453,158 bytes). These large
files and the ZIP are retained outside Git; their sizes and SHA-256 digests are
recorded in the manifest. No public download location has been assigned.
Training images are not included in this module.

## Recorded run

| Item | Recorded value |
|---|---|
| Log date | 28 August 2026; timezone unspecified |
| Framework | PaddlePaddle 3.3.0, `gpu:0` |
| Model | `PP-OCRv5_mobile_rec`; `SVTR_LCNet`; `PPLCNetV3`, scale 0.95 |
| Initialization | `PP-OCRv5_mobile_rec_pretrained.pdparams` |
| Completed training | 50 epochs; 15 training steps per epoch; final global step 750 |
| Optimizer | Adam; configured learning rate 0.0005; Cosine schedule; 5 warmup epochs |
| Loader | Configured batch size 128; training uses `MultiScaleSampler`, `fix_bs=False` |
| Recognition image shape | `[3, 48, 320]` |
| Evaluation / spaces | `eval_batch_step=[0, 15]`; `use_space_char=False` |
| Best logged validation | `acc=0.6157024538965928` (61.570245%); epoch 49 |
| Best logged `norm_edit_dis` | `0.9233930242858713` |
| Last-epoch validation | `acc=0.6074379914281821`; epoch 50 |
| Best checkpoint prefix | `./output/hungarian_plate_rec/best_accuracy` |

The recovered configuration agrees with the settings printed for the completed
session except for `Global.distributed`: the YAML contains `true`, while the
log records `False`. The logged value describes that run. The reason for this
difference is not established; the original YAML has not been edited to hide it.
The exact PaddleOCR training-source revision and training GPU model remain
unrecorded; the later inference-platform snapshot does not establish them.

## Duration and repeated starts

The authors report approximately two hours for the training work. The file
contains four initialization sequences, rather than one uninterrupted run.

| Sequence | Log lines | First / last timestamp | Maximum logged epoch |
|---|---|---|---:|
| 1 | 1–126 | 16:08:35 / 16:08:36 | No epoch logged |
| 2 | 127–274 | 16:15:38 / 16:21:58 | 6 |
| 3 | 275–442 | 16:23:40 / 16:27:38 | 3 |
| 4 | 443–1163 | 16:31:53 / 17:55:48 | 50 |

The complete log spans **1 h 47 min 13 s**. The final, completed sequence
spans **1 h 23 min 55 s**, including its logged initialization, evaluation and
checkpoint activity. Neither number is a measurement of GPU kernel time.

## Dataset and duplicate-removal provenance

The supplied current lists contain **1,373 training and 241 validation entries**.
There are no repeated image paths within either list and no image-path overlap
between the lists. Nine literal plate labels occur in both splits, so these
checks do not establish independence at the plate or vehicle level.

All 1,614 split entries match `labels.txt`. That file has one additional row:

`ocr_dataset/unlabeled/plate_20260827_124744_831607_conf0.665.jpg`

The author reports that a colleague considered this sample a duplicate, so it
was deleted. The duplicate counterpart, criterion and deletion time were not
supplied. This is the reported reason for removal, not an independently verified
image-duplicate finding. The current train and validation lists omit the row;
the original label file is retained as supplied.

The same path appears in 53 missing-image errors in the log: three in sequence 3
and 50 in the completed sequence, before its validation results. Training
continues to epoch 50. The current list hashes do not establish the exact lists
used at those evaluations. Without the actual training loader and metric code,
the fallback behavior, effective validation membership and effect on the metric
remain unknown. The **61.57% is a logged OCR component validation result**, not
an independently reproduced result or camera-replay recognition accuracy.

One training label differs literally from the corrected review table:
`KKT617` in the split versus `KKT 617` in the review. The path is recorded in the
manifest. All validation labels match the corrected table. The review files also
retain one nonstandard status in the older table and three missing statuses in
the corrected table. These are preserved source inconsistencies; no automatic
label or row cleanup was applied.

The completed sequence records four pretrained-head shape mismatch warnings
(CTC 38 versus 18385 outputs; NRTR 42 versus 18389), followed by successful
pretrained loading. The original messages remain in the log.

## Checkpoint and runtime linkage

The recovered `ppocrv5_dict.txt` has exactly the SHA-256 recorded for deployed
`ppocr_keys.txt`, and its character order matches the runtime inference YAML.
The [runtime model manifest](../evidence/runtime_snapshot/models/model_hashes.json)
identifies the deployed export, including `inference.pdiparams` with SHA-256
`464c97b7fbd6958a96aa11d9affc6992c88b40a48e1844c46105f8b951d57a57`.

The recovered `best_model/model.pdparams` has SHA-256
`8999b66925c0e1457fa6f755c9a1f39da162d937e9636db05aad8ad3e2885dec`.
Static inspection of its serialized metadata finds a CTC output dimension of
38. The accompanying optimizer's scheduler records `last_epoch=735`, consistent
with 49 epochs times 15 training steps per epoch. These observations support
compatibility with the logged run, but do not prove that the supplied file is
the logged `best_accuracy` checkpoint or the source of the deployed export.
The binary files were inspected as pickle opcodes, without unpickling or running
the model.

No checkpoint `.states` file, export command or equivalent deployment mapping
was supplied. The remaining checkpoint link is **which saved checkpoint produced
the deployed inference files**. Training and inference-file hashes are expected
to identify different artifacts; equality of those hashes is not required.

The 19 September snapshot's missing-manifest notes remain historical records.
This directory documents the subsequently recovered material separately.
