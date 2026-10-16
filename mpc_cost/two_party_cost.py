"""Reproducible semi-honest two-party capacity estimates, 16 October 2026.

Run python -m mpc_cost.two_party_cost. These are conditional resource estimates,
not benchmarked deployments. See data/two_party_notes.txt for interpretation.
Keep the previous ten-party malicious model and its results unchanged.
"""
from dataclasses import asdict, dataclass
from math import ceil
from pathlib import Path
import json

from .garbled_circuit import kv_lookup
from .two_party_batch import batch_lookup
from .two_party_merge import merge_cost

ROOT = Path(__file__).resolve().parent
GIB = 2**30
YEAR_SECONDS = 365*24*3600


@dataclass(frozen=True)
class Deployment:
    qps: int = 10_000
    hourly_usd: float = 7.2576
    nic_bytes_second: float = 200e9/8*.65*.70*.70
    framing: float = 1.05
    gp3_gib_year: float = .96
    and_table_bytes: float = 32.
    label_bytes: int = 16
    stream_buffer_bytes_per_party: int = 64*2**20


def input_traffic(query_bits, position_bits, joint=True):
    """Classic chosen-input OT allowance, no amortized base-OT constant.

    Evaluator key/index bits: 32 B/bit forward,16 backward.
    Joint position: additionally16 B/bit G input label,32 B/bit E OT payload,
    16 B/bit E OT matrix. Free XOR combines the private contributions.
    In GRAM only G samples new positions, charged16 B/bit forward.
    """
    return dict(forward=32*query_bits+(48 if joint else 16)*position_bits,
                backward=16*(query_bits+(position_bits if joint else 0)))


def capacity(tables_bytes, state_bits, query_bits, position_bits, *,
             program_epoch_bytes=0, epoch_copies=1, states=1,
             joint=True, path_bits=0, dep=Deployment()):
    if min(tables_bytes, state_bits, program_epoch_bytes) < 0 or states < 1:
        raise ValueError('Invalid work or state')
    io = input_traffic(query_bits, position_bits, joint)
    # Evaluator receives decoding bits; reverse carries revealed old path bits.
    forward = dep.framing*(tables_bytes+io['forward']+257/8)
    backward = dep.framing*(io['backward']+path_bits/8)
    nodes_role = max(1, ceil(dep.qps*max(forward, backward)/dep.nic_bytes_second))
    ec2 = 2*nodes_role*dep.hourly_usd*8760
    state_bytes = 2*dep.label_bytes*state_bits*states*epoch_copies
    programs = program_epoch_bytes*states*epoch_copies
    buffers = 0 if program_epoch_bytes else 2*dep.stream_buffer_bytes_per_party
    storage = state_bytes+programs
    ssd = storage/GIB*dep.gp3_gib_year
    # gp3 max64TiB/volume; c6in200Gbps uses two ENIs. Assume one root
    # attachment and25 data-volume slots, with all retained epochs attached.
    storage_g = ceil((state_bytes/2)/(65536*GIB*25))
    storage_e = ceil((state_bytes/2+programs)/(65536*GIB*25))
    extra_storage_nodes = max(0, storage_g-nodes_role)+max(0, storage_e-nodes_role)
    storage_host_cost = extra_storage_nodes*dep.hourly_usd*8760
    return dict(tables_bytes_per_query=tables_bytes,
                forward_wire_bytes_per_query=forward,
                backward_wire_bytes_per_query=backward,
                total_wire_bytes_per_query=forward+backward,
                joint_position_input_bytes_per_query=64*position_bits if joint else 0,
                network_nodes_per_party=nodes_role, network_nodes_total=2*nodes_role,
                network_ec2_usd_year=ec2, state_bytes_both_parties=state_bytes,
                program_bytes_all_copies=programs, storage_bytes_total=storage,
                minimum_stream_ram_bytes_both_parties=buffers,
                stream_ram_excludes_workers_and_live_circuit_workspace=True,
                ssd_capacity_usd_year=ssd,
                attached_storage_nodes_garbler=storage_g,
                attached_storage_nodes_evaluator=storage_e,
                extra_attached_storage_nodes=extra_storage_nodes,
                extra_attached_storage_ec2_usd_year=storage_host_cost,
                network_plus_capacity_usd_year=ec2+ssd+storage_host_cost,
                cross_az_additional_usd_year=(forward+backward)*dep.qps*YEAR_SECONDS/1e9*.02,
                independent_states=states, epoch_copies=epoch_copies,
                unpriced=['CPU/free-XOR/switch hashes', 'intra-party routing',
                          'initial hidden layout', 'epoch renewal/reset protocol',
                          'SSD IOPS/throughput except separately stated batch sensitivity',
                          'client integration, backups, failover and operations'])


def batch_io_price(c, dep=Deployment(), states=1, io_size=64*1024):
    """Uncached persistent state R+W, 64KiB aggregated operations scenario.

    Full pool, B fetch paths and2B eviction paths; overlaps counted repeatedly.
    Scratch intermediates stay in RAM. This is a few-large-volume scenario;
    more small volumes can exploit included throughput/IOPS at lower cost.
    Extra EC2 below is relative to network fleet, not additive
    when the same instances satisfy both limits. No latency/locality guarantee.
    """
    bytes_q = c['label_state_read_write_bytes_per_party_batch']/c['batch']
    provision_bps = bytes_q*dep.qps/(.65*.70)
    throughput = provision_bps/2**20
    iops = provision_bps/io_size
    size_gib = states*c['label_state_bytes_per_party']/GIB
    volumes = max(ceil(size_gib/65536), ceil(throughput/2000),
                  ceil(iops/80000), 1)
    # A volume must provision >=4 IOPS per MiB/s of throughput.
    iops = max(iops, 4*throughput)
    surcharge_role = .48*max(throughput-125*volumes, 0)+.06*max(iops-3000*volumes, 0)
    nodes_role = max(ceil(provision_bps/12.5e9), ceil(iops/400000), ceil(volumes/25))
    return dict(read_write_bytes_per_party_query=bytes_q,
                operation_bytes_assumption=io_size, volumes_per_party=volumes,
                ebs_nodes_per_party=nodes_role,
                extra_gp3_io_usd_year_both_parties=2*surcharge_role,
                excludes_scratch_spill=True, is_io_latency_guarantee=False)


def core_layout(n, horizon=None):
    return kv_lookup(n, horizon=horizon, fanout=8,
                     base_cells=256 if n == 28 else 512, family='communication')


def gram_case(n, horizon=None, states=1, dep=Deployment()):
    core = core_layout(n, horizon)
    merge = merge_cost(core)
    table_bytes = (dep.and_table_bytes*core['generated_ands']+merge['per_query']['garbled_bytes']
                   +merge['output_binding']['garbled_bytes_per_query'])
    priced = capacity(table_bytes, core['retained_bits'], core['query_input_bits'],
                      core['fresh_position_bits'],
                      program_epoch_bytes=(table_bytes+16*core['fresh_position_bits']+257/8)*core['horizon'],
                      epoch_copies=2, states=states, joint=False, dep=dep)
    cpu_scenarios = []
    for window in merge['window_sensitivities']:
        if window['caller_window'] not in (64, 256):
            continue
        # Explicit unmeasured budget, not a hardware benchmark. Reset/handoff,
        # XOR, memory stalls and any remaining selectors still need accounting.
        hash_rate = 4e9
        hg = window['garbler_hashes_per_query']+4*core['generated_ands']
        he = window['evaluator_hash_upper_per_query']+2*core['visited_ands']
        ng = max(priced['network_nodes_per_party'], priced['attached_storage_nodes_garbler'],
                 ceil(dep.qps*hg/hash_rate))
        ne = max(priced['network_nodes_per_party'], priced['attached_storage_nodes_evaluator'],
                 ceil(dep.qps*he/hash_rate))
        cpu_scenarios.append(dict(window=window['caller_window'],
                                  assumed_effective_hashes_per_node_second=hash_rate,
                                  garbler_nodes=ng, evaluator_nodes=ne,
                                  conditional_usd_year=(ng+ne)*dep.hourly_usd*8760+priced['ssd_capacity_usd_year'],
                                  evaluator_is_loose_work_allowance=True,
                                  is_aggregate_work_capacity_only=True,
                                  validates_individual_state_throughput=False,
                                  requires_unimplemented_reset_and_epoch_handoff=True,
                                  excludes_free_xor_and_other_local_costs=True))
    return dict(log_records=n, horizon=core['horizon'], fanout=8,
                throughput_status='Unconstrained capacity scenario; not demonstrated to sustain target QPS',
                max_state_service_seconds_at_70pct_util=.7*states/dep.qps,
                measured_state_service_seconds=None,
                flat_base_cells=core['flat_base_cells'],
                generated_nonmerge_ands=core['generated_ands'],
                visited_nonmerge_ands=core['visited_ands'],
                state_bits=core['retained_bits'],
                merge_per_query=merge['per_query'],
                output_binding=merge['output_binding'],
                merge_window_sensitivities=merge['window_sensitivities'],
                hash_capacity_sensitivities=cpu_scenarios,
                epoch_duration_seconds=states*core['horizon']/dep.qps, price=priced)


def main():
    dep = Deployment()
    rows = []
    for n in (28, 32):
        reference = gram_case(n, dep=dep)
        # Fixed F8 layout isolates horizon/copy effects. Each horizon still
        # requires a valid new epoch, not just reusing one-time garbled tables.
        sweeps = []
        for states in (1, 16, 128):
            candidates = [gram_case(n, 2**t, states, dep) for t in range(18, n+5)]
            chosen = min(candidates, key=lambda c:c['price']['network_plus_capacity_usd_year'])
            sweeps.append(dict(states=states, selected=chosen,
                               all_points=[dict(horizon=x['horizon'],
                                                **x['price']) for x in candidates]))
        core = core_layout(n)
        sequential = capacity(dep.and_table_bytes*core['visited_ands'],
                              core['retained_bits'], core['query_input_bits'],
                              core['fresh_position_bits'], path_bits=core['fresh_position_bits'], dep=dep)
        batches = []
        for b in (256, 1024, 4096):
            candidates = [batch_lookup(n, b, f, cutoff)
                          for f in (4, 8, 16, 32) for cutoff in (256, 1024, 4096)]
            c = min(candidates, key=lambda x:x['ands_per_query'])
            price = capacity(dep.and_table_bytes*c['ands_per_query'], c['state_bits'],
                             256+2*(n+1), c['fresh_position_bits_per_query'],
                             path_bits=c['public_path_bits_per_query'], dep=dep)
            ebs = batch_io_price(c, dep)
            additional_nodes = 2*max(0, ebs['ebs_nodes_per_party']-price['network_nodes_per_party'])
            cpu = []
            for sustained_ands in (50e6, 200e6, 1000e6):
                nodes_role = max(price['network_nodes_per_party'], ebs['ebs_nodes_per_party'],
                                 ceil(c['ands_per_query']*dep.qps/sustained_ands))
                total = (2*nodes_role*dep.hourly_usd*8760+price['ssd_capacity_usd_year']
                         +ebs['extra_gp3_io_usd_year_both_parties'])
                cpu.append(dict(assumed_sustained_ands_per_node_second=sustained_ands,
                                assumed_rate_already_includes_utilization_and_scaling_losses=True,
                                nodes_per_party=nodes_role, usd_year=total,
                                includes_all_gate_and_free_xor_runtime_in_assumed_rate=True))
            batches.append(dict(circuit=c, price=price, persistent_io=ebs,
                                throughput_status='One-state price conditional on measured batch service limit',
                                measured_batch_service_seconds=None,
                                network_capacity_and_io_usd_year=price['network_plus_capacity_usd_year']
                                    +ebs['extra_gp3_io_usd_year_both_parties']
                                    +additional_nodes*dep.hourly_usd*8760,
                                cpu_sensitivities=cpu,
                                mean_batch_fill_seconds=(b-1)/(2*dep.qps),
                                one_state_max_batch_service_seconds_at_70pct_util=.7*b/dep.qps))
        targets = []
        for multiplier in (1, 2, 4):
            p = capacity(dep.and_table_bytes*core['visited_ands']*multiplier,
                         batches[0]['circuit']['state_bits'], core['query_input_bits'],
                         core['fresh_position_bits'], path_bits=core['fresh_position_bits'], dep=dep)
            targets.append(dict(work_multiplier_of_sequential_core=multiplier, price=p,
                                status='Engineering target, NOT a costed batch construction'))
        rows.append(dict(log_records=n, gram_reference=reference,
                         gram_horizon_sweeps=sweeps, sequential_streaming_core=sequential,
                         batch_cases=batches, efficient_batch_targets=targets))
    result = dict(as_of='2026-10-16', security='two-party semi-honest,128-bit labels',
                  routing_revision=dict(
                      scope='Only old leaf positions requested in the current batch are public.',
                      public_path_sort_and_terminal_output_permutation='Local; zero additional AND gates.',
                      estimated_gate_savings_per_query=0,
                      explanation='The previous ledger did not separately charge these public operations. '
                                  'Private pool inverse-routing allowances remain until a replacement '
                                  'extraction/compaction circuit is counted.',
                      is_new_optimized_pool_implementation=False),
                  correction='GRAM replica counts are capacity sensitivities only. '
                             'Apply the serial evaluator constraint in two_party_serial.py '
                             'before interpreting these as throughput budgets.',
                  deployment=asdict(dep), key_bits=256, value_bits=256,
                  table_count=2, slots_per_table='2N', same_availability_zone=True,
                  prices_source='data/aws_garbled_prices_2026-10-13.json, refreshed unchanged2026-10-14',
                  rows=rows)
    target = ROOT/'results'/'two_party_comparison.json'
    target.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    for r in rows:
        n=r['log_records']; p=r['gram_reference']['price']
        print(f'N=2^{n}: UNCONSTRAINED GRAM reference {p["tables_bytes_per_query"]/1e6:.2f} MB/q, '
              f'network+capacity ${p["network_plus_capacity_usd_year"]/1e6:.2f}M/year')
        for s in r['gram_horizon_sweeps']:
            v=s['selected']; p=v['price']
            print(f'  GRAM states={s["states"]}, T=2^{v["horizon"].bit_length()-1}, '
                  f'capacity-only ${p["network_plus_capacity_usd_year"]/1e6:.2f}M/year; '
                  f'requires <= {v["max_state_service_seconds_at_70pct_util"]*1000:.3f}ms/state/query')
        for c in r['batch_cases']:
            b=c['circuit']; p=c['price']
            print(f'  batch={b["batch"]}, F={b["fanout"]}, A={b["ands_per_query"]/1e6:.3f}M/q, '
                  f'{p["tables_bytes_per_query"]/1e6:.1f}MB/q, '
                  f'network+capacity+IO ${c["network_capacity_and_io_usd_year"]/1e6:.2f}M/year')


if __name__ == '__main__':
    main()
