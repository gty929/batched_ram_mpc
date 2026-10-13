"""Summarize saved 2^28 and 2^32 runs and generate the size-comparison section."""
import json
from math import ceil
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def render():
    results=[]
    for exponent,sub in ((28,''),(32,'size_2p32')):
        folder=ROOT/'results'/sub
        summary=json.loads((folder/'summary.json').read_text())
        central=next(s for s in summary['scenarios'] if s['scenario']=='central')
        comparison=json.loads((folder/'bottleneck_scan_comparison.json').read_text())
        results.append(dict(exponent=exponent,central=central,comparison=comparison))
    (ROOT/'results/size_comparison.json').write_text(json.dumps(results,indent=2)+'\n')
    a,b=results
    x,y=a['central']['result'],b['central']['result']
    # The explanatory comparison is specific to these two read-only service
    # scenarios. Reject incompatible reruns instead of emitting stale prose.
    for case in results:
        design=case['central']['design']
        expected=dict(records=2**case['exponent'],key_bytes=32,value_bytes=32,
                      parties=10,threshold=4,rate=10_000)
        if any(design[key] != value for key,value in expected.items()):
            raise ValueError('Size section requires the audited 32-byte/ten-party/10k-read scenarios.')
        if case['central']['result']['transfer_usd_year'] != 0:
            raise ValueError('Size section EC2 comparison assumes zero charged cross-AZ transfer.')
    if a['central']['deployment'] != b['central']['deployment'] or a['central']['backend'] != b['central']['backend']:
        raise ValueError('Size section requires common backend and deployment assumptions.')
    rows=[]
    def row(label,one,two):rows.append(f'{label} & {one} & {two} '+r'\\')
    row('Logical records',r'$2^{28}$',r'$2^{32}$')
    row('Raw key/value database',*(f"{case['central']['design']['records']*64/2**30:g} GiB" for case in results))
    row('Batch / map packing fanout',f"{x['batch']} / {x['fanout']}",f"{y['batch']} / {y['fanout']}")
    row('Actual flat base (labels/table)',f"{x['base_cells']:,}",f"{y['base_cells']:,}")
    row('Recursive ORAM trees/table',x['levels'],y['levels'])
    row('Secure outputs/read',f"{x['reductions_per_read']/1e6:.2f}M",f"{y['reductions_per_read']/1e6:.2f}M")
    row('Sent MB/read/party',f"{x['sent_mb_per_party_read']:,.1f}",f"{y['sent_mb_per_party_read']:,.1f}")
    row('State TiB/party/replica',f"{x['state_gib_per_party_per_replica']/1024:.2f}",f"{y['state_gib_per_party_per_replica']/1024:.2f}")
    row('Nodes/party/replica',x['nodes_per_party_per_replica'],y['nodes_per_party_per_replica'])
    row('Independent replicas',x['replicas'],y['replicas'])
    row('All-party EC2 instances',f"{x['total_instances']:,}",f"{y['total_instances']:,}")
    row('Modeled mean latency',f"{a['central']['queue']['mean_seconds']:.2f} s",f"{b['central']['queue']['mean_seconds']:.2f} s")
    row('Conditional EC2 USD/year',f"\\${x['total_usd_year']/1e9:.2f}B",f"\\${y['total_usd_year']/1e9:.2f}B")
    scanrows=[]
    for case in results:
        for r in case['comparison']['rows']:
            scanrows.append(f"$2^{{{case['exponent']}}}$ & {r['name'].replace('Circuit OPRAM reference','OPRAM').replace('Naive full-key scan','Full-key scan').replace('Indexed 2D dot scan','Indexed 2D scan')} & "
                f"{r['cpu_operations_per_read']/1e9:,.2f} & {r['sent_bytes_party_per_read']/1e9:,.3f} & "
                f"{r['capacity_equivalent']['annual_resource_equivalent_usd']/1e9:,.2f} "+r'\\')
    oram=next(r for r in b['comparison']['rows'] if r['name']=='Circuit OPRAM reference')
    phase=oram['phase_split_batch'];q=b['central']['design']['batch']
    no_mem=b['comparison']['oram_without_storage_constraint']
    sku=b['comparison']['assumptions']['instance']
    if sku['name'] != y['instance'] or no_mem['instance'] != y['instance']:
        raise ValueError('Memory comparison must retain the selected instance type.')
    memory_usable=sku['memory_gib']*b['central']['deployment']['memory_usable']
    memory_min=ceil(y['memory_required_gib_per_party_per_replica']/memory_usable)
    if not (y['cpu_seconds']>=max(y['network_seconds'],y['ram_seconds'])
            and no_mem['nodes_per_party_per_replica']<memory_min<=y['nodes_per_party_per_replica']
            and a['comparison']['oram_without_storage_constraint']['total_instances']==x['total_instances']
            and b['central']['queue']['mean_seconds']<a['central']['queue']['mean_seconds']):
        raise ValueError('Saved results no longer support the CPU/memory bottleneck comparison; revise prose.')
    fanout_note=(r'The larger selection is on the upper fanout boundary; '
                 if y['fanout']==256 else r'The larger selection is within the fanout grid; ')
    fanout_note+=r'it is the best point in this grid, not a global optimum.'
    base_note=f"The flat base contains {y['base_cells']:,} labels."
    if y['base_cells']>y['cutoff']:
        if ceil(y['base_cells']/y['fanout'])>=2*y['batch']:
            raise ValueError('Base exceeds cutoff without the expected minimum-tree-size guard.')
        base_note=(f"The flat base contains {y['base_cells']:,} labels despite a nominal cutoff of "
                   f"{y['cutoff']:,}, because the next tree would have fewer than "+r'$2B$ leaves. '
                   r'The model stops recursion there.')
    full_scan=next(r for r in b['comparison']['rows'] if r['name']=='Naive full-key scan')
    indexed_scan=next(r for r in b['comparison']['rows'] if r['name']=='Indexed 2D dot scan')
    text=r'''
\clearpage
\section{Scaling the interactive MPC service to \texorpdfstring{$2^{32}$}{2 to the 32} records}
\label{sec:scale}
The larger proposal case retains 32-byte keys, 32-byte values, ten parties,
four malicious corruptions with abort, and 10,000 logical reads/s. We repeat the
complete parameter sweep and its CPU/exchange sensitivities. Both cases use two
cuckoo arrays whose combined capacity is $4N$ at the rounded 40\% load ceiling;
the actual occupancy is 25\%. These estimates cover flat key/value lookups, not
Merkle-proof retrieval. The $2^{28}$ case is a power-of-two planning size, not the
proposal's exact 206.8-million-account count.

\begin{center}\small\begin{tabular}{lrr}\toprule
Selected central reference & Smaller database & Larger database\\\midrule
SIZE_ROWS
\bottomrule\end{tabular}\end{center}
The smaller selection uses \texttt{SMALL_SKU}; the larger uses
\texttt{LARGE_SKU}. Prices, throughput assumptions and the MEAN_LIMIT-second mean
limit are unchanged. The full search includes batches 64--2048, fanouts 4--256,
both metadata representations and both sorting templates. FANOUT_NOTE
BASE_NOTE
The complete sensitivity runs are saved in \texttt{results/size\_2p32/}.

\textbf{The bottleneck changes with size.} For the $2^{32}$ selection, CPU demand
is CPU_SECONDS s/batch, network demand is NET_SECONDS s and dependent exchanges
add ROUND_SECONDS s. CPU still controls the resource term, but RAM capacity also
constrains provisioning: the state plus modeled scratch/buffer requires MEM_TIB
TiB per party per replica. Each selected INSTANCE_GIB-GiB instance provides USABLE_GIB GiB of
usable RAM, requiring at least MEMORY_MIN nodes; the grid selects MEMORY_SELECTED. At the same fixed
circuit and instance type, removing only the memory constraint gives NO_MEM_NODES nodes,
NO_MEM_REPLICAS replicas and approximately \$NO_MEM_B B/year. Thus the earlier statement
that storage does not affect the chosen fleet applies to the $2^{28}$ reference.

Per $2^{32}$ logical read and party, preprocessing accounts for OFF_MB MB and
OFF_CPU million weighted CPU operations; online work accounts for ON_MB MB and
ON_CPU million operations. These are the same source-derived phase allocations
as Section~\ref{sec:bottleneck}, not new measured rates. The selected mean is lower than in the
smaller case because memory capacity forces a larger parallel allocation, not
because larger databases inherently have lower latency.

\subsection{Scan comparison at both sizes}
\begin{center}\small\begin{tabular}{llrrr}\toprule
Records & Construction & Weighted Gops/read & GB sent/read & USD B/year\\
&&\multicolumn{2}{c}{per party}&all parties\\\midrule
SCAN_ROWS
\bottomrule\end{tabular}\end{center}
The last column uses the common aggregate resource-capacity model from Section~\ref{sec:bottleneck};
it does not include a latency-feasible replica schedule. In particular, its ORAM
figures differ from the dedicated-replica costs above. Scan state remains shared
across concurrent read workers: at $2^{32}$, it is FULL_SCAN_GIB GiB/party for full-key
scanning and INDEXED_SCAN_GIB GiB/party for the indexed two-array scan. Full scanning grows
almost exactly 16-fold in computation and traffic. Indexed scanning grows about
16-fold in local work and fourfold in transmitted data because of the balanced
two-dimensional layout. All figures still depend on unmeasured CPU rates.
'''
    replacements={'SIZE_ROWS':'\n'.join(rows),'SCAN_ROWS':'\n'.join(scanrows),
        'SMALL_SKU':x['instance'],'LARGE_SKU':y['instance'],
        'MEAN_LIMIT':f"{b['central']['deployment']['mean_latency_limit']:g}",
        'FANOUT_NOTE':fanout_note,'BASE_NOTE':base_note,
        'CPU_SECONDS':f"{y['cpu_seconds']:.3f}",'NET_SECONDS':f"{y['network_seconds']:.3f}",
        'ROUND_SECONDS':f"{y['round_seconds']:.3f}",
        'MEM_TIB':f"{y['memory_required_gib_per_party_per_replica']/1024:.2f}",
        'INSTANCE_GIB':f"{sku['memory_gib']:g}",'USABLE_GIB':f'{memory_usable:g}',
        'MEMORY_MIN':str(memory_min),'MEMORY_SELECTED':str(y['nodes_per_party_per_replica']),
        'NO_MEM_NODES':str(no_mem['nodes_per_party_per_replica']),
        'NO_MEM_REPLICAS':str(no_mem['replicas']),
        'NO_MEM_B':f"{no_mem['total_usd_year']/1e9:.2f}",
        'FULL_SCAN_GIB':f"{full_scan['storage_gib_per_party']:,.0f}",
        'INDEXED_SCAN_GIB':f"{indexed_scan['storage_gib_per_party']:,.0f}",
        'OFF_MB':f"{phase['offline_sent_bytes']/q/1e6:.1f}",
        'ON_MB':f"{phase['online_sent_bytes']/q/1e6:.1f}",
        'OFF_CPU':f"{phase['offline_cpu_operations']/q/1e6:.1f}",
        'ON_CPU':f"{phase['online_cpu_operations']/q/1e6:.1f}"}
    for old,new in replacements.items():text=text.replace(old,new)
    (ROOT/'size_comparison_notes.tex').write_text(text,encoding='utf-8')


if __name__=='__main__':render()
