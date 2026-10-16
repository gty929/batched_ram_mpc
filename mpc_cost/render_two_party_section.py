"""Generate the current two-party report section from the reproducible ledger."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def render():
    data = json.loads((ROOT / 'results/two_party_comparison.json').read_text())
    serial = json.loads((ROOT / 'results/two_party_serial_comparison.json').read_text())
    cases = [r['batch_cases'][0] for r in data['rows']]
    circuits = [c['circuit'] for c in cases]

    def pair(fn):
        return ' & '.join(fn(c) for c in cases)

    def line(label, fn):
        return label + ' & ' + pair(fn) + r' \\'

    rows = '\n'.join([
        line('AND gates / complete lookup (M)', lambda c: f"{c['circuit']['ands_per_query']/1e6:.3f}"),
        line('Garbled tables / lookup (MB)', lambda c: f"{c['price']['tables_bytes_per_query']/1e6:.1f}"),
        line('Network hosts per party', lambda c: str(c['price']['network_nodes_per_party'])),
        line('Network + SSD + modeled I/O (M USD/year)', lambda c: f"{c['network_capacity_and_io_usd_year']/1e6:.2f}"),
        line('With assumed 200M AND/s/node (M USD/year)', lambda c: f"{next(s['usd_year'] for s in c['cpu_sensitivities'] if s['assumed_sustained_ands_per_node_second']==200e6)/1e6:.2f}"),
        line('With assumed 50M AND/s/node (M USD/year)', lambda c: f"{next(s['usd_year'] for s in c['cpu_sensitivities'] if s['assumed_sustained_ands_per_node_second']==50e6)/1e6:.2f}"),
    ])
    inverse_rows = []
    labels = [('request_conflicts', 'Private request conflict routing'),
              ('pool_fetch', 'Private pool result extraction/alignment'),
              ('eviction_select', 'Private eviction routing/alignment'),
              ('flat_base_duplicates', 'Private flat-map routing')]
    for key, label in labels:
        values = [c['routing_audit']['retained_private_inverse_ands_per_query'][key] for c in circuits]
        inverse_rows.append(label + ' & ' + ' & '.join(f'{v/1e6:.4f}' for v in values) + r' \\')
    totals = [c['routing_audit']['retained_private_inverse_total_ands_per_query'] for c in circuits]
    inverse_rows.append('Total retained inverse allowance & ' + ' & '.join(f'{v/1e6:.4f}' for v in totals) + r' \\')

    gram_rows = []
    for t in (.05, .1, .5):
        points = [next(c for c in r['complete_service_time_scenarios']
                       if c['assumed_state_service_seconds'] == t) for r in serial['rows']]
        gram_rows.append(f'{1000*t:.0f} ms & {points[0]["required_independent_states"]:,} & '
                         + ' & '.join(f"{p['price']['network_plus_capacity_usd_year']/1e9:.3f}" for p in points)
                         + r' \\')

    text = r'''{\color{teal}\large CURRENT TWO-PARTY PROPOSAL ESTIMATE}\par
{\color{navy}\LARGE\bfseries Garbled RAM and interactive Circuit OPRAM}\par
Updated 16 October 2026, America/New\_York\par
\textbf{Scope.} Two semi-honest parties; 10,000 flat key--value reads/s;
$N=2^{28}$ or $2^{32}$ records, 32-byte keys and 32-byte values, same-AZ
placement. Both cuckoo-table probes and both parties are included. The smaller
case is a padded planning size, not the exact 206.8M-account geometry. Merkle
proofs are outside this estimate. The ten-party analysis following these pages
is retained as historical research, not the current proposal recommendation.

\section{Current and proposed approaches}
\textbf{Current: two-party Garbled RAM. Proposed: streamed interactive 2PC
with Circuit OPRAM.} The proposed approach avoids retained future garbled
programs and exposes parallel work within a batch. Its resource estimate
remains conditional on a complete batch schedule and measured CPU/I/O rates.

\textbf{Routing review.} Only old leaf positions requested in the current batch
are opened, after duplicate masking. Sorting those positions and permuting the
associated wire labels is local work: no garbled sorting or Waksman circuit is
needed for a public permutation. Authorized final outputs, including selected
old child positions, can be decoded and reordered locally when the output
permutation is known. Secret results can also be rewired locally under a public
permutation. Live replacement positions remain hidden.

\textbf{Recomputed result: no additional gate discount from this change alone.}
The prior ledger did not separately charge public path ordering or terminal
output unpermutation. Its inverse-routing terms follow secret UID/destination
sorts and include private extraction/alignment allowances. They cannot all be
deleted as though they were public output permutations. A narrower extraction
or compaction circuit could reduce them, but has not yet been counted.

\begin{center}\small
\begin{tabularx}{\linewidth}{Xrr}\toprule
Interactive template, $B=256$, packing 8 & $N=2^{28}$ & $N=2^{32}$\\\midrule
CURRENT_ROWS
\bottomrule\end{tabularx}\end{center}
All annual figures cover both parties and one state. The assumed CPU rates
include FreeXOR/runtime and utilization losses; neither rate is a benchmark.
The network/storage row omits CPU. Intra-party routing, complete initialization,
recovery and operational costs remain unpriced. These figures are planning
estimates, not proven upper/lower bounds or achieved service budgets.

\clearpage
\section{Which routing costs remain}
\begin{center}\small
\begin{tabularx}{\linewidth}{Xrr}\toprule
Retained private inverse-routing allowance (M AND/lookup) & $N=2^{28}$ & $N=2^{32}$\\\midrule
INVERSE_ROWS
\bottomrule\end{tabularx}\end{center}
These amounts are \emph{subsets} of the total AND counts, not additional costs.
They are conservative composition allowances, not established minima. The
template does not establish that each resident record must return to its old
pool slot. Retaining a reordered pool may help, but output extraction and the
next state's invariants must then be specified and priced.

\paragraph{Why public paths do not determine the pool permutation.}
Pool lookup matches requested UIDs against hidden resident UIDs. After that
secret sort, the request rows occupy secret positions among resident records;
decoding the entire sorted array would expose unintended internal information.
Private extraction or compaction must produce the allowed outputs before local
reordering applies. Eviction selection depends on hidden destinations and
priorities, while cleanup hides real/dummy status. Distinct UIDs can share a
leaf, so equality of public paths cannot replace UID matching or deduplication.

\paragraph{Leading arithmetic.}
The three pool phases account for about 85--87\% of the current AND count.
With $A$ ANDs per lookup, half gates produce $32A$ bytes of tables. At
$R=10{,}000$ lookups/s, the per-party network count is
\[
 n_{\rm NIC}=\left\lceil\frac{1.05R(32A+\text{input bytes})}
 {7.9625\times10^9}\right\rceil,
 \qquad C_{\rm EC2}=2n_{\rm NIC}\cdot7.2576\cdot8760.
\]
The effective rate uses a 200-Gbps NIC with factors 0.65, 0.70 and 0.70.
The denominator is bytes/s; the multiplier 1.05 budgets framing. Prices retain
the October 12 AWS feed snapshot, refreshed unchanged on October 14; this is
not a new live price quote. The two roles are charged separately.

\paragraph{State count and latency remain conditional.}
For complete batch service time $L_B$ and batch size $B$,
\[
 S=\left\lceil\frac{10{,}000L_B}{0.70B}\right\rceil.
\]
One state at $B=256$ requires $L_B\le17.92$ ms. The mean batch-fill delay is
12.75 ms before queueing and service. Aggregate NIC/AND capacity does not prove
this latency. The $B=1024$ and $4096$ rows remain available in the JSON ledger;
no newly measured service time is implied by this routing review.

\clearpage
\section{Garbled RAM reference and next measurements}
The current-work comparison must enforce sequential evaluator service before
pricing independent states. Using the existing two-epoch retention model and
optimizing the horizon for each assumed service time gives:
\begin{center}\small
\begin{tabular}{lrrr}\toprule
Assumed complete lookup service & States & $N=2^{28}$ (B USD/year) & $N=2^{32}$ (B USD/year)\\\midrule
GRAM_ROWS
\bottomrule\end{tabular}\end{center}
These cover network EC2, SSD capacity and attachment hosts, not full CPU,
SSD I/O or secure epoch renewal. Service times are assumptions, not Garbled
Merge measurements. The comparison does not establish an empirical savings
ratio or a universal Garbled RAM cost lower bound.

\paragraph{Next analysis.}
Specify a private output-extraction circuit that can retain pool order and
route only necessary result bits; validate packed-map updates and duplicate
handling. Then count its gates and live labels, benchmark both 2PC roles and
distributed batch service, and choose worker/replica counts from that service
time. Bucket capacity, pool slack and the service-lifetime overflow bound also
remain unresolved. Public-path routing is already removed from the secure
gate budget; treating it as a second discount would double-count the saving.

\paragraph{Reproduction.}
\begin{verbatim}
python -m mpc_cost.two_party_cost
python -m mpc_cost.two_party_serial
python -m unittest mpc_cost.test_two_party mpc_cost.test_garbled -v
python -m mpc_cost.render_report
python -m mpc_cost.render_short_report
\end{verbatim}
The routing decomposition is in
\texttt{results/two\_party\_comparison.json}; assumptions are in
\texttt{data/two\_party\_notes.txt}. The tests validate accounting, not a
complete implementation or security proof.

\paragraph{Primary references.}
Circuit OPRAM: \url{https://eprint.iacr.org/2016/1084};
half gates: \url{https://www.cs.virginia.edu/~evans/pubs/ec2015/};
Garbled Merge: \url{https://eprint.iacr.org/2026/761}.
The finite Boolean compilation and deployment assumptions are this study's
model, not measured results reported by those papers.
'''
    for key, value in [('CURRENT_ROWS', rows), ('INVERSE_ROWS', '\n'.join(inverse_rows)),
                       ('GRAM_ROWS', '\n'.join(gram_rows))]:
        text = text.replace(key, value)
    (ROOT / 'two_party_notes.tex').write_text(text, encoding='utf-8')
    return data


if __name__ == '__main__':
    render()
