#!/usr/bin/env python3
"""Audit four exported ZIPs and emulate one OCR gate on a frozen event stream.

Python standard library + ffprobe. No neural inference and no ground-truth
accuracy estimation. The 10-second switching protocol is exploratory; it is
not the 30-second-period protocol originally proposed for a five-minute clip.
"""
import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
from zipfile import ZipFile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_run(path):
    with ZipFile(path) as z:
        readcsv = lambda name: list(csv.DictReader(io.StringIO(z.read(name).decode('utf-8-sig'))))
        obs = readcsv('results/observations.csv')
        tracks = readcsv('results/test.csv')
        run = json.loads(z.read('run.json'))
        config = json.loads(z.read('config/pilot_config.json'))
        log = z.read('logs/stdout.log').decode()
        source_hash = sha(z.read('video/source.mp4'))
        assert source_hash == re.search(r'^Video SHA256: (\w+)$', log, re.M).group(1)
        jrows = [json.loads(x) for x in z.read('results/plate_observations.jsonl').decode().splitlines() if x.strip()]
        assert len(jrows) == len(obs)
        assert Counter(r['rejection_reason'] for r in jrows) == Counter(r['rejection_reason'] for r in obs)
        assert sum(r['accepted_for_vote'] for r in jrows) == sum(r['accepted_for_vote'] == 'True' for r in obs)
        result = {
            'run': run['id'], 'mode': run['mode'], 'source_run': run['replay_source_id'],
            'threshold': config['parameters']['ocr_threshold'], 'archive_sha256': sha(path.read_bytes()),
            'source_sha256': source_hash, 'playback_sha256': sha(z.read('video/playback.mp4')),
            'revision': re.search(r'^Code revision: (\w+)$', log, re.M).group(1),
            'processed_frames': int(re.search(r'Recorded and analyzed (\d+) frames', log).group(1)),
            'observations': len(obs), 'accepted': sum(r['accepted_for_vote']=='True' for r in obs),
            'rejections': dict(Counter(r['rejection_reason'] for r in obs if r['rejection_reason'])),
            'finalized_lifetimes': len(tracks), 'output_lifetimes': sum(bool(r['plate_text']) for r in tracks),
            'parameters': config['parameters'], 'configuration_completeness': config['completeness'],
            'configuration_unavailable': config['unavailable'],
        }
        return result, obs, tracks


def canonical_obs(rows):
    ignore = {'run_id','captured_at','accepted_for_vote','rejection_reason'}
    return [{k:v for k,v in r.items() if k not in ignore} for r in rows]


def canonical_tracks(rows):
    keys = ('car_id','tracker_id','connection_index','vehicle_class','vehicle_class_id',
            'vehicle_confidence','vehicle_x1','vehicle_y1','vehicle_x2','vehicle_y2','termination_reason')
    return [{k:r[k] for k in keys} for r in rows]


def summarize(obs, tracks, thresholds):
    groups = defaultdict(list)
    accepted = []
    for i, row in enumerate(obs):
        if row['normalized_text'] and float(row['ocr_confidence']) >= thresholds[i]:
            groups[row['car_id']].append(row)
            accepted.append(i)
    outputs = []
    tied = 0
    for track in tracks:
        readings = groups[track['car_id']]
        by_text = defaultdict(list)
        for row in readings:
            by_text[row['normalized_text']].append(float(row['ocr_confidence']))
        candidates = [dict(text=s, weight=sum(p), support=len(p), mean=sum(p)/len(p), maximum=max(p))
                      for s,p in by_text.items()]
        candidates.sort(key=lambda c:(-c['weight'],-c['support'],-c['mean'],-c['maximum'],c['text']))
        if len(candidates)>1 and all(candidates[0][k] == candidates[1][k] for k in ('weight','support','mean','maximum')):
            tied += 1
        win = candidates[0] if candidates else dict(text='',weight=0.0,support=0,mean=None,maximum=None)
        outputs.append(dict(car_id=track['car_id'], accepted=len(readings), **win))
    return dict(accepted=len(accepted), accepted_indices=accepted,
                output_lifetimes=sum(bool(x['text']) for x in outputs),
                lexical_ties=tied, outputs=outputs)


def frame_times(zip_path):
    with ZipFile(zip_path) as z, tempfile.TemporaryDirectory() as d:
        p=Path(d)/'source.mp4';p.write_bytes(z.read('video/source.mp4'))
        cmd=['ffprobe','-v','error','-select_streams','v:0','-show_streams','-show_frames',
             '-show_entries','stream=width,height,r_frame_rate,avg_frame_rate,time_base,nb_frames,duration:frame=best_effort_timestamp',
             '-of','json',str(p)]
        info=json.loads(subprocess.check_output(cmd))
    stream=info['streams'][0];base=Fraction(stream['time_base'])
    raw=[int(f['best_effort_timestamp'])*base for f in info['frames']]
    pts=[t-raw[0] for t in raw]
    assert all(a<b for a,b in zip(pts,pts[1:]))
    return stream,pts


def scheduled(pts, grid, radius, update, period):
    """Advance scheduled decisions before each observation's source frame."""
    active=grid[0];next_update=Fraction(0);history=[];states=[]
    for i,t in enumerate(pts):
        while next_update<=t:
            q=grid[0] if int(next_update//period)%2==0 else grid[-1]
            feasible=[g for g in grid if abs(g-active)<=radius]
            new=min(feasible,key=lambda g:(abs(g-q),g))
            history.append(dict(scheduled_time=float(next_update),first_source_frame=i,
                                actual_source_time=float(t),proposal=float(q),previous=float(active),
                                applied=float(new),step=float(abs(new-active))))
            active=new;next_update+=update
        q=grid[0] if int(t//period)%2==0 else grid[-1]
        states.append((float(grid[0]),float(q),float(active)))
    return states,history


def writecsv(path,rows):
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--protocol',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    protocol=json.loads(args.protocol.read_text())
    data={n:read_run(args.input_dir/f'prediction-run-{n}.zip') for n in (20,21,22,23)}
    checks={
        'all_source_bytes_equal':len({d[0]['source_sha256'] for d in data.values()})==1,
        'all_reported_revisions_equal':len({d[0]['revision'] for d in data.values()})==1,
        'replay_predecision_observations_identical':canonical_obs(data[21][1])==canonical_obs(data[22][1])==canonical_obs(data[23][1]),
        'replay_vehicle_fields_identical':canonical_tracks(data[21][2])==canonical_tracks(data[22][2])==canonical_tracks(data[23][2]),
        'replay_only_recorded_parameter_difference_threshold':all(
            {k:v for k,v in data[n][0]['parameters'].items() if k!='ocr_threshold'} ==
            {k:v for k,v in data[21][0]['parameters'].items() if k!='ocr_threshold'} for n in (22,23)),
    }
    assert all(checks.values()),checks
    obs,tracks=data[21][1:]
    constant={}
    for n,(meta,rows,ts) in data.items():
        out=summarize(rows,ts,[meta['threshold']]*len(rows))
        assert out['accepted_indices']==[i for i,r in enumerate(rows) if r['accepted_for_vote']=='True']
        for computed,actual in zip(out['outputs'],ts):
            assert computed['car_id']==actual['car_id']
            assert computed['text']==actual['plate_text']
            assert computed['accepted']==int(actual['plate_total_observations'])
            assert computed['support']==int(actual['plate_support_count'])
            assert abs(computed['weight']-float(actual['plate_weighted_vote']))<1e-10
        assert out['lexical_ties']==0
        constant[str(meta['threshold'])]=summarize(obs,tracks,[meta['threshold']]*len(obs)) if n!=20 else out
        checks[f'run{n}_gate_and_consensus_reconstructed']=True
    for tau in (.5,.8):constant[str(tau)]=summarize(obs,tracks,[tau]*len(obs))
    # R20 is a distinct capture-mode analysis, not a threshold control.
    constant['0.3']=summarize(obs,tracks,[.3]*len(obs))
    stream,pts=frame_times(args.input_dir/'prediction-run-21.zip')
    assert len(pts)==data[21][0]['processed_frames']
    grid=list(map(Fraction,protocol['threshold_grid']));radius=Fraction(protocol['radius'])
    states,decisions=scheduled(pts,grid,radius,Fraction(protocol['update_seconds']),Fraction(protocol['proposal_half_period_seconds']))
    assert all(Fraction(str(d['step']))<=radius for d in decisions)
    variants={}
    for j,name in enumerate(('F','A','G')):
        variants[name]=summarize(obs,tracks,[states[int(r['frame_id'])][j] for r in obs])
        assert variants[name]['lexical_ties']==0
    # Offset sensitivity is mandatory because exports do not explicitly declare
    # whether frame_id is zero-based. It cannot validate that convention.
    offset={name:summarize(obs,tracks,[states[max(0,int(r['frame_id'])-1)][j] for r in obs])
            for j,name in enumerate(('F','A','G'))}
    checks['minus_one_frame_offset_preserves_all_variant_memberships_and_winners']=all(
        offset[name]==variants[name] for name in variants)
    assert checks['minus_one_frame_offset_preserves_all_variant_memberships_and_winners']
    comparison=[]
    for i,t in enumerate(tracks):
        row={'car_id':t['car_id']}
        for name,res in variants.items():
            row[name+'_text']=res['outputs'][i]['text'];row[name+'_accepted']=res['outputs'][i]['accepted']
        comparison.append(row)
    admissions=[{'observation_index':i,'frame_id':r['frame_id'],'source_time':float(pts[int(r['frame_id'])]),
                 'car_id':r['car_id'],'normalized_text':r['normalized_text'],'ocr_confidence':r['ocr_confidence'],
                 **{name+'_accept':i in variants[name]['accepted_indices'] for name in variants}}
                for i,r in enumerate(obs)]
    summary={'scope':'Fixed full-pipeline replay audit and exploratory gate-only chronological emulation; no ground-truth accuracy',
             'runs':[d[0] for d in data.values()], 'checks':checks,'stream':stream,
             'protocol_sha256':sha(args.protocol.read_bytes()),'protocol':protocol,
             'constant_gate_controls':constant,'variants':variants,'decisions':decisions,
             'variant_final_strings_identical':len({tuple(o['text'] for o in x['outputs']) for x in variants.values()})==1,
             'live_and_replay_predecision_streams_identical':canonical_obs(data[20][1])==canonical_obs(obs),
             'playback_video_identical_across_exports':len({d[0]['playback_sha256'] for d in data.values()})==1,
             'frame_index_convention':'Assumed zero-based for presentation; minus-one sensitivity does not change any reported emulation membership or winner. Convention requires source-code confirmation.',
             'plot_timestamps':'source PTS of OCR observations, not finalization times; emitted-event source times are not in these exports'}
    (args.output_dir/'audit.json').write_text(json.dumps(summary,indent=2)+'\n')
    writecsv(args.output_dir/'decisions.csv',decisions)
    writecsv(args.output_dir/'frame_thresholds.csv',[dict(frame=i,time=float(t),F=states[i][0],A=states[i][1],G=states[i][2]) for i,t in enumerate(pts)])
    writecsv(args.output_dir/'lifetime_comparison.csv',comparison)
    writecsv(args.output_dir/'observation_admission.csv',admissions)
    print(json.dumps({'checks':checks,'constant_controls':{k:{x:v[x] for x in ('accepted','output_lifetimes')} for k,v in constant.items()},
                      'variants':{k:{x:v[x] for x in ('accepted','output_lifetimes')} for k,v in variants.items()},
                      'identical_final_strings':summary['variant_final_strings_identical'],'decisions':decisions},indent=2))


if __name__=='__main__':main()
