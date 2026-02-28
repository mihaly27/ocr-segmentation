# IPS Single-Image Reference Implementation (Inverse Packing Segmentation)

This is a minimal, runnable Python implementation of the **Inverse-Packing Segmentation (IPS)** idea for **one image** (a license-plate crop).

## What it does
1. Preprocess (threshold + morphology) -> binary mask
2. Connected components (CC) extraction
3. Candidate generation (split proposals)
4. Beam search over segmentations with geometric scoring (fit + overlap + priors)
5. Deterministic decision trace (+ SHA-256 hash)
6. (Optional) OCR backend on the selected segments

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python main.py --image /path/to/plate_crop.jpg --outdir out --gt ABC123
```

Outputs:
- `out/segments.png` (visualization)
- `out/trace.json` (traceable decision log)
- `out/result.json` (predicted string + metrics placeholders)

## Optional modules (not required for the core run)
If you want detector/OCR alternatives, you can install and enable:
- **YOLOv8**: `ultralytics` (e.g., `from ultralytics import YOLO`)
- **EasyOCR**: `easyocr`
- **PaddleOCR**: `paddleocr`
- **Tesseract**: already supported via `pytesseract` (requires the system `tesseract` binary)

You can select OCR backends via `--ocr_backend`.

## Determinism
The pipeline enforces deterministic ordering and tie-breaks and exports a `trace_hash` computed from a sorted JSON serialization of the trace.

