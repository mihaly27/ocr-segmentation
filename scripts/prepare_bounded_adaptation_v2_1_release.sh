#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
v1="$repo_root/mathematical_framework/recalibration_2026"
v2="$repo_root/mathematical_framework/recalibration_2026_v2"
challenge="$v2/challenges/activation_carryover_v1"
release_dir="$repo_root/release/bounded_adaptation_v2_1"
artifact_dir="$release_dir/artifacts"

if [[ -n "$(git -C "$repo_root" status --short)" ]]; then
  echo "ERROR: working tree must be clean before release capture" >&2
  exit 1
fi

declare -a copies=(
  "$v1/outputs/w_calibration.json|$artifact_dir/w_calibration.json"
  "$v1/outputs/w_phase1_local/selected_samples.json|$artifact_dir/w_phase1_selected_samples.json"
  "$v2/outputs/preflight.json|$artifact_dir/v2_preflight.json"
  "$v2/outputs/v2_grid_check.json|$artifact_dir/v2_grid_check.json"
  "$v2/outputs/delta_selection/selected_delta.json|$artifact_dir/v2_selected_delta.json"
  "$v2/outputs/delta_selection/delta_calibration_summary.csv|$artifact_dir/v2_delta_calibration_summary.csv"
  "$v2/outputs/confirmation/confirmation_plan.json|$artifact_dir/v2_confirmation_plan.json"
  "$v2/outputs/confirmation/confirmation_audit.json|$artifact_dir/v2_confirmation_audit.json"
  "$challenge/outputs/challenge_audit.json|$artifact_dir/v21_challenge_audit.json"
  "$challenge/outputs/freeze_summary.json|$artifact_dir/v21_freeze_summary.json"
  "$challenge/outputs/MANIFEST.sha256|$artifact_dir/v21_manifest.sha256"
)

for pair in "${copies[@]}"; do
  src="${pair%%|*}"
  if [[ ! -f "$src" ]]; then
    echo "ERROR: required artifact missing: $src" >&2
    exit 1
  fi
done

mkdir -p "$artifact_dir"
for pair in "${copies[@]}"; do
  src="${pair%%|*}"
  dst="${pair#*|}"
  install -m 0644 "$src" "$dst"
done

python_bin="$repo_root/ips_single_image/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  echo "ERROR: expected Python environment missing: $python_bin" >&2
  exit 1
fi

{
  echo "captured_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "git_commit=$(git -C "$repo_root" rev-parse HEAD)"
  echo "git_branch=$(git -C "$repo_root" branch --show-current)"
  echo "python=$($python_bin --version 2>&1)"
  echo "tesseract=$(tesseract --version 2>&1 | head -n 1)"
  echo "kernel=$(uname -srvmo)"
  echo
  echo "python_packages:"
  "$python_bin" -m pip freeze --all
} > "$release_dir/SOFTWARE_ENVIRONMENT.txt"

(
  cd "$release_dir"
  find . -type f ! -name ARTIFACTS.sha256 -print0 \
    | sort -z \
    | xargs -0 sha256sum > ARTIFACTS.sha256
)

echo "Release metadata captured in: $release_dir"
echo "Review, git add the directory, commit, merge to main, and tag."
