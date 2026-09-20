#!/usr/bin/env python3
"""Render the paper's additional figure from the audited replay JSON/CSV."""
import argparse
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--notes',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
audit=json.loads((args.notes/'audit.json').read_text())
frames=list(csv.DictReader((args.notes/'frame_thresholds.csv').open()))
obs=list(csv.DictReader((args.notes/'observation_admission.csv').open()))
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':7.5,'axes.labelsize':7.5,
                     'axes.titlesize':8,'legend.fontsize':7,'pdf.fonttype':42,'ps.fonttype':42})
fig,axs=plt.subplots(2,1,figsize=(3.48,2.75),sharex=True,
                    gridspec_kw={'height_ratios':[1,1.12]})
colors={'F':'#737780','A':'#d87926','G':'#164f80'}
styles={'F':':','A':'--','G':'-'}
t=[float(r['time']) for r in frames]
for name in ('F','A','G'):
    axs[0].step(t,[float(r[name]) for r in frames],where='post',color=colors[name],
                ls=styles[name],lw=1.55 if name=='G' else 1.25,label=name)
    values=[0];times=[0];total=0
    for r in obs:
        if r[name+'_accept']=='True':total+=1
        times.append(float(r['source_time']));values.append(total)
    times.append(float(audit['stream']['duration']));values.append(total)
    assert total==audit['variants'][name]['accepted']
    axs[1].step(times,values,where='post',color=colors[name],ls=styles[name],lw=1.4,
                label=f'{name}: {total}')
axs[0].set_title('(a) Thresholds on the recorded timeline',loc='left',pad=6)
axs[0].set_ylabel('OCR threshold');axs[0].set_ylim(.24,.93);axs[0].set_yticks([.3,.5,.8])
axs[0].legend(loc='upper left',ncol=3,frameon=False,handlelength=2,borderaxespad=.25)
axs[1].set_title('(b) Accepted observations (not accuracy)',loc='left',pad=6)
axs[1].set_ylabel('Cumulative count');axs[1].set_xlabel('Source-video time (s)')
axs[1].set_ylim(0,222);axs[1].legend(loc='upper left',ncol=1,frameon=False,handlelength=2)
axs[1].text(.97,.10,'A = G: 19 output lifetimes',transform=axs[1].transAxes,
            ha='right',fontsize=7,color='#222222')
for ax in axs:
    ax.set_xlim(0,30);ax.set_xticks([0,5,10,15,20,25,30])
    ax.spines[['top','right']].set_visible(False)
    ax.grid(axis='y',color='#d9dde1',lw=.45)
    ax.set_axisbelow(True)
for boundary in (10,20):
    for ax in axs:ax.axvline(boundary,color='#b5bbc3',lw=.55,zorder=0)
fig.tight_layout(pad=.6,h_pad=.85)
args.output.parent.mkdir(parents=True,exist_ok=True)
fig.savefig(args.output.with_suffix('.pdf'),metadata={'Title':'Exploratory controlled OCR-gate replay','Author':'Analysis of supplied run exports'})
fig.savefig(args.output.with_suffix('.png'),dpi=350)
print(args.output.with_suffix('.pdf'))
