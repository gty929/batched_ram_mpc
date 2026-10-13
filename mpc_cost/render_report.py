"""Generate report tables, standalone figures, and a LaTeX report from results.
Requires matplotlib; PDF compilation is a separate pdflatex command.
"""
import csv
import json
from pathlib import Path
from .render_bottleneck_section import render as render_bottleneck_section
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results'
render_bottleneck_section()
summary=json.loads((OUT/'summary.json').read_text())
scenarios=summary['scenarios']
central=next(x for x in scenarios if x['scenario']=='central')
x=central['result']
envelope=json.loads((ROOT/'data/capacity_envelope.json').read_text())
topology=json.loads((OUT/'topology.json').read_text())
circuits=json.loads((OUT/'circuits.json').read_text())

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
                     'axes.spines.right':False,'axes.labelcolor':'#17324d'})
fig,ax=plt.subplots(figsize=(7.4,3.5),layout='constrained')
rows=list(csv.DictReader((OUT/'frontier.csv').open()))
for name,label,col in [('central','2B weighted operations/s','#176b73'),
                       ('faster_cpu','8B weighted operations/s','#4b76a5'),
                       ('slower_cpu','0.5B weighted operations/s','#ba7943')]:
    r=sorted([z for z in rows if z['scenario']==name],key=lambda z:int(z['batch']))
    ax.plot([int(z['batch']) for z in r],[float(z['total_usd_year'])/1e9 for z in r],
            'o-',label=label,color=col)
ax.set_xscale('log',base=2);ax.set_xticks([64,128,256,512,1024,2048],labels=['64','128','256','512','1024','2048'])
ax.set_xlabel('Logical queries per centrally formed batch')
ax.set_ylabel('Conditional EC2 cost ($ billion/year)')
ax.set_title('All-arithmetic reference; feasible modeled mean latency ≤ 5 s',loc='left',fontsize=11)
ax.legend(frameon=False,fontsize=8);ax.grid(axis='y',alpha=.2)
fig.savefig(OUT/'batch_cost.png',dpi=180);plt.close(fig)

fig,ax=plt.subplots(figsize=(7.4,3.4),layout='constrained')
er=envelope['rows'];g=[r['outputs_per_read'] for r in er]
ax.loglog(g,[r['raw_nic_only_annual_usd']/1e6 for r in er],'o-',label='Peak-NIC resource floor',color='#91a3b0')
ax.loglog(g,[r['headroom_nic_only_annual_usd']/1e6 for r in er],'o-',label='NIC with assumed headroom',color='#176b73')
ax.loglog(g,[next(t['annual_usd'] for t in r['conditional_scalar_cpu_and_nic']
                    if t['unmeasured_weighted_operations_per_sec_64vcpu']==2e9)/1e6 for r in er],
            'o-',label='CPU + NIC; assumed 2B operations/s',color='#ba7943')
ax.set_xlabel('Secure scalar reductions or dot-product outputs per logical read')
ax.set_ylabel('Annual resource cost ($ million)')
ax.set_title('An optimization target, not a provisioned ORAM deployment',loc='left',fontsize=11)
ax.legend(frameon=False,fontsize=8);ax.grid(alpha=.2,which='major')
fig.savefig(OUT/'capacity_envelope.png',dpi=180);plt.close(fig)

def esc(s):return str(s).replace('_',r'\_')
def dollars(v):return f'{v/1e6:,.1f}'
scenario_rows='\n'.join(f"{esc(r['scenario'])} & {r['result']['batch']} & {r['result']['fanout']} & "
    f"{r['result']['base_cells']:,} & {r['result']['total_usd_year']/1e9:.2f} & {r['queue']['mean_seconds']:.2f} \\\\" for r in scenarios if 'result' in r)
env_rows='\n'.join(f"{r['outputs_per_read']:,} & {r['raw_nic_only_annual_usd']/1e6:.2f} & "
    f"{r['headroom_nic_only_annual_usd']/1e6:.2f} & "
    f"{next(t['annual_usd'] for t in r['conditional_scalar_cpu_and_nic'] if t['unmeasured_weighted_operations_per_sec_64vcpu']==2e9)/1e6:.2f} \\\\" for r in er)
level_rows='\n'.join(f"{i} & {l['records']:,} & {l['payload_words']} & {l['pool_records']:,} & {l['lower_path_levels']} \\\\" for i,l in enumerate(circuits['central']['levels']))
az_all=next(r['transfer_usd_year'] for r in topology if r['scenario']=='central' and r['placement']=='all_cross_AZ')
report=r'''\documentclass[11pt]{article}
\usepackage[letterpaper,margin=0.85in]{geometry}
\usepackage[T1]{fontenc}
\usepackage{lmodern,microtype,amsmath,amssymb,booktabs,tabularx,graphicx,xcolor,enumitem}
\usepackage[hyphens]{url}
\usepackage{hyperref,fancyhdr}
\definecolor{navy}{HTML}{17324D}\definecolor{teal}{HTML}{176B73}
\hypersetup{colorlinks=true,linkcolor=navy,urlcolor=teal,pdftitle={Honest-majority MPC database: construction and cost model}}
\setlength{\parindent}{0pt}\setlength{\parskip}{5pt}\setlength{\emergencystretch}{2em}
\setlist{nosep,leftmargin=1.5em}\setlength{\headheight}{14pt}
\pagestyle{fancy}\fancyhf{}\fancyhead[L]{\small\textcolor{navy}{Honest-majority MPC database}}
\fancyhead[R]{\small Conditional research estimate}\fancyfoot[C]{\thepage}
\newcommand{\F}{\mathbb F}
\begin{document}
{\color{teal}\large CONSTRUCTION AND CAPACITY STUDY}\par
{\color{navy}\LARGE\bfseries A 10,000-query/s key--value database\\in ten-party honest-majority MPC}\par
Updated 13 October 2026, America/New\_York\par
\textbf{Target:} $2^{28}$ records, 32-byte keys and values; ten parties, at most four
malicious corruptions, security with abort; average response time at most five seconds.

\section{Decision for the proposal}
\textbf{Continue with two cuckoo tables over binary Circuit OPRAM, but make the
arithmetic compilation and private routing the research contribution.} Probe both
tables in parallel; use a shared central batcher, grouped recursive-map updates,
private dot products, a larger flat base, and a sweep of position-map packing.
The important distinction is between increasing the number of labels per
recursive record and changing the ORAM tree's branching factor: this study changes
the former and retains the binary-tree eviction invariant.

\textbf{A low annual budget is not yet supported.} The explicit all-arithmetic
reference used here has millions of secure reduction outputs per logical read.
Its AWS sensitivity scenarios land in the billion-dollar/year range. That is a
warning about this compilation, not an impossibility result for the problem.
No complete malicious ten-party Circuit OPRAM benchmark or proof of these new
compiled circuits was produced. In particular, the model does not establish the
best achievable construction among mixed-domain, shuffle-based, hierarchical, or
other MPC memory protocols.

The useful budget milestone is to measure and reduce the complete per-read work
vector. A backend-conditional envelope below shows that even 10,000--30,000 secure
outputs per read can consume millions of dollars/year across ten parties. Those
counts are \emph{optimization targets}, not achieved costs of the proposed system.

\paragraph{Suggested proposal language.}
\begin{quote}
We will develop an honest-majority MPC key--value service using batched oblivious
access rather than a direct multiparty garbled-RAM extension. Our design combines
parallel cuckoo probes, arithmetic-aware recursive position maps, private inner
products, and optimized oblivious routing. We target 10,000 reads per second and
mean response time below five seconds. Preliminary circuit and cloud accounting
identifies metadata conversion and pool routing as the principal bottlenecks;
meeting a practical cost target requires reducing these costs. We will validate
throughput and annual operating costs with a complete malicious ten-party
implementation including preprocessing, maintenance, and all-party communication.
\end{quote}

\section{What the numerical search found}
The program searches batches64--2048, fanouts4--256, flat cutoffs256--65536,
compact versus field-bit metadata, sorting networks versus a checked-shuffle
quicksort template, five EC2 instance sizes, and machines/replicas. It minimizes
EC2 expenditure among points with modeled mean latency below five seconds.
The cutoffs are requested limits; the actual flat map may be larger when another
recursive tree would be too small to support its parallel batch.

\begin{center}\small
\begin{tabular}{lrrrrr}\toprule
Scenario & Batch & Fanout & Actual base & \$/year (B) & Mean (s)\\\midrule
SCENARIO_ROWS
\bottomrule\end{tabular}\end{center}
These are independently optimized scenarios, not confidence intervals. The
two-second-target row tightens the mean-latency cap to two seconds
while retaining the central hardware assumptions. All other rows use five seconds.
The CPU
capacity assumptions are0.5,2,8 billion \emph{weighted} local field operations per
64-vCPU node/s. They are not measured EC2 performance. Exchange-delay assumptions
are0.05,0.2,0.5ms; the central value is0.2ms. No-overlap sums CPU, network and RAM
service time; other rows take their maximum. The latency simulation assumes
Poisson arrivals and service-time coefficient of variation0.05, and cannot predict
real network tails or failures.

\includegraphics[width=\linewidth]{results/batch_cost.png}

The central minimum uses BATCH queries, fanout FANOUT, BASE scalar labels in each
flat base, and LEVELS recursive tree levels per cuckoo table. Its state occupies
STATE\,GiB per party per replica. It uses NODES machines per party per replica and
REPLICAS independent replica groups (INSTANCES machines across all parties).
Its modeled mean latency is MEAN\,s, of which ROUND\,s is dependent exchange time.
This enormous deployment is an accounting result, not a recommended AWS launch.
No EC2 capacity availability, quota increase, or linear scaling to this size has
been established.

\begin{center}\small\begin{tabular}{rrrrr}\toprule
Level & Records per table & Payload words & Pool records & Lower path buckets\\\midrule
LEVEL_ROWS
\bottomrule\end{tabular}\end{center}

Per logical read, this point charges REDUCTIONS million reduction outputs,
BITS thousand preprocessed random bits, and SENT\,MB transmitted per party.
The byte count includes the leading backend costs and5\% framing. Stored-field-bit
metadata reduces conversion work but expands persistent state to roughly12--13\,TiB
per party for typical grid points. That is \emph{not} the memory cost of a properly
packed Boolean-sharing implementation; this model charges every bit as an
authenticated arithmetic share.

Fanout128 wins the central scenario because it removes recursive levels; the
low-exchange scenario instead favors fanout32. Thus neither ``largest payload''
nor ``smallest base'' is a robust optimum. For prototyping, test batches128--1024,
fanouts16,32,64,128, and actual bases of a few thousand to32768 labels. Small batches
keep formation latency low; the model's several-second delay comes mainly from
computation and dependent communication, not waiting to fill batches.

\section{A cost envelope for optimization targets}
For $G$ scalar reductions or private-dot-product \emph{outputs} per read, the
leading SY-Shamir traffic proxy is
\[
 V_{\mathrm{party/read}}=G\cdot\frac{59}{6}\cdot16\ \text{bytes},\qquad
 V_{\mathrm{party/sec}}=10^4 V_{\mathrm{party/read}}.
\]
This excludes additional random bits, long-dot local work, conversions, routing,
and special openings unless they are charged separately. It is a conditional
backend relation, not an information-theoretic MPC lower bound.

\begin{center}\small\begin{tabular}{rrrr}\toprule
Outputs/read & Peak NIC floor & NIC + headroom & Assumed CPU + NIC\\
&\multicolumn{3}{c}{USD millions/year, all ten parties}\\\midrule
ENV_ROWS
\bottomrule\end{tabular}\end{center}
The table uses \texttt{r6in.32xlarge},200Gbps,\$11.15712/hour. Headroom includes
65\% NIC utilization,70\% operating utilization, a1.12 hottest-party factor, and
5\% framing. CPU+NIC assumes83 weighted operations/scalar output and2 billion
operations/s per64vCPU. It does not provision RAM, state replicas, dependent-round
latency, intraparty routing, failover, or database initialization. Consequently
even the rightmost column is not a sufficient deployment budget.

\includegraphics[width=\linewidth]{results/capacity_envelope.png}

The gap from the reference's roughly3 million outputs/read to a30,000-output
target is about100-fold. Packing position maps alone cannot credibly be assigned
that improvement. A substantially different metadata/routing implementation is
needed before such a target can be presented as an expected system result.

\section{Backend and scheduling assumptions}
The accounting is tied to MP-SPDZ revision
\texttt{73eb8556cdfc670c5d3dc1067a3ae5b4ad0d4441}, using authenticated SY-Shamir,
$n=10,t=4,p=2^{127}-1$. The source-derived leading coefficient is approximately
$59/6$ field words sent per party per scalar/dot output; a checked opening costs
8 words, and an authenticated random bit about24 words. A scalar multiplication
has one exchange; the current dot-product path has two sequential exchanges.
An active-check barrier adds at least four phases. Leading coefficients are not
complete measured wall-clock costs.\footnote{Pinned protocol source:
\url{https://github.com/data61/MP-SPDZ/tree/73eb8556cdfc670c5d3dc1067a3ae5b4ad0d4441/Protocols}.}

Keep these three kinds of arithmetic separate:
\begin{itemize}
\item One secret-selector payload mux uses one scalar product per field word.
\item A $k$-bit secret comparison uses a prefix circuit of about$3k-2$
products before its conditional movement; it is not one arithmetic gate.
\item An inner product of length$k$ has one communicated output but$\Theta(k)$
local arithmetic. Random bits and exact field-to-bit conversion require their
own preprocessing ledger.
\end{itemize}
The model's exact canonical-mask conversion and path-planning circuits have
explicit proxy coefficients. The mask acceptance work is charged offline;
conversion/opening phases are charged online. For a simple sustainable service
schedule, the batch resource time includes \emph{both} online and offline work.
Ready preprocessing and overlapped maintenance can lower online latency, but
their steady-state compute and network capacity must still be provisioned.

For $K$ machines per party in one replica, the capacity model uses
\[
 T_{\mathrm{service}}=D\tau+
 \max\{T_{\mathrm{network}},T_{\mathrm{CPU}},T_{\mathrm{RAM}}\},\qquad
 J=\left\lceil\frac{10^4T_{\mathrm{service}}}{0.7B}\right\rceil.
\]
$J$ is the number of independent evolving ORAM replicas. Each replica stores the
entire shared database; $K$ shards its physical state and computation. A0.7
distributed-efficiency factor and explicit intraparty share-routing traffic
limit ideal scaling. The model adds scratch and a rough traffic-derived
preprocessing inventory proxy. An implementation must replace that proxy with
actual material sizes. The price is $10JKp_{\mathrm{hour}}\cdot8760$.

A central dispatcher forms a batch before choosing a replica. Mean formation
waiting is approximately$(B-1)/(2R)$:6.35ms at$B=128$ and51.15ms at$B=1024$.
Splitting arrivals into$J$ independent batchers would multiply that delay and is
not the deployment being priced. Every replica finishes maintenance before
accepting its next batch. The script also simulates dispatch queues, and tests
that inadequate service capacity causes queues to grow.

\section{AWS placement changes the answer}
The official Linux/shared-tenancy US East (N. Virginia) offer snapshot is
\texttt{20261012193925}, published12 October2026, with selected prices effective
1 October2026. Raw rows and a refresh script are retained.\footnote{Official
offer feed: \url{https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.csv}.}

Same physical AZ VPC-peering traffic can avoid transfer fees, including across
accounts. Cross-AZ peering is\$0.01/GB at each endpoint, or\$0.02 for a transmitted
GB counted once.\footnote{\url{https://docs.aws.amazon.com/vpc/latest/peering/what-is-vpc-peering.html};
\url{https://aws.amazon.com/vpc/pricing/}.}
Thus at10,000 outputs/read, the leading all-cross-AZ transfer bill alone is
\$99.2 million/year under this backend. For the central reference circuit it is
\$AZB billion/year, before compute. A4/3/3-party placement gives crossing fraction
$66/90$ only for uniformly weighted all-to-all communication; actual protocol
traffic needs a byte-weighted graph. AWS billing-unit assumptions are exposed.

Advertised NIC bandwidth is per direction; single-flow limits and multi-NIC
configuration matter. In particular, \texttt{r6in.32xlarge} needs both network
cards to attain the aggregate200Gbps. No sustained MPC bandwidth or collective
latency is guaranteed by the instance specification.\footnote{
\url{https://docs.aws.amazon.com/ec2/latest/UserGuide/ec2-instance-network-bandwidth.html};
\url{https://docs.aws.amazon.com/ec2/latest/instancetypes/mo.html}.}
The prices exclude EBS, snapshots, setup, backups, client transfer, NAT,
orchestration, failover reserve, support, taxes, and engineering. Same-provider
or same-AZ placement does not by itself establish independent corruption domains.

\input{construction_notes.tex}

\input{bottleneck_scan_notes.tex}

\section{Reproduction and next decision}
From the repository root:
\begin{verbatim}
python -m mpc_cost.run --full
python -m mpc_cost.compare_scans
python -m unittest discover -s mpc_cost -p "test_*.py" -v
python -m mpc_cost.render_report
\end{verbatim}
Compile \texttt{mpc\_cost/mpc\_oram\_cost\_report.tex} with its working directory
set to \texttt{mpc\_cost}. The program has no runtime dependencies beyond Python's
standard library; generating figures additionally needs Matplotlib and PDF
compilation needs LaTeX. \texttt{README.txt} explains overrides and price refresh.

The tests validate arithmetic witnesses (comparison, gated decoding, duplicate
updates, Fermat equality), recursive base dimensions, metadata movement, all-party
and replica billing, transfer send-counting, and queue saturation. They do not
validate an unimplemented ORAM security proof or MPC performance.

Before choosing a proposal budget, benchmark checked scalar batches, long dot
products, mask production, and a complete recursive read with duplicate updates.
Measure online latency and sustainable total resource use separately, then replace
the proxy counts and sweep the parameters again.
\end{document}
'''
replacements={'SCENARIO_ROWS':scenario_rows,'ENV_ROWS':env_rows,'LEVEL_ROWS':level_rows,
              'BATCH':str(x['batch']),'FANOUT':str(x['fanout']),'BASE':f"{x['base_cells']:,}",
              'LEVELS':str(x['levels']),'STATE':f"{x['state_gib_per_party_per_replica']:,.0f}",
              'NODES':str(x['nodes_per_party_per_replica']),'REPLICAS':str(x['replicas']),
              'INSTANCES':f"{x['total_instances']:,}",'MEAN':f"{central['queue']['mean_seconds']:.2f}",
              'ROUND':f"{x['round_seconds']:.2f}",'REDUCTIONS':f"{x['reductions_per_read']/1e6:.2f}",
              'BITS':f"{x['random_bits_per_read']/1e3:.1f}",'SENT':f"{x['sent_mb_per_party_read']:.1f}",
              'AZB':f"{az_all/1e9:.1f}"}
for old,new in replacements.items():report=report.replace(old,new)
spacing={
 'batches64':'batches 64', 'fanouts4':'fanouts 4', 'cutoffs256':'cutoffs 256',
 'are0.5,2,8':'are 0.5, 2, and 8', 'are0.05,0.2,0.5ms':'are 0.05, 0.2, and 0.5 ms',
 'is0.2ms':'is 0.2 ms', 'variation0.05':'variation 0.05', 'and5\\%':'and 5\\%',
 'roughly12':'roughly 12', 'Fanout128':'Fanout 128', 'fanout32':'fanout 32',
 'batches128':'batches 128', 'fanouts16,32,64,128':'fanouts 16, 32, 64, and 128',
 'to32768':'to 32768', ',200Gbps':', 200 Gbps', ',\\$11.15712':', \\$11.15712',
 'utilization,70':'utilization, 70', 'a1.12':'a 1.12', 'assumes83':'assumes 83',
 'and2 billion':'and 2 billion', 'per64vCPU':'per 64 vCPU', 'roughly3':'roughly 3',
 'a30,000':'a 30,000', 'about100':'about 100', 'about24':'about 24',
 'about$3k':'about $3k', 'A0.7':'A 0.7', 'approximately$':'approximately $',
 ':6.35ms':': 6.35 ms', ' at$B':' at $B', 'and51.15ms':'and 51.15 ms',
 'published12':'published 12', 'October2026':'October 2026', 'at10,000':'at 10,000',
 'A4/3/3':'A 4/3/3', 'aggregate200Gbps':'aggregate 200 Gbps',
 'or32768':'or 32768'
}
for old,new in spacing.items():report=report.replace(old,new)
(ROOT/'mpc_oram_cost_report.tex').write_text(report,encoding='utf-8')
print('Report LaTeX and figures written.')
