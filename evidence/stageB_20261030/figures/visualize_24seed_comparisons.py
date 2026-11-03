"""Plot all 24 paired network seeds for the original five-method comparison."""
from pathlib import Path
import argparse,csv,json,math,sys
import numpy as np
from scipy import stats
import matplotlib as mpl
mpl.use('Agg')
import matplotlib.pyplot as plt

SKILL_SCRIPTS=Path.home()/'.agents/skills/nature-figure/scripts'
sys.path.insert(0,str(SKILL_SCRIPTS))
from audit_panel_alignment import require_matplotlib_panel_alignment

mpl.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
    'font.size':8.,'axes.labelsize':8.,'xtick.labelsize':7.5,'ytick.labelsize':7.5,
    'svg.fonttype':'none','pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False,
    'axes.linewidth':.7,'xtick.major.width':.7,'ytick.major.width':.7})
BLUE='#225b7b';LIGHT='#9eafb8';GRID='#e6e9eb';INK='#20272a'
CONTROLS=['EADCM-CE','LANTERN-CE','Base-hybrid','Pre-recovery-JLC-R']
LABELS=['EADCM','LANTERN','JLC-Base','JLC-Core']
FIELDS=['coverage_pct','source_coverage_p5_pct']

def rows(path):
    with path.open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--compact',required=True,type=Path)
    ap.add_argument('--internal',required=True,type=Path)
    args=ap.parse_args()
    source=args.source.resolve();out=args.output.resolve()
    raw=rows(source/'paired_seed_differences.csv')
    tests=rows(source/'five_method_holm8.csv')
    assert len(raw)==24*4*2 and len(tests)==8
    seeds=sorted({int(r['seed']) for r in raw})
    assert len(seeds)==24
    base=[r for r in rows(args.compact/'run_metrics.csv') if r['study']=='confirmation' and
          r['method'] in ('JLC-R','EADCM-CE','LANTERN-CE')]
    extra=rows(args.internal/'run_metrics.csv')
    assert len(base)==576 and len(extra)==384
    lookup={(r['method'],r['condition'],float(r['supply']),int(r['seed'])):r for r in base+extra}
    assert len(lookup)==960
    cells=[('SYNTHETIC_G20',1.),('SYNTHETIC_G20',.7),('WINTER_G20',1.),('WINTER_G20',.7),
           ('T2_G20',1.),('T2_G20',.7),('T3_G20',1.),('T3_G20',.7)]
    data={};testmap={(r['control'],r['endpoint']):r for r in tests}
    extents=[0.];testprob=[]

    for control in CONTROLS:
        for field in FIELDS:
            selected=[r for r in raw if r['control']==control and r['endpoint']==field]
            selected.sort(key=lambda r:int(r['seed']))
            assert len(selected)==24 and [int(r['seed']) for r in selected]==seeds
            v=np.asarray([float(r['difference']) for r in selected])
            assert np.isfinite(v).all()
            for i,seed in enumerate(seeds):
                direct=np.mean([float(lookup[('JLC-R',c,z,seed)][field])-
                                float(lookup[(control,c,z,seed)][field]) for c,z in cells])
                assert math.isclose(v[i],direct,rel_tol=1e-9,abs_tol=1e-8)
            row=testmap[(control,field)]
            mu=float(v.mean());sd=float(v.std(ddof=1))
            assert math.isclose(mu,float(row['mean_difference']),rel_tol=1e-9,abs_tol=1e-9)
            if sd==0:
                assert row['ci95_low']=='' and row['ci95_high']=='' and row['p']==''
                lo=hi=mu;prob=1.
            else:
                se=sd/math.sqrt(24);half=float(stats.t.ppf(.975,23)*se);lo=mu-half;hi=mu+half
                prob=float(2*stats.t.sf(abs(mu/se),23))
                for actual,key in [(lo,'ci95_low'),(hi,'ci95_high'),(prob,'p')]:
                    assert math.isclose(actual,float(row[key]),rel_tol=1e-9,abs_tol=1e-9),(control,field,key)
            p=float(row['holm8_adjusted_p']);assert 0<=p<=1
            testprob.append((control,field,prob,p))
            data[(control,field)]=(v,mu,lo,hi,p)
            extents.extend(v.tolist());extents.extend([lo,hi])
    order=sorted(range(8),key=lambda i:testprob[i][2]);running=0.;adjusted=[0.]*8
    for rank,i in enumerate(order):
        running=max(running,(8-rank)*testprob[i][2]);adjusted[i]=min(1.,running)
    assert all(math.isclose(adjusted[i],testprob[i][3],rel_tol=1e-9,abs_tol=1e-8) for i in range(8))
    lower=5*math.floor((min(extents)-1.)/5)
    upper=5*math.ceil((max(extents)+1.)/5)
    if upper-lower<10:upper=lower+10
    out.mkdir(parents=True,exist_ok=False)
    fig,axes=plt.subplots(1,2,figsize=(7.1,3.05),sharey=True,layout='constrained')
    fig.suptitle('Paired network seeds  ·  mean and nominal 95% interval',fontsize=7.1,color='#53616a')
    jitter=np.linspace(-.19,.19,24)
    for ax,field,title,letter in zip(axes,FIELDS,['Fresh-state coverage','Source P5'],['a','b']):
        for y,control in zip(range(3,-1,-1),CONTROLS):
            vals,mu,lo,hi,p=data[(control,field)]
            ax.scatter(vals,y+jitter,s=9,c=LIGHT,alpha=.7,linewidths=0,zorder=2)
            ax.errorbar(mu,y,xerr=np.array([[mu-lo],[hi-mu]]),fmt='o',markersize=5,
                        markerfacecolor=BLUE if p<.05 else 'white',markeredgecolor=BLUE,
                        markeredgewidth=1.05,ecolor=BLUE,elinewidth=1.35,capsize=2.3,capthick=.9,zorder=4)
        ax.axvline(0,color='#818a8f',linewidth=.75,linestyle='--')
        ax.set_xlim(lower,upper);ax.set_xticks(np.arange(lower,upper+1,5))
        ax.set_ylim(-.6,3.6);ax.set_yticks(range(3,-1,-1),LABELS)
        ax.text(0,1.035,letter,transform=ax.transAxes,fontweight='bold',fontsize=9,va='bottom',color=INK)
        ax.text(.09,1.035,title,transform=ax.transAxes,fontweight='bold',fontsize=8.5,va='bottom',color=INK)
        ax.grid(axis='x',color=GRID,linewidth=.65,zorder=0);ax.tick_params(axis='y',length=0,pad=5)
        ax.set_axisbelow(True)
    axes[1].tick_params(labelleft=False)
    fig.supxlabel('JLC-R minus control (percentage points)',fontsize=8.2)
    fig.canvas.draw()
    require_matplotlib_panel_alignment(fig,json_out=out/'fig3_aggregate.alignment.json',
        overlay_svg=out/'fig3_aggregate.alignment.svg',tolerance_pt=1.5,gutter_tolerance_pt=1.5,
        require_panel_labels=True,strict=True)
    fig.savefig(out/'fig3_aggregate.svg',facecolor='white')
    fig.savefig(out/'fig3_aggregate.pdf',facecolor='white')
    fig.savefig(out/'fig3_aggregate.png',dpi=600,facecolor='white')
    fig.savefig(out/'fig3_aggregate.tiff',dpi=600,facecolor='white')
    plt.close(fig)
    (out/'data_contract.json').write_text(json.dumps({'status':'PASS','network_seeds':24,'paired_records':len(raw),
        'contrasts':CONTROLS,'endpoints':FIELDS,'no_seed_exclusions':True,
        'uncertainty':'nominal paired t 95% interval, df=23',
        'marker':'filled if Holm-8 adjusted p < 0.05; open otherwise',
        'sources':['paired_seed_differences.csv','five_method_holm8.csv']},indent=2),encoding='utf8')
    print('Figure 3 created from 24 paired seeds; source statistics verified.')
if __name__=='__main__':main()
