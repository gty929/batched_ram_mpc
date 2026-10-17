"""Embed reproducible tables into the standalone hierarchical ORAM report."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent


def table(headers, rows, columns=None, size='small'):
    columns = columns or ('l'+'r'*(len(headers)-1))
    lines = [rf'\begin{{center}}\{size}',
             rf'\begin{{tabular}}{{{columns}}}\toprule',
             ' & '.join(headers)+r'\\\midrule']
    lines += [' & '.join(map(str,row))+r'\\' for row in rows]
    lines += [r'\bottomrule\end{tabular}\end{center}']
    return '\n'.join(lines)


def mb(x): return f'{x/1e6:,.3f}'


def main():
    data = json.loads((ROOT/'results/hierarchical_split_comparison.json').read_text())
    primary = data['primary']
    chosen = [next(c for c in primary if c['log_records']==n and c['child_z']==64)
              for n in (28,32)]
    repl = {}
    repl['SUMMARY'] = table(['Primary: 512-to-64, $b=1024$', '$N=2^{28}$', '$N=2^{32}$'],[
        ['Rebuild MB/query',*[mb(c['rebuild_unframed_bytes_per_query']) for c in chosen]],
        ['Read MB/query',*[mb(c['read_unframed_bytes_per_query']) for c in chosen]],
        [r'\textbf{Total MB/query}',*[rf'\textbf{{{mb(c["total_unframed_bytes_per_query"])}}}' for c in chosen]],
        ['Current Circuit OPRAM MB/query','226.507','286.945'],
        ['Top global stash slots',*[c['rows'][-1]['global_stash']['capacity'] for c in chosen]],
    ])
    cs = [next(c for c in primary if c['log_records']==32 and c['child_z']==z) for z in (64,128)]
    caprows = [[a['log_capacity'],a['global_stash']['capacity'],b['global_stash']['capacity']]
               for a,b in zip(cs[0]['rows'],cs[1]['rows'])]
    # Compact two-panel table keeps every instantiated capacity explicit.
    half = (len(caprows)+1)//2
    panels = []
    for i in range(half):
        panels.append(caprows[i]+(caprows[i+half] if i+half<len(caprows) else ['--']*3))
    repl['CAPACITIES'] = table([r'$\log_2 n$','$G_{64}(n)$','$G_{128}(n)$',
                               r'$\log_2 n$','$G_{64}(n)$','$G_{128}(n)$'],panels,'rrrrrr')
    kernels = [c['local_refinement'] for c in cs]
    repl['LOCALCOUNTS'] = table(['Per 512-slot parent','64-slot leaves','128-slot leaves'],[
        ['Excess-selection planner ANDs',*[f'{k["preselection_ands"]:,}' for k in kernels]],
        ['Residual-extraction planner ANDs',*[f'{k["extraction_planner_ands"]:,}' for k in kernels]],
        ['Recursive-split planner ANDs',*[f'{k["recursive_planner_ands"]:,}' for k in kernels]],
        ['Total planner ANDs',*[f'{k["planner_ands"]:,}' for k in kernels]],
        ['Metadata-movement ANDs',*[f'{k["metadata_movement_ands"]:,}' for k in kernels]],
        ['Complete payload swaps',*[f'{k["payload_swaps"]:,}' for k in kernels]],
        ['Payload swap layers',*[k['payload_swap_layers'] for k in kernels]],
        ['Total MB at $c_V=160$',*[mb(32*k['ands']+160*k['payload_swaps']) for k in kernels]],
    ])
    rows=[]
    for logn in (28,32):
        u=next(c for c in data['unsplit'] if c['log_records']==logn)
        rows.append([rf'$2^{{{logn}}}$','512, unsplit',mb(u['rebuild_unframed_bytes_per_query']),
                     mb(u['read_unframed_bytes_per_query']),mb(u['total_unframed_bytes_per_query'])])
        for z in (64,128):
            c=next(c for c in primary if c['log_records']==logn and c['child_z']==z)
            rows.append([rf'$2^{{{logn}}}$',f'512 to {z}',mb(c['rebuild_unframed_bytes_per_query']),
                         mb(c['read_unframed_bytes_per_query']),mb(c['total_unframed_bytes_per_query'])])
        rows.append([rf'$2^{{{logn}}}$','Circuit OPRAM','--','--','226.507' if logn==28 else '286.945'])
    repl['RESULTS'] = table(['$N$','Construction','Rebuild MB','Read MB','Total MB'],rows,'llrrr')
    repl['RESULTS'] += '\n'+table(['512-to-64 traffic','$N=2^{28}$','$N=2^{32}$'],[
        ['Frontend and dedup MB/query',*[mb(c['frontend_and_dedup_unframed_bytes_per_query']) for c in chosen]],
        [r'Total with 5\% framing MB/query',*[mb(c['total_framed_bytes_per_query']) for c in chosen]],
        ['Maximum occupied-level read MB/query',*[mb(c['worst_read_unframed_bytes_per_query']) for c in chosen]],
    ])
    groupings = [
        ('Routing PRF and key schedules',['routing_prf','fresh_epoch_key_schedules']),
        ('Original source compactions',['source_compact_planner','source_compact_metadata','discard_top_tombstones']),
        ('Old-stash re-admission',['source_stash_reentry_planner','source_stash_reentry_metadata','source_stash_top_absence_clear']),
        ('Global butterfly',['mergesplit_planner','butterfly_metadata','retained_suffix_bits_in_butterfly']),
        ('Local excess, extraction, split',['local_split_planner','local_split_metadata']),
        ('Global residual collector',['global_stash_merge_planner','global_stash_merge_metadata','global_stash_overflow_check']),
    ]
    rows=[[label,*[mb(32*sum(c['rebuild_ands_components_per_query'].get(k,0) for k in keys)) for c in chosen]] for label,keys in groupings]
    rows += [['Packed payload operations',*[mb(160*c['rebuild_payload_swaps_per_query']) for c in chosen]],
             ['Total including fresh-key input',*[mb(c['rebuild_unframed_bytes_per_query']) for c in chosen]]]
    repl['DECOMPOSITION'] = table(['Rebuild component, MB/query','$N=2^{28}$','$N=2^{32}$'],rows)
    rows=[]
    for b in (512,1024,2048,4096):
        values=[]
        for n in (28,32):
            for z in (64,128):
                c=next(c for c in data['batch_sweep'] if (c['log_records'],c['child_z'],c['batch'])==(n,z,b))
                values.append(mb(c['total_unframed_bytes_per_query']))
        rows.append([b,*values,f'{(b-1)/20:.2f}'])
    repl['BATCHSWEEP'] = table(['$b$','28, $z64$','28, $z128$','32, $z64$','32, $z128$','Fill ms'],rows,'rrrrrr')
    rows=[]
    for price in (80,160,320,8192):
        vals=[]
        for n in (28,32):
            for z in (64,128):
                c=next(c for c in data['payload_sensitivity'] if (c['log_records'],c['child_z'],c['packed_payload_swap_bytes'])==(n,z,price))
                vals.append(mb(c['total_unframed_bytes_per_query']))
        rows.append([price,*vals])
    repl['PAYLOADSWEEP'] = table(['$c_V$ (bytes)','28, $z64$','28, $z128$','32, $z64$','32, $z128$'],rows,'rrrrr')
    repl['RESOURCES'] = table(['512-to-64 resource','$N=2^{28}$','$N=2^{32}$'],[
        ['Packed state per party, TB',*[f'{c["packed_state_bytes_per_party"]/1e12:,.3f}' for c in chosen]],
        ['Top rebuild communication, PB',*[f'{c["rows"][-1]["rebuild_unframed_bytes"]/1e15:,.3f}' for c in chosen]],
        ['Top rebuild payload swap layers',*[c['rows'][-1]['payload_swap_layers'] for c in chosen]],
        ['ANDs per lookup, million',*[f'{(c["rebuild_ands_per_query"]+c["read_ands_per_query"])/1e6:.3f}' for c in chosen]],
    ])+'\nThe AND row covers reads and rebuilding; the separately charged frontend adds a small amount.'
    text=(ROOT/'hierarchical_split_report.tex').read_text(encoding='utf-8')
    for name,value in repl.items():
        token=f'%%{name}%%'
        if text.count(token)!=1: raise ValueError(token)
        text=text.replace(token,value)
    if '%%' in text: raise AssertionError('Unresolved report placeholder')
    output=ROOT.parent/'output/latex/hierarchical_batch_oram_report.tex'
    output.write_text(text,encoding='utf-8')
    print(output)


if __name__=='__main__': main()
