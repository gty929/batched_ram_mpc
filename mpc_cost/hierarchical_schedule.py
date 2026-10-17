"""Bandwidth/round latency model and explicit pooled rebuild scheduler.

This is an analytical simulation, not an AWS latency benchmark. The lookup
workload is static: independently evolving ORAM replicas contain the same
logical database. Replication of application writes is outside this model.
Only the existing, audited B >= 512 construction is used.
"""
from dataclasses import dataclass
from dataclasses import replace
from math import ceil, log2
from pathlib import Path
import heapq
import json

import numpy as np

from .hierarchical_cache import adaptive_plan
from .hierarchical_throughput import Deployment, directions
from .hierarchical_latency import ready_latency
from .hierarchical_address import auxiliary, read_ands, inputs, scheme, current_case


@dataclass(frozen=True)
class Schedule:
    replicas: int = 4
    foreground_workers_per_party: int = 14
    background_workers_per_party: int = 15
    rtt_seconds: float = .0002
    qps: int = 10_000
    cache_cutoff_log: int = 16
    intraparty_remote_fraction: float = 0.
    cold_bucket_load_seconds: float = 0.
    preload_all_stash_prf: bool = False
    dram_active_bytes_second: float = 56e9
    # The binary counter offset uses thirds/fifths, rather than a common
    # dyadic boundary, when replicas is odd. All initial caches are warm.
    phase: str = 'even'


def arrays(c, s=Schedule(), dep=Deployment()):
    """Exact per-counter byte costs; expected cache-refill consumption.

    A newly created hot table receives its entire lookahead window. A live
    retained hot table replenishes consumed equality circuits. Retiring
    tables skip their final refill. Stash/PRF circuits are prepared for the
    next batch, and input-label bridges remain on the foreground path.
    """
    b = c['batch']
    k = int(log2(b))
    levels = c['lower_levels']
    length = 1 << levels
    d = directions(c)
    cache = adaptive_plan(c, cutoff_log=s.cache_cutoff_log)
    cached = {r['log_capacity']: r for r in cache['rows']}
    forward = np.zeros(length)
    reverse = np.zeros(length)
    preload = np.zeros(length)
    preload_reverse = np.zeros(length)
    occupied = np.zeros(length, dtype=np.uint8)
    cold = np.zeros(length, dtype=np.uint8)
    state_io = np.zeros(length)
    dram_io = np.zeros(length)
    for i, r in enumerate(c['rows'][:-1]):
        span = 1 << i
        hot = cached.get(r['log_capacity'])
        aux = bool(hot) or s.preload_all_stash_prf
        material=auxiliary(r)
        auxbytes = material['forward']
        saved = (32*127*c['child_z']*hot['expected_hit_fraction'] if hot else 0)+(auxbytes if aux else 0)
        bridge = 4096 if aux else 0
        cost = d['rows'][i]['read_forward'] - saved + bridge
        forward[span:2*span] = forward[:span] + cost
        reverse[span:2*span] = reverse[:span]+d['rows'][i]['read_backward']-(material['reverse'] if aux else 0)
        preload_cost = auxbytes if aux else 0
        preload[span:2*span] = preload[:span] + preload_cost
        preload_reverse[span:2*span] = preload_reverse[:span]+(material['reverse'] if aux else 0)
        occupied[span:2*span] = occupied[:span]+1
        cold[span:2*span] = cold[:span]+(0 if hot else 1)
        disk_slots = 0 if hot else c['child_z']+(0 if aux else r['global_stash']['capacity'])
        state_io[span:2*span] = state_io[:span]+2*2112*disk_slots
        a=read_ands(c,r)
        dram_io[span:2*span] = dram_io[:span]+2*32*a+2*2112*r['read_slots']+2*sum(inputs(r))
    top = c['rows'][-1]
    topmaterial=auxiliary(top)
    topaux=topmaterial['forward']
    forward += d['rows'][-1]['read_forward'] + d['frontend_forward']-(topaux if s.preload_all_stash_prf else 0)+(4096 if s.preload_all_stash_prf else 0)
    reverse += d['rows'][-1]['read_backward']+d['frontend_backward']-(topmaterial['reverse'] if s.preload_all_stash_prf else 0)
    if s.preload_all_stash_prf:
        preload += topaux
        preload_reverse += topmaterial['reverse']
    state_io += 2*2112*(c['child_z']+(0 if s.preload_all_stash_prf else top['global_stash']['capacity']))
    a=read_ands(c,top)
    dram_io += 2*32*a+2*2112*top['read_slots']+2*d['frontend_forward']+2*sum(inputs(top))
    occupied += 1
    cold += 1
    # Only results traverse the reverse bitonic network. Inputs being sorted
    # are Boolean key metadata, not packed application payloads. A parallel
    # segmented scan is bounded by two log(B) packed-OT rounds. Batched
    # one-hot payload extraction takes one more round across all tables.
    packed_rounds = k*(k+1)//2+2*k+1
    foreground_network = dep.framing*b*np.maximum(forward,reverse)/(s.foreground_workers_per_party*dep.nic_active)
    foreground_network += dep.framing*b*s.intraparty_remote_fraction*state_io/2/(s.foreground_workers_per_party*dep.nic_active)
    foreground_ebs = b*state_io/(s.foreground_workers_per_party*dep.ebs_raw*dep.ebs_efficiency)
    foreground_dram = b*dram_io/(s.foreground_workers_per_party*s.dram_active_bytes_second)
    foreground=np.maximum.reduce([foreground_network,foreground_ebs,foreground_dram])
    # Two additional endpoint/input-output synchronization rounds.
    foreground += s.rtt_seconds*(occupied+packed_rounds+2)
    foreground += s.cold_bucket_load_seconds*cold
    # Use the independently audited stage-by-stage loading model. Taking a
    # single maximum over all levels would hide a level-local EBS bottleneck.
    # Payload selection is deferred but its bytes are still charged once.
    ready_model=ready_latency(c,s.foreground_workers_per_party,
        cache_all_aux=s.preload_all_stash_prf,rtt=s.rtt_seconds,
        ebs_fixed=s.cold_bucket_load_seconds,
        intraparty_remote_fraction=s.intraparty_remote_fraction)
    stage_fg=np.zeros(length)
    stage_dram=np.zeros(length)
    for i, (r, rt) in enumerate(zip(c['rows'][:-1],ready_model['rows'][:-1])):
        span=1<<i
        product_time=dep.framing*b*80*r['read_slots']/(s.foreground_workers_per_party*dep.nic_active)
        stage_fg[span:2*span]=stage_fg[:span]+rt['service_seconds']+product_time+s.rtt_seconds
        stage_dram[span:2*span]=stage_dram[:span]+rt['dram_seconds']
    front_products=k*(k+1)/4+3*(b-1)/b
    final_products=front_products+top['read_slots']
    stage_fg+=ready_model['frontend_service_seconds']+ready_model['rows'][-1]['service_seconds']
    stage_fg+=dep.framing*b*80*final_products/(s.foreground_workers_per_party*dep.nic_active)
    stage_fg+=s.rtt_seconds*(packed_rounds+3)
    foreground=stage_fg
    front_gc=32*(10240+k*(k+1)/4*511+140*(b-1)/b)
    stage_dram+=ready_model['rows'][-1]['dram_seconds']+2*b*front_gc/(s.foreground_workers_per_party*s.dram_active_bytes_second)
    foreground_dram=stage_dram
    rebuild = np.zeros(length)
    rebuild_forward = np.zeros(length)
    rebuild_reverse = np.zeros(length)
    rebuild_internal = np.zeros(length)
    carry = np.zeros(length, dtype=np.uint8)
    for i, r in enumerate(c['rows']):
        sl = slice((1 << i)-1, None, 1 << (i+1)) if i < levels else slice(length-1,None)
        comp=r['components']; n=r['capacity']; h=r['parent_routing_stages']; suffix=int(log2(512/c['child_z']))
        global_metadata=comp['source_compact_metadata']+comp.get('source_stash_reentry_metadata',0)+comp['global_stash_merge_metadata']
        global_moves=64*global_metadata+128*global_metadata/130
        butterfly=4*n*h*(16*(130+h+suffix)+32)
        local=r['parent_buckets']*(512*(16*(130+suffix)+32)+(512+64)*2112)
        tiled_rebuild=global_moves+butterfly+local
        boundary=2112*((4 if r['top'] else 2)*n+2*n+r['source_stash_slots']+r['global_stash']['capacity'])
        internal=s.intraparty_remote_fraction*(tiled_rebuild+boundary)/2
        work = dep.framing*(max(d['rows'][i]['rebuild_forward'],d['rows'][i]['rebuild_backward'])+internal)
        rebuild_forward[sl]=d['rows'][i]['rebuild_forward']+internal
        rebuild_reverse[sl]=d['rows'][i]['rebuild_backward']+internal
        rebuild_internal[sl]=internal
        # A conservative serialization of payload OT round dependencies.
        net_time=work/(s.background_workers_per_party*dep.nic_active)
        disk_time=(tiled_rebuild+boundary)/(s.background_workers_per_party*dep.ebs_raw*dep.ebs_efficiency)
        rebuild[sl] = max(net_time,disk_time)
        rebuild[sl] += s.rtt_seconds*r['payload_swap_layers']
        carry[sl] = i
    # Next-batch stash/PRF preparation, including the wraparound state.
    refill_bytes = b*np.roll(preload,-1)
    refill_reverse_bytes = b*np.roll(preload_reverse,-1)
    # The exact hot equality cache lifecycle. Its total reproduces the
    # skip-final-refill expected inventory charge, up to negligible misses.
    for i, r in enumerate(c['rows'][:-1]):
        hot = cached.get(r['log_capacity'])
        if not hot:
            continue
        span = 1 << i
        period = 2*span
        queue = hot['gc_queue_ram_bytes_evaluator']*127/134
        consumed = b*32*127*c['child_z']*hot['expected_hit_fraction']
        refill_bytes[span-1::period] += queue
        # Every occupied counter except the last: equality refill after use.
        for offset in range(span,period-1):
            refill_bytes[offset::period] += consumed
    background = rebuild + dep.framing*np.maximum(refill_bytes,refill_reverse_bytes)/(s.background_workers_per_party*dep.nic_active)
    return dict(foreground_seconds=foreground, background_seconds=background,
                foreground_forward_bytes=(forward+s.intraparty_remote_fraction*state_io/2)*b,
                foreground_reverse_bytes=(reverse+s.intraparty_remote_fraction*state_io/2)*b,
                foreground_internal_bytes=s.intraparty_remote_fraction*state_io/2*b,
                background_forward_bytes=rebuild_forward+refill_bytes,
                background_reverse_bytes=rebuild_reverse+refill_reverse_bytes,
                background_internal_bytes=rebuild_internal,
                background_refill_bytes=refill_bytes,
                background_refill_reverse_bytes=refill_reverse_bytes,
                foreground_network_seconds=foreground_network,
                foreground_ebs_seconds=foreground_ebs,
                foreground_dram_seconds=foreground_dram,
                occupied_tables=occupied,carry=carry,
                packed_foreground_rounds=packed_rounds, cache=cache,
                period_batches=length)


def _query_quantile(response, batch, qps, quantile):
    """Quantile with deterministic arrivals and all B positions in a batch.

    Interpolate the exact staircase CDF rather than instantiate B copies of
    every response. A continuous fill distribution differs by <= 1/qps.
    """
    width = (batch-1)/qps
    lo, hi = float(response.min()), float(response.max()+width)
    for _ in range(50):
        mid = (lo+hi)/2
        cdf = np.clip((mid-response)/width,0,1).mean() if width else (response<=mid).mean()
        if cdf < quantile:
            lo=mid
        else:
            hi=mid
    return (lo+hi)/2


def latency_profile(c, s=Schedule(), dep=Deployment()):
    a=arrays(c,s,dep)
    fg=a['foreground_seconds']
    interval=c['batch']/s.qps
    return dict(batch=c['batch'],log_records=c['log_records'],replicas=s.replicas,address_scheme=scheme(c),qps=s.qps,
        foreground_workers_per_party=s.foreground_workers_per_party,
        background_workers_per_party=s.background_workers_per_party,
        total_workers_per_party=s.foreground_workers_per_party+s.background_workers_per_party,
        rtt_seconds=s.rtt_seconds,mean_fill_seconds=(c['batch']-1)/(2*s.qps),
        intraparty_remote_fraction=s.intraparty_remote_fraction,
        cold_bucket_load_seconds=s.cold_bucket_load_seconds,
        preload_all_stash_prf=s.preload_all_stash_prf,
        mean_foreground_network_seconds=float(a['foreground_network_seconds'].mean()),
        mean_foreground_ebs_seconds=float(a['foreground_ebs_seconds'].mean()),
        mean_foreground_dram_seconds=float(a['foreground_dram_seconds'].mean()),
        mean_ready_state_service_seconds=float(fg.mean()),
        max_ready_state_service_seconds=float(fg.max()),
        mean_ready_state_query_seconds=float(fg.mean())+(c['batch']-1)/(2*s.qps),
        p95_ready_state_query_seconds=_query_quantile(fg,c['batch'],s.qps,.95),
        p99_ready_state_query_seconds=_query_quantile(fg,c['batch'],s.qps,.99),
        foreground_utilization=float(fg.mean()/interval),
        background_utilization=float(a['background_seconds'].mean()/interval),
        background_mean_service_seconds=float(a['background_seconds'].mean()),
        packed_foreground_rounds=a['packed_foreground_rounds'],
        occupied_table_mean=float(a['occupied_tables'].mean()),
        no_queue_assumption=True,
        caveat='Ready-state latency only; scheduler queueing must be added.')


def provision(c, replicas=5, utilization=.70, **kwargs):
    """Size the two pools including serialized round/load latency.

    This policy deliberately leaves both pools <= utilization, including
    their modeled waits. Bandwidth-only sizing can use fewer workers.
    """
    unit=Schedule(replicas=replicas,foreground_workers_per_party=1,
                  background_workers_per_party=1,**kwargs)
    a=arrays(c,unit)
    k=int(log2(c['batch']))
    fgwait=unit.rtt_seconds*(float(a['occupied_tables'].mean())+a['packed_foreground_rounds']+2)
    cold_levels=sum(.5 for r in c['rows'][:-1] if r['log_capacity']>unit.cache_cutoff_log)+1
    fgwait+=unit.cold_bucket_load_seconds*cold_levels
    bground=sum(r['payload_swap_layers']*c['batch']/r['accesses_per_rebuild'] for r in c['rows'])*unit.rtt_seconds
    target=utilization*c['batch']/unit.qps
    if target <= max(fgwait,bground):
        raise ValueError('Round/load floor already exceeds target utilization')
    f=ceil((float(a['foreground_seconds'].mean())-fgwait)/(target-fgwait))
    def fgmean(workers):
        return ready_latency(c,workers,cache_all_aux=unit.preload_all_stash_prf,
            rtt=unit.rtt_seconds,ebs_fixed=unit.cold_bucket_load_seconds,
            intraparty_remote_fraction=unit.intraparty_remote_fraction)['mean_ready_batch_service_seconds']
    while fgmean(f)>target:
        f+=1
    while f>1 and fgmean(f-1)<=target:
        f-=1
    bg=ceil((float(a['background_seconds'].mean())-bground)/(target-bground))
    return replace(unit,foreground_workers_per_party=f,background_workers_per_party=bg)


def simulate(c, s=Schedule(), cycles=1., batches=None, dep=Deployment()):
    """Pooled read server plus preemptive shortest-remaining rebuild server.

    All workers in each pool jointly serve a job. The background pool may
    suspend a large rebuild for a newly arrived small rebuild. This changes
    inter-replica scheduling, not the construction's within-state semantics:
    a replica is unavailable until its whole rebuild+prefill job completes.
    Initial states use evenly spaced valid public counters; dummy warmup and
    initial construction costs are excluded. Ready replicas use oldest-use
    dispatch. Records/scratch reside on shared distributed per-party EBS.
    """
    a=arrays(c,s,dep)
    fg,bg=a['foreground_seconds'],a['background_seconds']
    period=a['period_batches']
    count=int(batches if batches is not None else ceil(cycles*period))
    if s.phase=='even':
        counters=[j*period//s.replicas for j in range(s.replicas)]
    elif s.phase=='zero':
        counters=[0]*s.replicas
    else:
        raise ValueError('unknown phase')
    ready=[(-s.replicas+j,j) for j in range(s.replicas)]
    heapq.heapify(ready)
    jobs=[]
    now=0.
    lastread=0.
    waits=np.empty(count)
    responses=np.empty(count)
    top_events=0
    completions=0
    lastuse=[-s.replicas+j for j in range(s.replicas)]

    def advance(target):
        nonlocal now, completions
        while jobs and now+jobs[0][0] <= target:
            work, ident=heapq.heappop(jobs)
            now+=work
            heapq.heappush(ready,(lastuse[ident],ident))
            completions+=1
        if jobs and target>now:
            work, ident=heapq.heappop(jobs)
            heapq.heappush(jobs,(max(0.,work-(target-now)),ident))
        now=target

    interval=c['batch']/s.qps
    for j in range(count):
        arrival=j*interval
        advance(max(arrival,lastread))
        while not ready:
            advance(now+jobs[0][0])
        _, ident=heapq.heappop(ready)
        counter=counters[ident]
        start=now
        done=start+fg[counter]
        advance(done)
        lastread=done
        waits[j]=start-arrival
        responses[j]=done-arrival
        counters[ident]=(counter+1)%period
        lastuse[ident]=j
        heapq.heappush(jobs,(bg[counter],ident))
        top_events+=counter==period-1
    out=latency_profile(c,s,dep)
    out.update(simulated_batches=count,simulated_seconds=count*interval,
        no_queue_assumption=False,
        caveat='Finite deterministic trace with admission queues; not an annual latency guarantee.',
        initial_phase=s.phase,simulated_top_rebuild_starts=top_events,
        mean_queue_seconds=float(waits.mean()),p95_queue_seconds=float(np.quantile(waits,.95)),
        p99_queue_seconds=float(np.quantile(waits,.99)),max_queue_seconds=float(waits.max()),
        mean_query_seconds=float(responses.mean())+(c['batch']-1)/(2*s.qps),
        p95_query_seconds=_query_quantile(responses,c['batch'],s.qps,.95),
        p99_query_seconds=_query_quantile(responses,c['batch'],s.qps,.99),
        max_query_seconds=float(responses.max())+(c['batch']-1)/s.qps,
        finish_backlog_seconds=max(0.,lastread-(count-1)*interval),
        final_counters=counters,
        finite_trace_not_guarantee=True,
        scheduler='Pooled foreground, preemptive SRPT background, oldest-ready state')
    return out


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',choices=('primary','variants'),default='primary')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    data=json.loads((root/'results/hierarchical_split_comparison.json').read_text())
    data['batch_sweep']=[current_case(c) for c in data['batch_sweep']]
    if args.suite=='variants':
        for batch,states,name in (
            (1024,7,'hierarchical_schedule_replicas.json'),
            (2048,5,'hierarchical_schedule_batch2048.json'),
            (2048,7,'hierarchical_schedule_batch2048_seven.json')):
            results=[]
            for c in data['batch_sweep']:
                if c['child_z']!=64 or c['batch']!=batch:
                    continue
                s=provision(c,replicas=states,intraparty_remote_fraction=1.,
                            cold_bucket_load_seconds=.0005,preload_all_stash_prf=True)
                result=simulate(c,s,cycles=2)
                results.append(result)
                print(json.dumps(result),flush=True)
            (root/'results'/name).write_text(json.dumps(results,indent=2)+'\n')
        return
    cases=[c for c in data['batch_sweep'] if c['child_z']==64 and c['batch'] in (512,1024)]
    results=[]
    for c in cases:
        s=provision(c,replicas=5,intraparty_remote_fraction=1.,cold_bucket_load_seconds=.0005,
                    preload_all_stash_prf=True)
        result=simulate(c,s,cycles=2)
        results.append(result)
        print(json.dumps(result),flush=True)
    # Publish only the complete consistent four-case suite.
    (root/'results/hierarchical_schedule.json').write_text(json.dumps(results,indent=2)+'\n')


if __name__=='__main__':
    main()
