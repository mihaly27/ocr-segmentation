#!/usr/bin/env bash
set -euo pipefail

: "${R:?Előbb futtasd: source ./set_recalibration_env.sh}"
: "${Q:?Q nincs beállítva}"
: "${S:?S nincs beállítva}"
: "${C:?C nincs beállítva}"
: "${O:?O nincs beállítva}"

COMPOSE="${S}/compose_manifest.py"
TEST_FILE="${Q}/tests/test_compose_manifest.py"

if [[ ! -f "${COMPOSE}" ]]; then
    echo "HIBA: nem található: ${COMPOSE}"
    exit 1
fi

if ! git -C "${R}" diff --cached --quiet; then
    echo "HIBA: már vannak staged változások. Előbb commitold vagy unstage-eld őket."
    git -C "${R}" status --short
    exit 1
fi

python - "${COMPOSE}" "${TEST_FILE}" <<'PY'
from pathlib import Path
import sys

compose_path = Path(sys.argv[1])
test_path = Path(sys.argv[2])

old = '''        "char_boxes": row.get("char_boxes", row.get("boxes", [])),'''
new = '''        # Store canonical JSON text because the frozen historical runner
        # stringifies this field before calling json.loads.
        "char_boxes": json.dumps(
            row.get("char_boxes", row.get("boxes", [])),
            ensure_ascii=False,
            separators=(",", ":"),
        ),'''

text = compose_path.read_text(encoding="utf-8")

if old in text:
    compose_path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Javítva: {compose_path}")
elif '"char_boxes": json.dumps(' in text:
    print(f"Már javítva: {compose_path}")
else:
    raise SystemExit("HIBA: a cserélendő char_boxes sor nem található.")

if test_path.exists():
    test_text = test_path.read_text(encoding="utf-8")
    old_test = '''self.assertEqual(combined[0]["char_boxes"][0]["x"], 1)'''
    new_test = '''self.assertEqual(json.loads(combined[0]["char_boxes"])[0]["x"], 1)'''

    if old_test in test_text:
        test_path.write_text(
            test_text.replace(old_test, new_test, 1),
            encoding="utf-8",
        )
        print(f"Teszt javítva: {test_path}")
    elif new_test in test_text:
        print(f"Teszt már javítva: {test_path}")
PY

python -m compileall -q "${S}"
python -m unittest discover -s "${Q}/tests" -v

git -C "${R}" add \
    mathematical_framework/recalibration_2026/scripts/compose_manifest.py \
    mathematical_framework/recalibration_2026/tests/test_compose_manifest.py

if ! git -C "${R}" diff --cached --quiet; then
    git -C "${R}" commit -m \
        "fix character-box JSON encoding in recalibration manifests"
fi

while read -r SEED CONDITION; do
    TRAJECTORY="${O}/delta_grid/trajectory_${SEED}_${CONDITION}"
    DATASET="${C}/delta_${SEED}_${CONDITION}"

    echo
    echo "Manifest újragenerálása: ${SEED} / ${CONDITION}"

    python "${S}/compose_manifest.py" \
        --phase1-selected "${O}/w_phase1_local/selected_samples.json" \
        --phase1-manifest "${C}/w_calibration/annotations.jsonl" \
        --phase1-root "${C}/w_calibration" \
        --trajectory-manifest "${DATASET}/annotations.jsonl" \
        --trajectory-root "${DATASET}" \
        --trajectory-label "${SEED}-${CONDITION}" \
        --output-manifest "${TRAJECTORY}/composite_manifest.jsonl" \
        --output-dev-selected "${TRAJECTORY}/dev_selected.json"
done <<'EOF'
86082311 touch
86082331 broken
86082351 combo
EOF

python - "${O}/delta_grid/trajectory_86082311_touch/composite_manifest.jsonl" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])

assert isinstance(row["char_boxes"], str)
boxes = json.loads(row["char_boxes"])
assert isinstance(boxes, list)

print(f"Manifest ellenőrzés OK: {path}")
print(f"Első minta boxainak száma: {len(boxes)}")
PY

git -C "${R}" status --short

echo
echo "Hotfix kész. A delta-grid smoke futás újraindítható."
