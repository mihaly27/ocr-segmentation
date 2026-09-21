# Completing the first Heimdall release

This module lives inside `mihaly27/ocr-segmentation`. The parent repository
already has releases for other studies; the Heimdall supplement has no assigned
release version or Zenodo DOI yet. The intended first supplement version is
`1.0.0`, to be assigned when the archive is finalized.

## Current evidence

The original OCR log, recovered configuration and dictionary, aggregate audit
of the supplied dataset lists/review tables, and hashes of the external dataset
and checkpoint/optimizer files are documented under [`training/`](../training/README.md). The author-reported
duplicate removal is recorded. The historical validation membership and loader
fallback, exact training-source revision, and mapping from checkpoint to
deployed export remain unverified. Archiving this scoped supplement does not
require claiming a complete neural-pipeline reproduction.

The Git module includes the log, configuration, dictionary and aggregate audit.
The dataset list/review contents, training images, model weights and optimizer
state remain external. If the checkpoint is added as a separate
Zenodo file, verify it against the recorded hash and update the archive's
contents/access description. Do not imply that a digest is a public download.

## Archive preparation

1. Finalize the included materials, authors/contributors, access and reuse
   terms. The parent repository has a research-use `LICENSE`; confirm the
   intended archive terms and include the applicable license text in the
   standalone package. Preserve third-party terms.
2. Complete the module's `CITATION.cff` with the actual version and publication
   date. Its repository and module URLs are already present. Do not reuse the
   DOI of another study or insert a guessed DOI.
3. From `heimdall-replay-study/`, run
   `python3 scripts/verify_included_tables.py`. Verify the log and recovered
   files against `training/manifest.json`; refresh `SHA256SUMS.json` for every distributed
   module file except that checksum manifest itself.
4. Commit the finalized module. An optional identifying Git tag can be named
   `heimdall-replay-v1.0.0`; a tag identifies a commit of the entire repository,
   while the curated archive below contains only this module.
5. Create a **separate manual Zenodo upload** for the Heimdall supplement. Upload
   a ZIP containing this finalized module, describe it as supplementary data
   and analysis code, and record the full source commit plus the module URL.
   The automatic GitHub–Zenodo integration archives repository releases and
   does not create an independent record for this subdirectory.
6. Reserve the new record's DOI in the Zenodo draft if it is needed in files
   before publication. A reserved DOI is not registered until publication.
   If citation files change after reservation, refresh their checksums and
   the final commit/archive reference before publishing.
7. Publish the completed record and put its actual version-specific DOI in
   the manuscript and module citation metadata. Subsequent metadata-only
   updates should be distinguishable from changes to experimental evidence.

The bibliographic starting point is the title and author order already in
[`CITATION.cff`](../CITATION.cff), with resource type **Dataset** for the
supplementary evidence and accompanying analysis code. Record the exact
archive version and the actual publication date when assigned.

Official references:

- [Zenodo manual upload and DOI reservation](https://help.zenodo.org/docs/deposit/create-new-upload/)
- [Zenodo license fields, including custom licenses](https://help.zenodo.org/docs/deposit/describe-records/licenses/)
- [Zenodo GitHub integration](https://help.zenodo.org/docs/github/enable-repository/)
- [GitHub releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
