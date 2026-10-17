from pathlib import Path
import json
import pymupdf
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[2]
pdf = pymupdf.open(root / 'output/pdf/interactive_batch_oram_report.pdf')
out = root / 'tmp/pdfs/interactive_report_qa'
out.mkdir(parents=True, exist_ok=True)
pages = []
summary = []
for i, page in enumerate(pdf):
    pix = page.get_pixmap(dpi=120)
    path = out / f'page-{i + 1:02d}.png'
    pix.save(path)
    pages.append(path)
    blocks = page.get_text('blocks')
    outside = [b[:4] for b in blocks if b[0] < 24 or b[1] < 20 or b[2] > page.rect.width - 24 or b[3] > page.rect.height - 20]
    text = page.get_text()
    summary.append({'page': i + 1, 'characters': len(text), 'edge_blocks': outside, 'unresolved_markers': '??' in text})
for start in range(0, len(pages), 4):
    canvas = Image.new('RGB', (1440, 1920), '#d9dfe4')
    draw = ImageDraw.Draw(canvas)
    for j, path in enumerate(pages[start:start + 4]):
        im = Image.open(path).convert('RGB')
        im.thumbnail((696, 908))
        x, y = (j % 2) * 720 + 12, (j // 2) * 960 + 38
        canvas.paste(im, (x, y))
        draw.text((x, y - 24), f'Page {start + j + 1}', fill='#17324d')
    canvas.save(out / f'contact-{start // 4 + 1:02d}.png')
(out / 'checks.json').write_text(json.dumps(summary, indent=2))
print(json.dumps({'pages': len(pdf), 'edge_issues': sum(bool(s['edge_blocks']) for s in summary), 'unresolved_pages': sum(s['unresolved_markers'] for s in summary), 'render_directory': str(out)}, indent=2))
