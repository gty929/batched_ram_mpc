"""Build the seven-page colleague briefing, updated 16 October 2026.

Run from the repository root with reportlab installed. The optional workspace
dependency directory is used by the artifact-generation environment.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tmp' / 'pdf-deps'))
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT = ROOT / 'output' / 'pdf' / 'mpc_oram_cost_report_short.pdf'
RESULTS = ROOT / 'mpc_cost' / 'results'
two_party = json.loads((RESULTS / 'two_party_comparison.json').read_text())
serial = json.loads((RESULTS / 'two_party_serial_comparison.json').read_text())

def batch_case(log_records, batch=256):
    row = next(r for r in two_party['rows'] if r['log_records'] == log_records)
    return next(c for c in row['batch_cases'] if c['circuit']['batch'] == batch)

def serial_case(log_records, seconds=0.1):
    row = next(r for r in serial['rows'] if r['log_records'] == log_records)
    return next(c for c in row['complete_service_time_scenarios']
                if c['assumed_state_service_seconds'] == seconds)

current = [batch_case(n) for n in (28, 32)]
larger_batch = [batch_case(n, 1024) for n in (28, 32)]
annual = [c['network_capacity_and_io_usd_year'] / 1e6 for c in current]
cpu_annual = [next(s['usd_year'] for s in c['cpu_sensitivities']
                  if s['assumed_sustained_ands_per_node_second'] == 200e6) / 1e6
              for c in current]
service_ms = current[0]['one_state_max_batch_service_seconds_at_70pct_util'] * 1000

def pair(values, precision=2):
    return '/'.join(f'{v:.{precision}f}' for v in values)

def state_size(value):
    return f'{value / 1e15:.3f} PB' if value >= 1e15 else f'{value / 1e12:.3f} TB'

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
add('COLLEAGUE BRIEFING  /  16 OCTOBER 2026', 'label')
add('Cost of a private database', 'title')
add('Proposal focus: two-party semi-honest computation. Historical ten-party analysis is retained on pages 2-4.', 'small')
callout('Current work: Garbled RAM. Proposed work: interactive 2PC with Circuit OPRAM. Public batch-path ordering and authorized output reordering cost no AND gates; this audit establishes no further numerical saving in the existing template.')
section('The service we are evaluating')
add('The target is <b>10,000 flat key-value reads per second</b>, with mean response below five seconds, for 2<super>28</super> or 2<super>32</super> records. Keys and values are each 32 bytes; both parties are in the same AWS availability zone. Merkle proof retrieval is outside this estimate.')
section('Two-party proposal comparison')
table([
    ['Conditional model result', '2<super>28</super> records', '2<super>32</super> records'],
    ['Current: GRAM, assumed 100 ms state service',
     *[f'<b>${serial_case(n)["price"]["network_plus_capacity_usd_year"] / 1e9:.3f} billion</b>' for n in (28, 32)]],
    ['Proposed: interactive, NIC + SSD / I/O', *[f'<b>${v:.2f} million</b>' for v in annual]],
    ['Proposed: with assumed 200M AND/s/node', *[f'${v:.2f} million' for v in cpu_annual]],
], [244, 136, 136])
add('Annual costs include both parties. GRAM includes network, SSD capacity and attachment hosts; its CPU, full I/O and secure renewal remain unpriced. Interactive figures include modeled persistent I/O. Different unmeasured service assumptions prevent interpreting their ratio as a demonstrated saving.', 'small')
section('What the routing audit establishes')
add('Once duplicate-safe old paths are revealed, both parties can sort them and reorder their encoded request UIDs locally. Authorized outputs can be decoded and reordered locally. These public operations had no separate charge in the template, so the recalculated total is unchanged. The charged inverse routes belong to private pool sorting and extraction; reducing them requires a concrete replacement circuit.')
add(f'Streamed Circuit OPRAM avoids future-program retention and exposes batch parallelism. The proposed row assumes batch 256 and one state, requiring complete service within <b>{service_ms:.2f} ms</b>. Neither that timing nor the CPU rate has been measured. Page 5 explains the sequential GRAM constraint; page 6 details the interactive estimate.', 'small')

# 2. Enough architecture to make the fleet and cost intelligible.
page('02 / Historical ten-party interactive design', 'What the earlier estimate includes')
add('Archived ten-party malicious model (up to four corruptions, security with abort): <b>$2.33B/$5.16B per year</b> at modeled mean responses of <b>4.77/3.97 seconds</b>, for the two database sizes. These are separate historical estimates, not the proposed two-party budget.', 'small')
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
page('03 / Historical ten-party cost drivers', 'Local computation is the first bottleneck')
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
page('04 / Historical ten-party garbled-RAM model', 'Preprocessing and retention dominate')
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
add('Securely carrying a live state into the next epoch requires more than re-encoding its bits. The model also leaves local evaluation speed, SSD throughput, machine allocation and cloud capacity unvalidated. <b>The sequential-throughput issue on page 5 also prevents treating these resource figures as a validated 10,000-read/s fleet.</b> Two-party coefficients cannot be substituted directly into this malicious model.')

# 5. Sequential service, not aggregate core capacity, determines state copies.
page('05 / Two-party semi-honest: garbled merge', 'Sequential evaluation drives replication')
add('Both two-party models use two cuckoo tables of 2N slots, two probes and an eight-entry stash; each stored payload has 513 bits. Accounting uses 128-bit labels, FreeXOR and <b>32 bytes per AND</b> (half gates), with 16-byte merge joins counted separately. This is a backend substitution, not the artifact\'s native ThreeHalves gate size.')
section('What PicoGRAM establishes [1, 2]')
add('PicoGRAM describes its evaluator as mostly sequential. Its online-optimized variant <b>already avoids DDH/SIMD garbling</b>: a 64-bit RAM access takes 9.73 ms at 2<super>16</super> words; 25 ms at 2<super>24</super> and 41 ms at 2<super>30</super> are paper extrapolations. These are not timings of garbled merge or of a two-probe, 64-byte lookup. Removing DDH therefore does not establish a faster evaluator; merge adds PRF work.')
add('Recursive maps must return old positions before outer paths can be fetched; reinsertion and eviction modify shared state. The two cuckoo tables can run on two lanes, but adding cores does not give linear speedup for successive accesses to either table. SIMD and inter-request overlap need an implemented schedule.')
callout('Required copies S = ceil(10,000 x L / 0.70), where L is the complete state service time in seconds, including maintenance before the next query. 128 copies require L <= 8.96 ms; 500 require L <= 35 ms.')
table([
    ['Assumed service per KV', 'Required states', 'Annual 2<super>28</super>', 'Annual 2<super>32</super>'],
    ['100 ms', '1,429', '$0.991B', '$13.563B'],
    ['500 ms', '7,143', '$4.307B', '$65.839B'],
    ['1 second', '14,286', '$8.378B', '$130.621B'],
], [164, 106, 123, 123])
add('Conditional <b>network EC2 + SSD capacity and attachment hosts</b>, both parties. Each row reoptimizes the prepared horizon at a fixed, unmeasured L. Two complete epochs, literal labels and separate one-time programs per state are retained. CPU, full SSD I/O, temporary space, initialization and secure renewal are additional; these are not GRAM cost lower bounds.', 'small')
section('Communication savings do not establish runtime')
add('At horizon T = 2N and map packing 8, the source-derived model produces <b>61.47/80.38 MB of tables per lookup</b>, including merge and output bindings. Live labels occupy 49.39/799.91 TB per party per state. The literal artifact\'s full-horizon merge computation is impractical at these sizes; small-window resets and handoff need implementation. Aggregate hash throughput cannot replace the service-time constraint.')
add('For scale, a hypothetical 64-call reset window gives 30.40M/41.28M evaluator merge hashes per lookup at T = 2N. At 40 cycles/hash and 2.2 GHz, that is 0.55/0.75 seconds of scalar merge work alone. Two table lanes can overlap; SIMD may help. This is a work sensitivity with unimplemented reset/handoff and assumed visit statistics, not a measured latency or circuit-depth bound.', 'small')

# 6. Streaming and batch parallelism, with the one-state feasibility condition.
page('06 / Two-party semi-honest: streamed batches', 'Trade retained programs for interaction')
add('The evaluator reveals duplicate-safe old fetch positions or independent dummy paths to the garbler, which streams the next circuit. Both parties can sort these public paths and reorder encoded request UIDs locally: <b>no garbled Waksman network is needed</b>. Fresh replacement positions remain hidden [3].')
section('Public ordering is free; private pool extraction is unresolved')
add('Authorized data outputs and selected old recursive-map positions may be decoded and restored to request order locally. A public permutation also reorders encoded outputs without AND gates. These operations had no separate charge in the template. Its inverse-route allowances instead accompany hidden pool sorting, state alignment and result extraction. <b>They are not proved necessary</b>, but removing them requires a complete alternative extraction/compaction circuit, including conflicts and internal state updates.')
section('Explicit Boolean template, batch 256')
table([
    ['Per lookup / annual resource model', '2<super>28</super> records', '2<super>32</super> records'],
    ['AND gates per lookup', *[f'{c["circuit"]["ands_per_query"] / 1e6:.3f} million' for c in current]],
    ['Garbled table bytes per lookup', *[f'{c["circuit"]["table_bytes_per_query"] / 1e6:.1f} MB' for c in current]],
    ['Live label state per party, one copy', *[state_size(c['circuit']['label_state_bytes_per_party']) for c in current]],
    ['NIC + SSD capacity / modeled I/O, per year', *[f'<b>${v:.2f} million</b>' for v in annual]],
], [260, 128, 128])
add(f'Both parties, one state, decimal units. Recalculation preserves these totals: the verified change is 0 ANDs. At an assumed effective 200M AND/s/node, CPU provisioning raises totals to ${pair(cpu_annual)}M. Pool composition, recursive updates and eviction remain planning allowances; this is not an executed trace or a proved finite upper bound.', 'small')
add(f'Fresh positions are XORs of private party inputs; FreeXOR adds no ANDs. Labels and OT are charged separately: fresh-position input traffic is {pair([c["price"]["joint_position_input_bytes_per_query"] / 1e3 for c in current])} KB/lookup. Joint hidden initialization remains unpriced.', 'small')
section('Batch latency must justify the state count')
add(f'<b>S = ceil(10,000 x L<sub>batch</sub> / (0.70 x B)).</b> One state at B = 256 requires service <= {service_ms:.2f} ms. At B = 1,024 the limit is 71.68 ms: a 50 ms batch needs one state; 500 ms needs seven. CPU throughput alone does not establish these latencies.')
add(f'At B = 1,024, the unchanged template gives {pair([c["circuit"]["table_bytes_per_query"] / 1e6 for c in larger_batch], 1)} MB/lookup and ${pair([c["network_capacity_and_io_usd_year"] / 1e6 for c in larger_batch])}M/year. Tables are streamed and discarded; live state remains. Compact XOR shares could reduce the 16-byte-per-bit state representation, with conversion/OT costs still to price.', 'small')

# 7. Decision, calibration work, and compact primary-source provenance.
page('07 / Recommended next steps and sources', 'Measure service time before choosing a fleet')
add('Focus the proposal on <b>two-party semi-honest computation</b>: current Garbled RAM versus proposed interactive Circuit OPRAM. Its opportunity is batch parallelism and less retained garbled code. Public request/output ordering is free, but does not by itself eliminate private pool processing.')
section('1. Measure a complete state cycle')
add('For garbled merge, measure both table probes, recursive maps, PRFs, label/table I/O, eviction and the proposed reset/renewal mechanism. Report state service time and active core-seconds separately. For batch OPRAM, measure full batch depth, dependent exchanges and worker scaling, including duplicate queries, misses and map-block conflicts.')
section('2. Optimize, then enforce the throughput constraint')
add('Replace the generic pool inverse-route allowances with a concrete extraction and compaction design before subtracting them. Preserve hidden resident UIDs, destinations and real/dummy status. Then tune packing, batch size and the flat base; derive copies from measured service time at 70% utilization before pricing workers and storage.')
section('3. Calibrate cost and security together')
add('Validate joint hidden initialization, duplicate-safe path revelation, position refresh, state transitions and lifetime overflow bounds. Measure CPU, network and storage I/O on the intended topology. Streaming retains live state; short-epoch renewal and compact state conversion need complete accounting. Pages 2-4 preserve the earlier ten-party study as historical context.')
add('<b>Price basis.</b> Two-party figures use AWS US East Linux/shared On-Demand prices refreshed 14 October 2026 (feed version 20261012193925): c6in.32xlarge $7.2576/hour, 200 Gbps NIC; gp3 $0.96/GiB-year. Network planning uses 65% efficiency, 70% distributed efficiency and 70% utilization, with both roles charged. These factors are not measured protocol throughput.', 'small')
add('<b>Scope.</b> Flat read-only key-value service with private client-supplied hash indices; no Merkle proofs. Setup, a client gateway, backups, failover reserve, support, taxes and engineering are unpriced. Coverage differs across tables; every quoted range is conditional, not a confidence interval or complete budget.', 'small')
section('Evidence and reproduction')
add('[1] Liu et al., <link href="https://eprint.iacr.org/2026/761" color="#176B73"><i>Improved Garbled RAM via Garbled Merge</i>, ePrint 2026/761</link>, final revision 9 August 2026; <link href="https://zenodo.org/records/20751401" color="#176B73">artifact v2</link>. Byte/hash measurements do not establish end-to-end service throughput.', 'small')
add('[2] <link href="https://eprint.iacr.org/2025/1479" color="#176B73"><i>PicoGRAM</i>, ePrint 2025/1479</link>, Table 2, Section 7, Appendices D.2 and E.3. Communication-, end-to-end- and online-optimized variants are distinct; their best numbers cannot be combined.', 'small')
add('[3] Chan and Shi, <link href="https://eprint.iacr.org/2016/1084" color="#176B73"><i>Circuit OPRAM</i>, ePrint 2016/1084</link>. The two-party Boolean cost template is this study\'s proposed compilation, not a benchmark reported by that paper.', 'small')
add('[4] Historical ten-party figures: retained in the full report. Current two-party derivations and routing audit: <i>mpc_cost/data/two_party_notes.txt</i>, <i>two_party_accuracy_review.txt</i> and <i>two_party_serial_notes.txt</i>; results: <i>two_party_comparison.json</i> and <i>two_party_serial_comparison.json</i> under <i>mpc_cost/results/</i>. Commands: <i>mpc_cost/README.txt</i>.', 'small')

def decorate(c, doc):
    c.saveState()
    c.setStrokeColor(TEAL)
    c.setLineWidth(1.4)
    c.line(48, 750, 564, 750)
    c.setFont('Brief', 9)
    c.setFillColor(MUTED)
    c.drawString(48, 763, 'PRIVATE DATABASE COST STUDY')
    c.drawRightString(564, 763, 'Conditional cost study')
    c.setStrokeColor(HexColor('#CBD8DE'))
    c.setLineWidth(0.5)
    c.line(48, 40, 564, 40)
    c.setFont('Brief', 8.5)
    c.drawString(48, 26, 'Colleague briefing | Updated 16 October 2026')
    c.drawRightString(564, 26, f'{doc.page} / 7')
    c.restoreState()

OUT.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(str(OUT), pagesize=(612,792), leftMargin=48, rightMargin=48,
                        topMargin=57, bottomMargin=53, title='Private database: seven-page cost briefing',
                        author='Research briefing', subject='Condensed conditional cost study, 16 October 2026')
doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
print(OUT)
