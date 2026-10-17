"""AWS transfer/loading capacity for the binary hierarchical ORAM ledger.

CPU costs are omitted at the user's instruction. This is a resource and
scheduling model, not an AWS benchmark. Run as a module from the repo root.
"""
from dataclasses import asdict, dataclass
from math import ceil, log2
from pathlib import Path
import json

from .hierarchical_io import state_io
from .hierarchical_address import (read_ands, inputs, epoch_inputs,
                                   current_case, scheme, auxiliary, SCHEME)

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Deployment:
    qps: int = 10_000
    framing: float = 1.05
    nic_raw: float = 25e9
    nic_efficiency: float = .65
    distributed_efficiency: float = .70
    utilization: float = .70
    ebs_raw: float = 12.5e9
    ebs_efficiency: float = .65
    memory_bytes: int = 256*2**30
    usable_memory: float = .75
    scratch_reserve: float = .15

    @property
    def nic_active(self):
        return self.nic_raw*self.nic_efficiency*self.distributed_efficiency

    @property
    def nic_budget(self):
        return self.nic_active*self.utilization

    @property
    def ebs_budget(self):
        return self.ebs_raw*self.ebs_efficiency*self.utilization


def directions(c):
    """Reconcile both directions exactly to the previously reported bytes."""
    b = c['batch']
    k = int(log2(b))
    comparisons = k*(k+1)/4
    front_ands = 10240+comparisons*511+140*(b-1)/b
    front_back = 4096+80*(comparisons+3*(b-1)/b)
    front_total = c['frontend_and_dedup_unframed_bytes_per_query']
    rows = []
    read_f = read_r = rebuild_f = rebuild_r = 0.
    suffix = int(log2(512/c['child_z']))
    for r in c['rows']:
        bits = r['parent_routing_stages']+suffix
        a = read_ands(c,r)
        fi,ri = inputs(r)
        forward = 32*a+80*r['read_slots']+bits/8+fi
        backward = 80*r['read_slots']+bits/8+ri
        rb = 80*r['rebuild_payload_swaps']+epoch_inputs(r)/4
        rf = r['rebuild_unframed_bytes']-rb
        weight = 1 if r['top'] else .5
        read_f += weight*forward
        read_r += weight*backward
        rebuild_f += rf/r['accesses_per_rebuild']
        rebuild_r += rb/r['accesses_per_rebuild']
        rows.append(dict(log_capacity=r['log_capacity'], capacity=r['capacity'],
                         top=r['top'],read_forward=forward,read_backward=backward,
                         rebuild_forward=rf,rebuild_backward=rb,
                         accesses_per_rebuild=r['accesses_per_rebuild'],
                         swap_layers=r['payload_swap_layers']))
    return dict(frontend_forward=front_total-front_back,frontend_backward=front_back,
                read_forward=read_f,read_backward=read_r,
                rebuild_forward=rebuild_f,rebuild_backward=rebuild_r,
                forward=front_total-front_back+read_f+rebuild_f,
                backward=front_back+read_r+rebuild_r,
                gc=32*(front_ands+c['read_ands_per_query']+c['rebuild_ands_per_query']),
                rows=rows)


def analyze(c, dep=Deployment()):
    d = directions(c)
    wire = dep.framing*d['forward']
    nodes = ceil(dep.qps*wire/dep.nic_budget)
    io = state_io(c,qps=dep.qps,ebs_bytes_second=dep.ebs_budget,
                  nic_nodes_per_party=nodes)
    # Reconstruct the documented I/O component sums independently of their
    # public JSON field names, to make the arithmetic explicit here.
    record = 2112
    selectors = c['read_payload_selectors_per_query']
    read_state = 2*record*selectors
    boundary = sum(record*((4 if r['top'] else 2)*r['capacity']
                           +2*r['capacity']+r['source_stash_slots']
                           +r['global_stash']['capacity'])/r['accesses_per_rebuild']
                   for r in c['rows'])
    moves = c['rebuild_ands_components_per_query']
    movement_bits = sum(v for key,v in moves.items()
                        if 'metadata' in key or key=='retained_suffix_bits_in_butterfly')
    switch_movement = 64*movement_bits+128*c['rebuild_payload_swaps_per_query']
    tiled = read_state+boundary
    tiled_rebuild = 0.
    for r in c['rows']:
        n=r['capacity']; interval=r['accesses_per_rebuild']
        h=r['parent_routing_stages']; suffix=int(log2(512/c['child_z']))
        a=r['components']
        global_moves = 64*(a['source_compact_metadata']
                          +a.get('source_stash_reentry_metadata',0)
                          +a['global_stash_merge_metadata'])
        # The three global networks move 130 metadata bits and a 32-B share.
        global_swaps = (a['source_compact_metadata']
                        +a.get('source_stash_reentry_metadata',0)
                        +a['global_stash_merge_metadata'])/130
        global_moves += 128*global_swaps
        butterfly = 4*n*h*(16*(130+h+suffix)+32)
        # Read parent input, write all leaves and a fixed 64-slot local stash.
        local = r['parent_buckets']*(512*(16*(130+suffix)+32)+(512+64)*record)
        tiled_rebuild += (global_moves+butterfly+local)/interval
    tiled += tiled_rebuild
    state_ram = c['packed_state_bytes_per_party']
    top = d['rows'][-1]
    top_stash = c['rows'][-1]['global_stash']['capacity']
    stash_wire = dep.framing*top_stash*(134*32+80)
    private_inputs=sum((1 if r['top'] else .5)*sum(inputs(r)) for r in c['rows'])
    memory_scenario = 2*d['gc']+switch_movement+read_state+boundary+2*private_inputs
    io_scenarios = {}
    for name,amount in [
        ('resident_scratch',read_state+boundary),
        ('tiled',tiled),
        ('every_switch_spilled',read_state+boundary+switch_movement),
        ('tiled_plus_one_gc_disk_read',tiled+d['gc']),
        ('tiled_plus_gc_disk_write_read',tiled+2*d['gc']),
    ]:
        io_scenarios[name] = dict(bytes_per_query=amount,
            nodes_for_affected_role=ceil(dep.qps*amount/dep.ebs_budget),
            qps_at_network_fleet=nodes*dep.ebs_budget/amount)
    # Sensitivity: a balanced owner-computes implementation transmits half
    # the record R+W byte volume if every inter-kernel movement is remote.
    # This is not a routing theorem; expose it rather than hide it in .70.
    intra=[]
    for remote_fraction in (0,.5,1):
        per_direction=tiled_rebuild/2*remote_fraction
        total_wire=wire+dep.framing*per_direction
        intra.append(dict(remote_fraction=remote_fraction,
                          extra_bytes_per_query_per_party_direction=per_direction,
                          nodes_per_party=ceil(dep.qps*total_wire/dep.nic_budget)))
    return dict(log_records=c['log_records'],child_z=c['child_z'],batch=c['batch'],address_scheme=scheme(c),
        directions=d,forward_wire_bytes_per_query=wire,
        backward_wire_bytes_per_query=dep.framing*d['backward'],
        network_nodes_per_party=nodes,network_nodes_total=2*nodes,
        network_qps_per_worker_pair=dep.nic_budget/wire,
        network_qps_at_selected_fleet=nodes*dep.nic_budget/wire,
        state_io=io,io_scenarios=io_scenarios,
        persistent_state_bytes_per_party=state_ram,
        ram_hosts_75pct_no_scratch=ceil(state_ram/(dep.memory_bytes*dep.usable_memory)),
        ram_hosts_with_15pct_scratch=ceil(state_ram*(1+dep.scratch_reserve)
                                       /(dep.memory_bytes*dep.usable_memory)),
        record_movement_dram_scenario_bytes_per_query=memory_scenario,
        effective_dram_bps_needed_per_network_host=dep.qps*memory_scenario/nodes,
        tiled_ebs_extra_headroom_bytes_per_query=nodes*dep.ebs_budget/dep.qps-tiled,
        top_stash_forward_wire_bytes_per_query=stash_wire,
        top_stash_budgeted_qps_one_worker=dep.nic_budget/stash_wire,
        top_stash_network_workers=ceil(dep.qps*stash_wire/dep.nic_budget),
        mean_read_frontend_active_seconds=(d['read_forward']+d['frontend_forward'])
            *dep.framing*c['batch']/(nodes*dep.nic_active),
        mean_all_work_active_seconds_per_batch=wire*c['batch']/(nodes*dep.nic_active),
        mean_batch_fill_seconds=(c['batch']-1)/(2*dep.qps),
        top_rebuild_active_seconds=dep.framing*top['rebuild_forward']/(nodes*dep.nic_active),
        top_rebuild_reserved_rate_seconds=dep.framing*top['rebuild_forward']/(nodes*dep.nic_budget),
        top_recurrence_seconds_single_state=(1<<c['log_records'])/dep.qps,
        top_rebuild_swap_layers=top['swap_layers'],intraparty_network_sensitivity=intra,
        capacity_is_not_a_latency_schedule=True)


def main():
    from .hierarchical_cache import cache_plan, adaptive_plan
    raw=json.loads((ROOT/'results/hierarchical_split_comparison.json').read_text())
    raw['primary']=[current_case(c) for c in raw['primary']]
    dep=Deployment()
    rows=[analyze(c,dep) for c in raw['primary']]
    for row,c in zip(rows,raw['primary']):
        row['caches']=[cache_plan(c,cutoff_log=k,lookahead=4) for k in (16,20)]
        row['adaptive_cache']=adaptive_plan(c,cutoff_log=16)
        for cache in row['caches']+[row['adaptive_cache']]:
            state_saving=sum(2*2112*(c['child_z']+r['global_stash_slots'])
                             *r['average_occupied_weight'] for r in cache['rows'])
            cache['state_io_saving_bytes_per_query']=state_saving
            cached_io=row['io_scenarios']['tiled']['bytes_per_query']-state_saving
            cache['tiled_io_after_state_cache_bytes_per_query']=cached_io
            cache['tiled_io_hosts_after_state_cache']=ceil(dep.qps*cached_io/dep.ebs_budget)
            cache['demand_bucket_gc_bytes_avoided_per_query']=sum(
                r['cached_bucket_gc_work_bytes_per_query']*r['expected_hit_fraction']
                for r in cache['rows'])
            source_rows={r['log_capacity']:r for r in c['rows']}
            stash_prf=sum(r['average_occupied_weight']*auxiliary(source_rows[r['log_capacity']])['gc']
                          for r in cache['rows'])
            cache['optional_stash_and_prf_demand_gc_avoided_bytes_per_query']=stash_prf
            cache['network_nodes_by_refill_policy']={}
            for policy,key in [('full_window','full_window_retirement_waste_bytes_per_query'),
                               ('skip_final_refill','skip_final_refill_waste_bytes_per_query')]:
                cache['network_nodes_by_refill_policy'][policy]=ceil(dep.qps*dep.framing
                    *(row['directions']['forward']+cache[key])/dep.nic_budget)
            factor=127/134
            bridge=4096*cache['expected_cached_table_visits_per_query']
            extra=factor*cache['skip_final_refill_waste_bytes_per_query']+bridge
            cache['immutable_equality_variant']=dict(
                ands_per_slot=127,query_label_bridge_bytes_per_visit=4096,
                bridge_bytes_per_query=bridge,
                gc_queue_ram_bytes_evaluator=factor*cache['gc_queue_ram_bytes_evaluator'],
                demand_gc_avoided_bytes_per_query=factor*cache['demand_bucket_gc_bytes_avoided_per_query'],
                extra_forward_bytes_per_query_skip_final_refill=extra,
                network_nodes_per_party=ceil(dep.qps*dep.framing
                    *(row['directions']['forward']+extra)/dep.nic_budget),
                all_remote_boundary_sensitivity_nodes_per_party=ceil(dep.qps*dep.framing
                    *(row['directions']['forward']+extra
                      +row['intraparty_network_sensitivity'][-1]
                       ['extra_bytes_per_query_per_party_direction'])/dep.nic_budget),
                conditions=['Fingerprint labels retained after deletion until epoch retirement',
                    'One-use query lane and globally unique gate tweaks',
                    'Compatible FreeXOR offset across equality and finalizer',
                    'Equality outputs remain encoded; atomic lane allocation',
                    'Batch-start occupancy snapshot; aggregate deletion once per slot',
                    'Finalizer allowance inherited from scan ledger, not yet compiled'])
        # Alternative requested by the user: queue four fresh versions for
        # every cold bucket, on EBS; keep adaptive hot queues in RAM. Count
        # incoming cold material written once and used versions read once.
        all_cache=cache_plan(c,cutoff_log=c['log_records'],lookahead=4)
        hot_uniform=row['caches'][0]
        hot=row['adaptive_cache']
        factor=127/134
        cold_gc=factor*(all_cache['cached_bucket_gc_work_bytes_per_query']
                        -hot_uniform['cached_bucket_gc_work_bytes_per_query'])
        cold_waste=factor*(all_cache['skip_final_refill_waste_bytes_per_query']
                           -hot_uniform['skip_final_refill_waste_bytes_per_query'])
        cold_bridge=4096*(all_cache['expected_cached_table_visits_per_query']
                          -hot_uniform['expected_cached_table_visits_per_query'])
        extra=hot['immutable_equality_variant']['extra_forward_bytes_per_query_skip_final_refill']
        extra+=cold_waste+cold_bridge
        cold_io=2*cold_gc+cold_waste
        evaluator_io=hot['tiled_io_after_state_cache_bytes_per_query']+cold_io
        row['tiered_all_bucket_prefetch']=dict(
            hot_cutoff_log=16,cold_lookahead=4,
            evaluator_cold_gc_storage_bytes=factor*(all_cache['gc_queue_ram_bytes_evaluator']
                                                    -hot_uniform['gc_queue_ram_bytes_evaluator']),
            useful_cold_gc_bytes_per_query=cold_gc,cold_retirement_waste_bytes_per_query=cold_waste,
            cold_bridge_bytes_per_query=cold_bridge,
            extra_forward_bytes_per_query=extra,
            forward_wire_bytes_per_query=dep.framing*(row['directions']['forward']+extra),
            network_nodes_per_party=ceil(dep.qps*dep.framing*(row['directions']['forward']+extra)
                                         /dep.nic_budget),
            evaluator_ebs_bytes_per_query=evaluator_io,
            evaluator_ebs_nodes=ceil(dep.qps*evaluator_io/dep.ebs_budget),
            garbler_ebs_nodes=hot['tiled_io_hosts_after_state_cache'],
            all_remote_boundary_sensitivity_nodes_per_party=ceil(dep.qps*dep.framing
                *(row['directions']['forward']+extra+row['intraparty_network_sensitivity'][-1]
                 ['extra_bytes_per_query_per_party_direction'])/dep.nic_budget),
            caveats=['Peak simultaneous all-level queue reservation; one ORAM state',
                     'Only bucket equality GCs are spooled; rebuild GCs stream to RAM',
                     'Cold cache warmup must finish after table-label epoch is defined',
                     'Cache refill concurrency and cold EBS read latency remain to be scheduled'])
    result=dict(date='2026-10-17',address_scheme=SCHEME,deployment=asdict(dep),
                nic_active_bytes_second=dep.nic_active,nic_budget_bytes_second=dep.nic_budget,
                ebs_budget_bytes_second=dep.ebs_budget,primary=rows,
                assumptions=['Negligible CPU, fresh streamed garbling, same AZ',
                    'Network budget includes .70 utilization; active durations exclude that factor',
                    'RAM caches contain fresh one-time circuit versions, not reusable garbling',
                    'No measured DRAM rate or globally scheduled latency guarantee',
                    'Tiled record I/O excludes planner/OT scratch, with explicit headroom',
                    'Initial database construction, cache warmup, and replica consistency excluded'])
    path=ROOT/'results/hierarchical_throughput.json'
    path.write_text(json.dumps(result,indent=2)+'\n')
    for r in rows:
        print(f"N2^{r['log_records']} z{r['child_z']}: NIC {r['network_nodes_per_party']}/party, "
              f"tiled EBS {r['io_scenarios']['tiled']['nodes_for_affected_role']}/party, "
              f"top rebuild {r['top_rebuild_active_seconds']/60:.2f} minutes")


if __name__=='__main__':
    main()
