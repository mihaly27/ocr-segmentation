#!/usr/bin/env bash
# Usage: bash scripts/extract_frame.sh input.mp4 375 output.png
# Zero-based encoded frame index. Decoding only; no crop, drawing or enhancement.
set -euo pipefail
if [[ $# -ne 3 || ! "$2" =~ ^[0-9]+$ ]]; then
  echo 'Usage: extract_frame.sh input.mp4 zero_based_index output.png' >&2
  exit 2
fi
ffmpeg -v error -i "$1" -vf "select=eq(n\,$2)" -frames:v 1 -y "$3"
test -s "$3"
