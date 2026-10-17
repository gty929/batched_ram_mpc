"""Conditional cost ledger for interactive Circuit OPRAM with two shuffles.

Run ``python -m mpc_cost.interactive_shuffle_cost``.  This is a reproducible
composition of costed kernels and the existing Boolean planning template;
it is not an implemented OPRAM, a security proof, or a measured deployment.
The historical prices in two_party_cost.Deployment are deliberately retained.

The primary row uses ordinary Boolean labels in all garbled computations.
Pool records temporarily become ordinary packed XOR shares for two private
permutations.  They are then conservatively re-input at 64 bytes/logical bit.
No reduction of a 256-bit value to two Boolean wires is assumed.
"""
from __future__ import annotations

from dataclasses import asdict
from math import ceil
from pathlib import Path
import json

from .two_party_batch import batch_lookup, clog2
from .two_party_cost import Deployment, batch_io_price


ROOT = Path(__file__).resolve().parent
GIB = 2**30
BATCHES = (8, 16, 32, 64, 128, 256)
FANOUTS = (4, 8, 16, 32)
BASE_CUTOFFS = (16, 32, 64, 128, 256, 512, 1024, 2048, 4096)
CMAC_ANDS_PER_QUERY = 10_240


def waksman_switches(items: int) -> int:
    """Switch count of an arbitrary-size recursive Waksman network.

    S(1)=0 and S(n)=S(floor(n/2))+S(ceil(n/2))+n-1.  This is a
    switch count, not a claim that a circuit implementing a secret switch
    costs one byte or one AND independently of the switched record width.
    The separate two-shuffle transport construction supplies that pricing.
    """
    if items < 1:
        raise ValueError('A permutation must have at least one item')
    levels = clog2(items)
    return items*levels-(1 << levels)+1


def pool_shuffle_ledger(address_bits: int, record_bits: int, batch: int,
                        pool_records: int) -> dict:
    """One table/tree/batch: match tags, shuffle shares, open tags, re-input.

    Tags 1..B each occur exactly once: either on the matching resident
    record or on its appended dummy.  Unselected rows have tag zero.  This
    fixed tag multiset hides which requests hit the pool after both parties'
    independently secret permutations.  Returned records remain shared.

    UID equality, validity and representative gating use h+2 AND/match.
    Unique live UIDs and secret request deduplication make matches disjoint.
    Tags are XORs of public tag constants masked by match bits, so their
    construction introduces no further ANDs.  Result grouping/fanout and
    saved inverse controls remain in request_conflicts's original allowance;
    the result-dependent portions must execute AFTER retrieval.

    The selected two-permutation transport budget is
      (2*n+4*S)*ceil((R+t)/8) + 32*S bytes,
    split equally by direction.  The last two terms are separate switch
    transport and OT-extension allowances, not garbled AND tables.  Opening
    both parties' packed tag shares adds 2*ceil(n*t/8) bytes.  GC-to-share
    output uses local permutation/color bits and has no network payload.
    Re-input costs 48*n*R bytes G->E and 16*n*R E->G.  Tags are public after
    opening and do not require re-input.  Base OT setup is not charged here.
    """
    if min(address_bits, record_bits, batch, pool_records) < 1:
        raise ValueError('Widths and counts must be positive')
    n = pool_records+batch
    tag_bits = clog2(batch+1)
    switches = waksman_switches(n)
    row_bytes = ceil((record_bits+tag_bits)/8)
    data_bytes = 2*n*row_bytes
    switch_bytes = 4*switches*row_bytes
    extension_bytes = 32*switches
    tag_open_bytes = 2*ceil(n*tag_bits/8)
    symmetric = data_bytes+switch_bytes+extension_bytes+tag_open_bytes
    reinput_bits = n*record_bits
    ands = batch*pool_records*(address_bits+2)
    return dict(address_bits=address_bits, record_bits=record_bits,
                requests=batch, pool_records=pool_records, shuffle_items=n,
                tag_bits=tag_bits, packed_row_bytes=row_bytes,
                switches_per_permutation=switches,
                match_ands=ands, match_table_bytes=32*ands,
                two_shuffle_record_bytes=data_bytes,
                two_shuffle_switch_bytes=switch_bytes,
                two_shuffle_ot_extension_bytes=extension_bytes,
                tag_opening_bytes=tag_open_bytes,
                symmetric_protocol_bytes=symmetric,
                symmetric_forward_bytes=symmetric//2,
                symmetric_backward_bytes=symmetric//2,
                reinput_bits=reinput_bits,
                reinput_forward_bytes=48*reinput_bits,
                reinput_backward_bytes=16*reinput_bits,
                gc_to_share_network_bytes=0,
                tag_reinput_bits=0)


def _sum_pool_ledgers(ledgers: list[dict]) -> dict:
    fields = ('match_ands', 'match_table_bytes', 'two_shuffle_record_bytes',
              'two_shuffle_switch_bytes', 'two_shuffle_ot_extension_bytes',
              'tag_opening_bytes', 'symmetric_protocol_bytes',
              'symmetric_forward_bytes', 'symmetric_backward_bytes',
              'reinput_bits', 'reinput_forward_bytes',
              'reinput_backward_bytes')
    # Both cuckoo tables execute the same collection of recursive trees.
    return {name: 2*sum(x[name] for x in ledgers) for name in fields}


def circuit_case(log_records: int, batch: int, fanout: int, base_cutoff: int,
                 *, bucket_z: int = 3, pool_slack: int = 128) -> dict:
    """Replace only the specified kernels; retain all other allowances."""
    base = batch_lookup(log_records, batch, fanout, base_cutoff,
                        bucket_z=bucket_z, pool_slack=pool_slack)
    trees = base['trees_per_table']
    ledgers = [pool_shuffle_ledger(t['address_bits'], t['record_bits'],
                                  batch, t['pool_records']) for t in trees]
    pools = _sum_pool_ledgers(ledgers)
    removed = 2*sum(t['parts']['pool_fetch']['ands'] for t in trees)
    fused_savings = 2*batch*base['base_cells']*base['base_label_bits']
    components = {
        phase: 2*sum(t['parts'][phase]['ands'] for t in trees)
        for phase in trees[0]['parts'] if phase != 'pool_fetch'
    }
    components['pool_match_tags'] = pools['match_ands']
    components['packed_recursive_updates'] = 2*sum(
        p['ands'] for p in base['packed_updates_per_table'])
    components['fused_flat_base'] = 2*base['base_work_per_table']['ands']-fused_savings
    components['application_match_and_select'] = base['application_ands']
    components['aes_cmac_frontend'] = batch*CMAC_ANDS_PER_QUERY
    ands = sum(components.values())
    if ands != base['ands_per_batch']-removed-fused_savings+pools['match_ands']+batch*CMAC_ANDS_PER_QUERY:
        raise AssertionError('Kernel substitution accounting mismatch')
    positions = base['fresh_position_bits_per_query']
    paths = base['public_path_bits_per_query']
    # x=x_G XOR x_E, each share256bits; indices are computed internally.
    traffic = dict(
        garbled_tables_forward=32*ands/batch,
        shuffle_records_each_direction=pools['two_shuffle_record_bytes']/(2*batch),
        shuffle_switches_each_direction=pools['two_shuffle_switch_bytes']/(2*batch),
        shuffle_ot_extension_each_direction=pools['two_shuffle_ot_extension_bytes']/(2*batch),
        tag_opening_each_direction=pools['tag_opening_bytes']/(2*batch),
        reinput_forward=pools['reinput_forward_bytes']/batch,
        reinput_backward=pools['reinput_backward_bytes']/batch,
        query_share_input_forward=48*256,
        query_share_input_backward=16*256,
        joint_position_input_forward=48*positions,
        joint_position_input_backward=16*positions,
        # Reveal requested old paths to BOTH parties: G sends zero-label
        # colors, E sends active-label colors. Each side XORs the two.
        public_old_paths_forward=paths/8,
        public_old_paths_backward=paths/8,
        answer_share_conversion_network=0,
        plaintext_answer_decoding=0,
    )
    symmetric = pools['symmetric_protocol_bytes']/(2*batch)
    forward = (traffic['garbled_tables_forward']+symmetric
               +traffic['reinput_forward']+traffic['query_share_input_forward']
               +traffic['joint_position_input_forward']
               +traffic['public_old_paths_forward'])
    backward = (symmetric+traffic['reinput_backward']
                +traffic['query_share_input_backward']
                +traffic['joint_position_input_backward']
                +traffic['public_old_paths_backward'])
    return dict(
        log_records=log_records, batch=batch, fanout=fanout,
        base_cutoff=base_cutoff, bucket_z=bucket_z, pool_slack=pool_slack,
        base_cells=base['base_cells'], base_label_bits=base['base_label_bits'],
        tree_address_bits=[t['address_bits'] for t in trees],
        tree_payload_bits=[t['payload_bits'] for t in trees],
        tree_record_bits=[t['record_bits'] for t in trees],
        baseline_ands_per_batch=base['ands_per_batch'],
        removed_pool_fetch_ands_per_batch=removed,
        fused_flat_savings_ands_per_batch=fused_savings,
        ands_per_batch=ands, ands_per_query=ands/batch,
        and_components_per_batch=components,
        and_components_per_query={k: v/batch for k, v in components.items()},
        table_bytes_per_query=32*ands/batch,
        pool_protocol_per_tree_per_table=ledgers,
        pool_protocol_both_tables_per_batch=pools,
        unframed_traffic_bytes_per_query=traffic,
        unframed_forward_bytes_per_query=forward,
        unframed_backward_bytes_per_query=backward,
        unframed_total_bytes_per_query=forward+backward,
        fresh_position_bits_per_query=positions,
        public_path_bits_per_query=paths,
        state_bits=base['state_bits'],
        label_state_bytes_per_party=base['label_state_bytes_per_party'],
        persistent_bits_touched_per_batch=base['persistent_bits_touched_per_batch'],
        label_state_read_write_bytes_per_party_batch=base['label_state_read_write_bytes_per_party_batch'],
        path_reveal_barriers=base['path_reveal_barriers'],
        pool_shuffle_invocations_per_table=len(trees),
        interaction_rounds=None,
        interaction_note='Two table chains can run in parallel. Path reveals, interactive shuffle/OT and tag opening require a dependency schedule; this ledger does not equate gate depth or shuffle calls to round trips.',
        persistent_prf_context_logical_bits_per_party=11*128+128,
        persistent_prf_context_label_bytes_per_party=16*(11*128+128),
        prf_setup_ands_per_epoch=6400,
        prf_setup_input_bytes_per_epoch=64*128,
        prf_setup_amortization_charged=False,
        output_bits_shared_between_parties=257,
        external_client_delivery_priced=False,
    )


def price_case(c: dict, *, dep: Deployment = Deployment(), states: int = 1) -> dict:
    """Historical directional NIC/state/I/O estimate, with separate CPU rows.

    CPU rows price ordinary AND work ONLY.  They omit local XORs, OT/shuffle
    work, AES/PRG transport hashes, serialization and distribution.  They are
    not the older model's purported complete-runtime AND-rate scenarios.
    """
    if states < 1:
        raise ValueError('At least one state is required')
    forward = dep.framing*c['unframed_forward_bytes_per_query']
    backward = dep.framing*c['unframed_backward_bytes_per_query']
    network_hosts = max(1, ceil(dep.qps*max(forward, backward)/dep.nic_bytes_second))
    # Include the small immutable PRF context in capacity, while retaining
    # exactly the pre-existing persistent database I/O envelope.
    per_party_state = (c['label_state_bytes_per_party']
                       +c['persistent_prf_context_label_bytes_per_party'])*states
    storage_hosts = max(1, ceil(per_party_state/(65536*GIB*25)))
    io = batch_io_price(c, dep, states=states)
    hosts = max(network_hosts, storage_hosts, io['ebs_nodes_per_party'])
    ssd = 2*per_party_state/GIB*dep.gp3_gib_year
    io_cost = io['extra_gp3_io_usd_year_both_parties']
    host_cost = 2*hosts*dep.hourly_usd*8760
    cpu = []
    for rate in (50e6, 200e6, 1000e6):
        cpu_hosts = max(hosts, ceil(dep.qps*c['ands_per_query']/rate))
        cpu.append(dict(assumed_ordinary_ands_per_node_second=rate,
                        nodes_per_party=cpu_hosts,
                        ordinary_and_capacity_usd_year=2*cpu_hosts*dep.hourly_usd*8760+ssd+io_cost,
                        includes_ot_shuffle_xor_runtime=False,
                        is_complete_cpu_budget=False))
    return dict(
        forward_wire_bytes_per_query=forward,
        backward_wire_bytes_per_query=backward,
        total_wire_bytes_per_query=forward+backward,
        network_nodes_per_party=network_hosts,
        capacity_and_io_nodes_per_party=hosts,
        nodes_total=2*hosts,
        network_ec2_usd_year=2*network_hosts*dep.hourly_usd*8760,
        extra_capacity_io_ec2_usd_year=2*(hosts-network_hosts)*dep.hourly_usd*8760,
        ssd_capacity_usd_year=ssd,
        modeled_persistent_io_usd_year=io_cost,
        network_capacity_and_io_usd_year=host_cost+ssd+io_cost,
        persistent_io=io,
        state_bytes_per_party=per_party_state,
        ordinary_and_cpu_sensitivities=cpu,
        independent_states=states,
        retained_program_bytes=0,
        minimum_stream_buffers_both_parties=2*dep.stream_buffer_bytes_per_party,
        buffers_exclude_worker_scratch_and_ot_state=True,
        one_state_max_batch_service_seconds_at_70pct_util=.7*c['batch']/dep.qps,
        mean_batch_fill_seconds=(c['batch']-1)/(2*dep.qps),
        measured_batch_service_seconds=None,
        supports_claimed_qps=False,
    )


def _choice_key(row: dict) -> tuple:
    p = row['price']
    return (p['network_capacity_and_io_usd_year'],
            p['forward_wire_bytes_per_query'], p['total_wire_bytes_per_query'],
            row['circuit']['ands_per_query'], row['circuit']['fanout'],
            row['circuit']['base_cutoff'])


def _compact(row: dict) -> dict:
    c, p = row['circuit'], row['price']
    return dict(batch=c['batch'], fanout=c['fanout'], base_cutoff=c['base_cutoff'],
                base_cells=c['base_cells'], path_reveal_barriers=c['path_reveal_barriers'],
                ands_per_query=c['ands_per_query'], table_bytes_per_query=c['table_bytes_per_query'],
                forward_wire_bytes_per_query=p['forward_wire_bytes_per_query'],
                backward_wire_bytes_per_query=p['backward_wire_bytes_per_query'],
                total_wire_bytes_per_query=p['total_wire_bytes_per_query'],
                network_nodes_per_party=p['network_nodes_per_party'],
                network_capacity_and_io_usd_year=p['network_capacity_and_io_usd_year'])


def sweep(log_records: int, *, dep: Deployment = Deployment()) -> dict:
    all_rows, by_batch = [], []
    for batch in BATCHES:
        rows = []
        for fanout in FANOUTS:
            for cutoff in BASE_CUTOFFS:
                c = circuit_case(log_records, batch, fanout, cutoff)
                rows.append(dict(circuit=c, price=price_case(c, dep=dep)))
        all_rows.extend(rows)
        by_batch.append(min(rows, key=_choice_key))
    chosen = min(by_batch, key=_choice_key)
    minimum_forward = min(all_rows, key=lambda r: (r['price']['forward_wire_bytes_per_query'],
                                                  r['price']['network_capacity_and_io_usd_year']))
    return dict(log_records=log_records, selected=chosen,
                minimum_forward_case=_compact(minimum_forward),
                best_by_batch=by_batch,
                all_points=[_compact(row) for row in all_rows])


def main() -> None:
    dep = Deployment()
    result = dict(
        as_of='2026-10-16',
        status='Conditional kernel-composition planning estimate; no executed full protocol or throughput benchmark',
        security='Two-party semi-honest; secret-shared query and AES-128 PRF key;128-bit garbling labels',
        prices_source='Historical Deployment constants: October12 AWS price-feed snapshot retained in two_party_cost.py; not a live quote',
        deployment=asdict(dep),
        sweep=dict(batch=list(BATCHES), fanout=list(FANOUTS), base_cutoff=list(BASE_CUTOFFS),
                   objective='Minimum historical network+capacity+modeled I/O price; then forward and total bytes'),
        primary_representation='Ordinary Boolean garbling labels; temporary ordinary packed XOR shares in pool shuffles',
        packed_value_sensitivity=dict(
            status='Not priced in this composition',
            proposed_packed_labels_per_256bit_value=2,
            unresolved='A packed-word selection primitive and conversions between its encoding, Boolean GC and ordinary XOR shares are required. Replacing256Boolean wires by2without that construction is not a priced optimization.'),
        caveats=[
            'The original pool eviction/cleanup, recursive packed update and parallel eviction composition allowances remain.',
            'Request deduplication occurs before disclosure; result-dependent grouping and inverse routing must be scheduled after retrieval.',
            'The two-shuffle transport/OT constants are explicit construction assumptions, not an executed implementation trace.',
            'Shuffle tag multiplicities must be fixed: each request tag once and zero on all remaining rows.',
            'Base-OT setup, PRF setup amortization, hidden database initialization and external-client input/output delivery are excluded.',
            'Ordinary AND CPU sensitivities do not charge the substantial shuffle, OT, re-input, XOR, hash, memory or intraparty distribution work.',
            'Z3, pool slack128 and cuckoo stash8 need a finite service-lifetime failure analysis.',
            'Selected one-state rows require measured complete batch reuse time; aggregate network or CPU capacity alone does not prove10kQPS.',
            'A dependency schedule for path opening, two interactive shuffles and tag opening is not yet costed in RTTs.',
            'Persistent garbling labels require a concrete composable label-renewal and hash-tweak protocol.',
        ],
        rows=[sweep(n, dep=dep) for n in (28, 32)],
    )
    target = ROOT/'results'/'interactive_shuffle_comparison.json'
    target.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    for row in result['rows']:
        c, p = row['selected']['circuit'], row['selected']['price']
        print(f'N=2^{row["log_records"]}: B{c["batch"]}/F{c["fanout"]}/base{c["base_cells"]}; '
              f'{c["ands_per_query"]/1e6:.6f}M AND/query; '
              f'{p["forward_wire_bytes_per_query"]/1e6:.6f}MB forward, '
              f'{p["backward_wire_bytes_per_query"]/1e6:.6f}MB backward; '
              f'{p["network_nodes_per_party"]}NIC hosts/party; '
              f'${p["network_capacity_and_io_usd_year"]/1e6:.6f}M/year conditional')


if __name__ == '__main__':
    main()
