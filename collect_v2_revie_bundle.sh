#!/usr/bin/env bash
set -Eeuo pipefail

# Collect the compact, frozen V2 evidence needed for manuscript review.
# Usage:
#   ./collect_v2_review_bundle.sh [REPO_ROOT] [OUTPUT_ZIP]
#
# Defaults on Node01:
#   REPO_ROOT=/home/mszabo/ocr-segmentation
#   OUTPUT_ZIP=/home/mszabo/v2_review_bundle_<UTC timestamp>.zip

REPO_ROOT="${1:-/home/mszabo/ocr-segmentation}"
UTC_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_ZIP="${2:-/home/mszabo/v2_review_bundle_${UTC_STAMP}.zip}"

V1_REL="mathematical_framework/recalibration_2026"
V2_REL="mathematical_framework/recalibration_2026_v2"
V2_OUT_REL="${V2_REL}/outputs"
CONF_REL="${V2_OUT_REL}/confirmation"

if [[ ! -d "$REPO_ROOT/.git" ]]; then
    echo "ERROR: not an ocr-segmentation Git repository: $REPO_ROOT" >&2
    exit 2
fi

if [[ -e "$OUTPUT_ZIP" ]]; then
    echo "ERROR: output already exists; refusing to overwrite: $OUTPUT_ZIP" >&2
    exit 2
fi

mkdir -p "$(dirname "$OUTPUT_ZIP")"

STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/v2-review-bundle.XXXXXX")"
cleanup() {
    if [[ -n "${STAGING_DIR:-}" && -d "$STAGING_DIR" ]]; then
        rm -rf -- "$STAGING_DIR"
    fi
}
trap cleanup EXIT

BUNDLE_ROOT="$STAGING_DIR/repository"
mkdir -p "$BUNDLE_ROOT"

declare -a MISSING_REQUIRED=()
declare -A COPIED=()

copy_relative() {
    local relative_path="$1"
    local source_path="$REPO_ROOT/$relative_path"
    local target_path="$BUNDLE_ROOT/$relative_path"

    if [[ -n "${COPIED[$relative_path]:-}" ]]; then
        return 0
    fi
    mkdir -p "$(dirname "$target_path")"
    cp -p -- "$source_path" "$target_path"
    COPIED["$relative_path"]=1
}

require_file() {
    local relative_path="$1"
    if [[ ! -f "$REPO_ROOT/$relative_path" ]]; then
        MISSING_REQUIRED+=("$relative_path")
        return 0
    fi
    copy_relative "$relative_path"
}

optional_file() {
    local relative_path="$1"
    if [[ -f "$REPO_ROOT/$relative_path" ]]; then
        copy_relative "$relative_path"
    fi
}

copy_small_tree() {
    local relative_root="$1"
    if [[ ! -d "$REPO_ROOT/$relative_root" ]]; then
        return 0
    fi

    while IFS= read -r -d '' source_path; do
        local relative_path="${source_path#"$REPO_ROOT/"}"
        copy_relative "$relative_path"
    done < <(
        find "$REPO_ROOT/$relative_root" \
            \( -type d \( -name '__pycache__' -o -name '_tmp_runs' \
                           -o -name 'cache' -o -name 'cache_shared' \
                           -o -name 'cache_shared_global' \) -prune \) -o \
            \( -type f \
               \( -name '*.json' -o -name '*.jsonl' -o -name '*.csv' \
                  -o -name '*.yaml' -o -name '*.yml' -o -name '*.txt' \
                  -o -name '*.sha256' -o -name '*.py' -o -name '*.md' \) \
               -print0 \)
    )
}

# Frozen protocol, input lock, calibration selection, and final evidence freeze.
require_file "$V2_REL/protocol.yaml"
require_file "$V2_REL/v2_input_lock.json"
require_file "$V2_OUT_REL/delta_selection/selected_delta.json"
require_file "$V2_OUT_REL/delta_selection/delta_calibration_summary.csv"
require_file "$V2_OUT_REL/delta_selection/delta_calibration_by_condition.csv"
require_file "$V2_OUT_REL/v2_grid_check.json"
require_file "$V2_OUT_REL/freeze_summary.json"
require_file "$V2_OUT_REL/MANIFEST.sha256"
require_file "$CONF_REL/confirmation_audit.json"

# Independently calibrated W and the frozen Phase-1 selection used by V2.
require_file "$V1_REL/outputs/w_calibration.json"
require_file "$V1_REL/outputs/w_phase1_local/selected_samples.json"

# Five disjoint confirmatory trajectories.
for seed in 86082721 86082722 86082723 86082724 86082725; do
    trajectory_rel="$CONF_REL/trajectory_${seed}"
    run_rel="$trajectory_rel/confirmatory_main"

    require_file "$trajectory_rel/composite_manifest.jsonl"
    require_file "$trajectory_rel/dev_selected.json"
    require_file "$run_rel/summary.json"
    require_file "$run_rel/partition_map.json"
    require_file "$run_rel/frozen_experiment_config.json"
    require_file "$run_rel/recalibration_injection.json"
    require_file "$run_rel/reference_calibration.json"
    require_file "$run_rel/controller_events.csv"
    require_file "$run_rel/window_results.csv"
    require_file "$run_rel/sample_results.csv"
    require_file "$run_rel/paired_comparisons.csv"
done

# Gate selectivity and deterministic safety-branch challenge.
FIRST_TRAJECTORY_REL="$CONF_REL/trajectory_86082721"
require_file "$FIRST_TRAJECTORY_REL/gate_stress.csv"
require_file "$FIRST_TRAJECTORY_REL/gate_stress.summary.json"
require_file "$FIRST_TRAJECTORY_REL/safety_challenge.csv"
require_file "$FIRST_TRAJECTORY_REL/safety_challenge.summary.json"

if (( ${#MISSING_REQUIRED[@]} > 0 )); then
    echo "ERROR: required review files are missing:" >&2
    printf '  - %s\n' "${MISSING_REQUIRED[@]}" >&2
    echo "No ZIP was created." >&2
    exit 3
fi

# Include all other compact tabular/JSON confirmation and selection outputs,
# together with the exact V2 scripts/tests and the historical execution engine.
copy_small_tree "$V2_OUT_REL/delta_selection"
copy_small_tree "$CONF_REL"
copy_small_tree "$V2_REL/scripts"
copy_small_tree "$V2_REL/tests"

optional_file "$V2_REL/RUNBOOK.md"
optional_file "$V2_REL/V2_DESIGN_RATIONALE_HU.md"
optional_file "$V2_REL/PACKAGE_CONTENTS.sha256"
optional_file "mathematical_framework/ips_main_experiment.py"
optional_file "synthetic-generator/synthetic_plate_generator_fixed_v2.py"
optional_file "audit_v2_confirmation.py"
optional_file "show_v2_selection.sh"
optional_file "check_v2_radius.sh"
optional_file "check_manifest.sh"

{
    echo "bundle_version=v2_manuscript_review_bundle_v1"
    echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "source_repo=$REPO_ROOT"
    echo "git_branch=$(git -C "$REPO_ROOT" branch --show-current)"
    echo "git_commit=$(git -C "$REPO_ROOT" rev-parse HEAD)"
    echo "git_status_begin"
    git -C "$REPO_ROOT" status --short
    echo "git_status_end"
    echo "final_manifest_sha256=$(sha256sum "$REPO_ROOT/$V2_OUT_REL/MANIFEST.sha256" | awk '{print $1}')"
    echo "confirmation_audit_sha256=$(sha256sum "$REPO_ROOT/$CONF_REL/confirmation_audit.json" | awk '{print $1}')"
} > "$STAGING_DIR/BUNDLE_METADATA.txt"

(
    cd "$STAGING_DIR"
    find . -type f ! -name 'BUNDLE_CONTENTS.sha256' -print0 \
        | LC_ALL=C sort -z \
        | xargs -0 sha256sum > BUNDLE_CONTENTS.sha256
)

python3 - "$STAGING_DIR" "$OUTPUT_ZIP" <<'PY'
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import sys

source = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2]).resolve()

with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        archive.write(path, path.relative_to(source).as_posix())
PY

FILE_COUNT="$(find "$STAGING_DIR" -type f | wc -l)"
ZIP_SIZE="$(du -h "$OUTPUT_ZIP" | awk '{print $1}')"
ZIP_SHA256="$(sha256sum "$OUTPUT_ZIP" | awk '{print $1}')"

echo
echo "v2_review_bundle: PASS"
echo "files: $FILE_COUNT"
echo "size: $ZIP_SIZE"
echo "zip: $OUTPUT_ZIP"
echo "sha256: $ZIP_SHA256"
echo
echo "Run this on your local machine to download it:"
printf 'scp mszabo@192.168.1.187:%q "$HOME/Downloads/"\n' "$OUTPUT_ZIP"

