from pathlib import Path
import json
import pymupdf
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[2]
pdf = pymupdf.open(root/'output/pdf/hierarchical_aws_throughput.pdf')
out = root/'tmp/pdfs/hierarchical_current_fleet_qa'
pages = sorted(out.glob('page-*.png'))
assert len(pages)==len(pdf), (len(pages),len(pdf))
summary=[]
for i,page in enumerate(pdf):
    blocks=page.get_text('blocks')
    outside=[list(b[:4]) for b in blocks
             if b[0]<24 or b[1]<20 or b[2]>page.rect.width-24 or b[3]>page.rect.height-20]
    text=page.get_text()
    summary.append(dict(page=i+1,characters=len(text),edge_blocks=outside,
                        unresolved_markers='??' in text))
for start in range(0,len(pages),4):
    canvas=Image.new('RGB',(1530,2040),'#d9dfe4')
    draw=ImageDraw.Draw(canvas)
    for j,path in enumerate(pages[start:start+4]):
        im=Image.open(path).convert('RGB')
        im.thumbnail((735,960))
        x,y=(j%2)*765+15,(j//2)*1020+40
        canvas.paste(im,(x,y))
        draw.text((x,y-24),f'Page {start+j+1}',fill='#17324d')
    canvas.save(out/f'contact-{start//4+1:02d}.png')
(out/'checks.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(dict(pages=len(pdf),edge_issues=sum(bool(s['edge_blocks']) for s in summary),
                      unresolved_pages=sum(s['unresolved_markers'] for s in summary)),indent=2))
