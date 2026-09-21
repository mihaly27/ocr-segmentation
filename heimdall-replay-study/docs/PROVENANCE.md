# Provenance of the repository snapshot

The initial files were selected from `Informatics2026_Heimdall_Supplement.zip`, the reviewer supplement assembled on 20 September 2026 for the six-page manuscript. Camera images, crops, observation tables, reference worksheet, recorded audit reports, scripts and the runtime snapshot retain their original bytes. The source archive and retained-file digests are listed in `source_package_manifest.json`.

The repository excludes internal reviewer responses, editorial TODOs, historical README copies and bibliography-maintenance notes. The full editorial history remains in the separate manuscript package. Machine-readable source manifests and research audits remain available under their original paths.

The 19 September runtime snapshot supplies model and source digests, tracker YAML, OCR inference configuration, package versions and visible hardware details. It does not prove historical checkpoint/runtime identity with R20–R23 or resolve inherited detector settings. The original snapshot's notes about missing training manifests describe the collection state at that time and must not be silently rewritten after later logs are added.

The eight confident human-reference cases come from a joint review. No independent blinded ratings or complete traffic inventory are claimed. The numerical results concern a retrospective readable subset and original application lifetimes, which are not deduplicated physical vehicle passages.

Recorded strings and images remain unchanged. This repository organization does not anonymize them, establish public-redistribution rights, or extend permissions over the proprietary recognition engine. Version 1.0.0 retains the parent repository's research-use terms in the included `LICENSE`; third-party materials remain subject to their respective terms.

Git line-ending conversion is disabled for this snapshot so that Windows checkouts do not invalidate recorded file digests. Later training files should also be retained in their original form and described through a separate manifest.

## Training log added on 21 September 2026

`training/train.log` preserves the supplied file byte-for-byte. Its SHA-256, logged configuration, session boundaries, validation metrics and source-line references are recorded in `training/manifest.json`. The approximately two-hour duration is an author report; the precise timestamp spans are calculated from the log, whose timezone is unspecified.

This addition supplies the source for the previously reported 61.57% OCR component validation figure. It does not establish the original validation membership or its error handling: the completed session logs the same missing-image error 50 times. It also does not prove that the best checkpoint was exported into the files captured by the September runtime snapshot. Those historical snapshot files and their recorded hashes remain unchanged.

## Configuration, checkpoint metadata and dataset files recovered on 21 September 2026

The subsequent `ocr_extract.zip` contains a training YAML, character dictionary,
model parameters and optimizer state. The YAML and dictionary are included
unchanged under `training/`; the binary files remain outside Git with their
sizes and hashes in the training manifest. The five separately supplied
dataset text/TSV files are retained unchanged under `training/dataset/`.

The recovered dictionary matches the runtime dictionary digest and character
order. The configuration matches the final completed log sequence except for
the stored/logged `distributed` flag. Static optimizer metadata is consistent
with 49 epochs of 15 steps. These comparisons establish compatibility of
specific artifacts, not an independently verified export/deployment history.

The author reports that a colleague considered the missing sample a duplicate
and it was deleted. This statement explains the reported removal; no duplicate
counterpart or deletion timestamp was supplied. The current validation list
omits the sample while the original label file retains it. The historical
validation membership, loader fallback and metric impact remain unverified.
The training summary records split overlap and review-label discrepancies.

This recovery does not alter the original runtime snapshot, replay data,
source-package manifest or training log. It does not assign a release version,
DOI or new reuse license.

## Version 1.0.0 archive preparation

The module now carries version `1.0.0` in its citation metadata and includes an
unchanged copy of the parent repository's `LICENSE`. These packaging changes
do not change any experimental evidence or establish the missing historical
validation/export links. No Zenodo DOI is inserted before one has actually
been reserved or assigned. A standalone archive must identify its exact source
commit and retain the module's checksum manifest.
