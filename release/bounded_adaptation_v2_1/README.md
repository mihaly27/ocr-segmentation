# Bounded adaptation V2/V2.1 archival release

Run `scripts/prepare_bounded_adaptation_v2_1_release.sh` on Node01 before
creating the release commit and tag. The script copies compact result-defining
artifacts from ignored output directories into this directory, records the exact
software environment and Git provenance, and creates `ARTIFACTS.sha256`.

Large corpora and per-sample outputs remain outside Git and should be attached
to the GitHub release as frozen evidence bundles. Record their SHA-256 values in
`EVIDENCE_BUNDLES.sha256` before publishing the release.
