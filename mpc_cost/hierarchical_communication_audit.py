"""Reconcile every useful byte and expose representation/interface sensitivities.

This audits the Boolean-fingerprint baseline without silently changing it.
Packed-fingerprint transport is a separately priced, uncompiled alternative.
All base costs count BOTH interparty directions, in bytes per logical query.
Distributed intra-party sends and framing have separate explicit fields.
"""
from math import log2
from pathlib import Path
import json

from .hierarchical_cache import adaptive_plan
from .hierarchical_io import state_io
from .hierarchical_throughput import directions
from .hierarchical_address import prf_ands, inputs, epoch_inputs as row_epoch_inputs, current_case, scheme, SCHEME

ROOT=Path(__file__).resolve().parent


def audit(c):
    b=c['batch']; k=int(log2(b)); z=c['child_z']
    a=c['rebuild_ands_components_per_query']
    swaps=c['rebuild_payload_swaps_per_query']
    scan=c['read_payload_selectors_per_query']
    tables=c['average_occupied_tables']
    movement=sum(v for name,v in a.items()
                 if 'metadata' in name or name=='retained_suffix_bits_in_butterfly')
    planners=sum(a.values())-movement-a['routing_prf']-a['fresh_epoch_key_schedules']
    epoch_inputs=sum(row_epoch_inputs(r)/r['accesses_per_rebuild'] for r in c['rows'])
    lookup_ands=sum((1 if r['top'] else .5)*prf_ands(r) for r in c['rows'])
    dummy_inputs=sum((1 if r['top'] else .5)*sum(inputs(r)) for r in c['rows'])
    current=scheme(c)==SCHEME
    addr=sum((1 if r['top'] else .5)*2*(r['parent_routing_stages']
             +c['local_refinement']['suffix_bits'])/8 for r in c['rows'])
    useful={
        'application_key_input':64*256,
        'application_fingerprint_prf':32*10240,
        'deduplication_and_result_propagation':c['frontend_and_dedup_unframed_bytes_per_query']-64*256-32*10240,
        ('lookup_single_real_prf' if current else 'lookup_real_and_dummy_prfs'):32*lookup_ands,
        'lookup_fingerprint_equality':32*127*scan,
        'lookup_other_boolean_work':32*(c['read_ands_per_query']-lookup_ands-127*scan),
        'lookup_packed_payload':160*scan,
        'lookup_address_disclosure':addr,
        'rebuild_boolean_movement':32*movement,
        'rebuild_routing_prfs':32*a['routing_prf'],
        'rebuild_planners_and_checks':32*planners,
        'rebuild_epoch_key_setup_and_inputs':32*a['fresh_epoch_key_schedules']+epoch_inputs,
        'rebuild_packed_payload':160*swaps,
    }
    if current:
        useful['lookup_private_dummy_randomness_inputs']=dummy_inputs
    if abs(sum(useful.values())-c['total_unframed_bytes_per_query']) > 1e-6:
        raise AssertionError('Communication components do not reconcile')
    key_movement=4096*swaps
    flags_movement=64*swaps
    tag_movement=32*movement-key_movement-flags_movement

    # Cost by rebuild stage, independent of semantic-field decomposition.
    stage={}
    for name,prefix,metadata_keys in (
        ('source_main_compaction','source_compact',('source_compact_metadata',)),
        ('source_stash_readmission','source_stash_reentry',('source_stash_reentry_metadata',)),
        ('parent_butterfly','mergesplit',('butterfly_metadata','retained_suffix_bits_in_butterfly')),
        ('local_refinement','local_split',('local_split_metadata',)),
        ('global_residual_collection','global_stash_merge',('global_stash_merge_metadata',))):
        metadata_ands=sum(a.get(x,0.) for x in metadata_keys)
        if name=='parent_butterfly':
            ss=sum(10*r['capacity']*r['parent_routing_stages']/r['accesses_per_rebuild'] for r in c['rows'])
        elif name=='local_refinement':
            ss=sum(r['parent_buckets']*c['local_refinement']['payload_swaps']/r['accesses_per_rebuild'] for r in c['rows'])
        else:
            ss=metadata_ands/130
        stage[name]=dict(metadata_gc=32*metadata_ands,
                         planner_gc=32*a.get(prefix+'_planner',0),payload_ot=160*ss)
        stage[name]['total']=sum(stage[name].values())
    stage['fresh_hashes_and_key_setup']=dict(total=useful['rebuild_routing_prfs']+
                                             useful['rebuild_epoch_key_setup_and_inputs'])
    stage['remaining_checks']=dict(total=32*sum(v for name,v in a.items()
        if name in ('discard_top_tombstones','source_stash_top_absence_clear','global_stash_overflow_check')))
    if abs(sum(x['total'] for x in stage.values())-c['rebuild_unframed_bytes_per_query']) > 1e-6:
        raise AssertionError('Rebuild stages do not reconcile')

    hot=adaptive_plan(c,cutoff_log=16)
    waste=hot['skip_final_refill_waste_bytes_per_query']*127/134
    bridges=4096*tables
    d=directions(c)
    io=state_io(c)['tiled_components_bytes_per_query']
    rebuild_io=sum(io.values())-io['read_bucket_and_stash_full_read_write']
    cold_visits=sum(1 if r['top'] else .5 for r in c['rows'] if r['log_capacity']>16)
    cold_reads=2*2112*z*cold_visits  # All stashes and small tables are in RAM.
    internal_per_direction=(rebuild_io+cold_reads)/2
    forward=d['forward']+waste+bridges
    reverse=d['backward']

    # Sensitivity: independent fresh label pairs at persistent-state inputs.
    # This is NOT added when importing committed wire pairs directly.
    persistent_rebuild_slots=sum(((4 if r['top'] else 2)*r['capacity']+r['source_stash_slots'])
                                 /r['accesses_per_rebuild'] for r in c['rows'])
    relabel_read=32*130*scan
    relabel_rebuild=32*130*persistent_rebuild_slots

    # Optional separate backend: 128-bit key + 256-bit payload in word OTs.
    # Source key wires convert locally to shares. n keys reenter before PRF;
    # all 2n+G published positions reenter before Boolean lookup storage.
    rein_keys=sum((3*r['capacity']+r['global_stash']['capacity'])/r['accesses_per_rebuild']
                 for r in c['rows'])
    conversions=8192*rein_keys
    extra_word_ot=64*swaps
    packed_delta=-key_movement+extra_word_ot+conversions

    return dict(log_records=c['log_records'],batch=b,child_z=z,address_scheme=scheme(c),
        useful=useful,useful_total=sum(useful.values()),rebuild_stages=stage,
        rebuild_fields=dict(key_gc=key_movement,flags_gc=flags_movement,
                            transient_tag_gc=tag_movement,payload_ot=160*swaps),
        prf=dict(initial_aes_calls=2,lookup_aes_calls=(1 if current else 2)*tables,
                 rebuild_aes_calls=sum(r['capacity']/r['accesses_per_rebuild'] for r in c['rows']),
                 datapath_bytes=32*(10240+lookup_ands+a['routing_prf']),
                 extra_initial_aes_block_bytes=163840,
                 full_hierarchy_independent_address_bits=sum(r['parent_routing_stages']+
                    c['local_refinement']['suffix_bits'] for r in c['rows'])),
        deployment=dict(cache_waste_forward=waste,query_bridges_forward=bridges,
            unframed_interparty_forward=forward,unframed_interparty_reverse=reverse,
            framed_interparty_total=1.05*(forward+reverse),
            internal_per_party_per_direction=internal_per_direction,
            internal_all_parties_total_sends=2*internal_per_direction,
            framed_network_total_sends=1.05*(forward+reverse+2*internal_per_direction),
            bottleneck_nic_direction_per_party=1.05*(forward+internal_per_direction),
            note='Count network sends once, not both sender and receiver. Each party internally sends and receives I.'),
        unrelated_labels_sensitivity=dict(read=relabel_read,rebuild=relabel_rebuild,
            total=relabel_read+relabel_rebuild,extra_input_ports_only=True),
        full_extra_128bit_tag_sensitivity=dict(extra_movement=key_movement,
            maximum_rebuild_prf_saving=useful['rebuild_routing_prfs'],
            one_saved_aes_break_even_extra_swaps=(max(prf_ands(r) for r in c['rows'])/128
                                                  if current else 40)),
        optional_packed_fingerprint_rebuild=dict(removed_key_gc=key_movement,
            extra_word_ot=extra_word_ot,key_reinput=conversions,
            total=sum(useful.values())+packed_delta,
            rebuilding=c['rebuild_unframed_bytes_per_query']+packed_delta,
            status='Separate uncompiled representation variant; no revised AWS prices claimed.'))


def main():
    source=json.loads((ROOT/'results/hierarchical_split_comparison.json').read_text())
    cases=[current_case(c) for c in source['batch_sweep'] if c['batch'] in (1024,2048) and c['child_z']==64]
    out=dict(baseline='Boolean 128-bit fingerprints and 2 flags; packed 256-bit payloads; fresh table-epoch PRFs',
             cases=[audit(c) for c in cases])
    path=ROOT/'results/hierarchical_communication_audit.json'
    path.write_text(json.dumps(out,indent=2)+'\n')
    for r in out['cases']:
        print(f"N=2^{r['log_records']} B={r['batch']} useful={r['useful_total']/1e6:.6f} MB/q "
              f"all network sends={r['deployment']['framed_network_total_sends']/1e6:.6f} MB/q")


if __name__=='__main__':
    main()
