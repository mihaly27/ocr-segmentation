R="$HOME/ocr-segmentation"
Q1="$R/mathematical_framework/recalibration_2026"
Q2="$R/mathematical_framework/recalibration_2026_v2"
P2="$Q2/protocol.yaml"
S2="$Q2/scripts"
C2="$Q2/corpora"
O2="$Q2/outputs"
L2="$Q2/v2_input_lock.json"
PY="$R/ips_single_image/.venv/bin/python"
W1="$Q1/outputs/w_calibration.json"
PHASE1="$Q1/outputs/w_phase1_local/selected_samples.json"
W1DATA="$Q1/corpora/w_calibration"
SELECTED="$O2/delta_selection/selected_delta.json"

"$PY" - "$C2" <<'PY'
from pathlib import Path
import json
import sys

root = Path(sys.argv[1])
seeds = [86082721, 86082722, 86082723, 86082724, 86082725]

for seed in seeds:
    corpus = root / f"confirmation_{seed}"
    config = json.loads(
        (corpus / "dataset_config.json").read_text(encoding="utf-8")
    )

    annotations = sum(
        1 for _ in (corpus / "annotations.jsonl").open(encoding="utf-8")
    )
    images = sum(1 for _ in (corpus / "images").glob("*.png"))
    masks = sum(1 for _ in (corpus / "masks").glob("*.png"))

    print(
        f"seed={seed} config_n={config['n']} "
        f"annotations={annotations} images={images} masks={masks}"
    )

    assert config["seed"] == seed
    assert config["n"] == 10000
    assert annotations == 10000
    assert images == 10000
    assert masks == 10000

print("confirmation_corpora: PASS")
PY
