#!/usr/bin/env python3
"""Recompute a retrospective, restricted human-reference comparison.

Python standard library only. The worksheet supplies the human strings; the
separate, visually established mapping supplies identities. Neither OCR text
similarity nor this script establishes a vehicle match. No new inference.
"""
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_sheet(path):
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(path) as z:
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            root = ET.fromstring(z.read('xl/sharedStrings.xml'))
            strings = [''.join(x.itertext()) for x in root.findall('s:si', ns)]
        root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        result = []
        for row in root.findall('s:sheetData/s:row', ns):
            values = {}
            for cell in row.findall('s:c', ns):
                col = re.sub(r'[0-9]', '', cell.attrib['r'])
                if cell.find('s:f', ns) is not None:
                    raise ValueError('Unexpected formula in the reference worksheet')
                typ = cell.get('t')
                val = cell.find('s:v', ns)
                if typ == 'inlineStr':
                    text = ''.join(t.text or '' for t in cell.findall('s:is//s:t', ns))
                elif typ == 's':
                    text = strings[int(val.text)]
                else:
                    text = val.text if val is not None else ''
                values[col] = text
            result.append((int(row.attrib['r']), values))
    assert result[0][1] == {'A': 'szín', 'B': 'tipus', 'C': 'felirat', 'D': 'biztonság'}
    return {r: dict(color=v.get('A', ''), vehicle=v.get('B', ''),
                    text=v.get('C', ''), certainty=v.get('D', ''))
            for r, v in result[1:]}


def key(s):
    """Only case/separator normalization. Never replace or delete characters."""
    return re.sub(r'[\s-]', '', s).upper()


def classify(row):
    c = row['certainty']
    if 'nem biztos' in c:
        return 'uncertain'
    if 'nem felismerhet' in c:
        return 'plate_present_unreadable'
    if 'rendszám van' in c and 'felismerhet' in c:
        return 'confident_plate'
    if row['text'] == 'TEAM':
        return 'nonplate_lettering'
    if row['text'] == 'nincs':
        return 'no_plate_string_recorded'
    raise ValueError(row)


def main():
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-dir', type=Path, required=True)
    ap.add_argument('--worksheet', type=Path, default=root/'evidence/manual_r20/R20_manual_reference.xlsx')
    ap.add_argument('--mapping', type=Path, default=root/'evidence/manual_r20/visual_mapping.json')
    ap.add_argument('--emulation', type=Path, default=root/'notes/runs20_23/lifetime_comparison.csv')
    ap.add_argument('--output-dir', type=Path, default=root/'notes/manual_r20')
    a = ap.parse_args()
    mapping = json.loads(a.mapping.read_text())
    assert sha(a.worksheet.read_bytes()) == mapping['worksheet_sha256']
    refs = read_sheet(a.worksheet)
    assert len(refs) == 21
    classes = Counter(classify(r) for r in refs.values())
    confident = {r for r, v in refs.items() if classify(v) == 'confident_plate'}
    assert confident == {c['excel_row'] for c in mapping['cases'] if c['primary']}
    raw_runs, hashes, regions = {}, {}, []
    for run in (20, 21, 22, 23):
        path = a.input_dir/f'prediction-run-{run}.zip'
        with ZipFile(path) as z:
            hashes[str(run)] = {
                'archive_sha256': sha(path.read_bytes()),
                'source_video_sha256': sha(z.read('video/source.mp4'))}
            assert hashes[str(run)]['source_video_sha256'] == mapping['source_video_sha256']
            data = list(csv.DictReader(io.StringIO(z.read('results/test.csv').decode('utf-8-sig'))))
        raw_runs[f'R{run}'] = {int(r['car_id']): r for r in data}
    # The visual links were made on R21. Its primary winning regions are
    # exactly unchanged in the other two measured replays.
    for case in mapping['cases']:
        if not case['primary']:
            continue
        for ident in case['replay_ids']:
            for run in ('R22', 'R23'):
                for field in ('plate_text', 'plate_bbox_frame_number',
                              'plate_x1', 'plate_y1', 'plate_x2', 'plate_y2'):
                    assert raw_runs['R21'][ident][field] == raw_runs[run][ident][field]
    with a.emulation.open() as f:
        emulated = list(csv.DictReader(f))
    variants = {v: {int(r['car_id']): {'plate_text': r[v+'_text']} for r in emulated}
                for v in ('F', 'A', 'G')}
    variants = {**raw_runs, **variants}
    case_rows = []
    summaries = {}
    for variant, outputs in variants.items():
        for case in mapping['cases']:
            row = case['excel_row']
            group = 'R20' if variant == 'R20' else 'replay'
            ids = case[group+'_ids']
            selected = [outputs[i] for i in ids if outputs[i]['plate_text']]
            texts = [x['plate_text'] for x in selected]
            exact = sum(key(s) == key(refs[row]['text']) for s in texts)
            case_rows.append(dict(
                variant=variant, excel_row=row, case_id=case['case_id'],
                category=classify(refs[row]), primary=case['primary'],
                human_verbatim=refs[row]['text'], comparison_key=key(refs[row]['text']),
                in_hungarian_grammar=bool(re.fullmatch(r'[A-Z]{3,4}[0-9]{3}', key(refs[row]['text']))),
                linked_ids=';'.join(map(str, ids)), outputs=';'.join(texts),
                nonempty_outputs=len(texts), exact_outputs=exact if case['primary'] else '',
                at_least_one_exact=(exact > 0) if case['primary'] else '',
                mixed_exact_and_different=(0 < exact < len(texts)) if case['primary'] else ''))
            if variant in ('R20', 'R21'):
                for ident in ids:
                    r = outputs[ident]
                    if not r['plate_text']:
                        continue
                    frame = int(r['plate_bbox_frame_number'])
                    regions.append(dict(
                        run=variant, car_id=ident, case_id=case['case_id'], excel_row=row,
                        primary=case['primary'], source_frame_zero_based_assumption=frame,
                        source_seconds=frame/25.52,
                        plate_box=[float(r['plate_'+k]) for k in ('x1', 'y1', 'x2', 'y2')],
                        output=r['plate_text'], human_verbatim=refs[row]['text']))
        primary = [r for r in case_rows if r['variant'] == variant and r['primary']]
        assert len(primary) == 8
        hu = [r for r in primary if r['in_hungarian_grammar']]
        summaries[variant] = dict(
            reference_cases=len(primary), with_at_least_one_exact=sum(r['at_least_one_exact'] for r in primary),
            hungarian_format_cases=len(hu), hungarian_with_at_least_one_exact=sum(r['at_least_one_exact'] for r in hu),
            linked_nonempty_outputs=sum(r['nonempty_outputs'] for r in primary),
            exact_outputs=sum(r['exact_outputs'] for r in primary),
            mixed_cases=sum(r['mixed_exact_and_different'] for r in primary),
            cases_without_nonempty_output=sum(r['nonempty_outputs'] == 0 for r in primary))
    # A reported lifecycle is assigned at most once in the main comparison.
    for group in ('R20', 'replay'):
        ids = [i for c in mapping['cases'] if c['primary'] for i in c[group+'_ids']]
        assert len(ids) == len(set(ids))
    a.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, rows in [('reference_rows.csv', [dict(excel_row=r, **v, category=classify(v)) for r, v in refs.items()]),
                           ('case_results.csv', case_rows)]:
        with (a.output_dir/filename).open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    report = dict(
        scope='Retrospective agreement on eight confidently transcribed reference cases; not overall accuracy or recall.',
        worksheet_sha256=sha(a.worksheet.read_bytes()), mapping_sha256=sha(a.mapping.read_bytes()),
        categories=dict(classes), summaries=summaries, input_hashes=hashes,
        normalization='Upper case; remove whitespace and ASCII hyphens only; no character correction.',
        excluded='Four uncertain strings and all entries lacking an explicit confident plate reference.',
        matching='Assistant-assisted source-frame/appearance/position audit, stored separately; not selected by string equality.',
        limitations=mapping['limitations'])
    (a.output_dir/'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    (a.output_dir/'winning_regions.json').write_text(json.dumps(regions, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'categories': dict(classes), 'summaries': summaries}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
