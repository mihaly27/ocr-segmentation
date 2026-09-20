# Completing the first release

The repository currently has no release tag, assigned version, publication date, or Zenodo DOI. An initial Git commit can precede the first citable release.

1. Add the recovered training logs and configuration. Document their hashes and links to the train/validation manifests, selected checkpoints and deployed model exports. Preserve any unresolved historical identities as limitations.
2. Finalize the materials intended for public distribution and their reuse licenses. Add the appropriate license file(s); do not apply one blanket license to third-party or proprietary components.
3. Add the actual repository URL and the intended release version/date to `CITATION.cff`. Do not insert a guessed DOI.
4. Run `python3 scripts/verify_included_tables.py`. If the numerical evidence changes, document the changes and update dependent tables and figures.
5. Refresh `SHA256SUMS.json` after the files are finalized. It covers every distributed repository file except itself, Git internals and ignored local outputs.
6. Commit the completed snapshot, connect the repository to Zenodo, and publish the planned `v1.0.0` GitHub release. An ordinary commit or push is sufficient for the current working state; the release is the separate archival step.
7. Record the actual version-specific Zenodo DOI in the manuscript and repository. GitHub automatically provides source ZIP and tar archives for release tags. A separate curated supplement ZIP may also be attached as a release asset if needed by the submission process.

Official references:

- [GitHub releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
- [GitHub citation files](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-citation-files)
- [Zenodo GitHub integration](https://help.zenodo.org/docs/github/enable-repository/)

Publishing a release through GitHub–Zenodo creates an archive of that tagged repository state. If citation metadata is updated afterward with the newly assigned DOI, document that as a metadata update rather than silently changing the recorded experimental evidence.
