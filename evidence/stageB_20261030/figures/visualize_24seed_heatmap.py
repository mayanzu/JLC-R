"""Show 24-seed condition-specific coverage contrasts against external controls."""
from pathlib import Path
import argparse,csv,json,math
import numpy as np
from scipy import stats
import matplotlib as mpl
mpl.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm

mpl.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
 'font.size':8.,'axes.labelsize':8.,'xtick.labelsize':7.5,'ytick.labelsize':7.5,
 'svg.fonttype':'none','pdf.fonttype':42,'axes.linewidth':.7})
CELLS=[('SYNTHETIC_G20',1.),('SYNTHETIC_G20',.7),('WINTER_G20',1.),('WINTER_G20',.7),
       ('T2_G20',1.),('T2_G20',.7),('T3_G20',1.),('T3_G20',.7)]
CELL_LABELS=['Synthetic 1.0','Synthetic 0.7','T1 1.0','T1 0.7','T2 1.0','T2 0.7','T3 1.0','T3 0.7']
CONTROLS=['EADCM-CE','LANTERN-CE']
INK='#20272a'
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',required=True,type=Path)
 ap.add_argument('--output',required=True,type=Path)
 ap.add_argument('--compact',required=True,type=Path);ap.add_argument('--internal',required=True,type=Path)
 args=ap.parse_args()
 with (args.source/'cell_descriptive.csv').open(encoding='utf8',newline='') as f:raw=list(csv.DictReader(f))
 assert len(raw)==64
 table={(r['control'],r['endpoint'],r['condition'],float(r['supply'])):r for r in raw}
 assert len(table)==64
 def read(path):
  with path.open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))
 base=[r for r in read(args.compact/'run_metrics.csv') if r['study']=='confirmation' and
       r['method'] in ('JLC-R','EADCM-CE','LANTERN-CE')]
 extra=read(args.internal/'run_metrics.csv')
 assert len(base)==576 and len(extra)==384
 lookup={(r['method'],r['condition'],float(r['supply']),int(r['seed'])):r for r in base+extra}
 assert len(lookup)==960
 seeds=sorted({k[3] for k in lookup});assert len(seeds)==24
 ps=[]
 for r in raw:
  field=r['endpoint'];control=r['control'];condition=r['condition'];supply=float(r['supply'])
  v=np.array([float(lookup[('JLC-R',condition,supply,seed)][field])-
              float(lookup[(control,condition,supply,seed)][field]) for seed in seeds])
  mean=float(v.mean());sd=float(v.std(ddof=1))
  assert math.isclose(mean,float(r['mean_difference']),rel_tol=1e-9,abs_tol=1e-8)
  if sd==0:
   assert r['ci95_low']=='' and r['ci95_high']=='' and r['p']==''
   ps.append(1.)
  else:
   se=sd/math.sqrt(24);half=float(stats.t.ppf(.975,23)*se)
   prob=float(2*stats.t.sf(abs(mean/se),23))
   assert all(math.isclose(v,float(r[k]),rel_tol=1e-9,abs_tol=1e-8)
              for k,v in [('ci95_low',mean-half),('ci95_high',mean+half),('p',prob)])
   ps.append(prob)
 order=sorted(range(64),key=lambda i:ps[i]);adjusted=[0.]*64;running=0.
 for rank,i in enumerate(order):
  running=max(running,(64-rank)*ps[i]);adjusted[i]=min(1.,running)
 assert all(math.isclose(adjusted[i],float(r['holm64_adjusted_p']),rel_tol=1e-9,abs_tol=1e-8)
            for i,r in enumerate(raw))
 matrix=np.empty((8,2));entries={}
 for j,control in enumerate(CONTROLS):
  for i,(condition,supply) in enumerate(CELLS):
   r=table[(control,'coverage_pct',condition,supply)]
   mean=float(r['mean_difference']);lo=None if r['ci95_low']=='' else float(r['ci95_low'])
   hi=None if r['ci95_high']=='' else float(r['ci95_high']);p=float(r['holm64_adjusted_p'])
   assert int(r['n'])==24 and 0<=p<=1
   assert (lo is None and hi is None) or (lo<=mean<=hi)
   matrix[i,j]=mean;entries[(i,j)]=(mean,lo,hi,p,r['undefined_t']=='True')
 bound=5*math.ceil(max(5.,float(np.max(np.abs(matrix))))/5)
 out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
 fig,ax=plt.subplots(figsize=(7.1,4.25),layout='constrained')
 im=ax.pcolormesh(np.arange(3)-.5,np.arange(9)-.5,matrix,cmap='RdBu',
                  norm=TwoSlopeNorm(vmin=-bound,vcenter=0,vmax=bound),
                  shading='flat',edgecolors='white',linewidth=.9)
 ax.set_xlim(-.5,1.5);ax.set_ylim(7.5,-.5)
 ax.set_xticks([0,1],['JLC-R − EADCM','JLC-R − LANTERN']);ax.xaxis.tick_top()
 ax.set_yticks(range(8),CELL_LABELS);ax.tick_params(axis='both',which='major',length=0,pad=6)
 for edge in ax.spines.values():edge.set_visible(False)
 for (i,j),(mean,lo,hi,p,undefined) in entries.items():
  color='white' if abs(mean)>.62*bound else INK
  marker='‡' if undefined else '†' if p>=.05 else ''
  interval='interval undefined' if lo is None else f'[{lo:+.1f}, {hi:+.1f}]'
  ax.text(j,i-.12,f'{mean:+.1f}{marker}',ha='center',va='center',fontweight='bold',fontsize=8.5,color=color)
  ax.text(j,i+.18,interval,ha='center',va='center',fontsize=7.2,color=color)
 bar=fig.colorbar(im,ax=ax,fraction=.035,pad=.025);bar.outline.set_visible(False)
 if bar.solids is not None:
  bar.solids.set_rasterized(False);bar.solids.set_edgecolor('face')
 bar.set_label('Coverage difference (pp)',fontsize=8);bar.ax.tick_params(labelsize=7)
 fig.suptitle('Mean paired difference  ·  [nominal 95% interval]  ·  † Holm-64 p ≥ 0.05',
              fontsize=7.2,color='#53616a')
 fig.canvas.draw()
 fig.savefig(out/'fig4_external.svg',facecolor='white')
 fig.savefig(out/'fig4_external.pdf',facecolor='white')
 fig.savefig(out/'fig4_external.png',dpi=600,facecolor='white')
 fig.savefig(out/'fig4_external.tiff',dpi=600,facecolor='white')
 plt.close(fig)
 (out/'data_contract.json').write_text(json.dumps({'status':'PASS','network_seeds_per_cell':24,
  'shown_cells':16,'full_corrected_family':64,'scope':'post hoc exploratory',
  'uncertainty':'nominal paired t 95% interval; undefined for zero-variance differences',
  'alignment':'not applicable: one semantic heatmap panel with colorbar',
  'intentional_overlay':'mean and interval labels are centered inside their heatmap cells'},indent=2),encoding='utf8')
 print('Figure 4 created; post hoc Holm-64 family retained in full.')
if __name__=='__main__':main()
