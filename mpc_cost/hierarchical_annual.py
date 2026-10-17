"""Annual AWS budget for the explicitly scheduled hierarchical construction.

Prices are official us-east-1 Linux On-Demand/gp3 rows. This is a resource
projection, not a measured service or an optimized AWS purchasing plan.
Workers are shared across independent states; only storage/cache reservations
scale directly with the number of states. Both 2PC parties are charged.
"""
from math import ceil
from pathlib import Path
import json

from .hierarchical_cache import adaptive_plan, cache_plan
from .hierarchical_latency import ready_latency
from .hierarchical_address import current_case, scheme, SCHEME, LEGACY

ROOT = Path(__file__).resolve().parent
GIB = 2**30
MIB = 2**20


def prices():
    data = json.loads((ROOT/'data/aws_hierarchical_prices_2026-10-17.json').read_text())
    byunit = {r['Unit']: float(r['PricePerUnit']) for r in data['selected_rows']}
    return dict(instance_hour=byunit['Hrs'], capacity_gib_month=byunit['GB-Mo'],
                throughput_mib_second_month=byunit['GiBps-mo']/1024,
                iops_month=byunit['IOPS-Mo'], source=data['source_url'],
                access_date=data['access_date'])


def role_budget(workers, required_bytes, volumes_per_worker=8,
                raw_ebs_bytes_second=12.5e9, io_bytes=65536):
    """Provision full instance EBS bandwidth, with an explicit volume policy.

    Actual service applies 65% EBS efficiency elsewhere; full raw bandwidth is
    purchased here, avoiding a burst schedule backed only by average I/O billing.
    Each role has its own volumes. Logical striped/shared access is modeled by
    intra-party bytes, not by assuming gp3 can be multi-attached across hosts.
    """
    if workers < 1 or required_bytes < 0 or not 1 <= volumes_per_worker <= 25:
        raise ValueError('Invalid fleet, capacity, or attachment count')
    p = prices()
    v = workers*volumes_per_worker
    throughput = max(125, ceil(raw_ebs_bytes_second/(volumes_per_worker*MIB)))
    iops = max(3000, ceil(raw_ebs_bytes_second/(volumes_per_worker*io_bytes)),
               4*throughput)
    gib = max(1, ceil(required_bytes/(v*GIB)), ceil(iops/500) if iops > 3000 else 1)
    if throughput > 2000 or iops > 80000 or gib > 65536:
        raise ValueError('The requested gp3 provisioning exceeds a volume limit')
    ec2 = workers*8760*p['instance_hour']
    capacity = v*gib*12*p['capacity_gib_month']
    tp = v*(throughput-125)*12*p['throughput_mib_second_month']
    io = v*(iops-3000)*12*p['iops_month']
    return dict(workers=workers, volumes=v, volumes_per_worker=volumes_per_worker,
                required_bytes=required_bytes, provisioned_gib=v*gib,
                gib_per_volume=gib, throughput_mib_second_per_volume=throughput,
                iops_per_volume=iops, provisioned_raw_ebs_bytes_second_per_worker=
                throughput*MIB*volumes_per_worker,
                assumed_io_bytes=io_bytes, ec2_year=ec2, capacity_year=capacity,
                throughput_year=tp, iops_year=io, io_year=tp+io,
                total_year=ec2+capacity+tp+io)


def annual_case(c, schedule, volumes_per_worker=8, scratch_multiplier=1.25,
                cold_prefetch=False):
    """Budget the saved schedule; a sensitivity never claims a new schedule."""
    if schedule.get('address_scheme',LEGACY)!=scheme(c):
        raise ValueError('Schedule and cost case use different address protocols; rerun the schedule')
    states = schedule['replicas']
    workers = schedule['total_workers_per_party']
    n = 1 << c['log_records']
    tag_bits = c['rows'][-1]['parent_routing_stages'] + c['local_refinement']['suffix_bits']
    tagged_record = 2112 + 16*tag_bits
    scratch_array = 4*n*tagged_record
    scratch = scratch_multiplier*scratch_array
    persistent = c['packed_state_bytes_per_party']
    cold_bytes = 0.
    if cold_prefetch:
        cold_bytes = sum(r['gc_queue_ram_bytes_evaluator']*127/134
            for r in cache_plan(c, c['log_records'], 4)['rows'] if r['log_capacity'] > 16)
    g = role_budget(workers, states*(persistent+scratch), volumes_per_worker)
    e = role_budget(workers, states*(persistent+scratch+cold_bytes), volumes_per_worker)
    hot = adaptive_plan(c, cutoff_log=16)
    latency = ready_latency(c, schedule['foreground_workers_per_party'],
        cache_all_aux=schedule['preload_all_stash_prf'], cold_prefetch=cold_prefetch,
        rtt=schedule['rtt_seconds'], ebs_fixed=schedule['cold_bucket_load_seconds'],
        intraparty_remote_fraction=schedule['intraparty_remote_fraction'])
    total = g['total_year']+e['total_year']
    qps = schedule.get('qps', 10000)
    return dict(log_records=c['log_records'], batch=c['batch'], states=states,address_scheme=scheme(c),
        workers_per_party=workers, total_workers=2*workers,
        foreground_workers_per_party=schedule['foreground_workers_per_party'],
        background_workers_per_party=schedule['background_workers_per_party'],
        persistent_bytes_per_state_per_party=persistent,
        scratch_array_bytes_per_state_per_party=scratch_array,
        scratch_multiplier=scratch_multiplier, scratch_bytes_per_state_per_party=scratch,
        cold_gc_bytes_per_state_evaluator=cold_bytes,
        hot_cache_bytes_evaluator_per_state=hot['evaluator_ram_bytes_with_optional_prf'],
        all_aux_extra_bytes_evaluator_per_state=latency['all_aux_additional_ram_bytes'],
        reserved_cache_bytes_all_evaluators=states*(hot['evaluator_ram_bytes_with_optional_prf']
            +latency['all_aux_additional_ram_bytes']),
        usable_dram_bytes_per_party=workers*256*GIB*.75,
        garbler=g,evaluator=e, ec2_year=g['ec2_year']+e['ec2_year'],
        ebs_capacity_year=g['capacity_year']+e['capacity_year'],
        ebs_io_year=g['io_year']+e['io_year'], total_year=total,
        qps=qps, queries_per_year=qps*365*24*3600,
        dollars_per_million_queries=total/(qps*365*24*3600)*1e6,
        ready_latency=latency, schedule=schedule,
        caveat='Conditional resource projection; scratch is a reservation policy, not a proven live-set bound.')


def main():
    cases=json.loads((ROOT/'results/hierarchical_split_comparison.json').read_text())['batch_sweep']
    cases={(c['log_records'],c['batch']): current_case(c) for c in cases if c['child_z']==64}
    schedules=json.loads((ROOT/'results/hierarchical_schedule.json').read_text())
    out=[]
    for schedule in schedules:
        c=cases[schedule['log_records'],schedule['batch']]
        r=annual_case(c,schedule)
        r['volume_policy_25_total_year']=annual_case(c,schedule,volumes_per_worker=25)['total_year']
        r['scratch_zero_total_year']=annual_case(c,schedule,scratch_multiplier=0)['total_year']
        cold=annual_case(c,schedule,cold_prefetch=True)
        r['cold_prefetch_fixed_fleet_total_year']=cold['total_year']
        r['cold_prefetch_extra_capacity_year']=cold['ebs_capacity_year']-r['ebs_capacity_year']
        r['cold_prefetch_ready_latency']=cold['ready_latency']
        out.append(r)
    result=dict(prices=prices(),primary=out,address_scheme=SCHEME,
        policy=dict(region='us-east-1',same_az_private_traffic=True,
                    cpu_ignored=True,volumes_per_worker=8,
                    state_scratch_policy='1.25 times one 4N-slot tagged array per independent state',
                    annualized_steady_state=True))
    result['variants']=[]
    for name in ('hierarchical_schedule_replicas.json',
                 'hierarchical_schedule_batch2048.json',
                 'hierarchical_schedule_batch2048_seven.json'):
        for s in json.loads((ROOT/'results'/name).read_text()):
            result['variants'].append(annual_case(cases[s['log_records'],s['batch']],s))
    result['batch_traffic']=[dict(log_records=c['log_records'],batch=c['batch'],
        frontend=c['frontend_and_dedup_unframed_bytes_per_query'],
        read=c['read_unframed_bytes_per_query'], rebuild=c['rebuild_unframed_bytes_per_query'],
        total=c['total_unframed_bytes_per_query']) for c in cases.values()
        if c['batch'] in (512,1024,2048)]
    path=ROOT/'results/hierarchical_annual.json'
    path.write_text(json.dumps(result,indent=2)+'\n')
    for r in out:
        s=r['schedule']
        print(json.dumps(dict(logN=r['log_records'],B=r['batch'],workers=r['workers_per_party'],
            annual_million=r['total_year']/1e6,mean_ms=s['mean_query_seconds']*1000,
            p99_ms=s['p99_query_seconds']*1000)))


if __name__=='__main__':
    main()
