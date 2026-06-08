# Synthetic License-Plate Generator for IPS Ablation

## Install
```bash
pip install pillow numpy opencv-python
```

## Generate a quick pilot set
```bash
python synthetic_plate_generator.py --out synthetic_plates_pilot --n 500 --seed 27 --perturb all
```

## Generate the paper dataset
```bash
python synthetic_plate_generator.py --out synthetic_plates_sisy2026 --n 5000 --seed 27 --perturb all
```

## Outputs
- `images/*.png`: grayscale plate crops
- `masks/*_mask.png`: binary foreground masks
- `annotations.jsonl`: one JSON record per crop, including plate string and char boxes
- `manifest.csv`: compact table for batch runners
- `dataset_config.json`: reproducibility settings

Recommended paper wording:
"The primary evaluation uses a controlled synthetic benchmark generated with a fixed random seed.
Each sample has a known plate string, character boxes, binary foreground mask, perturbation label,
and generator parameters. This makes split/merge errors and prior-specific candidate rejections
measurable without manual annotation."
