"""Conditional fresh-garbled-circuit lookahead cache for small ORAM levels.

The cache stores distinct, single-use bucket circuit versions at the evaluator;
it does not reuse a garbling. Counts are unframed bytes. The occupancy model is
conditional on an occupied table receiving B independent uniform bucket draws.
Deduplicating requests is required before those draws; pseudorandomness alone
does not establish this distribution for an arbitrary address-selection policy.

This is a performance cache model, not a security proof or protocol compiler.
Dynamic OT, state/input-label binding, version chaining, address delivery,
initial setup, and application payload processing are outside this GC cache.
"""

from math import isfinite

from scipy.stats import binom
from .hierarchical_address import prf_ands, inputs


GC_BYTES_PER_AND = 32
BUCKET_ANDS_PER_SLOT = 134
STATE_BYTES_PER_SLOT = 2112  # 130 metadata labels plus a packed 32-byte share.
PRF_ANDS_PER_REQUEST_TABLE = 10240


def _nonnegative_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f'{name} must be a nonnegative integer')
    return value


def lookahead_statistics(batch, buckets, lookahead):
    """One-table miss statistics when every bucket starts with w fresh GCs.

    With X~Binomial(B,1/m), requests needing an additional circuit number
    m E[(X-w)+]. Its expectation follows the binomial tail identity
    B/m Pr[Bin(B-1,1/m)>=w] - w Pr[Bin(B,1/m)>w].
    The probability that ANY bucket exhausts its queue is at most
    min(1,m Pr[X>w]); this union bound is a performance bound only.
    """
    _nonnegative_int(batch, 'batch')
    _nonnegative_int(buckets, 'buckets')
    _nonnegative_int(lookahead, 'lookahead')
    if batch == 0 or buckets == 0:
        raise ValueError('batch and buckets must be positive')
    probability = 1. / buckets
    mean = batch * probability
    bucket_tail = float(binom.sf(lookahead, batch, probability))
    first_moment_tail = mean * float(
        binom.sf(lookahead - 1, batch - 1, probability))
    excess = max(0., min(mean, first_moment_tail - lookahead * bucket_tail))
    miss_requests = min(float(batch), buckets * excess)
    miss_fraction = miss_requests / batch
    return dict(
        batch=batch, buckets=buckets, lookahead=lookahead,
        mean_requests_per_bucket=mean,
        per_bucket_exhaustion_probability=bucket_tail,
        batch_any_miss_probability_upper_bound=min(1., buckets * bucket_tail),
        expected_miss_requests=miss_requests,
        expected_miss_fraction=miss_fraction,
        expected_hit_fraction=1. - miss_fraction,
        maximum_hit_fraction_from_capacity=min(1., buckets * lookahead / batch))


def choose_lookahead(batch, buckets, any_miss_budget):
    """Smallest w with m Pr[Bin(B,1/m)>w] <= a table-level budget."""
    if not isfinite(any_miss_budget) or not 0 < any_miss_budget < 1:
        raise ValueError('any_miss_budget must lie strictly between zero and one')
    # Validate the integer dimensions before using scipy or binary search.
    lookahead_statistics(batch, buckets, 0)
    lower, upper = -1, batch
    while upper - lower > 1:
        middle = (lower + upper) // 2
        tail = buckets * float(binom.sf(middle, batch, 1. / buckets))
        if tail <= any_miss_budget:
            upper = middle
        else:
            lower = middle
    return upper


def _plan(c, cutoff_log, widths, mode, any_miss_budget=None):
    _nonnegative_int(cutoff_log, 'cutoff_log')
    batch, z = c['batch'], c['child_z']
    _nonnegative_int(batch, 'batch')
    _nonnegative_int(z, 'child_z')
    if batch == 0 or z == 0:
        raise ValueError('batch and child_z must be positive')
    selected = [row for row in c['rows'] if row['log_capacity'] <= cutoff_log]
    bucket_gc = GC_BYTES_PER_AND * BUCKET_ANDS_PER_SLOT * z
    rows = []
    for row, width in zip(selected, widths):
        n = row['capacity']
        if (2 * n) % z:
            raise ValueError('a cached table must contain an integer bucket count')
        buckets = 2 * n // z
        stash = row['global_stash']['capacity']
        top = bool(row['top'])
        weight = 1. if top else .5
        interval = row['accesses_per_rebuild']
        stats = lookahead_statistics(batch, buckets, width)
        queue = buckets * width * bucket_gc
        work = weight * bucket_gc
        # Maintaining a full queue right until retirement leaves w unused
        # versions per bucket. Public remaining-lifetime refill suppression
        # could reduce this allowance, but is not modeled here.
        waste = queue / interval
        # A public retirement schedule allows skipping refill after the last
        # batch. At its start each bucket has w versions; unused inventory is
        # (w-X)+. This policy still refills between earlier batches.
        final_unused = max(0., width-stats['mean_requests_per_bucket']
                           +stats['expected_miss_requests']/buckets)
        drain_waste = buckets*final_unused*bucket_gc/interval
        rows.append(dict(
            log_capacity=row['log_capacity'], capacity=n, top=top,
            average_occupied_weight=weight, accesses_per_rebuild=interval,
            global_stash_slots=stash, bucket_gc_bytes=bucket_gc,
            persistent_state_ram_bytes_per_party=(2 * n + stash) * STATE_BYTES_PER_SLOT,
            gc_queue_ram_bytes_evaluator=queue,
            one_batch_stash_gc_bytes=batch * GC_BYTES_PER_AND * BUCKET_ANDS_PER_SLOT * stash,
            one_batch_prf_gc_bytes_optional=batch * GC_BYTES_PER_AND * prf_ands(row),
            one_batch_dummy_input_material_bytes=batch*sum(inputs(row)),
            cached_bucket_gc_work_bytes_per_query=work,
            full_window_retirement_waste_bytes_per_query=waste,
            skip_final_refill_waste_bytes_per_query=drain_waste,
            full_window_waste_to_cached_work_ratio=waste / work,
            **stats))
    if len(rows) != len(selected):
        raise ValueError('each selected table needs exactly one lookahead width')

    summed = (
        'persistent_state_ram_bytes_per_party',
        'gc_queue_ram_bytes_evaluator',
        'one_batch_stash_gc_bytes',
        'one_batch_prf_gc_bytes_optional',
        'one_batch_dummy_input_material_bytes',
        'cached_bucket_gc_work_bytes_per_query',
        'full_window_retirement_waste_bytes_per_query',
        'skip_final_refill_waste_bytes_per_query')
    result = {key: sum(row[key] for row in rows) for key in summed}
    weight_sum = sum(row['average_occupied_weight'] for row in rows)
    expected_misses = sum(row['average_occupied_weight'] * row['expected_miss_fraction']
                          for row in rows)
    tail_bound = min(1., sum(row['batch_any_miss_probability_upper_bound'] for row in rows))
    result.update(
        mode=mode, log_records=c['log_records'], batch=batch, child_z=z,
        cutoff_log=cutoff_log, cached_level_count=len(rows),
        bucket_gc_bytes=bucket_gc,
        expected_cached_table_visits_per_query=weight_sum,
        expected_missing_circuits_per_query=expected_misses,
        expected_miss_fraction=expected_misses / weight_sum if weight_sum else 0.,
        expected_hit_fraction=1. - expected_misses / weight_sum if weight_sum else 1.,
        batch_any_miss_probability_upper_bound=tail_bound,
        # Conservative union over all selected tables simultaneously; the
        # binary hierarchy does not actually keep all lower levels occupied.
        tail_bound_uses_all_selected_levels=True,
        adaptive_batch_any_miss_budget=any_miss_budget,
        rows=rows,
        assumptions=dict(
            cache='Distinct single-use bucket GC versions, evaluator-side',
            addresses='Conditional iid uniform bucket draws in each occupied table after request deduplication',
            cache_miss_is_performance_only=True,
            ram_reserves_all_selected_levels_simultaneously=True,
            retire_policy='Full-window upper allowance and skip-final-batch-refill alternative; more adaptive draining omitted',
            omitted=['dynamic OT', 'state and input-label interface proof',
                     'fresh-version chaining proof', 'initial cache fill and setup',
                     'application computation', 'GC buffers for other levels']))
    result['evaluator_ram_bytes_without_optional_prf'] = (
        result['persistent_state_ram_bytes_per_party']
        + result['gc_queue_ram_bytes_evaluator']
        + result['one_batch_stash_gc_bytes'])
    result['evaluator_ram_bytes_with_optional_prf'] = (
        result['evaluator_ram_bytes_without_optional_prf']
        + result['one_batch_prf_gc_bytes_optional']
        + result['one_batch_dummy_input_material_bytes'])
    result['bucket_prefetch_traffic_bytes_per_query_including_full_window_waste'] = (
        result['cached_bucket_gc_work_bytes_per_query']
        + result['full_window_retirement_waste_bytes_per_query'])
    return result


def cache_plan(c, cutoff_log=16, lookahead=4):
    """Reserve the same fresh-version lookahead at every selected bucket."""
    _nonnegative_int(lookahead, 'lookahead')
    selected = [row for row in c['rows'] if row['log_capacity'] <= cutoff_log]
    result = _plan(c, cutoff_log, [lookahead] * len(selected), 'uniform')
    result['lookahead'] = lookahead
    return result


def adaptive_plan(c, cutoff_log=16, any_miss_budget=1e-3):
    """Choose per-table w for a union-bound batch cache-miss budget.

    Every selected level receives the same share of the budget. These widths
    bound a single batch starting with full queues. They do not guarantee a
    service rate: versions consumed during a batch still require replenishing.
    """
    if not isfinite(any_miss_budget) or not 0 < any_miss_budget < 1:
        raise ValueError('any_miss_budget must lie strictly between zero and one')
    selected = [row for row in c['rows'] if row['log_capacity'] <= cutoff_log]
    table_budget = any_miss_budget / len(selected) if selected else any_miss_budget
    widths = [choose_lookahead(c['batch'], 2 * row['capacity'] // c['child_z'], table_budget)
              for row in selected]
    result = _plan(c, cutoff_log, widths, 'adaptive', any_miss_budget)
    result['per_table_any_miss_budget'] = table_budget
    return result
