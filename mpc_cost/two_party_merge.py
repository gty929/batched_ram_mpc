"""Two-party garbled-merge ledger from the 2026/761 v2 artifact.

This counts the conditional-link implementation, not native execution.
The source's MEASURE branch charges linear bytes, but its real GARBLE branch
uses a full-horizon grid.  Paper section 3.4 discusses resetting small stacks;
the downloaded switch_stack.cpp has neither resets nor randomized banding.
The window scenarios below are operation-count sensitivities, NOT an
implemented reset/state-handoff protocol or a measured throughput guarantee.

Sources: https://eprint.iacr.org/2026/761 and
https://zenodo.org/records/20751401 (June 18, 2026, v2).
Files: picogram_imp/gadgets/{link.cpp,switch_stack.cpp,circuit_oram.hpp}.
"""


def stack_grid(caller_calls: int, callee_calls: int, width: int) -> dict:
    """Exact garbler hash/GC counts for one artifact conditional link.

    S=sum_{t=0}^{T-1}(min(n,t)+1) counts diagonal states; D counts downward
    cells. GARBLE computes indicator switches twice, data switches once,
    and first applies W input-buffer hashes to each caller record.
    E's count depends on the actual control trace. The upper allowance uses
    at most D row cells, 2*S diagonal cells, S+D indicator hashes, and n*W
    translation hashes; it is deliberately loose and assumes all T calls run.
    It excludes XOR, memory allocation, network and retained-state accesses.
    """
    T, n, W = caller_calls, callee_calls, width
    if not 0 < n <= T or W < 1:
        raise ValueError('Require 0 < callee_calls <= caller_calls and width>0')
    S = (n + 1)*T - n*(n + 1)//2
    D = S - (T - n)
    return dict(joins=T*(W+1), header_bytes=8,
                garbled_bytes=16*T*(W+1)+8,
                garbler_hashes=2*S+W*(S+D)+T*W,
                evaluator_hash_upper=S+D+W*(D+2*S+n),
                diagonal_states=S, downward_cells=D)


def merge_cost(c: dict, windows=(64, 128, 256, 512)) -> dict:
    """Add a conditional-link ledger to garbled_circuit.kv_lookup output.

    Port width includes both meta_scan and access, in both directions:
      W = (1+p+h+2m)+(m+1)+(1+p+h+w)+w.
    Every parent invokes every child link, although only one child is active.
    T in a link is the parent's provisioned calls, not client batch size.

    Counts output-language binding joins separately: Func::garble binds the
    actual meta_scan/access outputs to their preassigned port languages.
    Does not count selector/reveal circuitry, prefix-sum implementation
    overhead, output decoding, or other non-stack gates (provided by c).
    Joint randomness and initialization also belong to a separate ledger.
    """
    horizon = c['horizon']
    table_count = c.get('table_count', 2)
    fields = ('joins', 'header_bytes', 'garbled_bytes', 'garbler_hashes',
              'evaluator_hash_upper')
    raw = {k: 0 for k in fields}
    binding_joins = 0
    binding_visited = 0
    scenarios = {K: {k: 0 for k in fields} for K in windows}
    rows = []
    for tree in c['probe']['trees']:
        h, w = tree['address_bits'], tree['payload_bits']
        m = max(1, ((h+1)//2).bit_length())
        levels = tree['node_levels']
        out_width = w+m+1
        binding_joins += table_count*sum(
            row['nodes']*row['provisioned_calls_per_node']*out_width
            for row in levels)
        binding_visited += table_count*(1+tree['extra_evictions'])*len(levels)*out_width
        for parent, child in zip(levels, levels[1:]):
            p = child['remaining_position_bits']
            W = 3+2*p+2*h+3*m+2*w
            T = parent['provisioned_calls_per_node']
            n = child['provisioned_calls_per_node']
            links = child['nodes']*table_count
            ledger = stack_grid(T, n, W)
            for key in fields:
                raw[key] += links*ledger[key]
            rows.append(dict(address_bits=h, payload_bits=w,
                             child_level=child['level'], port_width=W,
                             caller_calls=T, callee_calls=n,
                             links_both_tables=links))
            for K, result in scenarios.items():
                # A full-capacity K-by-K window handles arbitrary controls.
                # This avoids claiming a probabilistic child overflow bound.
                # It is more conservative than the paper's balanced windows.
                full, tail = divmod(T, K)
                a = stack_grid(K, K, W)
                b = stack_grid(tail, tail, W) if tail else None
                for key in fields:
                    result[key] += links*(full*a[key]+(b[key] if b else 0))
    per_query = {k: v/horizon for k, v in raw.items()}
    return dict(
        method='Source-derived conditional-link byte and garbler-hash count',
        source_url='https://zenodo.org/records/20751401',
        source_version='v2, June 18 2026',
        horizon=horizon, per_query=per_query,
        output_binding=dict(
            generated_joins_per_query=binding_joins/horizon,
            evaluated_joins_per_query=binding_visited,
            garbled_bytes_per_query=16*binding_joins/horizon,
            source='Func::garble and Bit::join, both meta_scan and access outputs',
            needed_for_preassigned_merge_port_languages=True,
            included_in_per_query_merge_cost=False),
        literal_full_horizon_epoch=raw,
        window_sensitivities=[dict(
            caller_window=K,
            **{k+'_per_query': v/horizon for k, v in result.items()},
            requires_unimplemented_reset_handoff=True,
            reset_handoff_gates_included=False,
            uses_randomized_banding=False)
            for K, result in scenarios.items()],
        rows=rows,
        is_native_measurement=False,
        includes_nonstack_gates=False,
        includes_selector_and_prefix_sum_overhead=False,
        includes_joint_randomness_or_initialization=False)


def visited_evaluator_merge(c: dict, window: int) -> dict:
    """Actual-path evaluator work for a HYPOTHETICAL full-capacity window.

    This is a phase/selector sensitivity, not a measured latency model. It
    counts all child links at EACH VISITED PARENT, not all provisioned nodes.
    It assumes a reset scheme whose local caller window has K calls and whose
    child links each have capacity n=K. K=min(window, source_parent_budget).
    Such resets/state handoffs are not implemented by the downloaded artifact.

    Derivation from v2 switch_stack.cpp::switch_stack_step (lines 300-423) and
    switch_stack_translate (lines 425-483): at local caller phase t, every one
    of b child links hashes t+1 indicators. The b-1 inactive children each hash
    W row cells. If the selected child previously received r real calls, its
    row lookahead and row prefill together hash K-1-r cells, each costing W+1
    hashes. Its diagonal-data and final port translation cost 2W(t+1). Thus

      H(t,r)=b(t+1)+(b-1)W+(K-1-r)(W+1)+2W(t+1).

    This is exact for that full-capacity window. An independent uniform b-way
    selector gives E[r | t]=t/b. Uniform t in [0,K-1] then gives the displayed
    mean. Actual deterministic evictions, balanced hidden permutations and
    finite node visit counts need not have this distribution. In particular,
    most low-level nodes of a short horizon can be in early phases: do not
    treat this stationary sensitivity as their measured finite-horizon mean.

    The min/max bounds use t=0,r=0 and t=K-1,r=0, respectively. They describe
    THIS chosen full-capacity window, not arbitrary native partial-capacity
    stacks. For budgets>=window the final shortened window is exposed in each
    row but not weighted into the stationary mean because the frequency with
    which actually visited nodes reach it has not been established.

    Excludes Boolean node work, output joins/XORs, state/memory access, network,
    resets, decoding, and input OT. Two independent cuckoo tables can run on
    separate evaluator lanes; their work adds but their critical-path work is
    one probe plus subsequent candidate checking. The function does NOT assume
    parallelism across successive accesses to the same mutable ORAM state.
    """
    if window < 1:
        raise ValueError('window must be positive')
    table_count = c.get('table_count', 2)
    by_tree = []
    total_mean = total_min = total_max = 0.
    for tree in c['probe']['trees']:
        h, w = tree['address_bits'], tree['payload_bits']
        m = max(1, ((h+1)//2).bit_length())
        traversals = 1+tree['extra_evictions']
        levels = []
        tree_mean = tree_min = tree_max = 0.
        for parent, child in zip(tree['node_levels'], tree['node_levels'][1:]):
            T = parent['provisioned_calls_per_node']
            K = min(window, T)
            b = child['nodes']//parent['nodes']
            W = 3+2*child['remaining_position_bits']+2*h+3*m+2*w
            mean = (b*(K+1)/2+(b-1)*W
                    +(K-1)*(1-1/(2*b))*(W+1)+W*(K+1))
            minimum = b+(b-1)*W+(K-1)*(W+1)+2*W
            maximum = b*K+(b-1)*W+(K-1)*(W+1)+2*W*K
            tree_mean += traversals*mean
            tree_min += traversals*minimum
            tree_max += traversals*maximum
            levels.append(dict(
                parent_level=parent['level'], branching_factor=b, port_width=W,
                source_parent_budget=T,
                source_child_budget=child['provisioned_calls_per_node'],
                hypothetical_child_capacity=K, effective_window=K,
                full_windows_in_parent_budget=T//window,
                final_tail_calls_in_parent_budget=T%window,
                expected_hashes_per_visited_parent_event=mean,
                minimum_hashes_per_visited_parent_event=minimum,
                maximum_hashes_per_visited_parent_event=maximum))
        total_mean += tree_mean
        total_min += tree_min
        total_max += tree_max
        by_tree.append(dict(address_bits=h, payload_bits=w, traversals=traversals,
                            expected_hashes_per_probe=tree_mean,
                            minimum_hashes_per_probe=tree_min,
                            maximum_hashes_per_probe=tree_max, levels=levels))
    return dict(
        requested_window=window, horizon=c['horizon'], table_count=table_count,
        expected_hashes_per_query=table_count*total_mean,
        expected_hashes_per_probe=total_mean,
        independent_table_lanes=table_count,
        critical_path_hashes_with_independent_table_lanes=total_mean,
        parallel_mean_is_not_expected_max_of_lane_times=True,
        minimum_phase_hashes_per_query=table_count*total_min,
        maximum_phase_hashes_per_query=table_count*total_max,
        by_tree=by_tree,
        source_url='https://zenodo.org/records/20751401',
        source='switch_stack.cpp::switch_stack_step and switch_stack_translate',
        model_type='Visited-path stationary window phase sensitivity',
        assumes_uniform_local_window_phase=True,
        assumes_independent_uniform_child_selectors=True,
        uses_actual_finite_horizon_visit_distribution=False,
        weights_final_partial_windows=False,
        requires_unimplemented_reset_handoff=True,
        replaces_source_child_capacity_with_full_window_capacity=True,
        is_native_measurement=False,
        counts_boolean_and_xor_work=False,
        supports_parallel_successive_accesses=False)


if __name__ == '__main__':
    import json
    from mpc_cost.garbled_circuit import kv_lookup
    results = {}
    for exponent in (28, 32):
        core = kv_lookup(exponent, fanout=8,
                         base_cells=256 if exponent == 28 else 512,
                         family='communication')
        result = merge_cost(core)
        result.pop('rows')
        results[str(exponent)] = result
    print(json.dumps(results, indent=2))
