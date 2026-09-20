#!/usr/bin/env python3
"""Render exact source-frame regions for auditing the eight reference cases.

Requires FFmpeg and Pillow. Cropping, rectangles, and labels only; no detail
reconstruction, denoising, generative processing, or character correction.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--source', type=Path, required=True)
ap.add_argument('--regions', type=Path, default=root/'notes/manual_r20/winning_regions.json')
ap.add_argument('--output-dir', type=Path, default=root/'evidence/manual_r20')
ap.add_argument('--figure-dir', type=Path, default=root/'figures')
a = ap.parse_args()
assert hashlib.sha256(a.source.read_bytes()).hexdigest() == '43de07ae5f762b247fa9455e89afedb48c244cc114091e49be782f3ddaa18f7d'
regions = [r for r in json.loads(a.regions.read_text()) if r['primary']]
frames = sorted({r['source_frame_zero_based_assumption'] for r in regions})
select = '+'.join('eq(n\\,%d)' % f for f in frames)
try:
    font = ImageFont.truetype('DejaVuSans.ttf', 14)
except OSError:
    font = ImageFont.load_default()
a.output_dir.mkdir(parents=True, exist_ok=True)
a.figure_dir.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(a.source),
                    '-vf', 'select='+select, '-fps_mode', 'vfr', str(tmp/'f%03d.png')], check=True)
    lookup = {f: tmp/f'f{i:03d}.png' for i, f in enumerate(frames, 1)}
    for run in ('R20', 'R21'):
        selected = [r for r in regions if r['run'] == run]
        board = Image.new('RGB', (1000, ((len(selected)+1)//2)*295), 'white')
        draw = ImageDraw.Draw(board)
        for j, r in enumerate(selected):
            x1,y1,x2,y2 = r['plate_box']; frame = r['source_frame_zero_based_assumption']
            x0 = max(0, min(1420, round((x1+x2)/2-250)))
            y0 = max(0, min(830, round((y1+y2)/2-170)))
            crop = Image.open(lookup[frame]).crop((x0,y0,x0+500,y0+250))
            ImageDraw.Draw(crop).rectangle((x1-x0,y1-y0,x2-x0,y2-y0), outline='red', width=2)
            if run == 'R21' and r['car_id'] in (21,50,12):
                filename = {21:'manual_dacia_343.png',50:'manual_dacia_357.png',12:'manual_tesla_407.png'}[r['car_id']]
                crop.save(a.figure_dir/filename)
            x,y = j%2*500,j//2*295
            draw.text((x+4,y+2), f"{run} ID {r['car_id']} | frame {frame} | Excel row {r['excel_row']}", fill='black', font=font)
            draw.text((x+4,y+21), f"Human: {r['human_verbatim']} | Output: {r['output']}", fill='black', font=font)
            board.paste(crop, (x,y+42))
        board.save(a.output_dir/f'{run}_reference_regions.jpg', quality=96, subsampling=0)
