# Heimdall version 1.0.0 and Zenodo

Supplement version `1.0.0` is prepared for a separate manual Zenodo deposit.
It is a scoped archive of `heimdall-replay-study/` within
`mihaly27/ocr-segmentation`. The Zenodo record has not yet been published and
no DOI has been assigned. Do not reuse another study's DOI.

## Included evidence and scope

The archive includes derived replay observations and decisions, analysis and
verification scripts, camera illustrations, the joint human-reference worksheet,
the runtime snapshot, and the recovered OCR training log, configuration,
dictionary, dataset lists and review tables. Model/checkpoint digests and the
author-reported duplicate removal are documented under `training/`.

The current splits contain 1,373 training and 241 validation entries. Their
exact historical use, validation loader fallback, training-source revision and
checkpoint-to-deployed-export mapping remain unverified. These limitations are
part of the archive description. The package supports checking the included
derived evidence; it does not claim complete neural-pipeline reproduction.

Raw training images, model weights, optimizer state, the proprietary CV engine,
original prediction-run archives and complete source videos remain external.
No public model-download location is claimed. If additional model files are
distributed in a later version, verify their hashes and update the contents
and access description for that version.

## Deposit metadata

| Field | Value |
|---|---|
| Title | Heimdall Camera-Replay Study: Supplementary Data and Analysis Code |
| Resource type | Dataset |
| Version | 1.0.0 |
| Creators, in order | Mihály Szabó; Attila Kovari; Gábor Kertész |
| Language | English |
| License | Custom: OCR Segmentation Research-Use License |
| File visibility | Public |

Use the full text of the included [`LICENSE`](../LICENSE), which is copied
unchanged from the parent repository. Choose **Add custom** in the Zenodo
license field and enter that title and the source license URL. Replace the
form's default CC-BY entry: the existing research-use terms have not been
changed to CC-BY. Preserve third-party terms.

Use the actual publication date for the record. Optional affiliations and
ORCIDs must be entered from verified author information; they are not inferred
from names. Record the full source commit and the commit-specific module URL
in the description or related-work metadata.

## Package verification and publication

1. From this module, run `python3 scripts/verify_included_tables.py`. Verify
   `SHA256SUMS.json`, which covers every module file except itself, and check
   the original training files against `training/manifest.json`.
2. Build a ZIP of this module from the exact prepared source commit. Include
   `LICENSE`, `CITATION.cff` and the checksum manifest. An archive-level
   provenance file may identify the source commit without changing the frozen
   module files.
3. Create a **new manual Zenodo upload** for this supplement and upload the
   curated ZIP. The automatic GitHub integration acts on repository releases,
   not independently on this subdirectory. A Git tag, if used, identifies the
   whole repository; the uploaded ZIP remains scoped to this module.
4. Enter the metadata above and an accurate description of the scope and
   limitations. Reserve the new record's DOI if needed before publication;
   a reserved DOI is registered only when the record is published.
5. Preview the file, authors, version, license and description, then publish
   the record. Record the actual version-specific DOI in the manuscript and
   repository citation metadata. A post-publication DOI-only repository
   update is distinct from the archived source commit.

Official references:

- [Zenodo upload and DOI reservation](https://help.zenodo.org/docs/deposit/create-new-upload/)
- [Zenodo custom licenses](https://help.zenodo.org/docs/deposit/describe-records/licenses/)
- [Zenodo GitHub integration](https://help.zenodo.org/docs/github/enable-repository/)
