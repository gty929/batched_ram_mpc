"""Transparent Circuit-OPRAM-inspired circuit and AWS capacity accounting.

This is a planning simulator, NOT an implementation, security proof, or measured
performance claim. Pool/eviction circuits are conservative design templates.
Costs of backend operations and actual deployment scaling require calibration.
All network byte counters count sends once; receive is a separate NIC constraint.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from math import ceil, log2, sqrt, log
import heapq
import random

GIB = 2**30
SECONDS_YEAR = 365 * 24 * 3600


def clog2(x: int) -> int:
    return (max(1, x) - 1).bit_length()


def pow2(x: int) -> int:
    return 1 << clog2(x)


def bitonic_shape(n: int) -> tuple[int, int, int]:
    """Padded items, exact compare-exchanges, parallel compare-exchange stages."""
    k = clog2(n)
    return 1 << k, (1 << k) * k * (k + 1) // 4, k * (k + 1) // 2


def decoder_shape(bits: int) -> tuple[int, int]:
    """Divide-and-conquer one-hot decoder with a secret valid input.
    The single valid multiplication is inside one recursive factor.
    """
    def pure(k: int) -> int:
        return 0 if k <= 1 else pure(k//2) + pure(k-k//2) + 2**k
    return pure(bits) + (1 if bits else 0), clog2(max(1,bits)) + (1 if bits else 0)


@dataclass
class Work:
    reductions: float = 0
    dot_outputs: float = 0
    local_products: float = 0
    random_bits: float = 0
    openings: float = 0
    phases: float = 0
    ram_bytes: float = 0
    direct_words: float = 0
    canonical_masks: float = 0  # attribution only; costs already in the other fields

    def add(self, other: Work, times: float = 1, sequential: bool = True) -> None:
        for name in ('reductions', 'dot_outputs', 'local_products', 'random_bits',
                     'openings', 'ram_bytes', 'direct_words', 'canonical_masks'):
            setattr(self, name, getattr(self, name) + getattr(other, name) * times)
        self.phases = self.phases + other.phases if sequential else max(self.phases, other.phases)

    def products(self, number: float, depth: float = 0) -> None:
        self.reductions += number
        self.local_products += 2 * number  # value and authentication-tag products
        self.phases += depth

    def dots(self, outputs: float, length: float, depth: float = 2) -> None:
        self.dot_outputs += outputs
        self.local_products += 4 * outputs * length
        self.phases += depth  # current SY-Shamir exchanges share and MAC separately


@dataclass(frozen=True)
class Design:
    records: int = 2**28
    key_bytes: int = 32
    value_bytes: int = 32
    parties: int = 10
    threshold: int = 4
    rate: int = 10_000
    batch: int = 512
    fanout: int = 16
    base_cutoff: int = 4096
    cuckoo_load_ceiling: float = 0.40
    cuckoo_stash: int = 8
    cuckoo_tables: int = 2  # always one probe to each table; independent trees in parallel
    bucket_z: int = 3
    pool_slack: int = 128
    field_bits: int = 127
    field_bytes: int = 16
    share_words: int = 2  # authenticated field value and tag
    metadata: str = 'compact'  # compact with conversion, or stored arithmetic bits
    conversion: str = 'canonical'  # exact full-field masks; no statistical truncation
    sort_cost_scale: float = 1.0  # sensitivity only, not a proven optimized compiler
    eviction_work_scale: float = 1.0  # template uncertainty
    sort_method: str = 'shuffle_quicksort'
    quicksort_depth_factor: float = 4.5  # assumed parallel height / ln(n), not tail guarantee


@dataclass(frozen=True)
class Backend:
    name: str = 'sy_shamir_source_proxy'
    reduction_words: float = 59 / 6  # 9 for value/MAC + 5/6 check randomness
    bit_words: float = 24
    opening_words: float = 8
    check_words: float = 161 / 6
    hot_party_factor: float = 1.12
    random_bit_local_products: float = 330  # source proxy ~309 plus unmeasured inversion margin
    reduction_local_overhead: float = 81  # scalar source proxy total ~83; check/interpolation included
    framing_factor: float = 1.05


@dataclass(frozen=True)
class Deployment:
    round_ms: float = 0.20
    local_products_per_sec_64vcpu: float = 2e9  # UNMEASURED weighted field-operation capacity
    ram_gbps_64vcpu: float = 40
    nic_efficiency: float = 0.65
    distributed_efficiency: float = 0.70
    utilization: float = 0.70
    memory_usable: float = 0.75
    scratch_fraction: float = 0.15
    prep_buffer_seconds: float = 0.10
    mean_latency_limit: float = 5.0
    az_fraction: float = 0.0
    transfer_usd_per_gb: float = 0.02
    billing_gb_bytes: int = 10**9
    fixed_response_ms: float = 20
    resource_overlap: bool = True
    intraparty_routing_factor: float = 1.0  # extra local-share traffic relative to circuit RAM moves


def canonical_bits(items: int, d: Design) -> Work:
    """Template for exact A2B: verified canonical random mask + modular subtraction.

    Rejection mask: field_bits random bits, acceptance product and opening.
    Modular subtraction/reduction proxy: 6*field_bits products, log-depth.
    Constants are explicit template inputs, not MP-SPDZ instruction benchmarks.
    For p=2^127-1 rejection probability is tiny; mask generation is offline.
    """
    w = Work(random_bits=items * d.field_bits, openings=2 * items, canonical_masks=items)
    w.products(items * (d.field_bits - 1 + 6 * d.field_bits))
    w.phases = 7 + 3 * clog2(d.field_bits)  # includes check before masked opening
    return w


def sort_route(items: int, key_bits: int, words: int, d: Design,
               reverse_words: int = 0, convert_items: int = 0) -> Work:
    """Bitonic: parallel-prefix comparison, swap key bits and field words.

    Comparator uses 3k-2 products, depth 1+ceil(log2 k); conditional swap
    costs k+words products and one phase. Reverse reuses secret controls.
    Sorting uses a unique (address, type, ordinal) key when stability matters.
    """
    padded, comps, stages = bitonic_shape(items)
    w = Work()
    if convert_items and d.metadata == 'compact':
        w.add(canonical_bits(convert_items, d))
    if d.sort_method == 'bitonic':
        w.products(comps * (4 * key_bits - 2 + words), stages * (2 + clog2(key_bits)))
        if reverse_words:
            w.products(comps * reverse_words, stages)
    elif d.sort_method == 'shuffle_quicksort':
        # Five separately chosen private uniform permutations: at least one
        # honest shuffler. Beneš networks; private switch inputs checked Boolean.
        # Unique (key,original-index) ranks are required before opening comparisons.
        # The inverse secret shuffle is charged on result restoration.
        shuffle_stages = max(0, 2 * clog2(padded) - 1)
        switches = (d.threshold + 1) * (padded // 2) * shuffle_stages
        w.products(switches * (words + key_bits + 1),
                   (d.threshold + 1) * shuffle_stages + 1)
        w.direct_words += 5 * switches  # explicit private-input/authentication proxy
        w.local_products += 100 * switches
        harmonic = log(padded) + 0.5772156649015329 + 1/(2*padded)
        compares = max(0, 2 * (padded + 1) * harmonic - 4 * padded)
        w.products(compares * (3 * key_bits - 2),
                   ceil(d.quicksort_depth_factor * log(max(2,padded))) * (6 + clog2(key_bits)) + 4)
        w.openings += compares
        if reverse_words:
            w.products(switches * reverse_words, (d.threshold + 1) * shuffle_stages)
        comps = switches + compares
    else:
        raise ValueError('Unknown sort method')
    w.ram_bytes += 4 * comps * (key_bits + words + reverse_words) * d.field_bytes * d.share_words
    if d.sort_cost_scale != 1:
        for name in ('reductions', 'dot_outputs', 'local_products', 'random_bits', 'openings', 'phases', 'ram_bytes', 'direct_words', 'canonical_masks'):
            setattr(w, name, getattr(w, name) * d.sort_cost_scale)
    return w


def base_access(cells: int, requests: int, d: Design) -> tuple[Work, str]:
    """Compare one-hot dot read/write against a sort/scan/inverse-route template.

    Conflict resolution is charged at every recursive transition elsewhere.
    One-hot uses power-of-two padding. Updates aggregate deltas per cell.
    Sort alternative charges full sort, segmented scan and reverse routing.
    Selection minimizes communication proxy, not just online products.
    """
    k, b = pow2(cells), requests
    one = Work()
    decoder_count, decoder_depth = decoder_shape(clog2(k))
    one.products(b * decoder_count, decoder_depth)
    one.dots(b, k)
    one.dots(k, b + 1)
    one.ram_bytes = 6 * b * k * d.field_bytes * d.share_words
    join = sort_route(k + b, clog2(k) + clog2(b) + 2, 5, d, reverse_words=2)
    # segmented overwrite/forward propagation and reverse segmented final-value pass
    join.products(12 * (k + b), 4 * clog2(k + b))
    def score(w: Work) -> float:
        return (w.reductions + w.dot_outputs) * (59/6) + w.random_bits * 24 + w.openings * 8
    return (one, 'one_hot_dot') if score(one) <= score(join) else (join, 'sort_scan')


def level_cost(records: int, payload: int, b: int, d: Design) -> tuple[Work, dict]:
    """Circuit OPRAM template: flattened top tree, private pool operations,
    public batch fetch paths, 2b disjoint-subtree deterministic evictions.

    Each pool phase is separately charged. No random path-union discount is used.
    Exact stash constants and this compilation require proof/implementation QA.
    """
    h = clog2(records)
    top = clog2(2 * b)
    if 2*b > pow2(records):
        raise ValueError('Batch exceeds tree regime; use a flat database or reduce batch.')
    lower = max(0, h - top + 1)
    pool = d.bucket_z * ((1 << top) - 1) + d.pool_slack
    addr = max(1, h)
    full = payload + (2 * h + 1 if d.metadata == 'bits' else 3)
    total = Work()
    # Dedup by logical address, private fanout, one representative per group.
    total.add(sort_route(b, addr + clog2(b) + 1, 4, d, reverse_words=payload))
    total.products((8 + 2*addr - 1) * b + b * payload, 4 * clog2(b) + 1 + clog2(addr))
    # Initial tree retrieval has b paths; all path slots tested, dot outputs.
    fetch_slots = b * d.bucket_z * lower
    if d.metadata == 'compact':
        total.add(canonical_bits(fetch_slots, d))
    total.products(fetch_slots * (2 * addr), clog2(addr) + 2)
    total.dots(b * full, max(1, d.bucket_z * lower))
    total.products(fetch_slots, 1)  # invalidate selected slots
    # Oblivious pool lookup/clear, eviction selection, and cleanup are distinct.
    phases = [
        ('pool_fetch', pool + b, addr + clog2(pool + b) + 2, full + 2, payload),
        # 2b public-subtree sentinel requests plus b newly fetched records:
        # inverse-route selected FULL records to the public subtree destinations.
        ('eviction_select', pool + 3*b, max(1, top) + clog2(h + 1) + clog2(pool + 3*b) + 2, full + 3, full),
        ('pool_cleanup', pool + 3*b, 1 + clog2(pool + 3*b), full + 2, 0),
    ]
    breakdown = {}
    for name, count, kb, words, reverse in phases:
        piece = sort_route(count, kb, words, d, reverse_words=reverse,
                           convert_items=pool if name in ('pool_fetch','eviction_select') else 0)
        piece.products((8 + 2 * full) * count, 4 * clog2(count))  # group propagation
        # Unique augmented sort keys hide ties, so unaugmented group equality
        # must still be computed SECRETLY at its actual bit width.
        group_bits = addr if name == 'pool_fetch' else max(1, top) if name == 'eviction_select' else 1
        piece.products((count - 1) * (2*group_bits - 1), 1 + clog2(group_bits))
        total.add(piece)
        breakdown[name] = asdict(piece)
    # 2b disjoint paths. Prefix eligibility, bucket winner, parallel path planner,
    # and prefix payload propagation. Work-efficient scan: <2L combines, depth2logL.
    paths = 2 * b
    slots = paths * d.bucket_z * lower
    ev = Work()
    if d.metadata == 'compact':
        ev.add(canonical_bits(2 * slots, d))  # addresses and leaf labels
    ev.products(2 * slots * max(0, h - 1), 2 * clog2(max(1, h)))
    depth_bits = max(1, clog2(h + 1))
    ev.products(paths * lower * (d.bucket_z - 1) * (4 * depth_bits + 2),
                clog2(d.bucket_z) * (clog2(depth_bits) + 2))
    # Conservative explicit planner coefficient; sensitivity exposed.
    ev.products(paths * 8 * max(1, lower) * (4 * depth_bits + 4),
                6 * clog2(max(1, lower)) * (clog2(depth_bits) + 2))
    ev.products(paths * (2 * d.bucket_z + 4) * max(1, lower) * full,
                4 * clog2(max(1, lower)) + 4)
    for name in ('reductions', 'dot_outputs', 'local_products', 'random_bits', 'openings', 'ram_bytes', 'canonical_masks'):
        setattr(ev, name, getattr(ev, name) * d.eviction_work_scale)
    total.add(ev)
    total.ram_bytes += 4 * (fetch_slots + slots + pool) * full * d.field_bytes * d.share_words
    # Fresh leaf labels sampled as authenticated bits; rejection unnecessary for 2^h.
    total.random_bits += b * h
    total.openings += b  # next public physical paths
    total.phases += 5  # checked opening barrier before access-pattern release
    meta_stored = 2 * h + 1 if d.metadata == 'bits' else 3
    tree_bytes = d.bucket_z * (2 * pow2(records) - (1 << top)) * (payload + meta_stored) * d.field_bytes * d.share_words
    pool_bytes = pool * (payload + 2 * h + 1) * d.field_bytes * d.share_words
    return total, dict(records=records, payload_words=payload, height=h,
                      lower_path_levels=lower, pool_records=pool,
                      tree_bytes=tree_bytes, pool_bytes=pool_bytes, work=asdict(total),
                      pool_phases=breakdown)


def circuit(d: Design) -> dict:
    if d.parties != 10 or d.threshold != 4:
        raise ValueError('Source-derived backend constants require n=10,t=4.')
    if d.field_bits != 127 or d.field_bytes != 16:
        raise ValueError('Default bit preprocessing proxy is specific to p=2^127-1.')
    if d.batch < 1 or d.fanout < 2 or d.base_cutoff < 1:
        raise ValueError('Invalid batch, fanout or base cutoff.')
    if d.fanout != pow2(d.fanout) or d.batch != pow2(d.batch):
        raise ValueError('This circuit template requires power-of-two fanout/batch.')
    if not 0 < d.cuckoo_load_ceiling < .5:
        raise ValueError('Two-choice single-slot cuckoo must use slack below 0.5.')
    if d.cuckoo_tables not in (1, 2):
        raise ValueError('Choose one two-probe table or two one-probe tables.')
    b = 2 * d.batch // d.cuckoo_tables
    slots = pow2(ceil(d.records / d.cuckoo_load_ceiling))
    key_words = ceil(8 * d.key_bytes / (d.field_bits - 1))
    value_words = ceil(8 * d.value_bytes / (d.field_bits - 1))
    payload = key_words + value_words
    w = Work()
    levels = []
    n = slots // d.cuckoo_tables
    # n is the number of labels in the position map for this tree. Stop BEFORE
    # creating another tree; its flat base has n scalar labels, not n/fanout.
    while True:
        piece, info = level_cost(n, payload, b, d)
        levels.append(info)
        w.add(piece)
        if n <= d.base_cutoff:
            break
        parent = ceil(n / d.fanout)
        # If another OPRAM would have fewer than 2b leaves, use flat current map.
        if parent < 2*b:
            break
        # Select child label, replace offsets, privately coalesce distinct offsets.
        sub = Work()
        dc, dd = decoder_shape(clog2(d.fanout))
        sub.products(b * dc, dd)
        sub.dots(b, d.fanout)
        sub.products(3 * b * d.fanout, 2 + 2 * clog2(b))
        w.add(sub)
        n, payload = parent, d.fanout
    base, base_method = base_access(n, b, d)
    w.add(base)
    # Independent cuckoo tables execute in parallel, so multiply work and memory,
    # but not dependent phases. Their ORAM states are independent.
    for name in ('reductions','dot_outputs','local_products','random_bits','openings','ram_bytes','direct_words','canonical_masks'):
        setattr(w, name, getattr(w, name) * d.cuckoo_tables)
    # Full exact key checks for two candidates and the always-scanned cuckoo stash.
    # Fermat equality: A_k=x^(2^k-1), chain1,2,3,6,7,14,28,56,63,126.
    # 125 squarings+9 combines+one final square =135; no random mask.
    eq_count = (2 + d.cuckoo_stash) * d.batch * key_words
    w.products(eq_count * 135, 135)
    w.products((2 + d.cuckoo_stash) * d.batch * (key_words - 1), clog2(key_words))
    w.dots(d.batch * value_words, 2 + d.cuckoo_stash)
    # Secret key/index input validity/authentication is conservatively budgeted;
    # client supplies public-hash indices, so no unselected PRF is assumed free.
    w.products(d.batch * (256 + 2 * clog2(slots)), 2)
    # Output check barrier and output release; preprocessing checks separate.
    w.phases += 5
    state = d.cuckoo_tables * (sum(x['tree_bytes'] + x['pool_bytes'] for x in levels)
                              + n * d.field_bytes * d.share_words)
    state += d.cuckoo_stash * (key_words + value_words) * d.field_bytes * d.share_words
    return dict(design=asdict(d), actual_cuckoo_load=d.records/slots,
                dense_cells=slots, levels=levels, base_cells=n, base_method=base_method,
                base_work=asdict(base), work=asdict(w), state_bytes_party=state,
                caveat='Derived circuit template and unmeasured deployment; not an implementation benchmark.')


def traffic(c: dict, backend: Backend = Backend()) -> dict:
    w = c['work']; d = c['design']
    outputs = w['reductions'] + w['dot_outputs']
    checks = max(1, ceil((outputs + 2*w['random_bits']) / 1_000_000))
    words = outputs * backend.reduction_words + w['random_bits'] * backend.bit_words
    words += w['openings'] * backend.opening_words + checks * backend.check_words + w['direct_words']
    sent = words * d['field_bytes'] * backend.framing_factor
    cpu = w['local_products'] + w['random_bits'] * backend.random_bit_local_products
    cpu += outputs * backend.reduction_local_overhead
    cpu += 35 * w['openings']
    # Wire words also entail encoding/interpolation; throughput calibration must
    # include these or reduction_local_overhead must be raised.
    return dict(sent_bytes_party_batch=sent, hottest_sent_bytes_batch=sent * backend.hot_party_factor,
                local_products_party_batch=cpu, checks=checks)


def provision(c: dict, sku: dict, nodes_per_party: int,
              dep: Deployment = Deployment(), backend: Backend = Backend()) -> dict | None:
    t = traffic(c, backend)
    d = c['design']; w = c['work']; k = nodes_per_party
    scale = 1 if k == 1 else k * dep.distributed_efficiency
    nic = sku['network_gbps'] * 1e9 / 8 * dep.nic_efficiency * scale
    cpu = dep.local_products_per_sec_64vcpu * sku['vcpu'] / 64 * scale
    ram = dep.ram_gbps_64vcpu * 1e9 * sku['vcpu'] / 64 * scale
    intra = w['ram_bytes'] * dep.intraparty_routing_factor if k > 1 else 0
    network_s = (t['hottest_sent_bytes_batch'] + intra) / nic
    cpu_s = t['local_products_party_batch'] / cpu
    ram_s = w['ram_bytes'] / ram
    rounds_s = w['phases'] * dep.round_ms / 1000
    resource_s = max(network_s, cpu_s, ram_s) if dep.resource_overlap else network_s + cpu_s + ram_s
    service = rounds_s + resource_s
    # Complete batch state/scratch plus short refillable preprocessing reserve.
    buffer = t['sent_bytes_party_batch'] / max(service, 1e-9) * dep.prep_buffer_seconds
    memory = c['state_bytes_party'] * (1 + dep.scratch_fraction) + buffer
    if memory > k * sku['memory_gib'] * GIB * dep.memory_usable:
        return None
    replicas = max(1, ceil(d['rate'] * service / (d['batch'] * dep.utilization)))
    mean = service + (d['batch'] - 1) / (2 * d['rate']) + dep.fixed_response_ms / 1000
    compute = replicas * k * d['parties'] * sku['hourly_usd'] * 8760
    bytes_year = t['sent_bytes_party_batch'] / d['batch'] * d['rate'] * d['parties'] * SECONDS_YEAR
    transfer = bytes_year / dep.billing_gb_bytes * dep.az_fraction * dep.transfer_usd_per_gb
    return dict(instance=sku['name'], batch=d['batch'], fanout=d['fanout'], cutoff=d['base_cutoff'],
                metadata=d['metadata'], sort_method=d['sort_method'], base_cells=c['base_cells'], base_method=c['base_method'],
                levels=len(c['levels']), nodes_per_party_per_replica=k, replicas=replicas,
                total_instances=replicas*k*d['parties'],
                aggregate_capacity_qps=replicas*d['batch']/service,
                service_seconds=service, model_mean_seconds=mean,
                meets_mean_limit=mean<=dep.mean_latency_limit,
                network_seconds=network_s,cpu_seconds=cpu_s,ram_seconds=ram_s,round_seconds=rounds_s,
                phases=w['phases'], reductions_per_read=(w['reductions']+w['dot_outputs'])/d['batch'],
                random_bits_per_read=w['random_bits']/d['batch'],
                sent_mb_per_party_read=t['sent_bytes_party_batch']/d['batch']/1e6,
                state_gib_per_party_per_replica=c['state_bytes_party']/GIB,
                memory_required_gib_per_party_per_replica=memory/GIB,
                compute_usd_year=compute, transfer_usd_year=transfer, total_usd_year=compute+transfer,
                usd_per_million=(compute+transfer)/(d['rate']*SECONDS_YEAR)*1e6)


def queue_simulation(batch: int, rate: float, service: float, replicas: int,
                     batches: int = 4000, seed: int = 20261012,
                     service_cv: float = .05, response_seconds: float = .02) -> dict:
    """Poisson arrivals, central full batches, first-free replica, lognormal service.
    No trace is available: this is a stated workload scenario, not an SLA forecast.
    Gamma order-statistic trick computes representative first/middle/last arrivals
    exactly in distribution; for actual latency quantiles generate every arrival.
    """
    rng = random.Random(seed)
    available = [0.] * replicas
    clock = 0.; samples = []; queues=[]
    sigma = sqrt(__import__('math').log(1 + service_cv**2))
    for i in range(batches):
        arrivals=[]
        for _ in range(batch):
            clock += rng.expovariate(rate)
            arrivals.append(clock)
        ready = heapq.heappop(available)
        start = max(clock, ready)
        duration = service * rng.lognormvariate(-sigma*sigma/2, sigma)
        end = start + duration
        heapq.heappush(available, end)
        if i >= min(500, batches//4):
            # Sample at most 32 actual queries per batch to bound memory.
            samples.extend(end - arrivals[j] + response_seconds for j in rng.sample(range(batch), min(32,batch)))
            queues.append(start-clock)
    samples.sort()
    return dict(mean_seconds=sum(samples)/len(samples),p95_seconds=samples[int(.95*(len(samples)-1))],
                p99_seconds=samples[int(.99*(len(samples)-1))],
                mean_dispatch_queue_seconds=sum(queues)/len(queues),
                assumptions='Poisson arrivals; central full batches; lognormal service CV=.05; no network tail/failure model.')
