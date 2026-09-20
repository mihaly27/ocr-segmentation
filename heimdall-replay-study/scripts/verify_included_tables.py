#!/usr/bin/env python3
"""Recompute gate and reference summaries from the included derived tables.

Python standard library only. This checks internal numerical consistency, not
the original exports, neural inference, source-video linkage, or human labels.
Run from any directory: python3 scripts/verify_included_tables.py
"""
from collections import Counter, defaultdict
import csv
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read_csv(relative):
    with (ROOT / relative).open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def check(condition, label):
    if not condition:
        raise ValueError(label)


def normalize(text):
    return re.sub(r'[\s-]', '', text.upper())


def reconstruct(observations, lifetimes, thresholds):
    votes = defaultdict(lambda: defaultdict(list))
    indices = []
    for index, (row, threshold) in enumerate(zip(observations, thresholds)):
        confidence = float(row['ocr_confidence'])
        if row['normalized_text'] and confidence >= threshold:
            indices.append(index)
            votes[row['car_id']][row['normalized_text']].append(confidence)
    outputs = []
    for lifetime in lifetimes:
        candidates = votes[lifetime['car_id']]
        winner = min(candidates, key=lambda text: (
            -sum(candidates[text]), -len(candidates[text]),
            -sum(candidates[text]) / len(candidates[text]),
            -max(candidates[text]), text)) if candidates else ''
        scores = candidates[winner] if winner else []
        outputs.append({'car_id': lifetime['car_id'], 'text': winner,
                        'accepted': sum(map(len, candidates.values())),
                        'support': len(scores), 'weight': sum(scores)})
    return indices, outputs


def main():
    notes = ROOT / 'notes'
    audit = json.loads((notes / 'runs20_23/audit.json').read_text())
    observations = read_csv('notes/runs20_23/observation_admission.csv')
    lifetimes = read_csv('notes/runs20_23/lifetime_comparison.csv')
    frames = read_csv('notes/runs20_23/frame_thresholds.csv')
    protocol_path = notes / 'controlled_replay_protocol.json'
    protocol = json.loads(protocol_path.read_text())
    check(hashlib.sha256(protocol_path.read_bytes()).hexdigest() ==
          audit['protocol_sha256'], 'frozen protocol digest')
    check(len(observations) == 319 and len(lifetimes) == 121, 'input counts')
    grid = list(map(Fraction, protocol['threshold_grid']))
    radius = Fraction(protocol['radius'])
    interval = Fraction(protocol['update_seconds'])
    period = Fraction(protocol['proposal_half_period_seconds'])
    active = grid[0]
    next_update = Fraction(0)
    steps = []
    for row in frames:
        time = Fraction(row['time'])
        while next_update <= time:
            proposal = grid[0] if int(next_update // period) % 2 == 0 else grid[-1]
            feasible = [v for v in grid if abs(v - active) <= radius]
            new = min(feasible, key=lambda v: (abs(v - proposal), v))
            steps.append(abs(new - active))
            active = new
            next_update += interval
        direct = grid[0] if int(time // period) % 2 == 0 else grid[-1]
        for name, value in zip(('F', 'A', 'G'), (grid[0], direct, active)):
            check(abs(float(value) - float(row[name])) < 1e-12,
                  f'frame {row["frame"]}, {name} trajectory')
    check(max(steps) == radius and sum(step > 0 for step in steps) == 4,
          'bounded-step property')
    report = {'scope': __doc__.strip(), 'constant_gates': {}, 'variants': {}}
    all_outputs = {}
    controls = {key: [float(key)] * len(observations)
                for key in audit['constant_gate_controls']}
    variants = {name: [float(frames[int(row['frame_id'])][name])
                       for row in observations] for name in ('F', 'A', 'G')}
    for category, schedules, expected in (
            ('constant_gates', controls, audit['constant_gate_controls']),
            ('variants', variants, audit['variants'])):
        for name, thresholds in schedules.items():
            indices, outputs = reconstruct(observations, lifetimes, thresholds)
            check(indices == expected[name]['accepted_indices'], f'{name} membership')
            for computed, stored in zip(outputs, expected[name]['outputs']):
                for key in ('car_id', 'text', 'accepted', 'support'):
                    check(computed[key] == stored[key], f'{name} lifetime {key}')
                check(abs(computed['weight'] - stored['weight']) < 1e-10,
                      f'{name} weighted vote')
            if category == 'variants':
                check(indices == [i for i, row in enumerate(observations)
                                  if row[name + '_accept'] == 'True'],
                      f'{name} CSV membership')
                check(all(o['text'] == r[name + '_text'] and
                          o['accepted'] == int(r[name + '_accepted'])
                          for o, r in zip(outputs, lifetimes)),
                      f'{name} CSV lifetime outputs')
            report[category][name] = {'accepted': len(indices),
                'nonempty_lifetimes': sum(bool(o['text']) for o in outputs)}
            all_outputs[name] = {o['car_id']: o['text'] for o in outputs}
    check(all_outputs['A'] == all_outputs['G'], 'A/G final strings')
    cases = read_csv('notes/manual_r20/case_results.csv')
    references = read_csv('notes/manual_r20/reference_rows.csv')
    manual = json.loads((notes / 'manual_r20/audit.json').read_text())
    check(dict(Counter(r['category'] for r in references)) == manual['categories'],
          'reference categories')
    report['human_reference'] = {}
    for variant in ('R20', 'R21', 'R22', 'R23', 'F', 'A', 'G'):
        rows = [r for r in cases if r['variant'] == variant and r['primary'] == 'True']
        coverage = exact = total = mixed = 0
        for row in rows:
            strings = row['outputs'].split(';') if row['outputs'] else []
            matches = sum(normalize(v) == normalize(row['human_verbatim']) for v in strings)
            check(matches == int(row['exact_outputs']), f'{variant} reference matches')
            if variant != 'R20':
                source = {'R21': '0.3', 'R22': '0.46', 'R23': '0.77'}.get(variant, variant)
                linked = [all_outputs[source][i] for i in row['linked_ids'].split(';')
                          if all_outputs[source][i]]
                check(linked == strings, f'{variant} linked outputs')
            coverage += matches > 0
            exact += matches
            total += len(strings)
            mixed += 0 < matches < len(strings)
        expected = manual['summaries'][variant]
        check((len(rows), coverage, exact, total, mixed) ==
              (expected['reference_cases'], expected['with_at_least_one_exact'],
               expected['exact_outputs'], expected['linked_nonempty_outputs'],
               expected['mixed_cases']), f'{variant} reference summary')
        report['human_reference'][variant] = {
            'cases': len(rows), 'covered': coverage, 'matching_outputs': exact,
            'linked_outputs': total, 'mixed_cases': mixed}
    worksheet = ROOT / 'evidence/manual_r20/R20_manual_reference.xlsx'
    check(hashlib.sha256(worksheet.read_bytes()).hexdigest() == manual['worksheet_sha256'],
          'unchanged human worksheet')
    report['result'] = 'PASS'
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
