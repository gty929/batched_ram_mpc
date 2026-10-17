"""Explicit state-I/O scenarios for the hierarchical split ORAM ledger.

This module does not assume that the complete database fits in RAM.  The tiled
scenario keeps a single 1,024-slot MergeSplit or 512-slot local refinement in
RAM, and materializes the boundary between large butterfly stages.  It charges
all record traffic in the global compaction networks to external storage.

These are conditional movement ledgers, not a measured external-memory
implementation.  Planner labels, OT matrices, garbled-table staging, temporary
copies other than those stated, and read amplification are additional traffic.
The initial/final persistent boundary pass is deliberately charged separately:
an implementation can fuse some of it with the first/last compaction passes.
Consequently this small term can conservatively double count boundary traffic.
"""
from math import ceil


METADATA_BITS = 130
LABEL_BYTES = 16
PAYLOAD_BYTES = 32
SLOT_BYTES = METADATA_BITS * LABEL_BYTES + PAYLOAD_BYTES


def state_io(c, qps=10_000, ebs_bytes_second=12.5e9 * .65 * .70,
             nic_nodes_per_party=None):
    """Return per-party bytes/query and scenario assumptions for saved case c.

    ``c`` is one result of hierarchical_split_cost.scenario().  Reads charge a
    complete rewrite of every scanned slot, including stashes.  Only occupancy
    labels need logically change, so this intentionally exceeds an optimized
    column-oriented update.  All figures count reads plus writes.

    A secret metadata-bit swap reads two input labels and writes two output
    labels (64 B), while its 256-bit payload swap moves four shares (128 B).
    This is movement traffic; intermediate gate labels can require more memory.
    """
    if qps <= 0 or ebs_bytes_second <= 0:
        raise ValueError('Positive QPS and EBS bandwidth are required')
    d = c['local_refinement']['suffix_bits']
    parent = c['parent_z']
    local_stash = c['local_stash']
    a = c['rebuild_ands_components_per_query']
    metadata_move_ands = sum(
        value for name, value in a.items()
        if 'metadata' in name or name == 'retained_suffix_bits_in_butterfly')
    swaps = c['rebuild_payload_swaps_per_query']
    full_switch_movement = 4 * LABEL_BYTES * metadata_move_ands + 4 * PAYLOAD_BYTES * swaps

    parts = {
        'read_bucket_and_stash_full_read_write':
            2 * SLOT_BYTES * c['read_payload_selectors_per_query'],
        'persistent_initial_source_and_final_target_boundary': 0.,
        'source_compaction_all_swap_layers': 0.,
        'old_stash_reentry_all_swap_layers': 0.,
        'global_stash_collector_all_swap_layers': 0.,
        'butterfly_outer_stage_boundaries': 0.,
        'local_refinement_tile_input_and_outputs': 0.,
    }
    # These three components move only canonical metadata, with no routing tag.
    for output_name, component in (
        ('source_compaction_all_swap_layers', 'source_compact_metadata'),
        ('old_stash_reentry_all_swap_layers', 'source_stash_reentry_metadata'),
        ('global_stash_collector_all_swap_layers', 'global_stash_merge_metadata'),
    ):
        parts[output_name] = a.get(component, 0.) / METADATA_BITS * 4 * SLOT_BYTES

    max_mergesplit_tile = max_local_tile = 0
    for row in c['rows']:
        n = row['capacity']
        interval = row['accesses_per_rebuild']
        parents = row['parent_buckets']
        h = row['parent_routing_stages']
        source_slots = (4 if row['top'] else 2) * n
        source_stash_slots = row['source_stash_slots']
        target_stash_slots = row['global_stash']['capacity']
        parts['persistent_initial_source_and_final_target_boundary'] += (
            source_slots + source_stash_slots + 2 * n + target_stash_slots
        ) * SLOT_BYTES / interval

        # Each of h stages reads and writes all 2n records once.  All log2(2Z)
        # conditional-swap layers inside an individual MergeSplit stay local.
        tagged_slot_bytes = SLOT_BYTES + LABEL_BYTES * (h + d)
        parts['butterfly_outer_stage_boundaries'] += (
            4 * n * h * tagged_slot_bytes / interval)

        # High parent-address bits have been consumed.  Read a complete parent
        # with d low routing bits, then write its 512 final slots and 64 residual
        # slots.  Residual collection is separately counted above.
        parts['local_refinement_tile_input_and_outputs'] += parents * (
            parent * (SLOT_BYTES + LABEL_BYTES * d)
            + (parent + local_stash) * SLOT_BYTES
        ) / interval
        # Record buffers only; planner/GC/OT workspace must be added separately.
        max_mergesplit_tile = max(max_mergesplit_tile,
                                 2 * (2 * parent) * tagged_slot_bytes)
        max_local_tile = max(max_local_tile,
                             2 * parent * (SLOT_BYTES + LABEL_BYTES * d)
                             + local_stash * SLOT_BYTES)

    boundary = parts['persistent_initial_source_and_final_target_boundary']
    bucket_rw = parts['read_bucket_and_stash_full_read_write']
    scenarios = {
        'resident_rebuild_scratch': bucket_rw + boundary,
        'tiled_small_kernels_global_layers_spilled': sum(parts.values()),
        'every_record_switch_layer_spilled': bucket_rw + boundary + full_switch_movement,
    }
    result = {
        'slot_bytes_per_party': SLOT_BYTES,
        'per_party_read_plus_write_bytes_per_query': scenarios,
        'tiled_components_bytes_per_query': parts,
        'record_switch_movement_bytes_per_query': full_switch_movement,
        'ebs_effective_bytes_per_second_per_node': ebs_bytes_second,
        'ebs_nodes_per_party': {
            name: max(1, ceil(qps * value / ebs_bytes_second))
            for name, value in scenarios.items()
        },
        'maximum_mergesplit_two_record_buffers_bytes': max_mergesplit_tile,
        'maximum_local_refinement_record_buffers_bytes': max_local_tile,
        'notes': [
            'Each scenario excludes garbled-circuit staging and planner/OT scratch I/O.',
            'The resident-scratch row requires an additional working-memory feasibility check.',
            'Tiled kernels need only MiB-sized record buffers, but a complete global planner schedule is unimplemented.',
            'Global compaction record layers are charged fully even where RAM caching could eliminate passes.',
            'The separate persistent boundary charge can overlap the first/last global-compaction passes.',
            'Full bucket rewrites are conservative; metadata columns may reduce update writes.',
            'Physical I/O amplification and per-volume IOPS are outside these byte counts.',
        ],
    }
    if nic_nodes_per_party is not None:
        if nic_nodes_per_party < 1:
            raise ValueError('At least one NIC node is required')
        q_capacity = nic_nodes_per_party * ebs_bytes_second / qps
        result['additional_bytes_per_query_before_exceeding_nic_sized_ebs_fleet'] = {
            name: q_capacity - value for name, value in scenarios.items()
        }
    return result
