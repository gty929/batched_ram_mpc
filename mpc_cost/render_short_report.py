"""Build the five-page colleague briefing from the 13 October cost study.

Run from the repository root with reportlab installed. The optional workspace
dependency directory is used by the artifact-generation environment.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tmp' / 'pdf-deps'))
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT = ROOT / 'output' / 'pdf' / 'mpc_oram_cost_report_short.pdf'
NAVY, TEAL = HexColor('#17324D'), HexColor('#176B73')
INK, MUTED, PALE = HexColor('#263746'), HexColor('#5A6875'), HexColor('#EEF4F6')
FONT_DIR = Path('C:/Windows/Fonts')
for name, file in [('Brief', 'calibri.ttf'), ('BriefBold', 'calibrib.ttf'), ('BriefItalic', 'calibrii.ttf')]:
    pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
pdfmetrics.registerFontFamily('Brief', normal='Brief', bold='BriefBold', italic='BriefItalic', boldItalic='BriefBold')

styles = {
    'body': ParagraphStyle('body', fontName='Brief', fontSize=11.2, leading=15, textColor=INK, spaceAfter=8),
    'small': ParagraphStyle('small', fontName='Brief', fontSize=9.4, leading=12, textColor=MUTED, spaceAfter=6),
    'title': ParagraphStyle('title', fontName='BriefBold', fontSize=25, leading=28, textColor=NAVY, spaceAfter=12),
    'head': ParagraphStyle('head', fontName='BriefBold', fontSize=19, leading=23, textColor=NAVY, spaceAfter=12),
    'sub': ParagraphStyle('sub', fontName='BriefBold', fontSize=12.8, leading=16, textColor=TEAL, spaceBefore=7, spaceAfter=5),
    'label': ParagraphStyle('label', fontName='BriefBold', fontSize=10, leading=13, textColor=TEAL, spaceAfter=8),
    'cell': ParagraphStyle('cell', fontName='Brief', fontSize=10.5, leading=13, textColor=INK),
    'th': ParagraphStyle('th', fontName='BriefBold', fontSize=10.2, leading=12.5, textColor=white),
    'callout': ParagraphStyle('callout', fontName='BriefBold', fontSize=12.1, leading=16, textColor=NAVY),
}
story = []
def p(text, style='body'):
    return Paragraph(text, styles[style])
def add(text, style='body'):
    story.append(p(text, style))
def section(text):
    add(text, 'sub')
def table(rows, widths):
    data = [[p(str(c), 'th' if i == 0 else 'cell') for c in row] for i, row in enumerate(rows)]
    t = Table(data, colWidths=widths, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [PALE, white]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LINEBELOW', (0, -1), (-1, -1), 0.6, HexColor('#CBD8DE')),
    ]))
    story.extend([t, Spacer(1, 9)])
def callout(text):
    t = Table([[p(text, 'callout')]], colWidths=[516])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), PALE),
        ('BOX', (0,0), (-1,-1), 0.6, HexColor('#CBD8DE')),
        ('LEFTPADDING',(0,0),(-1,-1),12), ('RIGHTPADDING',(0,0),(-1,-1),12),
        ('TOPPADDING',(0,0),(-1,-1),11), ('BOTTOMPADDING',(0,0),(-1,-1),11),
    ]))
    story.extend([t, Spacer(1, 11)])
def page(label, title):
    if story:
        story.append(PageBreak())
    add(label.upper(), 'label')
    add(title, 'head')

# 1. A stand-alone executive summary, with the conditional status beside the cost.
add('COLLEAGUE BRIEFING  /  14 OCTOBER 2026', 'label')
add('Cost of a ten-party<br/>private database', 'title')
add('Five-page summary of the 13 October 2026 construction and capacity study.', 'small')
callout('Recommendation: continue with batched interactive MPC, and make reducing metadata and private-routing costs the next research milestone. A practical deployment budget still needs an end-to-end benchmark.')
section('The service we are evaluating')
add('The target is <b>10,000 key-value reads per second</b>, with mean response time below five seconds, for either 2<super>28</super> records (268 million) or 2<super>32</super> records (4.29 billion). Keys and values are each 32 bytes. Ten parties jointly compute on secret-shared data, tolerating up to four malicious parties with security with abort.')
section('Headline results')
table([
    ['Conditional model result', '2<super>28</super> records', '2<super>32</super> records'],
    ['Interactive MPC: annual EC2 cost', '<b>$2.33 billion</b>', '<b>$5.16 billion</b>'],
    ['Interactive MPC: mean response', '4.77 seconds', '3.97 seconds'],
    ['Garbled RAM: annual network EC2 + SSD', '<b>$10.33-18.52 billion</b>', '<b>$21.59-38.71 billion</b>'],
    ['Garbled RAM: mean response', 'Not established', 'Not established'],
], [244, 136, 136])
add('Annual costs cover <b>all ten parties</b> at a sustained 10,000 reads/s. The garbled results use the prepared horizons that minimize the upper cost endpoint in the tested grid. Their ranges describe network-role imbalance; they do not bound omitted costs.', 'small')
section('What these numbers mean')
add('The interactive reference is limited mainly by local arithmetic; memory capacity also constrains the larger database. In the garbled model, recurring preprocessing dominates traffic, while retaining a long prepared execution can make SSD capacity the largest expense.')
add('These are <b>conditional research estimates</b>, not measured deployment costs or lower bounds on private lookup. The models use different scheduling and CPU assumptions. Their comparison supports a research direction, but does not establish a universal protocol ranking.')

# 2. Enough architecture to make the fleet and cost intelligible.
page('02 / Interactive design', 'What the interactive estimate includes')
add('The working design places two cuckoo hash tables over binary Circuit OPRAM, a batched oblivious-memory construction. Every lookup probes both tables in parallel, checks the full key, and returns a value and membership result. Oblivious access hides the requested locations; even logical reads update the private placement state.')
add('A central dispatcher forms batches before assigning them to independent replicas. Within each replica, several machines per party divide the state and computation. Each replica carries a complete, independently evolving ORAM state. This replication is a major reason the fleet is much larger than the raw database suggests.')
table([
    ['Selected configuration', '2<super>28</super> records', '2<super>32</super> records'],
    ['Raw key-value data', '16 GiB', '256 GiB'],
    ['Queries per batch / map packing', '128 / 128', '512 / 256'],
    ['Secure outputs per read', '3.36 million', '6.10 million'],
    ['Sent data per read, per party', '629.2 MB', '1,085.8 MB'],
    ['Persistent state per party, per replica', '1.88 TiB', '30.05 TiB'],
    ['Machines per party, per replica', '6', '96'],
    ['Independent replica groups', '530', '110'],
    ['Total EC2 instances, all parties', '<b>31,800</b>', '<b>105,600</b>'],
], [260, 128, 128])
add('MB is decimal; GiB and TiB are binary units. Traffic includes framing. Persistent state excludes scratch and preprocessing buffers. Map packing is the number of labels per recursive record; the interactive ORAM tree remains binary.', 'small')
section('Why batching alone does not solve the cost')
add('Batching exposes parallelism, but private comparisons, metadata conversion, payload movement, recursive-map updates and eviction still require substantial work. A private dot product can communicate one reduced output while performing many local multiplications. Counting only communicated outputs therefore misses a major cost driver.')
add('At 10,000 reads/s, forming a 128-query batch adds only about <b>6.35 milliseconds</b> of mean waiting. The several-second response time comes mainly from computation and dependent exchanges. Moving work offline may reduce response latency, but its steady-state production must still be paid for.')
add('The larger model has a lower selected latency because memory requirements force a larger parallel allocation. This is not evidence that increasing the database size improves performance. Both configurations are grid-search selections, not proven global optima.', 'small')

# 3. Resource diagnosis and the most useful alternative baseline.
page('03 / Cost drivers', 'Local computation is the first bottleneck')
add('For the smaller interactive reference, CPU demand exceeds network and memory demand. The model overlaps these resources, then adds dependent communication phases:')
table([
    ['Per 128-query batch', 'Modeled time'],
    ['CPU, including preprocessing', '<b>3.45 s</b>'],
    ['Network, including internal routing', '2.22 s'],
    ['RAM traffic', '0.09 s'],
    ['Dependent exchanges', '1.29 s'],
    ['Service time: 1.29 + max(3.45, 2.22, 0.09)', '<b>4.74 s</b>'],
], [380, 136])
add('Preprocessing accounts for about 36% of CPU work and 24% of transmitted bytes; most remaining work is online. These are derived allocations that can change with scheduling. At 2<super>32</super> records, RAM capacity also forces more machines.')
section('A low-communication scan can still be expensive')
add('A full-key scan compares the query with every record. An indexed two-dimensional scan uses private dot products to reduce communication but still processes the entire arrays locally. For the smaller database:')
table([
    ['Per read, per party', 'Interactive OPRAM', 'Full-key scan', 'Indexed 2D scan'],
    ['CPU proxy, billion operations', '0.340', '3,059', '25.79'],
    ['Sent data, decimal GB', '0.629', '6,075', '0.041'],
], [177, 113, 113, 113])
add('The indexed scan uses about 6.5% of the reference traffic but <b>76 times its local arithmetic</b>. It remains a useful bandwidth-oriented benchmark if batched matrix kernels outperform the assumed CPU proxy.')
section('Which assumptions move the answer most?')
add('<b>CPU and scheduling.</b> For 2<super>28</super> records, independently optimized faster- and slower-CPU scenarios cost $1.52 billion and $6.06 billion/year. Disabling resource overlap gives $3.96 billion/year. These are scenario results, not confidence limits.')
add('<b>Placement.</b> The headline estimates assume same-availability-zone placement without marginal inter-party transfer fees. Cross-zone traffic is charged at $0.02 per transmitted GB across both endpoints in the retained price snapshot. Network placement can overwhelm compute savings.')
add('Central assumptions include 2 billion weighted field operations/s per 64 vCPUs, 0.2 ms per exchange, 65% NIC efficiency and 70% operating utilization. None is a measured guarantee for this MPC service.', 'small')

# 4. Keep the important horizon distinction without the full gate derivation.
page('04 / Garbled-RAM comparison', 'Preprocessing and retention dominate')
add('Garbled RAM prepares an encoded computation before queries are evaluated. Few online rounds do not imply low total operating cost: at 10,000 reads/s, the prepared computation must be replenished continuously. In this model, <b>about 97.7% of transmitted bytes are preprocessing</b>.')
add('The estimate assumes networking is the throughput bottleneck and sets garbled-stack and associated adaptor costs to zero under a proposed migration of a two-party optimization. This is a conditional multiparty construction, not an executed ten-party benchmark. CPU evaluation and a five-second response time have not been established.')
section('The prepared horizon is a major budget choice')
add('An epoch is the number of future queries prepared in advance; it is not a batch that waits to fill. Longer epochs amortize setup-related work over more queries but retain more garbled tables. The reference keeps two complete epochs, representing the current and next execution, plus encoded state.')
table([
    ['Database / policy', 'Hours prepared per epoch', 'SSD per year', 'Total per year'],
    ['2<super>28</super>: reference and selected horizon', '14.91', '$2.14B', '$10.33-18.52B'],
    ['2<super>32</super>: reference horizon', '238.61', '$44.44B', '$55.07-65.69B'],
    ['2<super>32</super>: selected shorter horizon', '14.91', '$4.46B', '$21.59-38.71B'],
], [200, 98, 86, 132])
add('B denotes billion USD; totals include network-capacity EC2 plus SSD for all parties. The selected horizon minimizes the upper endpoint within the tested grid. The range reflects party send/receive imbalance, not a complete uncertainty bound.', 'small')
add('Shortening the larger case to about 15 hours substantially lowers the estimate. The reference SSD footprint is therefore a retention-policy consequence, not an unavoidable storage lower bound. Shorter epochs also increase recurring preparation per query, so the shortest horizon is not automatically cheapest.')
section('What must be solved before this becomes a service estimate')
add('The ledger does not fully price <b>malicious correlation generation, joint hidden-state initialization, secure epoch renewal, or the necessary representation conversions</b>. Accepting a continuing stream of external client queries also needs a service-security argument beyond the cited standalone protocol.')
add('Securely carrying a live state into the next epoch requires more than re-encoding its bits. The model also leaves local evaluation speed, SSD throughput, machine allocation and cloud capacity unvalidated. The reported upper endpoint consequently does not cap the eventual deployment cost.')

# 5. Clear decision and evidence needed, with compact provenance.
page('05 / Recommended next steps', 'Turn the cost model into a measured budget')
add('Retain interactive arithmetic compilation as the working direction. The next milestone should be a complete malicious ten-party recursive-read benchmark that shows where work can be reduced and what throughput is sustainable.')
section('1. Measure one complete batch')
add('Include preprocessing replenishment, exact comparisons and conversions, private routing, duplicate map-block updates, misses and eviction. Record per-read communication, local work, memory and dependent phases. Measure online latency separately from the total resources needed to sustain the service.')
section('2. Optimize the expensive operations')
add('Prioritize metadata representation and private routing; specialize pool cleanup and retrieval rather than treating every operation as a general sort. Tune recursive-map packing and the flat base together. Benchmark the indexed scan with batched matrix kernels as a serious alternative. Any improved schedule must preserve state-update dependencies.')
section('3. Reprice only after the implementation is calibrated')
add('Replace proxy coefficients with measured traces, rerun the parameter search, and test queues and network tails on the intended topology. Validate lifetime stash/overflow bounds, input consistency and initialization. Confirm cloud capacity and operational requirements before committing to a production budget.')
section('The scale of improvement required')
add('The smaller reference produces about 3.36 million secure outputs/read. Reaching 30,000 would require roughly a <b>100-fold reduction</b>; position-map packing alone does not justify that expectation. Even the following simplified targets have material annual costs:')
table([
    ['Optimization target', 'Assumed CPU + NIC cost, all ten parties'],
    ['10,000 outputs/read', '$2.93 million/year'],
    ['30,000 outputs/read', '$8.80 million/year'],
], [215, 301])
add('These are targets, not achieved designs or complete budgets. The envelope omits RAM/state provisioning, latency scheduling, initialization and additional conversion/routing costs.', 'small')
add('<b>Scope and budget limits.</b> This is a flat key-value read study, not a write service or Merkle-proof retrieval system. The main frontend accepts privately supplied hash indices. Interactive EC2 figures exclude EBS/backups, setup, client transfer, orchestration, failover reserve, support, taxes and engineering; the garbled totals add only the stated SSD capacity policy.')
add('<b>Basis.</b> Condensed from <i>Honest-majority MPC database: construction and cost model</i>, updated 13 October 2026: sections 1-5 and 9-12. Figures retain its AWS US East snapshot published 12 October 2026; prices were not refreshed for this brief. Detailed derivations, protocol sources and reproduction commands remain in the full report and <font name="BriefItalic">mpc_cost/README.txt</font>.', 'small')

def decorate(c, doc):
    c.saveState()
    c.setStrokeColor(TEAL)
    c.setLineWidth(1.4)
    c.line(48, 750, 564, 750)
    c.setFont('Brief', 9)
    c.setFillColor(MUTED)
    c.drawString(48, 763, 'TEN-PARTY MPC DATABASE')
    c.drawRightString(564, 763, 'Conditional cost study')
    c.setStrokeColor(HexColor('#CBD8DE'))
    c.setLineWidth(0.5)
    c.line(48, 40, 564, 40)
    c.setFont('Brief', 8.5)
    c.drawString(48, 26, 'Colleague briefing | Based on the 13 October 2026 study')
    c.drawRightString(564, 26, f'{doc.page} / 5')
    c.restoreState()

OUT.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(str(OUT), pagesize=(612,792), leftMargin=48, rightMargin=48,
                        topMargin=57, bottomMargin=53, title='Ten-party MPC database: five-page cost briefing',
                        author='Research briefing', subject='Condensed conditional cost study, 14 October 2026')
doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
print(OUT)
