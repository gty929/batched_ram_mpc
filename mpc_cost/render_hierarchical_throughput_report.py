"""Render one consistent current-construction AWS report from saved results."""
from math import ceil
from pathlib import Path
import json
from .render_hierarchical_split_report import table as base_table
from .hierarchical_address import SCHEME

ROOT=Path(__file__).resolve().parent


def table(headers,rows,columns=None,size='small',caption=None):
    result=base_table(headers,rows,columns,size)
    return result+('\n'+r'{\footnotesize '+caption+r'\par}' if caption else '')


def main():
    throughput=json.loads((ROOT/'results/hierarchical_throughput.json').read_text())
    annual=json.loads((ROOT/'results/hierarchical_annual.json').read_text())
    audit=json.loads((ROOT/'results/hierarchical_communication_audit.json').read_text())['cases']
    selected=sorted([r for r in annual['variants'] if r['states']==7],key=lambda r:(r['batch'],r['log_records']))
    if len(selected)!=4 or any(r['address_scheme']!=SCHEME or r['schedule']['address_scheme']!=SCHEME for r in selected):
        raise ValueError('Need four current-protocol, seven-state schedules')
    if throughput['address_scheme']!=SCHEME or annual['address_scheme']!=SCHEME or any(r['address_scheme']!=SCHEME for r in audit):
        raise ValueError('Report inputs contain stale protocols')
    audit=sorted(audit,key=lambda r:(r['batch'],r['log_records']))
    primary=[r for r in throughput['primary'] if r['child_z']==64]
    lower={(r['log_records'],r['batch']):r for r in annual['primary']+annual['variants'] if r['states']==5}
    def n(r): return rf"$2^{{{r['log_records']}}}$"
    def ms(value): return f'{value*1000:.1f}'
    repl={}
    repl['RESULTPROSE']=(rf"At 10,000 queries/s, the seven-state deployment costs "
        rf"\textbf{{\${selected[0]['total_year']/1e6:.2f}M/\${selected[1]['total_year']/1e6:.2f}M annually}} "
        rf"for $N=2^{{28}}/2^{{32}}$ with $B=1024$. At $B=2048$, the cost is "
        rf"\textbf{{\${selected[2]['total_year']/1e6:.2f}M/\${selected[3]['total_year']/1e6:.2f}M}}, "
        rf"with about {ms(selected[2]['schedule']['mean_query_seconds'])}/{ms(selected[3]['schedule']['mean_query_seconds'])} ms mean "
        rf"and {ms(selected[2]['schedule']['p99_query_seconds'])}/{ms(selected[3]['schedule']['p99_query_seconds'])} ms p99 query latency.")
    repl['SUMMARY']=table(['Records','$B$','$F$','$R$','USD M/year','Mean ms','p99 ms','Max ms'],[
        [n(r),r['batch'],r['foreground_workers_per_party'],r['background_workers_per_party'],
         f"{r['total_year']/1e6:.3f}",*[ms(r['schedule'][k]) for k in ('mean_query_seconds','p99_query_seconds','max_query_seconds')]]
        for r in selected],'rrrrrrrr',size='footnotesize',caption='Seven states. F and R are foreground and background workers per party; annual cost charges both parties. Max is a finite-trace observation.')
    repl['PRUNING']=table(['Address bits','Retained S-boxes','ANDs','GC bytes'],[
        [bits,s,s*32,f'{s*1024:,}'] for bits,s in [('1--8',133),('9--16',134),('17--24',135),('25--32',136)]
    ],'rrrr',caption='Expanded-key datapath; the full 1280-AND epoch-key schedule is charged separately.')
    headers=['MB/query',r'$28$, 1024',r'$32$, 1024',r'$28$, 2048',r'$32$, 2048']
    def four(rows,caption=None): return table(headers,rows,'lrrrr',size='footnotesize',caption=caption)
    categories=[('Application-key shared input','application_key_input'),
        ('Canonical fingerprint PRF','application_fingerprint_prf'),
        ('Deduplication and result propagation','deduplication_and_result_propagation'),
        ('Lookup: one address PRF','lookup_single_real_prf'),
        ('Lookup: private dummy randomness','lookup_private_dummy_randomness_inputs'),
        ('Lookup: fingerprint equality','lookup_fingerprint_equality'),
        ('Lookup: other Boolean work','lookup_other_boolean_work'),
        ('Lookup: packed value extraction','lookup_packed_payload'),
        ('Lookup: address disclosure','lookup_address_disclosure'),
        ('Rebuild: Boolean field movement','rebuild_boolean_movement'),
        ('Rebuild: fresh routing PRFs','rebuild_routing_prfs'),
        ('Rebuild: planners and checks','rebuild_planners_and_checks'),
        ('Rebuild: epoch-key setup and inputs','rebuild_epoch_key_setup_and_inputs'),
        ('Rebuild: packed value movement','rebuild_packed_payload')]
    repl['COMMUNICATION']=four([[title,*[f"{r['useful'][key]/1e6:.6f}" for r in audit]] for title,key in categories]
        +[[r'\textbf{Total useful communication}',*[rf"\textbf{{{r['useful_total']/1e6:.6f}}}" for r in audit]]],
        'Both interparty directions, before framing and cache waste. Column labels are log2(records), batch size.')
    repl['STAGES']=four([[title,*[f"{r['rebuild_stages'][key]['total']/1e6:.6f}" for r in audit]] for title,key in (
        ('Source main-array compaction','source_main_compaction'),('Old-stash readmission','source_stash_readmission'),
        ('512-slot parent butterfly','parent_butterfly'),('Local refinement and residual extraction','local_refinement'),
        ('Global residual collection','global_residual_collection'),('Fresh hashes and epoch-key setup','fresh_hashes_and_key_setup'),
        ('Tombstone and overflow checks','remaining_checks'))],
        'An alternative grouping of rebuilding from the previous table, not additional communication.')
    repl['NETWORK']=four([[title,*[f"{r['deployment'][key]/1e6:.6f}" for r in audit]] for title,key in (
        ('Unused equality-prefetch versions','cache_waste_forward'),('Query-label bridges','query_bridges_forward'),
        (r'Interparty total, 5\% framing','framed_interparty_total'),
        ('Internal sends across both parties, unframed','internal_all_parties_total_sends'),
        (r'All network sends, 5\% framing','framed_network_total_sends'),
        ('Limiting NIC direction per party, framed','bottleneck_nic_direction_per_party'))])
    uniform=primary[0]['caches'][0]; adaptive=primary[0]['adaptive_cache']
    repl['CACHE']=table(['GB per evaluator/state; $B=1024$','Four versions','Adaptive'],[
        [title,*[f"{p[key]/1e9:.6f}" for p in (uniform,adaptive)]] for title,key in (
            ('Bucket GC queue (134-AND allowance)','gc_queue_ram_bytes_evaluator'),
            ('Persistent small-table state','persistent_state_ram_bytes_per_party'),
            ('One future stash batch','one_batch_stash_gc_bytes'),
            ('One future address-PRF batch','one_batch_prf_gc_bytes_optional'),
            ('Private dummy-input transcripts','one_batch_dummy_input_material_bytes'),
            ('Total reserved RAM','evaluator_ram_bytes_with_optional_prf'))],
        'lrr',caption=r'All seven table capacities through $2^{16}$ reserved simultaneously; fresh single-use material.')
    repl['CAPACITY']=table(['Records','$B$','NIC-only hosts/party','Scheduled hosts/party','FG use','BG use'],[
        [n(r),r['batch'],ceil(10000*a['deployment']['bottleneck_nic_direction_per_party']/throughput['nic_budget_bytes_second']),
         r['workers_per_party'],rf"{100*r['schedule']['foreground_utilization']:.1f}\%",rf"{100*r['schedule']['background_utilization']:.1f}\%"]
        for r,a in zip(selected,audit)],'rrrrrr',size='footnotesize',caption='The NIC floor includes private dummy inputs, cache waste, bridges, and internal redistribution. Scheduled pools also include modeled loading/round delays.')
    io=[]
    for title,key in [('Tiled rebuild and state I/O','tiled'),('Every swap layer spilled','every_switch_spilled'),
                      ('Tiled + one GC disk read','tiled_plus_one_gc_disk_read'),
                      ('Tiled + GC write/read','tiled_plus_gc_disk_write_read')]:
        io.append([title,*[f"{r['io_scenarios'][key]['bytes_per_query']/1e6:.3f}" for r in primary]])
    repl['IO']=table(['MB/query per party, before RAM state caching','$N=2^{28}$','$N=2^{32}$'],io,'lrr',size='footnotesize')
    repl['BUDGET']=table(['Records','$B$','EC2','EBS capacity','EBS I/O','Total'],[
        [n(r),r['batch'],*[f"{r[k]/1e6:.3f}" for k in ('ec2_year','ebs_capacity_year','ebs_io_year','total_year')]]
        for r in selected],'rrrrrr',caption='Annual USD millions; both parties; seven states, scratch, and peak provisioned I/O included.')
    repl['RAM']=table(['Records','$B$','All-state cache GB','Usable fleet RAM GB','EBS TB/party'],[
        [n(r),r['batch'],f"{r['reserved_cache_bytes_all_evaluators']/1e9:.3f}",
         f"{r['usable_dram_bytes_per_party']/1e9:.1f}",f"{r['garbler']['required_bytes']/1e12:.3f}"]
        for r in selected],'rrrrr',size='footnotesize',caption='EBS includes seven persistent states and seven scratch reservations. RAM is aggregate; cache placement and working buffers still need implementation.')
    repl['STATES']=table(['Records','$B$','Five-state max ms','Seven-state max ms','Added USD M/year'],[
        [n(r),r['batch'],ms(lower[r['log_records'],r['batch']]['schedule']['max_query_seconds']),
         ms(r['schedule']['max_query_seconds']),f"{(r['total_year']-lower[r['log_records'],r['batch']]['total_year'])/1e6:.3f}"]
        for r in selected],'rrrrr',size='footnotesize',caption='Same current protocol and worker pools; only state, scratch, and cache count change. Finite traces, not tail guarantees.')
    traffic=sorted(annual['batch_traffic'],key=lambda r:(r['log_records'],r['batch']))
    repl['BATCH']=table(['Records','$B$','Frontend','Lookup','Rebuild','Total'],[
        [n(r),r['batch'],*[f"{r[k]/1e6:.3f}" for k in ('frontend','read','rebuild','total')]] for r in traffic
    ],'rrrrrr',caption='Useful MB/query, both directions; the same single-PRF construction at each batch size.')
    sensitivity=[]
    for r in selected:
        l=r['ready_latency']
        sensitivity.append([n(r),r['batch'],ms(l['mean_query_seconds_no_queue_or_rebuild']),
            *[ms(next(t['mean_query_seconds'] for t in l['ebs_fixed_sensitivity'] if t['ebs_fixed_seconds']==v)) for v in (.001,.003)],
            ms(next(t['mean_query_seconds'] for t in l['rtt_sensitivity'] if t['rtt_seconds']==.001))])
    repl['LATENCYSENS']=table(['Records','$B$','Primary ready','EBS 1 ms','EBS 3 ms','RTT 1 ms'],sensitivity,
        'rrrrrr',size='footnotesize',caption='Mean query ms with a ready state and unchanged foreground pool. Change one delay at a time.')
    source=(ROOT/'hierarchical_throughput_report.tex').read_text()
    for key,value in repl.items(): source=source.replace('%%'+key+'%%',value)
    if '%%' in source: raise ValueError('Unresolved report marker')
    path=ROOT.parent/'output/latex/hierarchical_aws_throughput.tex'
    path.write_text(source,encoding='utf-8')
    print(path)


if __name__=='__main__': main()
