# Batch runner for SISY IPS ablation

## 1. Adjust the variant flags

Edit `variants_sisy2026.template.json` so the flags match your actual `main.py`.

The default runner command is:

```bash
python main.py -image {image} -outdir {outdir} -gt {gt} {variant_args}
```

If your software uses different argument names, either edit the JSON flags or pass a full custom command template with `--cmd-template`.

## 2. Pilot run

```bash
python batch_runner.py \
  --manifest synthetic_plates_sisy2026/manifest.csv \
  --dataset-root synthetic_plates_sisy2026 \
  --software-dir /home/mszabo/ocr-segmentation \
  --variants variants_sisy2026.template.json \
  --out runs/pilot \
  --workers 2 \
  --limit 20
```

## 3. Full run

```bash
python batch_runner.py \
  --manifest synthetic_plates_sisy2026/manifest.csv \
  --dataset-root synthetic_plates_sisy2026 \
  --software-dir /home/mszabo/ocr-segmentation \
  --variants variants_sisy2026.template.json \
  --out runs/sisy2026_full \
  --workers 12 \
  --timeout 180
```

## 4. Outputs

- `runs/.../results.csv`: one row per sample and variant
- `runs/.../summary_by_variant.csv`: quick aggregate by variant
- `runs/.../outputs/<variant>/<sample_id>/`: raw output, stdout, stderr, command.txt
- `runs/.../batch_config.json`: full batch configuration

## 5. Important

The runner does not know your exact IPS CLI. It is intentionally template-driven.
If the paper code currently does not support `--mode`, `--w_density`, etc.,
either add those flags to `main.py`, or change the variant args accordingly.
