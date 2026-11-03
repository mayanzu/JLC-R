"""Render the two prespecified factorial endpoint contrasts from saved CSV."""
from __future__ import annotations
import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

mpl.rcParams.update({
    'font.family':'sans-serif', 'font.sans-serif':['Arial','DejaVu Sans'],
    'font.size':8, 'axes.labelsize':8.5, 'xtick.labelsize':7.5,
    'ytick.labelsize':8, 'svg.fonttype':'none', 'pdf.fonttype':42,
    'axes.spines.top':False, 'axes.spines.right':False, 'axes.linewidth':.7,
})

FACTORS=['A','G','R','AG','AR','GR','AGR']
LABELS=['Activity cadence','Demand Guard','Bounded recovery',
        'Cadence × Guard','Cadence × recovery','Guard × recovery',
        'Cadence × Guard × recovery']


def alignment(fig,out):
    skill=Path.home()/'.agents/skills/nature-figure/scripts'
    if skill.is_dir():sys.path.insert(0,str(skill))
    try:
        from audit_panel_alignment import require_matplotlib_panel_alignment
    except ModuleNotFoundError:
        fig.canvas.draw();boxes=[ax.get_position().bounds for ax in fig.axes]
        assert len(boxes)==2
        w,h=fig.get_size_inches()*72
        deviations={'bottom_pt':abs(boxes[0][1]-boxes[1][1])*h,
                    'height_pt':abs(boxes[0][3]-boxes[1][3])*h,
                    'width_pt':abs(boxes[0][2]-boxes[1][2])*w}
        assert max(deviations.values())<=1.5,deviations
        (out/'fig4_factorial.alignment.json').write_text(json.dumps(
            {'verdict':'PASS','method':'portable-two-panel-check','deviations':deviations},indent=2),encoding='utf8')
    else:
        require_matplotlib_panel_alignment(fig,
            json_out=str(out/'fig4_factorial.alignment.json'),
            overlay_svg=str(out/'fig4_factorial.alignment.svg'),
            tolerance_pt=1.5,gutter_tolerance_pt=1.5,require_panel_labels=True,strict=True)


def render(source,out):
    with source.open(encoding='utf8',newline='') as f:data=list(csv.DictReader(f))
    assert len(data)==14
    fig,axes=plt.subplots(1,2,figsize=(7.1,3.55),sharey=True,layout='constrained')
    ys=np.arange(7)[::-1]
    for ax,metric,title,letter,xlim,ticks in zip(
        axes,['coverage_pct','source_coverage_p5_pct'],['Fresh-state coverage','Source P5'],
        ['a','b'],[(-1.4,13.2),(-1.3,6.2)],[[0,3,6,9,12],[0,1,2,3,4,5,6]]):
        ax.axvline(0,color='#929292',linewidth=.8,linestyle='--',zorder=0)
        for pos,factor in zip(ys,FACTORS):
            matches=[r for r in data if r['endpoint']==metric and r['contrast']==factor]
            assert len(matches)==1;r=matches[0]
            mean,low,high=[float(r[k]) for k in ('mean','ci95_low','ci95_high')]
            assert low<=mean<=high
            supported=float(r['p_holm14'])<.05
            color='#265f80'
            ax.errorbar(mean,pos,xerr=np.array([[mean-low],[high-mean]]),fmt='o',
                markersize=4.8,markerfacecolor=color if supported else 'white',
                markeredgecolor=color,markeredgewidth=.9,ecolor=color,
                elinewidth=1,capsize=2,zorder=3)
        ax.set_xlim(*xlim);ax.set_xticks(ticks);ax.set_ylim(-.65,6.65)
        ax.set_yticks(ys,LABELS);ax.tick_params(axis='y',length=0)
        ax.grid(axis='x',color='#e7e7e7',linewidth=.5,zorder=0)
        ax.text(0,1.035,letter,transform=ax.transAxes,fontweight='bold',fontsize=9,va='bottom')
        ax.text(.08,1.035,title,transform=ax.transAxes,fontweight='bold',fontsize=8.5,va='bottom')
    axes[1].tick_params(labelleft=False)
    fig.supxlabel('Factorial contrast (percentage points)',fontsize=8.5)
    fig.canvas.draw();alignment(fig,out)
    fig.savefig(out/'fig4_factorial.svg');fig.savefig(out/'fig4_factorial.pdf')
    fig.savefig(out/'fig4_factorial.tiff',dpi=600)
    fig.savefig(out/'fig4_factorial.png',dpi=300)
    plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True);render(args.source,args.output)
