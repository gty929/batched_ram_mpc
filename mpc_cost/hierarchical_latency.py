"""Conditional ready-state latency for the hierarchical AWS transfer model.

CPU is omitted. A worker count means the workers that a ready batch may use,
not automatically every worker in a deployment. Rebuild pauses, admission
queueing, replica consistency, client transport, and application evaluation
are outside this function. No number here is an AWS latency measurement.
"""
from math import isfinite, log2

from .hierarchical_cache import adaptive_plan, cache_plan
from .hierarchical_throughput import Deployment, directions
from .hierarchical_address import auxiliary, read_ands, inputs, scheme


def ready_latency(c, foreground_workers, cache_all_aux=False,
                  cold_prefetch=False, rtt=.0002, ebs_fixed=.001,
                  intraparty_remote_fraction=0.):
    """Estimate an occupied-level-weighted batch service time, in seconds.

    One stage can overlap NIC transfer, DRAM loading, and EBS loading. The
    fixed EBS allowance is inside that maximum, not added to a network stage
    which already hides it. Cold state/GC reads within one table are assumed
    parallel; one EBS wave per table is an optimistic scheduling assumption.

    Fresh equality circuits for capacities <=2^16 use the adaptive RAM
    queues. Stash and PRF circuits for those tables are ready in RAM. With
    cache_all_aux, one batch of stash/PRF circuits and stash state for every
    table is resident. cold_prefetch adds four equality versions per cold
    bucket on EBS. Cache refill remains in throughput/cost, not ready latency.

    Packed read selections are deferred until all metadata reads finish,
    then run as one batched OT layer. Segmented propagation uses a <=3B-work
    up/down tree with <=2log2(B)+1 layers. Inverse bitonic routing adds
    log2(B)(log2(B)+1)/2 layers. Each layer is assigned one RTT-equivalent
    scheduling allowance; this is not a proof of cryptographic round count.
    """
    if (isinstance(foreground_workers, bool)
            or not isinstance(foreground_workers, int)
            or foreground_workers < 1):
        raise ValueError('foreground_workers must be a positive integer')
    if not all(isfinite(x) and x >= 0 for x in (rtt, ebs_fixed)):
        raise ValueError('RTT and fixed EBS delay must be nonnegative')
    if not isfinite(intraparty_remote_fraction) or not 0 <= intraparty_remote_fraction <= 1:
        raise ValueError('intraparty_remote_fraction must be between zero and one')
    b = c['batch']
    if b < 512 or b & (b - 1):
        raise ValueError('This ledger audits power-of-two batches >=512')
    dep = Deployment()
    workers = foreground_workers
    nic = workers * dep.nic_active
    ebs = workers * dep.ebs_raw * dep.ebs_efficiency
    dram = workers * 56e9  # Explicit active-rate proxy, not an AWS guarantee.
    factor = 127 / 134
    d = directions(c)
    hot = adaptive_plan(c, cutoff_log=16)
    hot_rows = {x['log_capacity']: x for x in hot['rows']}
    cold_rows = {}
    if cold_prefetch:
        cold_rows = {x['log_capacity']: x
                     for x in cache_plan(c, c['log_records'], 4)['rows']
                     if x['log_capacity'] > 16}

    k = int(log2(b))
    front_products = k * (k + 1) / 4 + 3 * (b - 1) / b
    front_gc = 32 * (10240 + k * (k + 1) / 4 * 511
                     + 140 * (b - 1) / b)
    # Payload propagation/routing runs at the end. Its bytes are taken out
    # here, then charged exactly once in the final packed transfer stage.
    front_forward = d['frontend_forward'] - 80 * front_products
    front_reverse = d['frontend_backward'] - 80 * front_products
    front_net = dep.framing * b * max(front_forward, front_reverse) / nic
    front_ram = 2 * b * front_gc / dram
    front_service = max(front_net, front_ram)
    rows = []
    dynamic_f = front_forward
    dynamic_r = front_reverse
    cached_gc_total = 0.
    cached_input_f = cached_input_r = 0.
    gc_disk_reads = 0.
    cold_state_bytes = 0.
    bridge_bytes = 0.
    intraparty_direction = 0.
    cold_waste = 0.
    aux_extra_ram = 0.
    aux_extra_state_ram = 0.
    aux_extra_input_ram = 0.
    cold_any_miss = 0.

    for row, direction in zip(c['rows'], d['rows']):
        nlog = row['log_capacity']
        is_hot = nlog in hot_rows
        weight = 1. if row['top'] else .5
        stash = row['global_stash']['capacity']
        slots = row['read_slots']
        material = auxiliary(row)
        aux = material['gc']
        aux_cached = is_hot or cache_all_aux
        equality_gc_cached = 0.
        if is_hot:
            cr = hot_rows[nlog]
            equality_gc_cached = factor * cr['bucket_gc_bytes'] * cr['expected_hit_fraction']
        elif cold_prefetch:
            cr = cold_rows[nlog]
            equality_gc_cached = factor * cr['bucket_gc_bytes'] * cr['expected_hit_fraction']
            cold_waste += factor * cr['skip_final_refill_waste_bytes_per_query']
            cold_any_miss += cr['batch_any_miss_probability_upper_bound']
        cached = equality_gc_cached + (aux if aux_cached else 0.)
        input_f,input_r = inputs(row)
        cached_f = input_f if aux_cached else 0.
        cached_r = input_r if aux_cached else 0.
        # Reserve two 128-wire common-Delta XOR translations (2048 B each):
        # the PRF/stash query lane and selected bucket equality lane. A cold
        # stage without a bucket cache needs at most the first port.
        bridge = 4096 if (is_hot or cold_prefetch or cache_all_aux) else 0
        online_forward = direction['read_forward'] - 80 * slots - cached - cached_f + bridge
        online_reverse = direction['read_backward'] - 80 * slots - cached_r
        state = 2 * 2112 * slots
        state_on_disk = 0 if is_hot else 2 * 2112 * (c['child_z'] if cache_all_aux else slots)
        # Optional owner-to-worker redistribution competes for the same NIC.
        # Half the state R+W volume is charged in each direction. These bytes
        # are same-party traffic, kept distinct from the 2PC wire ledger.
        intra = intraparty_remote_fraction * state_on_disk / 2
        online_forward += intra
        online_reverse += intra
        network = dep.framing * b * max(online_forward, online_reverse) / nic
        gc_on_disk = equality_gc_cached if (cold_prefetch and not is_hot) else 0.
        disk_seconds = b * (state_on_disk + gc_on_disk) / ebs
        has_disk = state_on_disk + gc_on_disk > 0
        # Includes one ingest and one evaluation pass for streamed GC, one
        # evaluation pass for cached GC, plus the charged state read/write.
        read_gc = 32*read_ands(c,row)
        # Conservatively retain the entire private-input transcript; an
        # implementation can discard OT messages and keep only active labels.
        ram_seconds = b * (state + 2 * read_gc - cached
                          +2*(input_f+input_r)-cached_f-cached_r) / dram
        floor = max(network, disk_seconds, ram_seconds)
        service = max(network, disk_seconds + (ebs_fixed if has_disk else 0.), ram_seconds)
        rows.append(dict(log_capacity=nlog, occupancy_weight=weight,
                         online_forward_bytes_per_visit=online_forward,
                         online_reverse_bytes_per_visit=online_reverse,
                         cached_gc_bytes_per_visit=cached,
                         cached_input_forward_bytes_per_visit=cached_f,
                         cached_input_reverse_bytes_per_visit=cached_r,
                         intraparty_each_direction_bytes_per_visit=intra,
                         state_ebs_bytes_per_visit=state_on_disk,
                         gc_ebs_bytes_per_visit=gc_on_disk,
                         network_seconds=network, ebs_bandwidth_seconds=disk_seconds,
                         dram_seconds=ram_seconds, has_ebs_stage=has_disk,
                         service_floor_seconds=floor, service_seconds=service))
        dynamic_f += weight * online_forward
        dynamic_r += weight * online_reverse
        cached_gc_total += weight * cached
        cached_input_f += weight*cached_f
        cached_input_r += weight*cached_r
        gc_disk_reads += weight * gc_on_disk
        cold_state_bytes += weight * state_on_disk
        bridge_bytes += weight * bridge
        intraparty_direction += weight * intra
        if cache_all_aux and not is_hot:
            aux_extra_ram += b * aux
            aux_extra_input_ram += b*(input_f+input_r)
            aux_extra_state_ram += 2112 * stash

    packed_products = c['read_payload_selectors_per_query'] + front_products
    packed_direction = 80 * packed_products
    packed_service = dep.framing * b * packed_direction / nic
    dynamic_f += packed_direction
    dynamic_r += packed_direction
    if abs(dynamic_r - intraparty_direction
           - (d['frontend_backward'] + d['read_backward']-cached_input_r)) > 1e-6:
        raise AssertionError('Forward/reverse payload separation lost bytes')
    before_cache = d['frontend_forward'] + d['read_forward']
    if abs(dynamic_f - intraparty_direction
           - (before_cache - cached_gc_total-cached_input_f + bridge_bytes)) > 1e-6:
        raise AssertionError('Cached/online GC traffic does not reconcile')

    mean_tables = c['average_occupied_tables']
    prefix_layers = 2 * k + 1
    inverse_layers = k * (k + 1) // 2
    # One initial input binding, one deferred read-selection layer, plus
    # level-address request stages and the two output payload networks.
    dependency_units = 2 + mean_tables + prefix_layers + inverse_layers
    floor = front_service + packed_service + sum(
        r['occupancy_weight'] * r['service_floor_seconds'] for r in rows)

    def service_at(fixed):
        return front_service + packed_service + sum(
            r['occupancy_weight'] * max(r['network_seconds'], r['dram_seconds'],
                r['ebs_bandwidth_seconds'] + (fixed if r['has_ebs_stage'] else 0.))
            for r in rows)

    service = service_at(ebs_fixed)
    fill = (b - 1) / (2 * dep.qps)
    ready = service + dependency_units * rtt
    refill_extra = factor * hot['skip_final_refill_waste_bytes_per_query']
    refill_extra += cold_waste + bridge_bytes
    expected_cold_tables = sum(r['occupancy_weight'] for r in rows if r['has_ebs_stage'])
    return dict(log_records=c['log_records'], batch=b, child_z=c['child_z'],address_scheme=scheme(c),
        foreground_workers=workers, cache_all_aux=bool(cache_all_aux),
        cold_prefetch=bool(cold_prefetch), rtt_seconds=rtt,
        ebs_fixed_seconds=ebs_fixed,
        intraparty_remote_fraction=intraparty_remote_fraction,
        intraparty_each_direction_bytes_per_query=intraparty_direction,
        read_forward_bytes_per_query=d['read_forward'],
        read_reverse_bytes_per_query=d['read_backward'],
        foreground_forward_before_cache_bytes_per_query=before_cache,
        foreground_forward_after_cache_bytes_per_query=dynamic_f,
        foreground_reverse_bytes_per_query=dynamic_r,
        foreground_crossparty_forward_after_cache_bytes_per_query=dynamic_f-intraparty_direction,
        foreground_crossparty_reverse_bytes_per_query=dynamic_r-intraparty_direction,
        packed_forward_and_reverse_each_bytes_per_query=packed_direction,
        read_packed_products_per_query=c['read_payload_selectors_per_query'],
        output_packed_products_per_query=front_products,
        cached_gc_bytes_per_query=cached_gc_total,
        cached_input_forward_bytes_per_query=cached_input_f,
        cached_input_reverse_bytes_per_query=cached_input_r,
        cached_forward_material_bytes_per_query=cached_gc_total+cached_input_f,
        bridge_bytes_per_query=bridge_bytes,
        all_aux_additional_bridge_bytes_per_query=(4096 * (mean_tables
            - hot['expected_cached_table_visits_per_query'])
            if cache_all_aux and not cold_prefetch else 0.),
        all_aux_additional_ram_bytes=aux_extra_ram + aux_extra_state_ram+aux_extra_input_ram,
        all_aux_additional_gc_ram_bytes=aux_extra_ram,
        all_aux_additional_input_ram_bytes=aux_extra_input_ram,
        all_aux_additional_state_ram_bytes=aux_extra_state_ram,
        hot_evaluator_ram_bytes=hot['evaluator_ram_bytes_with_optional_prf'],
        throughput_extra_forward_bytes_per_query=refill_extra,
        throughput_forward_bytes_per_query=d['forward'] + refill_extra,
        throughput_forward_including_foreground_redistribution_bytes_per_query=(
            d['forward'] + refill_extra + intraparty_direction),
        cold_state_ebs_bytes_per_query=cold_state_bytes,
        cold_gc_ebs_read_bytes_per_query=gc_disk_reads,
        cold_batch_any_miss_probability_upper_bound=min(1., cold_any_miss),
        frontend_service_seconds=front_service,
        packed_transfer_seconds=packed_service,
        bandwidth_loading_floor_seconds=floor,
        bandwidth_loading_service_seconds=service,
        mean_occupied_tables=mean_tables,
        max_occupied_tables=c['max_occupied_tables'],
        mean_cold_table_stages=expected_cold_tables,
        prefix_packed_layers=prefix_layers,
        inverse_bitonic_packed_layers=inverse_layers,
        dependency_rtt_equivalent_units=dependency_units,
        mean_ready_batch_service_seconds=ready,
        mean_batch_fill_seconds=fill,
        max_deterministic_arrival_fill_seconds=(b - 1) / dep.qps,
        mean_query_seconds_no_queue_or_rebuild=fill + ready,
        rtt_sensitivity=[dict(rtt_seconds=t, mean_ready_batch_service_seconds=service
            + dependency_units * t, mean_query_seconds=fill + service + dependency_units * t)
            for t in (.0001, .0002, .001)],
        ebs_fixed_sensitivity=[dict(ebs_fixed_seconds=t,
            bandwidth_loading_service_seconds=service_at(t),
            mean_query_seconds=fill + service_at(t) + dependency_units * rtt)
            for t in (0., .0005, .001, .003)],
        rows=rows,
        caveats=['Ready state and foreground priority are assumed',
                 'The offered rate is 10000 queries/s to this batch stream',
                 'Binary-counter occupancy is averaged, not a tail guarantee',
                 '56GB/s active DRAM per worker is a proxy, not a measured rate',
                 'One parallel EBS wave per table; IOPS/wave limits omitted',
                 'One RTT-equivalent per dependent packed layer is a scheduling assumption',
                 'Random OT preprocessing does not remove dependent online payload products',
                 'Query admission queues, rebuild pauses, cache warmup/misses, and replicas excluded'])
