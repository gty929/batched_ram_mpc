"""Binary hierarchical 2PC ORAM: 512 routing slots, 64/128 lookup slots.

Run python -m mpc_cost.hierarchical_split_cost. Requires scipy.
Analytical ledger, not an end-to-end implementation. All bytes unframed unless
explicitly marked; packed256-bit values are XOR shares, metadata is Boolean GC.
The two-direction word-OT conditional swap is budgeted at160 bytes.
Probability expressions are analytic bounds evaluated in floating point.
"""
from functools import lru_cache
from math import ceil, comb, exp, expm1, log, log1p, log2
from pathlib import Path
import json

from scipy.optimize import minimize_scalar
from scipy.special import logsumexp
from scipy.stats import poisson

from .hierarchical_cost import build, case as unsplit_case, compact, mergesplit

ROOT = Path(__file__).resolve().parent
Q = 2**32
LN2 = log(2)
PARENT = 512
LOCAL_STASH = 64
META = 130


def local_logp(z, s=LOCAL_STASH):
    g = PARENT//z
    terms = []
    for a in range(1, g+1):
        threshold = a*z+s+1
        if threshold > PARENT:
            continue
        mu = a*z/2
        terms.append(log(comb(g, a))-threshold*log(threshold/mu)+threshold-mu)
    return min(0., float(logsumexp(terms))) if terms else float('-inf')


def residual_logmgf(z, t):
    mu = z/2
    logp = float(poisson.logsf(z, mu))
    tilted = -t*z+mu*expm1(t)+float(poisson.logsf(z, mu*exp(t)))
    delta = tilted+log(-expm1(min(-1e-16, logp-tilted)))
    return log1p(exp(delta)) if delta < 700 else delta


def global_logp(n, z, capacity):
    m = 2*n//z
    result = minimize_scalar(
        lambda t: m*residual_logmgf(z, t)-(capacity+1)*t,
        bounds=(1e-8, 6.), method='bounded', options={'xatol': 1e-12})
    # Monotonicity plus Pr[Pois(n)>=n]>=1/2 for integer n.
    return min(0., result.fun+LN2), float(result.x)


@lru_cache(None)
def stash_capacity(n, z, batch=1024, budget_bits=66):
    target = -budget_bits*LN2-log(Q/batch)
    lo, hi = -1, 1
    while global_logp(n, z, hi)[0] > target:
        hi *= 2
    while hi-lo > 1:
        mid = (hi+lo)//2
        if global_logp(n, z, mid)[0] <= target:
            hi = mid
        else:
            lo = mid
    cap = 8*ceil(hi/8)
    lp, tilt = global_logp(n, z, cap)
    return dict(capacity=cap, minimum_capacity=hi, per_build_log2=lp/LN2,
                chernoff_tilt=tilt, per_build_target_log2=target/LN2)


def local_split(z):
    """Exact leaf-excess planning, one extraction, recursive feasible split.

    Plan ORCompact512 for each leaf's one-bit membership vector. Inverse-route
    a public first-z mask on ONE bit/slot to identify retained source entries.
    OR of disjoint per-leaf overflow flags is XOR. Then compact all excess
    once, copy the public first64 data fields into a local stash, clear these
    live bits in the main copy, and partition the feasible remainder.
    """
    if z not in (64, 128):
        raise ValueError('Audited for64/128 only')
    d = int(log2(PARENT//z))
    c = compact(PARENT)
    preselect = (PARENT//z)*(PARENT*d+c['planner_ands']+c['swaps']+PARENT)
    extraction_planner = c['planner_ands']+197
    recursion_planner = 0
    metadata_movement = c['swaps']*(META+d)
    payload_swaps = c['swaps']
    swap_depth = int(log2(PARENT))
    levels = []
    for j in range(d):
        size = PARENT >> j
        nodes = 1 << j
        ms = mergesplit(size//2)
        swaps = nodes*ms['swaps']
        planner = nodes*ms['planner_ands']
        # Route only as-yet-unconsumed suffix bits, including this stage bit.
        metadata_movement += swaps*(META+d-j)
        payload_swaps += swaps
        recursion_planner += planner
        swap_depth += int(log2(size))
        levels.append(dict(nodes=nodes,input_slots=size,swaps=swaps,planner_ands=planner))
    planner = preselect+extraction_planner+recursion_planner
    return dict(child_z=z,suffix_bits=d,preselection_ands=preselect,
                extraction_planner_ands=extraction_planner,
                recursive_planner_ands=recursion_planner,
                planner_ands=planner,metadata_movement_ands=metadata_movement,
                ands=planner+metadata_movement,payload_swaps=payload_swaps,
                payload_swap_layers=swap_depth,levels=levels)


def scenario(log_n, z, batch=1024, payload_swap_bytes=160):
    nmax = 1 << log_n
    L = log_n-int(log2(batch))
    if batch < PARENT or batch & (batch-1):
        raise ValueError('Power-of-two batch>=512 gives a genuine base hash table')
    split = local_split(z)
    d = split['suffix_bits']
    capacities = [stash_capacity(batch << i,z,batch) for i in range(L+1)]
    components = {}
    swaps = key_input = read_ands = read_selectors = addresses = 0.
    global_failure = parent_tests = routing_tests = 0.
    peak_slots = 4*nmax-2*batch+sum(x['capacity'] for x in capacities)
    worst_read_bytes = 0.
    rows = []
    for i in range(L+1):
        n = batch << i
        top = i == L
        base = build(n,PARENT,top=top)
        interval = nmax if top else 2*n
        p = 2*n//PARENT
        ledger = dict(base['and_components'])
        ledger['retained_suffix_bits_in_butterfly'] = base['butterfly_swaps']*d
        row_swaps = base['payload_switches']
        # Source arrays now also contain old global stashes. Compact main
        # arrays first, retain first n, append old stash slots in remaining n
        # positions, then compact2n. This explicitly pays for re-admission.
        source_stash = sum(x['capacity'] for x in capacities[:i])
        if top:
            source_stash += capacities[i]['capacity']
        if source_stash > n:
            raise AssertionError('Source stash concatenation does not fit')
        if source_stash:
            extra = compact(2*n)
            ledger['source_stash_reentry_planner'] = extra['planner_ands']
            ledger['source_stash_reentry_metadata'] = META*extra['swaps']
            ledger['source_stash_top_absence_clear'] = source_stash if top else 0
            row_swaps += extra['swaps']
        ledger['local_split_planner'] = p*split['planner_ands']
        ledger['local_split_metadata'] = p*split['metadata_movement_ands']
        row_swaps += p*split['payload_swaps']
        collect = compact(p*LOCAL_STASH)
        ledger['global_stash_merge_planner'] = collect['planner_ands']
        ledger['global_stash_merge_metadata'] = META*collect['swaps']
        # Conservative public-threshold overflow detection from total count.
        ledger['global_stash_overflow_check'] = 2*int(log2(p*LOCAL_STASH))+1
        row_swaps += collect['swaps']
        for key,value in ledger.items():
            components[key] = components.get(key,0.)+value/interval
        swaps += row_swaps/interval
        key_input += base['fresh_key_input_bytes']/interval
        parent_tests += Q*p/interval
        routing_tests += Q*base['buckets']*base['stages']/interval
        global_failure += (Q/interval)*2**capacities[i]['per_build_log2']
        w = 1. if top else .5
        slots = z+capacities[i]['capacity']
        a = 2*5120+134*slots+base['stages']+d+4
        read_ands += w*a
        read_selectors += w*slots
        addresses += w*2*(base['stages']+d)/8
        worst_read_bytes += 32*a+payload_swap_bytes*slots+2*(base['stages']+d)/8
        per_build = 32*sum(ledger.values())+payload_swap_bytes*row_swaps+base['fresh_key_input_bytes']
        depth = int(log2(base['source_slots']))
        if source_stash:
            depth += int(log2(2*n))
        depth += base['stages']*10+split['payload_swap_layers']+int(log2(p*LOCAL_STASH))
        rows.append(dict(log_capacity=int(log2(n)),capacity=n,top=top,
                         accesses_per_rebuild=interval,parent_buckets=p,
                         parent_routing_stages=base['stages'],global_stash=capacities[i],
                         source_stash_slots=source_stash,read_slots=slots,
                         rebuild_ands=sum(ledger.values()),rebuild_payload_swaps=row_swaps,
                         rebuild_unframed_bytes=per_build,components=ledger,
                         payload_swap_layers=depth))
    rebuild_bytes = 32*sum(components.values())+payload_swap_bytes*swaps+key_input
    read_bytes = 32*read_ands+payload_swap_bytes*read_selectors+addresses
    b = int(log2(batch))
    comparisons = b*(b+1)/4
    # Work-efficient parallel segmented result propagation. Three prefix
    # combines per input is a conservative scan allowance;140 includes
    # adjacent fingerprint equality, representative flags and present bits.
    dedup_ands = comparisons*511+140*(batch-1)/batch
    dedup_selectors = comparisons+3*(batch-1)/batch
    frontend = 32*10240+64*256
    dedup_bytes = 32*dedup_ands+payload_swap_bytes*dedup_selectors
    total = rebuild_bytes+read_bytes+frontend+dedup_bytes
    return dict(log_records=log_n,batch=batch,parent_z=PARENT,child_z=z,
        local_stash=LOCAL_STASH,packed_payload_swap_bytes=payload_swap_bytes,
        lower_levels=L,average_occupied_tables=L/2+1,max_occupied_tables=L+1,
        rebuild_ands_per_query=sum(components.values()),rebuild_ands_components_per_query=components,
        rebuild_payload_swaps_per_query=swaps,rebuild_unframed_bytes_per_query=rebuild_bytes,
        read_unframed_bytes_per_query=read_bytes,read_ands_per_query=read_ands,
        read_payload_selectors_per_query=read_selectors,worst_read_unframed_bytes_per_query=worst_read_bytes,
        frontend_and_dedup_unframed_bytes_per_query=frontend+dedup_bytes,
        total_unframed_bytes_per_query=total,total_framed_bytes_per_query=1.05*total,
        local_stash_lifetime_failure_log2=local_logp(z)/LN2+log2(parent_tests),
        global_stash_lifetime_failure_log2=log2(global_failure),
        parent_routing_lifetime_failure_log2=-PARENT*(1-log2(exp(1))/2)+log2(routing_tests),
        max_persistent_slots=peak_slots,packed_state_bytes_per_party=peak_slots*(16*META+32),
        local_refinement=split,rows=rows)


def main():
    primary = [scenario(logn,z) for logn in (28,32) for z in (64,128)]
    batch_sweep = [scenario(logn,z,batch) for logn in (28,32)
                   for batch in (512,1024,2048,4096) for z in (64,128)]
    sensitivity = [scenario(logn,z,payload_swap_bytes=c) for logn in (28,32)
                   for z in (64,128) for c in (80,160,320,8192)]
    result = dict(date='2026-10-17',description=__doc__,
        assumptions=dict(horizon=Q,global_stash_budget_bits=66,
            ideal_prf=True,canonical_fingerprint_collision_excluded=True,
            labels_bits=128,value_bits=256,key_fingerprint_bits=128,
            packet_framing=1.05,prf_contexts='Secret independent fingerprint/table/dummy contexts',
            numeric_certification='Analytic bounds, floating-point witnesses; not interval-certified',
            payload='Two128-bit XOR shares perparty; no Boolean reinput for pure movement',
            exclusions=['initialdatabaseconstruction','CPUandlocalhashwork','replicacountanddurability',
                        'applicationcomputationonreturnedvalues','baseOTsetup']),
        primary=primary,batch_sweep=batch_sweep,payload_sensitivity=sensitivity,
        unsplit=[unsplit_case(logn,1024,512,160) for logn in (28,32)])
    path = ROOT/'results/hierarchical_split_comparison.json'
    path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    for c in primary:
        print(f"N2^{c['log_records']} z{c['child_z']} B{c['batch']}: "
              f"rebuild{c['rebuild_unframed_bytes_per_query']/1e6:.3f}MB "
              f"read{c['read_unframed_bytes_per_query']/1e6:.3f}MB "
              f"total{c['total_unframed_bytes_per_query']/1e6:.3f}MB "
              f"stash{c['rows'][-1]['global_stash']['capacity']} "
              f"failureLog2{c['global_stash_lifetime_failure_log2']:.2f}")


if __name__ == '__main__':
    main()
