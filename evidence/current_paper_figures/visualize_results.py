"""Recreate four manuscript figures from saved paired-seed results.

The figures do not run a simulation. Every derived seed contrast is checked
against its archived mean and nominal paired-t interval before plotting.
"""
from pathlib import Path
import argparse,csv,json,math,sys
import numpy as np
from scipy import stats
import matplotlib as mpl
mpl.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE=ROOT.parent.parent/'算法最小复现包/JLC-R'
SKILL=Path.home()/'.agents/skills/nature-figure/scripts'
if SKILL.is_dir():sys.path.insert(0,str(SKILL))
try:
 from audit_panel_alignment import require_matplotlib_panel_alignment
except ModuleNotFoundError:
 require_matplotlib_panel_alignment=None

mpl.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
 'font.size':8.0,'axes.labelsize':8.0,'xtick.labelsize':7.5,'ytick.labelsize':7.5,
 'svg.fonttype':'none','pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False,
 'axes.linewidth':.7,'xtick.major.width':.7,'ytick.major.width':.7})
BLUE='#225b7b'; BROWN='#965631'; LIGHT='#9eafb8'; GRID='#e6e9eb'; INK='#20272a'
CELLS=[('SYNTHETIC_G20',1.0),('SYNTHETIC_G20',0.7),('WINTER_G20',1.0),('WINTER_G20',0.7),
       ('T2_G20',1.0),('T2_G20',0.7),('T3_G20',1.0),('T3_G20',0.7)]
CELL_LABELS=['Synthetic 1.0','Synthetic 0.7','T1 1.0','T1 0.7','T2 1.0','T2 0.7','T3 1.0','T3 0.7']
CONTROLS=['EADCM-CE','LANTERN-CE','Base-hybrid','Pre-recovery-JLC-R']
CONTROL_LABELS=['EADCM','LANTERN','JLC-Base','JLC-Core']
CONTRASTS=['A','G','R','AG','AR','GR','AGR']
FACTOR_LABELS=['Activity cadence','Demand Guard','Bounded recovery','Cadence × Guard',
               'Cadence × recovery','Guard × recovery','Cadence × Guard × recovery']

def rows(path):
 with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def check_interval(values,row,mean='mean_difference'):
 values=np.asarray(values,dtype=float)
 assert values.shape==(12,) and np.isfinite(values).all()
 mu=float(values.mean()); half=float(stats.t.ppf(.975,11)*values.std(ddof=1)/math.sqrt(12))
 for actual,key in [(mu,mean),(mu-half,'ci95_low'),(mu+half,'ci95_high')]:
  assert math.isclose(actual,float(row[key]),rel_tol=1e-8,abs_tol=1e-9),(key,actual,row[key])
 return mu,mu-half,mu+half

def one(data,**criteria):
 matches=[r for r in data if all(str(r[k])==str(v) for k,v in criteria.items())]
 assert len(matches)==1,(criteria,len(matches));return matches[0]

def jitter12():
 # Fixed vertical offsets are only a display aid; observations are not resampled.
 return np.linspace(-.19,.19,12)

def marks(ax,y,values,mean,lo,hi,color=BLUE,filled=True):
 ax.scatter(values,y+jitter12(),s=10,c=LIGHT,alpha=.72,linewidths=0,zorder=2)
 ax.errorbar(mean,y,xerr=np.array([[mean-lo],[hi-mean]]),fmt='o',markersize=5.0,
  markerfacecolor=color if filled else 'white',markeredgecolor=color,markeredgewidth=1.05,
  ecolor=color,elinewidth=1.35,capsize=2.3,capthick=.9,zorder=4)

def basic(ax,letter,title):
 ax.text(0,1.035,letter,transform=ax.transAxes,fontweight='bold',fontsize=9,va='bottom',color=INK)
 ax.text(.09,1.035,title,transform=ax.transAxes,fontweight='bold',fontsize=8.5,va='bottom',color=INK)
 ax.grid(axis='x',color=GRID,linewidth=.65,zorder=0)
 ax.tick_params(axis='y',length=0,pad=5);ax.set_axisbelow(True)

def save(fig,out,stem,multipanel=True):
 fig.canvas.draw()
 if multipanel:
  if require_matplotlib_panel_alignment is not None:
   require_matplotlib_panel_alignment(fig,json_out=out/(stem+'.alignment.json'),
    overlay_svg=out/(stem+'.alignment.svg'),tolerance_pt=1.5,gutter_tolerance_pt=1.5,
    require_panel_labels=True,strict=True)
  else:
   # Portable fallback for this fixed two-panel layout, in physical points.
   assert len(fig.axes)==2
   left,right=[ax.get_position().bounds for ax in fig.axes]
   width,height=fig.get_size_inches()*72
   differences={'bottom_pt':abs(left[1]-right[1])*height,
                'height_pt':abs(left[3]-right[3])*height,
                'width_pt':abs(left[2]-right[2])*width}
   assert max(differences.values())<=1.5,differences
   (out/(stem+'.alignment.json')).write_text(json.dumps(
    {'verdict':'PASS','method':'portable-two-panel-check','deviations':differences},indent=2),encoding='utf8')
 fig.savefig(out/(stem+'.svg'),facecolor='white')
 fig.savefig(out/(stem+'.pdf'),facecolor='white')
 fig.savefig(out/(stem+'.png'),dpi=300,facecolor='white')
 plt.close(fig)

def seed_index(data):
 lookup={(r['method'],r['condition'],float(r['supply']),int(r['seed'])):r for r in data}
 seeds=sorted({int(r['seed']) for r in data})
 assert len(lookup)==480 and len(seeds)==12 and len(CELLS)==8
 return lookup,seeds

def difference(lookup,seed,cell,control,field):
 condition,supply=cell
 return float(lookup[('JLC-R-RC2',condition,supply,seed)][field])-float(lookup[(control,condition,supply,seed)][field])

def aggregate(lookup,seeds,primary,out):
 fig,axes=plt.subplots(1,2,figsize=(7.1,3.05),sharey=True,layout='constrained')
 fig.suptitle('Seed contrasts  ·  mean and nominal 95% interval',fontsize=7.1,color='#53616a')
 for ax,field,title,letter in zip(axes,['coverage_pct','source_coverage_p5_pct'],['Fresh-state coverage','Source P5'],['a','b']):
  for pos,control in zip(range(3,-1,-1),CONTROLS):
   values=[np.mean([difference(lookup,seed,cell,control,field) for cell in CELLS]) for seed in seeds]
   r=one(primary,control=control,endpoint=field,cell='equal_weight_8cell')
   mu,lo,hi=check_interval(values,r)
   assert -5<min(values) and max(values)<28 and -5<lo<=hi<28
   marks(ax,pos,values,mu,lo,hi,BLUE,float(r['adjusted_p'])<.05)
  ax.axvline(0,color='#818a8f',linewidth=.75,linestyle='--');ax.set_xlim(-5,28)
  ax.set_xticks([-5,0,5,10,15,20,25]);ax.set_ylim(-.6,3.6);ax.set_yticks(range(3,-1,-1),CONTROL_LABELS);basic(ax,letter,title)
 axes[1].tick_params(labelleft=False)
 fig.supxlabel('JLC-R minus control (percentage points)',fontsize=8.2)
 save(fig,out,'fig3_aggregate')

def external_heatmap(lookup,seeds,tests,out):
 controls=['EADCM-CE','LANTERN-CE'];matrix=np.empty((8,2));entries={}
 for j,control in enumerate(controls):
  for i,(condition,supply) in enumerate(CELLS):
   cell=f'{condition}/{supply:.1f}';r=one(tests,control=control,endpoint='coverage_pct',cell=cell)
   v=[difference(lookup,seed,(condition,supply),control,'coverage_pct') for seed in seeds]
   mu,lo,hi=check_interval(v,r);matrix[i,j]=mu;entries[(i,j)]=(mu,lo,hi,float(r['adjusted_p']))
 assert matrix.min()>=-36 and matrix.max()<=36
 fig,ax=plt.subplots(figsize=(7.1,4.25),layout='constrained')
 im=ax.pcolormesh(np.arange(3)-.5,np.arange(9)-.5,matrix,cmap='RdBu',
                  norm=TwoSlopeNorm(vmin=-36,vcenter=0,vmax=36),
                  shading='flat',edgecolors='white',linewidth=.9)
 ax.set_xlim(-.5,1.5);ax.set_ylim(7.5,-.5)
 ax.set_xticks([0,1],['JLC-R − EADCM','JLC-R − LANTERN']);ax.xaxis.tick_top()
 ax.set_yticks(range(8),CELL_LABELS);ax.tick_params(axis='both',which='major',length=0,pad=6)
 for edge in ax.spines.values():edge.set_visible(False)
 for (i,j),(mu,lo,hi,p) in entries.items():
  color='white' if abs(mu)>22 else INK
  marker='†' if p>=.05 else ''
  ax.text(j,i-.12,f'{mu:+.1f}{marker}',ha='center',va='center',fontweight='bold',fontsize=8.5,color=color)
  ax.text(j,i+.18,f'[{lo:+.1f}, {hi:+.1f}]',ha='center',va='center',fontsize=7.2,color=color)
 bar=fig.colorbar(im,ax=ax,fraction=.035,pad=.025,ticks=[-30,-15,0,15,30]);bar.outline.set_visible(False)
 if bar.solids is not None:
  bar.solids.set_rasterized(False)
  # Matching edges remove viewer-dependent white seams between vector steps.
  bar.solids.set_edgecolor('face')
 bar.set_label('Coverage difference (pp)',fontsize=8);bar.ax.tick_params(labelsize=7)
 fig.suptitle('Mean paired difference  ·  [nominal 95% interval]  ·  † Holm-64 p ≥ 0.05',fontsize=7.2,color='#53616a')
 save(fig,out,'fig4_external',multipanel=False)

def factorial(raw,archive,out):
 lookup={(r['condition'],float(r['supply']),int(r['seed']),r['bits']):r for r in raw}
 seeds=sorted({k[2] for k in lookup});bits=[f'{i:03b}' for i in range(8)]
 assert len(lookup)==768 and len(seeds)==12
 design=[]
 for bit in bits:
  a,g,r=[2*int(x)-1 for x in bit];design.append([1,a,g,r,a*g,a*r,g*r,a*g*r])
 design=np.asarray(design,float);assert np.array_equal(design.T@design,8*np.eye(8))
 scale=np.asarray([2,2,2,4,4,4,8])
 fig,axes=plt.subplots(1,2,figsize=(7.1,3.85),sharey=True,layout='constrained')
 fig.suptitle('Seed contrasts  ·  mean and nominal 95% interval',fontsize=7.1,color='#53616a')
 for ax,field,title,letter,xlim,ticks in zip(axes,['coverage_pct','source_coverage_p5_pct'],
   ['Fresh-state coverage','Source P5'],['a','b'],[(-1.5,14),(-2.4,8.1)],
   [[0,3,6,9,12],[-2,0,2,4,6,8]]):
  estimates=[]
  for seed in seeds:
   blocks=[]
   for condition,supply in CELLS:
    y=np.asarray([float(lookup[(condition,supply,seed,b)][field]) for b in bits])
    blocks.append((design.T@y/8)[1:]*scale)
   estimates.append(np.mean(blocks,axis=0))
  estimates=np.asarray(estimates)
  ax.axhspan(3.5,6.5,facecolor='#f3f6f7',edgecolor='none',zorder=-2)
  for j,(factor,pos) in enumerate(zip(CONTRASTS,range(6,-1,-1))):
   r=one(archive,endpoint=field,contrast=factor);values=estimates[:,j]
   mu,lo,hi=check_interval(values,r,mean='mean')
   assert xlim[0]<min(values) and max(values)<xlim[1] and xlim[0]<lo<=hi<xlim[1]
   marks(ax,pos,values,mu,lo,hi,BLUE,float(r['p_holm14'])<.05)
  ax.axvline(0,color='#818a8f',linewidth=.75,linestyle='--');ax.set_xlim(*xlim);ax.set_xticks(ticks)
  ax.set_ylim(-.6,6.6);ax.set_yticks(range(6,-1,-1),FACTOR_LABELS);basic(ax,letter,title)
 axes[1].tick_params(labelleft=False)
 fig.supxlabel('Factorial contrast (percentage points)',fontsize=8.2)
 save(fig,out,'fig5_factorial')

def boundary(lookup,seeds,gaps,fair,out):
 gi={(r['condition'],float(r['supply']),int(r['seed'])):r for r in gaps if r['method']=='JLC-R-RC2'}
 assert len(gi)==96
 fig,axes=plt.subplots(1,2,figsize=(7.1,4.1),sharey=True,layout='constrained')
 fig.suptitle('Network seeds  ·  mean and nominal 95% interval',fontsize=7.1,color='#53616a')
 for pos,(condition,supply) in zip(range(7,-1,-1),CELLS):
  gv=np.asarray([float(gi[(condition,supply,seed)]['longest_observed_unfresh_p95_h']) for seed in seeds])
  assert np.isfinite(gv).all();mu=float(gv.mean());h=float(stats.t.ppf(.975,11)*gv.std(ddof=1)/math.sqrt(12))
  assert 0<gv.min() and gv.max()<300 and 0<mu-h<=mu+h<300
  marks(axes[0],pos,gv,mu,mu-h,mu+h,BLUE,True)
  cell=f'{condition}/{supply:.1f}'
  r=one(fair,control='LANTERN-CE',endpoint='source_coverage_jain',cell=cell)
  vals=[difference(lookup,seed,(condition,supply),'LANTERN-CE','source_coverage_jain') for seed in seeds]
  mu,lo,hi=check_interval(vals,r)
  assert -.25<min(vals) and max(vals)<.12 and -.25<lo<=hi<.12
  marks(axes[1],pos,vals,mu,lo,hi,BROWN,float(r['adjusted_p'])<.05)
 axes[0].set_xlim(0,300);axes[0].set_xticks([0,60,120,180,240,300]);axes[0].set_xlabel('Observed longest gap P95 (h)')
 axes[1].set_xlim(-.25,.12);axes[1].set_xticks([-.2,-.1,0,.1]);axes[1].axvline(0,color='#818a8f',linewidth=.75,linestyle='--')
 axes[1].set_xlabel('Jain difference, JLC-R − LANTERN')
 for ax,letter,title in zip(axes,['a','b'],['JLC-R monitoring gaps','Relative Jain fairness']):
  ax.set_yticks(range(7,-1,-1),CELL_LABELS);ax.set_ylim(-.6,7.6);basic(ax,letter,title)
 axes[1].tick_params(labelleft=False);save(fig,out,'fig6_boundaries')

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--package',type=Path,default=DEFAULT_PACKAGE)
 ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
 pkg=args.package.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
 result=pkg/'results';data=rows(result/'confirmation_480.csv');lookup,seeds=seed_index(data)
 aggregate(lookup,seeds,rows(result/'statistics/primary_holm8.csv'),out)
 external_heatmap(lookup,seeds,rows(result/'statistics/cell_primary_endpoints_holm64.csv'),out)
 factorial(rows(result/'rc2_supplement/factorial_seed_records_768.csv'),
           rows(result/'rc2_supplement/factorial_primary_holm14.csv'),out)
 boundary(lookup,seeds,rows(result/'monitoring_gaps_480.csv'),rows(result/'statistics/fairness_age_holm72.csv'),out)
 print('PASS: four vector figures generated; paired seed means and confidence intervals match saved statistics; no simulation.')

if __name__=='__main__':main()
