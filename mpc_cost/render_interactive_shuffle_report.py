"""Render numerical LaTeX tables and a self-contained report source.

Run the cost model first. This command performs no network calls and does not
invoke LaTeX. Compile output/latex/interactive_batch_oram_report.tex twice.
"""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent


def num(x, digits=3):
    return f'{x:,.{digits}f}'


def money(x):
    return rf'\${x/1e6:,.2f}M'


def table(headers, rows, columns=None):
    columns = columns or ('l'+'r'*(len(headers)-1))
    lines = [r'\begin{center}\small', rf'\begin{{tabular}}{{{columns}}}\toprule',
             ' & '.join(headers)+r'\\\midrule']
    lines += [' & '.join(str(v) for v in row)+r'\\' for row in rows]
    lines += [r'\bottomrule\end{tabular}', r'\end{center}']
    return '\n'.join(lines)+'\n'


def write(name, text):
    (ROOT/name).write_text(text, encoding='utf-8')


def main():
    data = json.loads((ROOT/'results/interactive_shuffle_comparison.json').read_text())
    studies = data['rows']
    cs = [r['selected']['circuit'] for r in studies]
    ps = [r['selected']['price'] for r in studies]
    write('interactive_shuffle_numbers.tex',
          '\n'.join(rf'\newcommand{{\PrimaryAnnual{name}}}{{{money(p["network_capacity_and_io_usd_year"])}}}'
                    for name, p in zip(('Small', 'Large'), ps))+'\n')
    headers = ['Primary selected scenario', r'$N=2^{28}$', r'$N=2^{32}$']
    summary = [
        ['Batch / map fanout', *[f'{c["batch"]} / {c["fanout"]}' for c in cs]],
        ['Ordinary ANDs/query (million)', *[num(c['ands_per_query']/1e6) for c in cs]],
        ['Total framed traffic/query (MB)', *[num(p['total_wire_bytes_per_query']/1e6) for p in ps]],
        ['NIC hosts per party', *[str(p['network_nodes_per_party']) for p in ps]],
        ['Persistent state per party (TB)', *[num(p['state_bytes_per_party']/1e12, 2) for p in ps]],
        ['Network + capacity + modeled I/O/year', *[money(p['network_capacity_and_io_usd_year']) for p in ps]],
    ]
    write('interactive_shuffle_summary_table.tex', table(headers, summary))

    sections = [r'''\subsection{Batch and recursion search}
The search enumerates $B\in\{8,16,32,64,128,256\}$,
$F\in\{4,8,16,32\}$, and requested base cutoffs
$\{16,32,64,128,256,512,1024,2048,4096\}$: 216 combinations per database
size. Each row below selects the cheapest network/state/I/O configuration
at that batch size. Both final selections use $B=32$, $F=4$, and an actual
base map of 2048 entries. The requested cutoff may have several equivalent
values; the actual instantiated base is what matters. Small batches lose
amortization of the fixed 128-record pool slack. Larger batches grow the
remaining padded sorting networks. Consequently the objective is not
monotone in batch size.
''']
    rows = []
    for left, right in zip(studies[0]['best_by_batch'], studies[1]['best_by_batch']):
        lc, lp = left['circuit'], left['price']
        rc, rp = right['circuit'], right['price']
        rows.append([lc['batch'], f'{lc["fanout"]}/{rc["fanout"]}',
                     num(lp['total_wire_bytes_per_query']/1e6, 1),
                     num(rp['total_wire_bytes_per_query']/1e6, 1),
                     money(lp['network_capacity_and_io_usd_year']),
                     money(rp['network_capacity_and_io_usd_year']),
                     num(.7*lc['batch']/10000*1000, 2)])
    sections.append(table(['$B$', '$F_{28}/F_{32}$', 'MB/q, 28', 'MB/q, 32',
                           r'\$/yr, 28', r'\$/yr, 32', r'$\tau_B$ limit (ms)'], rows))
    sections.append(r'''Traffic includes both directions and 5\% framing;
prices exclude CPU sizing. The final column is the one-state batch reuse
limit, not a predicted service time. Padding effects and the fixed slack
make this an optimum of the selected implementation template, not a lower
bound for OPRAM.

\subsection{Instantiated recursive trees}
Every selected tree has a 317-record pool, $r=6$, and a shuffle of 349
records. The final map has 2048 scalar entries of 11 bits. The table lists
each tree's address width $h$, payload width $D$, complete record width $W$,
and lower-path length $L=h-5$.
''')
    rows = []
    for i in range(max(len(c['tree_address_bits']) for c in cs)):
        row = [str(i)]
        for c in cs:
            if i < len(c['tree_address_bits']):
                h = c['tree_address_bits'][i]
                row += [str(h), str(c['tree_payload_bits'][i]), str(c['tree_record_bits'][i]), str(h-5)]
            else:
                row += ['--']*4
        rows.append(row)
    sections.append(table(['Level', '$h_{28}$', '$D_{28}$', '$W_{28}$', '$L_{28}$',
                           '$h_{32}$', '$D_{32}$', '$W_{32}$', '$L_{32}$'], rows))
    sections.append(r'''There are 10/12 dependent path-disclosure stages.
Choosing fanout 8 for the larger database offers a latency/storage tradeoff;
the selected fanout 4 minimizes the stated aggregate price objective, which
does not price round-trip latency.

\subsection{Ordinary garbled-circuit work}
The following rows are millions of ANDs per complete query, already summed
over both tables and every recursive level. They exclude OT and shuffle
messages, which are accounted separately.
''')
    labels = {
        'request_conflicts': 'Request grouping and private result routing',
        'subtree_fetch': 'Lower-path retrieval and clearing',
        'pool_match_tags': 'Pool UID matching and tags',
        'candidate_depth': 'Eviction-candidate depth',
        'eviction_select': 'Pool eviction selection',
        'pool_cleanup': 'Pool cleanup',
        'subtree_eviction': 'Lower-subtree eviction',
        'public_path_selection': 'Duplicate-masked path selection',
        'packed_recursive_updates': 'Coalesced recursive-map updates',
        'fused_flat_base': 'Fused flat position-map exchange',
        'application_match_and_select': 'Dictionary key match and value selection',
        'aes_cmac_frontend': 'AES-CMAC query frontend',
    }
    rows = [[label, *[num(c['and_components_per_query'][key]/1e6, 6) for c in cs]]
            for key, label in labels.items()]
    rows.append([r'\textbf{Total}', *[rf'\textbf{{{num(c["ands_per_query"]/1e6, 6)}}}' for c in cs]])
    sections.append(table(['Component (million AND/query)', '$2^{28}$', '$2^{32}$'], rows))
    for c in cs:
        components = c['and_components_per_query']
        fraction = (components['eviction_select']+components['pool_cleanup'])/c['ands_per_query']
        sections.append(f'For $N=2^{{{c["log_records"]}}}$, eviction selection and pool cleanup '
                        f'account for {100*fraction:.1f}\\% of ordinary ANDs.\n')
    sections.append(r'''These retained phases dominate after retrieval has been
improved. Optimizing the shuffle alone cannot remove them.

\subsection{Pool protocol: all costs, not only online bytes}
The main pool terms below include both tables and all trees, per query.
Re-input is charged even for the data already moved by the shuffle; these
are distinct operations. The unframed total is comparable to the old pool
phase only, not to the entire query.
''')
    def pool(c, key):
        return c['pool_protocol_both_tables_per_batch'][key]/c['batch']
    poolrows = [
        ['Metadata match tables', *[num(pool(c, 'match_table_bytes')/1e6, 6) for c in cs]],
        ['Online masked arrays', *[num(pool(c, 'two_shuffle_record_bytes')/1e6, 6) for c in cs]],
        ['Offline switch corrections', *[num(pool(c, 'two_shuffle_switch_bytes')/1e6, 6) for c in cs]],
        ['OT-extension allowance', *[num(pool(c, 'two_shuffle_ot_extension_bytes')/1e6, 6) for c in cs]],
        ['Tag-share opening', *[num(pool(c, 'tag_opening_bytes')/1e6, 6) for c in cs]],
        ['GC re-input, both directions', *[num((pool(c, 'reinput_forward_bytes')+pool(c, 'reinput_backward_bytes'))/1e6, 6) for c in cs]],
    ]
    totalpool = [sum(pool(c, k) for k in ('match_table_bytes','symmetric_protocol_bytes',
                                         'reinput_forward_bytes','reinput_backward_bytes')) for c in cs]
    poolrows.append(['Total pool retrieval', *[num(v/1e6, 6) for v in totalpool]])
    sections.append(table(['Pool component (MB/query)', '$2^{28}$', '$2^{32}$'], poolrows))
    sections.append(r'''\subsection{Complete directional communication}
''')
    trafficrows = [
        ['Garbled tables, forward', *[num(c['table_bytes_per_query']/1e6, 6) for c in cs]],
        ['Pool re-input, forward', *[num(c['unframed_traffic_bytes_per_query']['reinput_forward']/1e6, 6) for c in cs]],
        ['Pool re-input, reverse', *[num(c['unframed_traffic_bytes_per_query']['reinput_backward']/1e6, 6) for c in cs]],
        ['Shuffle + tags, both directions', *[num(pool(c, 'symmetric_protocol_bytes')/1e6, 6) for c in cs]],
        ['Query shares, both directions', *[num(64*256/1e6, 6) for c in cs]],
        ['Fresh-position inputs, both directions', *[num(64*c['fresh_position_bits_per_query']/1e6, 6) for c in cs]],
        ['Old-path disclosure, both directions', *[num(2*c['public_path_bits_per_query']/8/1e6, 6) for c in cs]],
        [r'\midrule Forward, after framing', *[num(p['forward_wire_bytes_per_query']/1e6, 6) for p in ps]],
        ['Reverse, after framing', *[num(p['backward_wire_bytes_per_query']/1e6, 6) for p in ps]],
        [r'\textbf{Total, after framing}', *[rf'\textbf{{{num(p["total_wire_bytes_per_query"]/1e6, 6)}}}' for p in ps]],
    ]
    sections.append(table(['Traffic component (MB/query)', '$2^{28}$', '$2^{32}$'], trafficrows))
    sections.append(r'''PRF setup is 6400 ANDs plus 8192 input bytes per
initialized state, before framing, and is not amortized into these per-query
rows. At an epoch of $T$ queries, add $(32\cdot6400+8192)/T$ bytes per query
before framing, together with any state handoff. Base OT and initial database
construction remain separate.

\subsection{Packed-value sensitivity without an unsupported gate discount}
A 256-bit ordinary Boolean value uses 4096 label bytes per party. A
two-carrier representation would use 32 bytes. For $M_{\rm value}$ physical
data/stash slots, the conditional state saving is exactly
$4064M_{\rm value}$ bytes per party. Recursive leaf labels are unchanged.
''')
    storage = []
    for c, p in zip(cs, ps):
        h = c['tree_address_bits'][0]
        r = (2*c['batch']).bit_length()-1
        pool_count = c['pool_protocol_per_tree_per_table'][0]['pool_records']
        slots = 2*(c['bucket_z']*((1 << (h+1))-(1 << r))+pool_count)+8
        storage.append(p['state_bytes_per_party']-4064*slots)
    sections.append(table(['State per party (TB)', '$2^{28}$', '$2^{32}$'], [
        ['Primary Boolean representation', *[num(p['state_bytes_per_party']/1e12, 3) for p in ps]],
        ['Conditional two-carrier values', *[num(s/1e12, 3) for s in storage]],
    ]))
    sections.append(r'''This is a storage sensitivity, not a complete second
deployment estimate. A packed backend must specify how shared values enter
and leave its encoding and what a secret-controlled move costs. The present
shuffle transports ordinary XOR shares; the Boolean color-bit conversion does
not prove a conversion for two opaque carriers. The earlier hypothetical
``two half-gate equivalents per value move'' cannot be included without those
interfaces. Ordinary compact XOR-share storage is another valid design
direction, but needs re-input accounting on every subsequently touched field.
''')
    write('interactive_shuffle_results.tex', '\n'.join(sections))

    deploy = [r'\subsection{Selected annual budgets}']
    rows = [
        ['NIC hosts per party', *[p['network_nodes_per_party'] for p in ps]],
        ['Additional capacity/I/O EC2/year', *[money(p['extra_capacity_io_ec2_usd_year']) for p in ps]],
        ['Network-sized EC2/year', *[money(p['network_ec2_usd_year']) for p in ps]],
        ['SSD capacity/year', *[money(p['ssd_capacity_usd_year']) for p in ps]],
        ['Modeled persistent I/O/year', *[money(p['modeled_persistent_io_usd_year']) for p in ps]],
        [r'\textbf{Combined annual capacity budget}', *[rf'\textbf{{{money(p["network_capacity_and_io_usd_year"])}}}' for p in ps]],
        ['Persistent R+W/query/party (MB)', *[num(p['persistent_io']['read_write_bytes_per_party_query']/1e6, 3) for p in ps]],
        ['State capacity, both parties (TB)', *[num(2*p['state_bytes_per_party']/1e12, 3) for p in ps]],
    ]
    deploy.append(table(['Both-party cost unless stated', '$2^{28}$', '$2^{32}$'], rows))
    deploy.append(r'''The minimum streaming buffer allowance is 64 MiB per
party. It is not the total RAM requirement: workers, in-flight circuit labels,
OT matrices, shuffle correlations, network buffers, and eviction scratch must
be provisioned. No full-horizon garbled program is retained.

\subsection{Known-work CPU sensitivity}
At the following assumed effective ordinary-AND rates per node, take the
maximum of NIC, storage/I/O, and ordinary-gate host counts. These figures
include the stated state and I/O budgets, but \emph{exclude} the additional
CPU cost of OT, shuffle, free-XOR, serialization, and distributed execution.
They therefore are not complete CPU-priced service budgets.
''')
    rows = []
    for a, b in zip(ps[0]['ordinary_and_cpu_sensitivities'], ps[1]['ordinary_and_cpu_sensitivities']):
        rows.append([num(a['assumed_ordinary_ands_per_node_second']/1e6, 0),
                     a['nodes_per_party'], b['nodes_per_party'],
                     money(a['ordinary_and_capacity_usd_year']), money(b['ordinary_and_capacity_usd_year'])])
    deploy.append(table(['Million AND/s/node', 'Hosts/party, 28', 'Hosts/party, 32', r'\$/yr, 28', r'\$/yr, 32'], rows))
    write('interactive_shuffle_deployment.tex', '\n'.join(deploy))

    # Expand only repo-local input fragments to provide a truly standalone .tex.
    def expand(text):
        return re.sub(r'\\input\{([^}]+)\}', lambda m: expand((ROOT/m.group(1)).read_text(encoding='utf-8')), text)
    final = expand((ROOT/'interactive_shuffle_report.tex').read_text(encoding='utf-8'))
    outdir = REPO/'output/latex'
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir/'interactive_batch_oram_report.tex'
    path.write_text(final, encoding='utf-8')
    print(f'Wrote {path} ({len(final):,} characters)')


if __name__ == '__main__':
    main()
