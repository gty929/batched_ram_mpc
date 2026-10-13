"""Boolean workload for a prospective multiparty garbled Circuit ORAM.

This is a SOURCE-DERIVED CIRCUIT TEMPLATE, not an executed native gate counter,
an optimized implementation, or a security proof.  It transcribes the local
read/evict operations in the 2026/761 authors' June-2026 artifact.  Its explicit
upper allowances count metadata, conditional swaps, recursion and flat maps.
All language-translation / garbled-stack gates are zero by the user's requested
research assumption.  Free XOR affects communication, not local work.

Primary source: https://zenodo.org/records/20751401
Files: picogram_imp/gadgets/{circuit_oram,rec_oram}.hpp,
       picogram_imp/types/{word,vec}.hpp.
The artifact is older than the final August ePrint revision.
"""
from dataclasses import dataclass, asdict
from math import ceil


def bits(x: int) -> int:
    return max(1, x.bit_length())


def optimal_log_way(p: int, maximum: int = 2) -> int:
    """The artifact's balanced tree: mostly four children, possibly two."""
    levels = (p + maximum - 1) // maximum
    return (p + levels - 1) // levels if levels else 1


@dataclass
class Gates:
    ands: float = 0
    xors: float = 0


def node_template(h: int, w: int, p: int, level: int, z: int,
                  g: int, tree_levels: int) -> Gates:
    """One node's generic metadata scan and access_local invocation.

    h = virtual address width, w = payload bits, p = remaining position bits,
    z = bucket slots, g = log2 children. m encodes a tree level 0..L.
    Assumptions for a deliberately simple Boolean lowering:
      m-bit compare <= m AND + 5m XOR; mux m AND + 2m XOR;
      conditional swap m AND + 3m XOR; equality m-1 AND + m XOR;
      q-bit popcount <= 2q AND + 6q XOR (carry-save plus ripple addition).
    Public constants/first-step constant propagation can reduce these counts.
    No claim that all compiler choices attain these allowances simultaneously.
    """
    m = bits(tree_levels)
    block_bits = w + h + p + 1
    if p:
        q = (p + g - 1) // g
        # Position XOR + grouped trailing-zero mask + popcount, then an
        # argmax, full virtual-address equality, and one-hot winner selection.
        meta_a = z * (max(0, p - 1) + 2*q + 2*m + h + 7) + 7*m + 6
        meta_x = z * (p + 6*q + 7*m + h) + 22*m
    else:
        # Leaf has no position-prefix calculation; it still matches addresses.
        meta_a = 2*m + z*(h + 2) + 2
        meta_x = 7*m + z*h
    outgoing_bits = p - g + h + w if p else 0
    # Three initial flags, one additional root flag, three per-slot flags;
    # move valid/address/position/payload, forward held block, mask read output.
    access_a = 3 + int(level == 0) + z*(block_bits + 3) + w
    access_x = 3*z*block_bits
    if p:
        access_a += 2 + outgoing_bits
        access_x += 2*outgoing_bits + w  # final XOR of child/local read results
    return Gates(meta_a + access_a, meta_x + access_x)


def vector_exchange(cells: int, width: int) -> Gates:
    """Exact chosen flat-map circuit: one-hot decoder + conditional swaps.

    The decoder shares prefixes: child0 = parent XOR child1, costing one
    AND per parent below the first level. For a power-of-two cells>=2 this
    gives cells-2 AND/XOR. Exactly one conditional swap executes semantically;
    all cells are garbled, and the carried word finishes holding the old value.
    This also handles the F-way packed position subblock update.
    """
    decoder = max(0, cells - 2)
    return Gates(cells*width + decoder, 3*cells*width + decoder)


def source_params(h: int, family: str = 'compute') -> tuple[int, int, int]:
    """(root stash, other bucket size, extra evictions) from ORAMConstParams.

    These are inherited prototype parameters. They do NOT establish a service-
    lifetime failure bound for 10k QPS or maliciously generated initial state.
    """
    if family == 'compute':
        return (42, 7, 1) if h < 16 else (50, 6, 1)
    if family == 'communication':
        if h < 8:
            return 17, 5, 2
        return (21, 4, 2) if h < 26 else (34, 3, 2)
    raise ValueError(family)


def tree_template(h: int, w: int, horizon: int,
                  family: str = 'compute') -> dict:
    """Count all provisioned node invocations, plus actually visited paths.

    Artifact constructor: root calls=(1+e)*T. Child budget=ceil(parent/way),
    plus N/way at the root, capped at parent budget. Later children inherit
    rounded division. Sum node multiplicities, not merely the visited path.
    """
    stash, bucket, extra = source_params(h, family)
    levels = (h + 1) // 2
    p, level, count = h, 0, 1
    calls = (1 + extra)*horizon
    generated_a = generated_x = visited_a = visited_x = state = 0
    input_labels = h  # fresh hidden replacement position; PRG/coin protocol extra
    rows = []
    while True:
        z = stash if level == 0 else bucket
        g = optimal_log_way(p)
        work = node_template(h, w, p, level, z, g, levels)
        generated_a += count*calls*work.ands/horizon
        generated_x += count*calls*work.xors/horizon
        visited_a += (1 + extra)*work.ands
        visited_x += (1 + extra)*work.xors
        state_bits = count*z*(w + h + p + 1)
        state += state_bits
        rows.append(dict(level=level, remaining_position_bits=p,
                         nodes=count, provisioned_calls_per_node=calls,
                         slots_per_node=z, local_ands=work.ands,
                         local_xors=work.xors, retained_bits=state_bits))
        if p == 0:
            break
        way = 1 << g
        child_calls = (calls + way - 1)//way
        if level == 0:
            child_calls += 1 << (p - g)
        calls = min(calls, child_calls)
        p -= g
        count *= way
        level += 1
    # CircuitORAM::access computes the new block's eligibility on the first
    # deterministic eviction. It is outside the per-node scan.
    q = (h + 1)//2
    extra_a, extra_x = max(0, h - 1) + 2*q, h + 6*q
    return dict(address_bits=h, payload_bits=w, root_stash=stash,
                bucket=bucket, extra_evictions=extra,
                generated_ands=generated_a + extra_a,
                generated_xors=generated_x + extra_x,
                visited_ands=visited_a + extra_a,
                visited_xors=visited_x + extra_x,
                retained_bits=state, fresh_position_bits=input_labels,
                node_levels=rows)


def recursive_probe(address_bits: int, payload_bits: int = 513,
                    horizon: int | None = None, fanout: int = 4,
                    base_cells: int = 1024,
                    family: str = 'compute') -> dict:
    """One dense RAM probe with recursive, privately updated position maps.

    Default payload is512 key/value bits+one occupied bit. A reserve encoding
    or separately demonstrated packing can remove that bit. At the last actual
    ORAM, its FULL scalar position map is flat; it is not divided by F again.
    """
    if fanout < 2 or fanout & (fanout - 1):
        raise ValueError('fanout must be a power of two >=2')
    if base_cells < 1:
        raise ValueError('base_cells must be positive')
    horizon = (1 << address_bits) if horizon is None else horizon
    if horizon < 1:
        raise ValueError('horizon must be positive')
    totals = dict(generated_ands=0., generated_xors=0., visited_ands=0.,
                  visited_xors=0., retained_bits=0, fresh_position_bits=0)
    h, w = address_bits, payload_bits
    logf = fanout.bit_length() - 1
    trees = []
    while True:
        t = tree_template(h, w, horizon, family)
        trees.append(t)
        for key in totals:
            totals[key] += t[key]
        if (1 << h) <= base_cells or h < logf:
            size = 1 << h
            base = vector_exchange(size, h)
            totals['retained_bits'] += size*h
            totals['generated_ands'] += base.ands
            totals['visited_ands'] += base.ands
            totals['generated_xors'] += base.xors
            totals['visited_xors'] += base.xors
            break
        packed = vector_exchange(fanout, h)
        totals['generated_ands'] += packed.ands
        totals['visited_ands'] += packed.ands
        totals['generated_xors'] += packed.xors
        totals['visited_xors'] += packed.xors
        w, h = fanout*h, h - logf
    return dict(**totals, trees=trees, flat_base_cells=size,
                flat_base_position_bits=h, horizon=horizon, fanout=fanout,
                payload_bits=payload_bits, family=family)


def benes_routing_setup(physical_slots: int, block_bits: int) -> dict:
    """Apply an already specified secret permutation to full-width blocks.

    Source initialization uses Waksman routing over ALL physical tree slots:
    circuit_oram.hpp::init_ram forms Block(valid, position, v_addr, data), with
    BOTH addresses still h bits; position trimming happens after routing.
    We use a padded, regular Benes network as an explicit conservative routing
    substitute. K=next_power_of_two(M), stages=2*log2(K)-1, K/2 switches/stage.
    Each secret conditional swap costs block_bits AND and 3*block_bits XOR.

    This helper does not compute or validate routing controls, generate the
    hidden balanced position permutation, choose valid target bucket slots,
    initialize the position map, or deliver/authenticate the control inputs.
    Its control_bits field counts supplied Boolean controls, not protocol cost.
    Padding adds dummy blocks and may admit constant folding not assumed here.
    """
    if physical_slots < 1 or block_bits < 1:
        raise ValueError('Physical slots and block width must be positive.')
    logk = (physical_slots - 1).bit_length()
    padded = 1 << logk
    stages = max(0, 2*logk - 1)
    switches = (padded // 2)*stages
    return dict(physical_slots=physical_slots, padded_slots=padded,
                padding_slots=padded-physical_slots, block_bits=block_bits,
                stages=stages, switches=switches, control_bits=switches,
                ands=switches*block_bits, xors=3*switches*block_bits)


def probe_routing_setup(probe: dict) -> dict:
    """Routing-only initialization for every actual tree of one dense probe.

    The final flat map and dictionary stash are not additional tree-routing
    networks. Their initialization and input encodings remain separate.
    """
    trees = []
    for tree in probe['trees']:
        slots = sum(row['nodes']*row['slots_per_node']
                    for row in tree['node_levels'])
        h, w = tree['address_bits'], tree['payload_bits']
        route = benes_routing_setup(slots, w + 2*h + 1)
        trees.append(dict(address_bits=h, payload_bits=w, **route))
    return dict(ands=sum(t['ands'] for t in trees),
                xors=sum(t['xors'] for t in trees),
                control_bits=sum(t['control_bits'] for t in trees), trees=trees,
                method='Padded Benes application of supplied valid secret controls',
                source='2026/761 artifact circuit_oram.hpp::init_ram',
                source_url='https://zenodo.org/records/20751401',
                block_width_formula='payload_bits + 2*address_bits + 1',
                switch_formula='(K/2)*(2*log2(K)-1), K=next_power_of_two(M)',
                includes_layout_generation=False,
                includes_control_generation_or_validation=False,
                includes_control_input_delivery=False,
                includes_flat_map_or_stash_initialization=False,
                included_in_default_generated_ands=False)


def kv_lookup(log_records: int, horizon: int | None = None,
              fanout: int = 4, base_cells: int = 1024,
              family: str = 'compute', cuckoo_stash: int = 8) -> dict:
    """Two tables of2N slots, two fixed probes plus resident stash scan.

    Ordinary one-slot cuckoo table load is1/4 of totalcapacity=4N here.
    Hash-function computation, jointly hidden random initial permutation and
    refresh, malicious initialization proof, and encoded input/output delivery
    remain separate ledger entries. The probe/core Boolean counts are complete
    only under those explicit external component assumptions.
    """
    h = log_records + 1
    p = recursive_probe(h, horizon=horizon, fanout=fanout,
                        base_cells=base_cells, family=family)
    routing = probe_routing_setup(p)
    # Exact 256-bit equality, AND with occupied, then mask256 output bits.
    # Candidate matches are mutually exclusive in a valid dictionary.
    candidates = 2 + cuckoo_stash
    app_a = candidates*(255 + 1 + 256) + candidates - 1  # membership flag
    app_x = candidates*256 + (candidates - 1)*256
    totals = {k: 2*p[k] for k in ('generated_ands', 'generated_xors',
                                'visited_ands', 'visited_xors',
                                'retained_bits', 'fresh_position_bits')}
    totals['generated_ands'] += app_a
    totals['visited_ands'] += app_a
    totals['generated_xors'] += app_x
    totals['visited_xors'] += app_x
    totals['retained_bits'] += cuckoo_stash*513
    # Main frontend: client supplies key and the two privately encoded indices.
    # Exact candidate equality prevents a false hit if a malicious client supplies
    # wrong indices; it can force a miss for its own query. Hash-in-circuit is a
    # separate stricter-functionality option and would remove the index inputs.
    # Joint randomness is required for every replacement leaf.
    # This is a functionality-level count, not n-party coin-generation traffic.
    totals['query_input_bits'] = 256 + 2*h
    totals['private_index_input_bits'] = 2*h
    totals['functionality_input_bits_per_query'] = totals['query_input_bits'] + totals['fresh_position_bits']
    totals['initial_state_bits'] = totals['retained_bits']
    totals['initial_state_bits_per_query_at_horizon'] = totals['retained_bits']/p['horizon']
    totals['stack_ands'] = totals['stack_joins'] = totals['stack_buffers'] = 0
    totals['hash_ands_external'] = None
    totals['malicious_initialization_cost_external'] = None
    totals['runtime_randomness_generation_external'] = None
    # Separate optional initialization ledger: preserve the default online/
    # provisioned node gate count and let pricing decide epoch amortization.
    totals['routing_setup_ands_per_epoch'] = 2*routing['ands']
    totals['routing_setup_xors_per_epoch'] = 2*routing['xors']
    totals['routing_setup_control_bits_per_epoch'] = 2*routing['control_bits']
    return dict(**totals, log_records=log_records, table_address_bits=h,
                table_slots=1 << h, table_count=2, record_bits=512,
                stored_payload_bits=513, cuckoo_stash=cuckoo_stash,
                horizon=p['horizon'], fanout=fanout, family=family,
                flat_base_cells=p['flat_base_cells'], probe=p,
                routing_setup=dict(table_count=2, per_table=routing))


if __name__ == '__main__':
    import json
    for exponent in (28, 32):
        result = kv_lookup(exponent)
        print(json.dumps({k: v for k, v in result.items() if k != 'probe'}, indent=2))
