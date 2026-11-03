"""Regenerate the external-coverage evidence figure from recomputed tests."""
from pathlib import Path
import json,sys
import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt

mpl.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
    'font.size':8,'axes.labelsize':8.5,'xtick.labelsize':7.5,'ytick.labelsize':8,
    'svg.fonttype':'none','pdf.fonttype':42,'axes.spines.top':False,
    'axes.spines.right':False,'axes.linewidth':.7})
def alignment(fig,out,stem='external_coverage'):
    # If the full audit helper is installed, use it; otherwise independently
    # check the only two equal-grid axes in this portable figure.
    skill=Path.home()/'.agents/skills/nature-figure/scripts'
    if skill.is_dir():sys.path.insert(0,str(skill))
    try:from audit_panel_alignment import require_matplotlib_panel_alignment
    except ModuleNotFoundError:
        fig.canvas.draw();boxes=[a.get_position().bounds for a in fig.axes]
        assert len(boxes)==2
        width,height=fig.get_size_inches()*72
        deviations=dict(bottom_pt=abs(boxes[0][1]-boxes[1][1])*height,
                        height_pt=abs(boxes[0][3]-boxes[1][3])*height,
                        width_pt=abs(boxes[0][2]-boxes[1][2])*width)
        assert max(deviations.values())<=1.5,deviations
        (out/(stem+'.alignment.json')).write_text(json.dumps(dict(verdict='PASS',method='portable-two-panel-check',deviations=deviations),indent=2),encoding='utf8')
    else:
        require_matplotlib_panel_alignment(fig,json_out=str(out/(stem+'.alignment.json')),
            overlay_svg=str(out/(stem+'.alignment.svg')),tolerance_pt=1.5,gutter_tolerance_pt=1.5,
            require_panel_labels=True,strict=True)
def external_coverage(tests,out):
    cells=['SYNTHETIC_G20/1.0','SYNTHETIC_G20/0.7','WINTER_G20/1.0','WINTER_G20/0.7',
           'T2_G20/1.0','T2_G20/0.7','T3_G20/1.0','T3_G20/0.7']
    labels=['Synthetic 1.0','Synthetic 0.7','T1 1.0','T1 0.7','T2 1.0','T2 0.7','T3 1.0','T3 0.7']
    panels=[('EADCM-CE','JLC-R − EADCM','#265f80'),('LANTERN-CE','JLC-R − LANTERN','#8a4a2a')]
    fig,axes=plt.subplots(1,2,figsize=(7.1,3.7),sharey=True,layout='constrained')
    y=np.arange(len(cells))[::-1]
    for ax,(control,title,color),letter in zip(axes,panels,['a','b']):
        selected=[]
        for cell in cells:
            match=[r for r in tests if r['control']==control and r['endpoint']=='coverage_pct' and r['cell']==cell]
            assert len(match)==1;selected.append(match[0])
        ax.axvline(0,color='#929292',linewidth=.8,linestyle='--',zorder=0)
        for pos,r in zip(y,selected):
            mean=float(r['mean_difference']);lo=float(r['ci95_low']);hi=float(r['ci95_high'])
            supported=float(r['adjusted_p'])<.05
            ax.errorbar(mean,pos,xerr=np.array([[mean-lo],[hi-mean]]),fmt='o',markersize=4.2,
                markerfacecolor=color if supported else 'white',markeredgecolor=color,
                markeredgewidth=.9,ecolor=color,elinewidth=1,capsize=2,zorder=3)
        ax.set_xlim(-15,45);ax.set_xticks([-10,0,10,20,30,40]);ax.set_ylim(-.65,7.65)
        ax.set_yticks(y,labels);ax.grid(axis='x',color='#e7e7e7',linewidth=.5,zorder=0)
        ax.tick_params(axis='y',length=0);ax.text(0,1.03,letter,transform=ax.transAxes,fontweight='bold',fontsize=9,va='bottom')
        ax.text(.08,1.03,title,transform=ax.transAxes,fontweight='bold',fontsize=8.5,va='bottom')
    axes[1].tick_params(labelleft=False);fig.supxlabel('Coverage difference (percentage points)',fontsize=8.5)
    fig.canvas.draw();alignment(fig,out)
    fig.savefig(out/'external_coverage.svg');fig.savefig(out/'external_coverage.pdf')
    fig.savefig(out/'external_coverage.tiff',dpi=600);fig.savefig(out/'external_coverage.png',dpi=300)
    plt.close(fig)
