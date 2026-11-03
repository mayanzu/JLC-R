"""Adapt the supplied vector field scene and existing transaction core."""
from pathlib import Path
import argparse
import xml.etree.ElementTree as ET
import cairosvg
import pymupdf

ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--output',type=Path,required=True,help='New output directory outside this package')
OUTPUT=ap.parse_args().output.resolve()
if OUTPUT.is_relative_to(ROOT.resolve()):ap.error('Output must be outside the package')
OUTPUT.mkdir(parents=True,exist_ok=False)
ASSETS=ROOT/'assets'
NS='http://www.w3.org/2000/svg'
ET.register_namespace('',NS)

def panel(source,prefix,y,height,viewbox):
    svg=ET.parse(source).getroot()
    for parent in svg.iter():
        for child in list(parent):
            if child.tag!=f'{{{NS}}}text':continue
            content=''.join(child.itertext()).strip()
            if content.startswith(('Model: seed 1101','Schematic day cycle;', 'JLC-R  ·  TWO-TIMESCALE',
                                   'Grants reserve one local hop','response charged only if reached')):
                parent.remove(child)
            elif content=='Rejected request stays paid;':child.text='Rejected request remains paid.'
            elif content=='Member-to-CH before response':child.text='Member-to-CH admission'
            elif content=='Integer guards; Eqs. (11)–(15); η = 1.25':
                child.text='Guards; Eqs. (11)–(15); η = 1.25'
    ids=[e.get('id') for e in svg.iter() if e.get('id')]
    for item in svg.iter():
        for key,value in list(item.attrib.items()):
            if key=='id':item.set(key,prefix+value)
            else:
                for old in ids:
                    value=value.replace(f'url(#{old})',f'url(#{prefix}{old})')
                    if value=='#'+old:value='#'+prefix+old
                item.set(key,value)
        item.attrib.pop('filter',None)
    for item in list(svg.iter()):
        if item.tag==f'{{{NS}}}defs':
            for child in list(item):
                if child.tag==f'{{{NS}}}filter':item.remove(child)
    svg.attrib.update(x='0',y=str(y),width='1120',height=str(height),viewBox=viewbox,overflow='hidden')
    return svg

root=ET.Element(f'{{{NS}}}svg',{'width':'440pt','height':f'{1525*440/1120:.6f}pt',
                                'viewBox':'0 0 1120 1525','version':'1.1'})
ET.SubElement(root,f'{{{NS}}}rect',{'x':'0','y':'0','width':'1120','height':'1525','fill':'#ffffff'})
root.append(panel(ASSETS/'figure1_scene.svg','field_',0,755,'0 0 1120 755'))
h=ET.SubElement(root,f'{{{NS}}}text',{'x':'50','y':'780','font-family':'Arial, Helvetica, sans-serif',
  'font-size':'15','font-weight':'700','letter-spacing':'2','fill':'#555555'})
h.text='(c)  INHERITED TRANSACTION CORE'
root.append(panel(ASSETS/'figure1_core.svg','core_',785,740,'0 60 1120 740'))
svg=OUTPUT/'figure1_model_core.svg'
ET.ElementTree(root).write(svg,encoding='utf-8',xml_declaration=True)

core=panel(ASSETS/'figure1_core.svg','core_',0,740,'0 60 1120 740')
core.attrib.update(width='440pt',height=f'{740*440/1120:.6f}pt')
core_svg=OUTPUT/'core_cropped.svg'
ET.ElementTree(core).write(core_svg,encoding='utf-8',xml_declaration=True)
core_pdf=OUTPUT/'core_cropped.pdf'
cairosvg.svg2pdf(url=str(core_svg),write_to=str(core_pdf))

scene=pymupdf.open(ASSETS/'figure1_scene.pdf'); page=scene[0]
page.add_redact_annot(pymupdf.Rect(0,570,840,600),fill=False,cross_out=False)
for rect in page.search_for('Schematic day cycle; not measured irradiance'):
    page.add_redact_annot(rect,fill=False,cross_out=False)
page.apply_redactions(images=0,graphics=0)
scene_clean=OUTPUT/'scene_no_footer.pdf';scene.save(scene_clean,garbage=4,deflate=True);scene.close()
scene=pymupdf.open(scene_clean);core_doc=pymupdf.open(core_pdf);out=pymupdf.open()
p=out.new_page(width=440,height=1525*440/1120)
p.show_pdf_page(pymupdf.Rect(0,0,440,755*440/1120),scene,0,clip=pymupdf.Rect(0,0,840,755*840/1120))
p.insert_text((50*440/1120,780*440/1120),'(c)  INHERITED TRANSACTION CORE',
              fontname='hebo',fontsize=15*440/1120,color=(.333,.333,.333))
p.show_pdf_page(pymupdf.Rect(0,785*440/1120,440,1525*440/1120),core_doc,0)
pdf=OUTPUT/'figure1_model_core.pdf';out.save(pdf,garbage=4,deflate=True);out.close();scene.close();core_doc.close()
doc=pymupdf.open(pdf);doc[0].get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False).save(OUTPUT/'figure1_model_core.png')
print(svg);print(pdf)
