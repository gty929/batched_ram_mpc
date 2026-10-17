"""Amortized binary hierarchical 2PC ORAM traffic, 16 October 2026.

Analytical kernel ledger, not an implementation or measured protocol.
Run: python -m mpc_cost.hierarchical_cost

Construction: direct binary-counter rebuilds, mutable deletion, one initial
batch deduplication, 128-bit PRF fingerprints, half-full bucket tables, no
position maps, no deamortization. A global ORCompact before each rebuild
balances the source slots; a binary butterfly uses ORCompact MergeSplits.
This extra global compaction is deliberately charged, including at the top.

The packed payload movement interface is parameterized, not inferred from
storage size. Its cost must include hidden selection and any per-move
conversion/relabeling. The 8192-byte row is a separate Boolean-payload
reference (256 ANDs), not a claim about a two-carrier backend.

References: local microrama.pdf sec2; 2022-1333.pdf sec3,5.1,AppB;
interactive_shuffle_primitives.tex for AES/half-gate/input conventions.
"""
from __future__ import annotations

import json
from math import log2
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AND_BYTES = 32
META_BITS = 130  # fingerprint128, occupied, present (keyed absent tombstone)
AES_ANDS = 5120
PAYLOAD_BITS = 256


def ilog2(n: int) -> int:
    if n < 2 or n & (n - 1):
        raise ValueError('Expected a power of two >=2')
    return n.bit_length() - 1


def compact(n: int) -> dict:
    """Exact swaps; our constructive Boolean schedule-planner upper count.

    Popcounts: 2n-2k-2; offsets: n-k-1; shared threshold decoding:
    n(k-4)+2k+4; leaf controls: n/2. Sum = n(k-1/2)-k+1.
    These are not gate counts stated by the paper.
    """
    k = ilog2(n)
    return dict(swaps=n*k//2, planner_ands=n*k-n//2-k+1)


def mergesplit(z: int) -> dict:
    """Exact-Z marks plus ORCompact, assuming neither real side overflows.

    Mark construction: real-left flags/popcount, dummy quota, parallel
    EXCLUSIVE dummy prefix ranks, comparisons and gating. Exclusive ranks
    fit in k bits even for an all-dummy input (inclusive ranks can reach n).
    Retains all routing bits.
    """
    n = 2*z
    k = ilog2(n)
    c = compact(n)
    marks = 3*k*n+4*n-2*k-2
    return dict(swaps=c['swaps'], marking_ands=marks,
                planner_ands=c['planner_ands']+marks)


def build(n: int, z: int, *, top: bool) -> dict:
    """Rebuild logical capacity n into 2n physical slots.

    Lower source: 2n slots; at most n live keyed entries including tombstones.
    Top source: 4n slots; clear tombstones, then at most n live database keys.
    Compact, retain first n slots, spread publicly into half-full buckets.
    Generate one new secret routing PRF tag per retained slot (even dummies).
    """
    if 2*n < 2*z:
        raise ValueError('Base must have at least two hash buckets')
    h = ilog2(2*n//z)
    source_slots = (4 if top else 2)*n
    c = compact(source_slots)
    ms = mergesplit(z)
    ms_calls = (n//z)*h
    butterfly_swaps = ms_calls*ms['swaps']
    parts = dict(
        source_compact_planner=c['planner_ands'],
        source_compact_metadata=c['swaps']*META_BITS,
        discard_top_tombstones=source_slots if top else 0,
        routing_prf=n*AES_ANDS,
        mergesplit_planner=ms_calls*ms['planner_ands'],
        butterfly_metadata=butterfly_swaps*(META_BITS+h),
        # Two independent expanded secret keys: real and dummy addressing.
        fresh_epoch_key_schedules=2*1280,
    )
    return dict(capacity=n, bucket_z=z, buckets=2*n//z, stages=h,
                source_slots=source_slots, top=top,
                and_components=parts, ands=sum(parts.values()),
                payload_switches=c['swaps']+butterfly_swaps,
                fresh_key_input_bytes=2*64*128,
                source_compact_swaps=c['swaps'],
                mergesplit_calls=ms_calls,
                butterfly_swaps=butterfly_swaps)


def case(log_n: int, batch: int, z: int, packed_swap_bytes: float) -> dict:
    n = 1 << log_n
    ell = log_n-ilog2(batch)
    if batch < z:
        raise ValueError('Use a genuine base hash table, at least two buckets')
    rows = []
    components: dict[str, float] = {}
    rebuild_switches = rebuild_key_inputs = bucket_tests = 0.
    for i in range(ell+1):
        capacity = batch << i
        top = i == ell
        ledger = build(capacity, z, top=top)
        interval = n if top else 2*capacity
        for key, value in ledger['and_components'].items():
            components[key] = components.get(key, 0.)+value/interval
        rebuild_switches += ledger['payload_switches']/interval
        rebuild_key_inputs += ledger['fresh_key_input_bytes']/interval
        bucket_tests += ledger['buckets']*ledger['stages']/interval
        rows.append(dict(**ledger, accesses_per_rebuild=interval))
    rebuild_ands = sum(components.values())
    rebuild_bytes = (AND_BYTES*rebuild_ands + rebuild_key_inputs
                     + packed_swap_bytes*rebuild_switches)

    # Each lower table is present half the counter cycle; top is permanent.
    # Include true/dummy PRFs, address mux, equality, found/present reductions,
    # clear flags, and one conservative payload selection per scanned slot.
    # Equal public bucket IDs may share a circuit; qZ comparisons stay charged.
    read_ands = read_selects = address_bytes = 0.
    worst_read_bytes = 0.
    for row in rows:
        weight = 1. if row['top'] else .5
        h = row['stages']
        ands = 2*AES_ANDS+134*z+h+4
        read_ands += weight*ands
        read_selects += weight*z
        address_bytes += weight*2*h/8
        worst_read_bytes += AND_BYTES*ands+z*packed_swap_bytes+2*h/8
    read_bytes = AND_BYTES*read_ands+read_selects*packed_swap_bytes+address_bytes

    b = ilog2(batch)
    comparisons_per_query = b*(b+1)/4
    # Sort 128-bit fingerprints; save private comparison bits. Return present
    # plus packed value by reverse network, after adjacent-run propagation.
    # The charged adjacent propagation is a linear chain; a shallow parallel
    # prefix implementation can require a larger constant. No latency claim.
    # Comparison allowance3k-2, key cswap128, reverse present cswap1.
    dedup_ands = comparisons_per_query*(3*128-2+128+1)+130*(batch-1)/batch
    dedup_switches = comparisons_per_query+(batch-1)/batch
    dedup_bytes = AND_BYTES*dedup_ands+dedup_switches*packed_swap_bytes
    frontend_bytes = AND_BYTES*2*AES_ANDS+64*256
    total_bytes = rebuild_bytes+read_bytes+dedup_bytes+frontend_bytes

    # Per bucket-stage ideal-PRF Chernoff bound (e/4)^(Z/2), plus union.
    # ln2 = 1/log2(e), exponent -Z*(1-1/(2ln2)).
    tail_log2 = -z*(1-log2(2.718281828459045)/2)
    q = 1 << 32
    failure_log2 = tail_log2+log2(q*bucket_tests)
    return dict(
        log_records=log_n, batch=batch, bucket_z=z, lower_levels=ell,
        base_hash_buckets=2*batch//z,
        expected_occupied_tables=ell/2+1, max_occupied_tables=ell+1,
        packed_payload_swap_bytes=packed_swap_bytes,
        planner_per_mergesplit=mergesplit(z),
        rebuild_ands_per_query=rebuild_ands,
        rebuild_ands_components_per_query=components,
        rebuild_payload_switches_per_query=rebuild_switches,
        rebuild_unframed_bytes_per_query=rebuild_bytes,
        read_ands_per_query=read_ands,
        read_payload_selects_per_query=read_selects,
        read_unframed_bytes_per_query=read_bytes,
        worst_read_unframed_bytes_per_query=worst_read_bytes,
        dedup_and_propagate_unframed_bytes_per_query=dedup_bytes,
        frontend_unframed_bytes_per_query=frontend_bytes,
        total_unframed_bytes_per_query=total_bytes,
        total_framed_bytes_per_query=1.05*total_bytes,
        bucket_stage_tests_per_query=bucket_tests,
        ideal_prf_overflow_log2_bound_over_2p32_accesses=failure_log2,
        max_persistent_slots=4*n-2*batch,
        packed_label_state_bytes_per_party=(4*n-2*batch)*(16*META_BITS+32),
        rows=rows,
    )


def main() -> None:
    primary = [case(log_n, 1024, 512, 160) for log_n in (28, 32)]
    small = [case(log_n, 256, 64, 160) for log_n in (28, 32)]
    boolean = [case(log_n, 1024, 512, AND_BYTES*PAYLOAD_BITS)
               for log_n in (28, 32)]
    result = dict(
        assumptions=dict(
            model='Analytical communication kernel ledger; not measured',
            security='Semi-honest, 128-bit labels, 32-byte half-gate AND',
            branching_factor=2, nominal_load=.5,
            packed_bytes_160='Illustrative all-in hidden swap of both carriers; conditional, not proved by two-label storage',
            boolean_payload_reference='8192B secret swap; no packed movement discount',
            read_cost='Amortized over public binary-counter occupancy; worst read shown separately',
            no_residuals_512='Ideal-PRF bucket-tail union bound; fingerprint collisions and PRF security separate',
            small_64='Main-network sensitivity only; invalid without extra overflow collection/recovery',
            excluded=['initial full database construction',
                      'CPU, XORs, network distribution and latency',
                      'concrete packed representation boundary conversion beyond switch parameter',
                      'replica count/consistency and persistent-state storage pricing'],
        ),
        primary_no_residual_bucket_512=primary,
        bucket_64_excluding_required_residual_handling=small,
        boolean_payload_reference=boolean,
    )
    path = ROOT/'results'/'hierarchical_comparison.json'
    path.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    for label, collection in [('Z512 packed conditional', primary),
                              ('Z64 omit residuals', small),
                              ('Z512 Boolean payload', boolean)]:
        for c in collection:
            print(label, 'N=2^'+str(c['log_records']),
                  'rebuildMB=', round(c['rebuild_unframed_bytes_per_query']/1e6, 4),
                  'readMB=', round(c['read_unframed_bytes_per_query']/1e6, 4),
                  'totalMB=', round(c['total_unframed_bytes_per_query']/1e6, 4),
                  'switches=', c['rebuild_payload_switches_per_query'],
                  'overflowLog2=', round(c['ideal_prf_overflow_log2_bound_over_2p32_accesses'], 2))


if __name__ == '__main__':
    main()
