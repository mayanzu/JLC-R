"""Recreate the aggregate effects, sampling tradeoff and service-boundary panels."""
from pathlib import Path
from collections import defaultdict
import math,statistics
import numpy as np
from scipy import stats
import matplotlib as mpl
import matplotlib.pyplot as plt
from analysis_core import ROOT,rows
from plot import alignment as require_matplotlib_panel_alignment

mpl.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
    'svg.fonttype':'none','pdf.fonttype':42})

METHODS=['JLC-R-RC2','EADCM-CE','LANTERN-CE','Base-hybrid','Pre-recovery-JLC-R']
LABELS=['JLC-R','EADCM','LANTERN','Base hybrid','Earlier JLC-R']
COLORS=['#265f80','#ac762b','#8a4a2a','#737b80','#9ba3a7']
CELLS=['SYNTHETIC_G20/1.0','SYNTHETIC_G20/0.7','WINTER_G20/1.0','WINTER_G20/0.7',
       'T2_G20/1.0','T2_G20/0.7','T3_G20/1.0','T3_G20/0.7']
CELL_LABELS=['Synthetic 1.0','Synthetic 0.7','T1 1.0','T1 0.7','T2 1.0','T2 0.7','T3 1.0','T3 0.7']
def interval(values):
    x=np.asarray(values,float);assert x.shape==(12,) and np.isfinite(x).all()
    m=float(x.mean());h=float(stats.t.ppf(.975,11)*x.std(ddof=1)/math.sqrt(12));return m,m-h,m+h
def point(ax,y,m,lo,hi,color,filled=True):
    ax.errorbar(m,y,xerr=np.array([[m-lo],[hi-m]]),fmt='o',markersize=4.2,
        markerfacecolor=color if filled else 'white',markeredgecolor=color,markeredgewidth=.9,
        ecolor=color,elinewidth=1,capsize=2,zorder=3)
def panel(ax,letter,title):
    ax.text(0,1.03,letter,transform=ax.transAxes,fontweight='bold',fontsize=9,va='bottom')
    ax.text(.08,1.03,title,transform=ax.transAxes,fontweight='bold',fontsize=8.5,va='bottom')
    ax.grid(axis='x',color='#e7e7e7',linewidth=.5,zorder=0);ax.tick_params(axis='y',length=0)
def save(fig,out,stem):
    fig.canvas.draw();require_matplotlib_panel_alignment(fig,out,stem)
    fig.savefig(out/(stem+'.svg'));fig.savefig(out/(stem+'.pdf'))
    fig.savefig(out/(stem+'.tiff'),dpi=600);fig.savefig(out/(stem+'.png'),dpi=300);plt.close(fig)

def aggregate_effects(primary,out):
    fig,axes=plt.subplots(1,2,figsize=(7.1,2.65),sharey=True,layout='constrained')
    y=np.arange(4)[::-1]
    for ax,field,title,letter in zip(axes,['coverage_pct','source_coverage_p5_pct'],['Fresh-state coverage','Source P5'],['a','b']):
        for pos,method,color in zip(y,METHODS[1:],COLORS[1:]):
            rr=[r for r in primary if r['control']==method and r['endpoint']==field];assert len(rr)==1;r=rr[0]
            point(ax,pos,float(r['mean_difference']),float(r['ci95_low']),float(r['ci95_high']),color,float(r['adjusted_p'])<.05)
        ax.axvline(0,color='#929292',linewidth=.8,linestyle='--');ax.set_xlim(-2,25)
        ax.set_xticks([0,5,10,15,20,25]);ax.set_ylim(-.6,3.6);ax.set_yticks(y,LABELS[1:]);panel(ax,letter,title)
    axes[1].tick_params(labelleft=False);fig.supxlabel('JLC-R minus control (percentage points)',fontsize=8.5)
    save(fig,out,'aggregate_effects')

def sampling_tradeoff(out):
    data=rows(ROOT/'results/confirmation_480.csv');fig,axes=plt.subplots(1,2,figsize=(7.1,2.85),sharey=True,layout='constrained')
    y=np.arange(5)[::-1]
    for ax,field,title,letter in zip(axes,['sample_completion_pct','fixed_demand_packet_delivery_pct'],
                                      ['Sample completion','Fixed-demand packet delivery'],['a','b']):
        for pos,method,color in zip(y,METHODS,COLORS):
            seed_values=defaultdict(list)
            for r in data:
                if r['method']==method:seed_values[int(r['seed'])].append(float(r[field]))
            assert len(seed_values)==12 and all(len(v)==8 for v in seed_values.values())
            m,lo,hi=interval([statistics.mean(v) for v in seed_values.values()]);point(ax,pos,m,lo,hi,color)
        ax.set_xlim(0,100);ax.set_xticks([0,20,40,60,80,100]);ax.set_ylim(-.6,4.6);ax.set_yticks(y,LABELS);panel(ax,letter,title)
    axes[1].tick_params(labelleft=False);fig.supxlabel('Percentage of fixed source-round demand',fontsize=8.5)
    save(fig,out,'sampling_tradeoff')

def service_boundary(fair,out):
    gaps=rows(ROOT/'results/monitoring_gaps_480.csv');fig,axes=plt.subplots(1,2,figsize=(7.1,3.7),sharey=True,layout='constrained')
    y=np.arange(8)[::-1]
    for pos,cell in zip(y,CELLS):
        cn,sp=cell.split('/');rr=[r for r in gaps if r['method']=='JLC-R-RC2' and r['condition']==cn and float(r['supply'])==float(sp)]
        m,lo,hi=interval([float(r['longest_observed_unfresh_p95_h']) for r in rr]);point(axes[0],pos,m,lo,hi,COLORS[0])
        matched=[r for r in fair if r['control']=='LANTERN-CE' and r['endpoint']=='source_coverage_jain' and r['cell']==cell]
        assert len(matched)==1;r=matched[0]
        point(axes[1],pos,float(r['mean_difference']),float(r['ci95_low']),float(r['ci95_high']),COLORS[2],float(r['adjusted_p'])<.05)
    axes[0].set_xlim(0,300);axes[0].set_xticks([0,60,120,180,240,300]);axes[0].set_xlabel('Observed longest gap P95 (h)')
    axes[1].set_xlim(-.23,.08);axes[1].set_xticks([-.2,-.1,0]);axes[1].axvline(0,color='#929292',linewidth=.8,linestyle='--')
    axes[1].set_xlabel('Jain difference, JLC-R − LANTERN')
    for ax,title,letter in zip(axes,['JLC-R monitoring gaps','Relative Jain fairness'],['a','b']):
        ax.set_yticks(y,CELL_LABELS);ax.set_ylim(-.65,7.65);panel(ax,letter,title)
    axes[1].tick_params(labelleft=False);save(fig,out,'service_boundary')
