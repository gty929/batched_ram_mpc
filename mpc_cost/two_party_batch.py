"""Boolean accounting for streamed two-party Circuit-OPRAM-style batches.

This is an explicit PLANNING TEMPLATE, not a compiled circuit, implementation,
security proof, or measured performance prediction.  It does not reuse the
arithmetic-reduction counters in model.py.  Its compare, mux, and bitonic kernels
have specified Boolean implementations.  Pool scan composition, packed-update
composition, and parallel eviction planner constants remain exposed allowances
which require a complete circuit and invariant audit.

Structure: Chan--Shi, Circuit OPRAM, https://eprint.iacr.org/2016/1084 .
Parallel eviction motivation: https://eprint.iacr.org/2017/861 .
Half gates: https://www.cs.virginia.edu/~evans/pubs/ec2015/ .
At 128-bit labels, half-gate tables require 32 bytes per counted AND.

The model is for fixed-batch reads from the repository's two-table dictionary:
two arrays of 2N cells, 513-bit payload (256 key+256 value+occupied), plus
an eight-entry resident stash.  Updates are internal position-map/ORAM updates.
It includes secret duplicate handling at every recursive level, pool retrieval,
candidate selection, pool cleanup, fixed 2B-subtree eviction, recursive packed
updates, and the *full* scalar flat map of the last instantiated tree.

Only the duplicate-masked old paths requested in a batch are opened. Sorting
these public paths and applying their public permutation to encoded requests
need no garbled gates. Authorized terminal outputs can also be reordered
locally. These operations were never separately charged here. The routing
audit identifies inverse-routing allowances after PRIVATE sorts that remain
in the existing template; it is a subset of the gate total, not an extra cost
or a lower bound on an optimized construction.

State bits are logical bits.  Linked-garbling storage is one active label/bit
at E and one zero-label/bit at G, i.e. 16*state_bits bytes at EACH party; a common
free-XOR delta is held by G. Fresh output labels replace touched state labels.
This is persistent ORAM state, not retained garbled tables. Compact XOR-share
storage is a different backend and must charge re-input/OT on touched state.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import json


def clog2(n: int) -> int:
    return (max(1, n) - 1).bit_length()


def pow2(n: int) -> int:
    return 1 << clog2(n)


@dataclass
class BooleanWork:
    ands: int = 0
    depth: int = 0

    def then(self, other: "BooleanWork") -> None:
        self.ands += other.ands
        self.depth += other.depth

    def parallel(self, other: "BooleanWork") -> None:
        self.ands += other.ands
        self.depth = max(self.depth, other.depth)


def bitonic_route(items: int, key_bits: int, payload_bits: int,
                  reverse_bits: int = 0) -> BooleanWork:
    """Concrete bitonic network plus inverse routing with saved swap controls.

    K=2^ceil(log2(items)), C=K*l*(l+1)/4, S=l*(l+1)/2.
    A parallel-prefix unsigned compare uses <=3k-2 AND, depth1+ceil(log2 k).
    A conditional swap uses one AND/bit; XOR operations are free in bandwidth.
    Payload excludes the sort key. Saved controls cost live workspace, not AND.
    """
    level = clog2(items)
    comparators = (1 << level) * level * (level + 1) // 4
    stages = level * (level + 1) // 2
    return BooleanWork(comparators * (4*key_bits - 2 + payload_bits + reverse_bits),
                       stages * (2 + clog2(key_bits) + int(reverse_bits > 0)))


def private_inverse_ands(items: int, reverse_bits: int) -> int:
    """Identify inverse swaps already counted by bitonic_route; add no work."""
    level = clog2(items)
    comparators = (1 << level) * level * (level + 1) // 4
    return comparators * reverse_bits


def grouped_scans(items: int, group_bits: int, width: int) -> BooleanWork:
    """Conservative two full-width segmented prefix sweeps plus final masking.

    Adjacent group equality: (items-1)*(group_bits-1) AND.
    Each work-efficient prefix sweep has <2(items-1) combines.  A segmented
    copy combine is a width-bit mux plus flag logic, budgeted width+2 AND.
    Two sweeps support forwarding results and propagating clear/update flags.
    Final selection/clearing allowance: items*(width+4). The exact use of this
    generic composition for each pool phase is still a template assumption.
    """
    a = max(0, items-1) * max(0, group_bits-1)
    a += 4*max(0, items-1)*(width+2) + items*(width+4)
    return BooleanWork(a, clog2(group_bits) + 4*clog2(items) + 2)


def pool_phase(items: int, key_bits: int, group_bits: int,
               record_bits: int, reverse_bits: int) -> BooleanWork:
    w = bitonic_route(items, key_bits, record_bits+3, reverse_bits)
    w.then(grouped_scans(items, group_bits, record_bits))
    return w


def flat_map(cells: int, requests: int, label_bits: int) -> BooleanWork:
    """Secret dedup then parallel one-hot reads and aggregated unique writes.

    Shared-prefix decoder: cells-2 AND for power-of-two cells; cells extra AND
    gate the secret representative flag. Read and delta write each cost
    cells*label_bits AND/request. Distinct representative addresses make the
    write deltas disjoint, so per-cell accumulation is XOR. Duplicate input
    labels are restored privately through saved sort controls and group scans.
    """
    w = bitonic_route(requests, clog2(cells)+clog2(requests)+1,
                      label_bits+2, label_bits)
    w.then(grouped_scans(requests, clog2(cells), label_bits))
    w.then(BooleanWork(requests*(max(0, cells-2)+cells+2*cells*label_bits),
                       clog2(cells)+3))
    return w


def packed_updates(requests: int, fanout: int, child_label_bits: int,
                   parent_address_bits: int) -> BooleanWork:
    """Allowance for coalescing multiple offsets of the same map block.

    A parent block is fetched once, then returned to its child requests. This
    charges decoding offsets, old-label extraction, masked new-label vectors,
    two segmented prefix sweeps over vectors (labels+presence masks), and full
    block application. Parent request sorting/fanout is already in level_cost.
    Six full vector-width passes are budgeted. The scan schedule/coefficient
    must be validated in an implementation; distinct offsets must never be
    committed as independent whole-block writes.
    """
    width = fanout*child_label_bits
    a = requests*(max(0, fanout-2)+fanout+6*width)
    a += 4*max(0, requests-1)*(width+fanout+2)
    a += max(0, requests-1)*max(0, parent_address_bits-1)
    return BooleanWork(a, clog2(fanout)+4*clog2(requests)+6)


def level_cost(address_bits: int, payload_bits: int, requests: int,
               bucket_z: int = 3, pool_slack: int = 128,
               planner_factor: int = 8, movement_factor_extra: int = 4) -> dict:
    """Binary OPRAM tree: top r=log2(2B) flattened, 2B disjoint evictions.

    Fetch paths may intersect. Their addresses are public but matches remain
    secret. Secret dedup ensures at most one representative for each logical
    record. Per-request matches against the same physical slot can therefore
    be XOR-aggregated before a SINGLE clear/write; naive concurrent writes are
    incorrect. Every path is padded, and duplicate requests use random paths.
    """
    h, b, z = address_bits, requests, bucket_z
    r = clog2(2*b)
    if r > h:
        raise ValueError("Tree must have at least 2B leaves")
    lower = h-r+1
    pool = z*((1 << r)-1)+pool_slack
    record = payload_bits+2*h+1  # full logical address, leaf label, validity
    parts: dict[str, BooleanWork] = {}

    parts['request_conflicts'] = bitonic_route(b, h+clog2(b)+1,
                                               record+2, record)
    parts['request_conflicts'].then(grouped_scans(b, h, record))

    fetch_slots = b*z*lower
    # Equality h-1, gate validity/representative 2, mask full record, accumulate
    # matches by free XOR, clear each matched physical slot with one AND.
    parts['subtree_fetch'] = BooleanWork(fetch_slots*(h+record+2), clog2(h)+4)
    parts['pool_fetch'] = pool_phase(pool+b, h+clog2(pool+b)+2, h,
                                     record, record)

    d = max(1, clog2(h+1))
    # Every pool candidate computes its deepest compatible level for the public
    # eviction suffix, with secret subtree destination. Prefixes+valid gating
    # cost <=2h AND per candidate; convert one-hot depth to binary with XOR.
    parts['candidate_depth'] = BooleanWork((pool+b)*2*h, clog2(h)+2)
    parts['eviction_select'] = pool_phase(pool+3*b,
                                          r+d+clog2(pool+3*b)+2,
                                          r, record, record)
    # Cleanup key=(dummy, unique ordinal); dummy status remains hidden.
    parts['pool_cleanup'] = pool_phase(pool+3*b, 1+clog2(pool+3*b),
                                       1, record, 0)

    paths = 2*b
    slots = paths*z*lower
    eligibility = slots*2*h
    winner_width = d+clog2(z)+1
    winners = paths*lower*(z-1)*(3*d-2+winner_width)
    # The planner is a PROXY based on a linear-work parallel-scan compilation,
    # NOT an exact count obtained from 2017/861. Its factor is a sensitivity.
    planner = paths*planner_factor*lower*(6*d+2)
    movement = paths*(2*z+movement_factor_extra)*lower*record
    eviction_depth = (clog2(h)+2 + clog2(z)*(clog2(d)+2)
                      +6*clog2(lower)*(clog2(d)+2)+4*clog2(lower)+4)
    parts['subtree_eviction'] = BooleanWork(eligibility+winners+planner+movement,
                                           eviction_depth)
    total = BooleanWork()
    for work in parts.values():
        total.then(work)
    # Select old representative label or unused fresh label for dummy query.
    # Reuse the nonrepresentative's discarded replacement as its dummy path.
    parts['public_path_selection'] = BooleanWork(b*h, 1)
    total.then(parts['public_path_selection'])

    # The permutations below depend on hidden logical UIDs, resident records,
    # or eviction metadata, rather than the public requested old leaf labels.
    # Inverse routing includes private extraction/alignment and state handling
    # allowances. A narrower replacement may be possible, but is not derived
    # by making a final B-result permutation public. This ledger is a SUBSET
    # of parts above and must never be added to, or discounted from, total.
    private_inverse = {
        'request_conflicts': private_inverse_ands(b, record),
        'pool_fetch': private_inverse_ands(pool+b, record),
        'eviction_select': private_inverse_ands(pool+3*b, record),
        'pool_cleanup': 0,
    }

    lower_slots = z*((1 << (h+1))-(1 << r))
    return dict(address_bits=h, payload_bits=payload_bits, record_bits=record,
                requests=b, top_levels=r, lower_path_levels=lower,
                pool_records=pool, state_bits=(lower_slots+pool)*record,
                persistent_bits_touched=(pool+3*b*z*lower)*record,
                persistent_pool_bits=pool*record,
                fresh_position_bits=b*h, public_path_bits=b*h,
                ands=total.ands, depth=total.depth,
                parts={name: asdict(value) for name, value in parts.items()},
                retained_private_inverse_ands=private_inverse,
                eviction_allowance=dict(eligibility=eligibility,
                                        bucket_winners=winners,
                                        planner=planner, movement=movement))


def batch_lookup(log_records: int, batch: int = 1024, fanout: int = 16,
                 base_cutoff: int = 4096, bucket_z: int = 3,
                 pool_slack: int = 128, planner_factor: int = 8,
                 cuckoo_stash: int = 8) -> dict:
    """Public call interface; all costs are for BOTH table probes per query.

    nonlinear_depth is a conservative *gate-depth schedule estimate*, NOT
    interaction rounds: Yao needs no round trip per AND layer. Path discovery
    causes one dependent interaction per recursive tree plus input/output
    boundaries. Pool/eviction scheduling can overlap but is serialized here.
    """
    if log_records < 1 or min(batch, base_cutoff, bucket_z) < 1 or pool_slack < 0:
        raise ValueError("Invalid size")
    if batch != pow2(batch) or fanout != pow2(fanout) or fanout < 2:
        raise ValueError("batch and fanout must be powers of two")
    h, payload = log_records+1, 513
    lf = clog2(fanout)
    trees, packed = [], []
    work = BooleanWork()
    while True:
        level = level_cost(h, payload, batch, bucket_z, pool_slack, planner_factor)
        trees.append(level)
        work.then(BooleanWork(level['ands'], level['depth']))
        if (1 << h) <= base_cutoff or h-lf < clog2(2*batch):
            break
        p = packed_updates(batch, fanout, h, h-lf)
        packed.append(dict(parent_address_bits=h-lf, child_label_bits=h,
                           ands=p.ands, depth=p.depth))
        work.then(p)
        payload, h = fanout*h, h-lf
    base = flat_map(1 << h, batch, h)
    work.then(base)
    # Tables parallelize. Their work/state double, their depth does not.
    ands = 2*work.ands
    candidates = 2+cuckoo_stash
    app = batch*(candidates*(255+1+256)+candidates-1)
    ands += app
    state = 2*(sum(t['state_bits'] for t in trees)+(1 << h)*h)+cuckoo_stash*513
    fresh = 2*sum(t['fresh_position_bits'] for t in trees)
    paths = 2*sum(t['public_path_bits'] for t in trees)
    # Upper envelope: all B fetch paths+2B eviction paths+pool at each tree;
    # repeated physical buckets are overcounted. The entire scalar flat map is
    # touched once per batch. This is persistent read/write I/O, not scratch.
    touched = 2*(sum(t['persistent_bits_touched'] for t in trees)+(1 << h)*h)
    touched += cuckoo_stash*513
    pool_bits = 2*sum(t['persistent_pool_bits'] for t in trees)
    private_inverse_batch = {
        name: 2*sum(t['retained_private_inverse_ands'][name] for t in trees)
        for name in trees[0]['retained_private_inverse_ands']
    }
    private_inverse_batch['flat_base_duplicates'] = 2*private_inverse_ands(batch, h)
    inverse_total = sum(private_inverse_batch.values())
    routing_audit = dict(
        public_request_path_sort_ands=0,
        public_request_wire_permutation_ands=0,
        authorized_output_unpermutation_ands=0,
        retained_private_inverse_ands_per_batch=private_inverse_batch,
        retained_private_inverse_ands_per_query={
            name: count/batch for name, count in private_inverse_batch.items()},
        retained_private_inverse_total_ands_per_batch=inverse_total,
        retained_private_inverse_total_ands_per_query=inverse_total/batch,
        savings_from_confirmed_optimization_ands_per_query=0,
        counted_subset_of_total_ands=True,
        interpretation=(
            'Private inverse swaps are already included in the total. They '
            'are template allowances for private extraction, alignment and '
            'state handling, not a proven minimum. Public request sorting '
            'and authorized terminal output reordering were never separately '
            'charged, so confirming them gives no additional discount.'),
        disclosure_assumptions=[
            'Only old leaf paths requested in this batch are opened, after secret duplicate masking at every recursive level.',
            'Public path permutations can reorder both parties\' corresponding encoded requests locally, without decoding UIDs.',
            'Local plaintext output reordering applies only to authorized data outputs and selected old child labels; the recipient must know the permutation.',
            'Fresh replacement leaves, resident pool metadata, unselected map entries and internal state remain private.',
            'A secret pool sort still needs private extraction to put authorized results in identifiable output slots before decoding.',
            'The evaluator-owned query and semi-honest assumptions are unchanged; no additional optimization from locally sorting private UIDs is assumed.',
        ])
    return dict(log_records=log_records, batch=batch, fanout=fanout,
                base_cutoff=base_cutoff, bucket_z=bucket_z, pool_slack=pool_slack,
                ands_per_batch=ands, ands_per_query=ands/batch,
                nonlinear_depth=work.depth+clog2(256)+2,
                and_parallelism=ands/(work.depth+clog2(256)+2),
                state_bits=state, label_state_bytes_per_party=16*state,
                persistent_bits_touched_per_batch=touched,
                persistent_pool_bits=pool_bits,
                label_state_read_write_bytes_per_party_batch=32*touched,
                table_bytes_per_batch=32*ands, table_bytes_per_query=32*ands/batch,
                fresh_position_bits_per_batch=fresh,
                fresh_position_bits_per_query=fresh/batch,
                public_path_bits_per_query=paths/batch,
                path_reveal_barriers=len(trees),
                base_cells=1 << h, base_label_bits=h,
                base_work_per_table=asdict(base), packed_updates_per_table=packed,
                trees_per_table=trees, application_ands=app,
                routing_audit=routing_audit,
                caveats=[
                    'Source-inspired Boolean template, not an executed gate trace.',
                    'Pool composition, packed updates and parallel eviction are allowances requiring implementation audit.',
                    'Z and pool slack are placeholders, not a service-lifetime overflow guarantee.',
                    'Full-width binary-tree state; no PRG-compressed label state or leaf-bit trimming assumed.',
                    'No complete hidden initialization, OT, fresh-input labels, client integration, or output delivery charged.',
                    'Fresh labels are XOR of private party inputs inside GC, never public coin tossing.',
                    'Untouched labels persist; touched state must acquire fresh output labels.',
                    'Half-gate bandwidth excludes free-XOR CPU/memory traffic and intra-party distribution.',
                ])


if __name__ == '__main__':
    for exponent in (28, 32):
        for batch_size in (256, 1024, 4096):
            result = batch_lookup(exponent, batch_size)
            print(json.dumps({k: v for k, v in result.items()
                              if k not in ('trees_per_table', 'packed_updates_per_table', 'caveats')},
                             sort_keys=True))
