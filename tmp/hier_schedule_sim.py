"""Temporary independent bandwidth-only hierarchical scheduling experiment."""
import heapq, json, time
from pathlib import Path
import numpy as np

data=json.loads(Path('mpc_cost/results/hierarchical_split_comparison.json').read_text())
ACTIVE=11.375e9
ARR=1024/10000

def prepare(s):
    rows=s['rows']; L=s['lower_levels']; M=1<<L; d=s['local_refinement']['suffix_bits']; b=s['batch']
    def f_read(r):
        a=10240+134*r['read_slots']+r['parent_routing_stages']+d+4
        return 32*a+80*r['read_slots']+(r['parent_routing_stages']+d)/8
    read=np.zeros(M)
    for i,r in enumerate(rows[:-1]):
        a=1<<i; read[a:2*a]=read[:a]+f_read(r)
    beta=10; comp=beta*(beta+1)/4
    frontend=32*10240+12288+32*(comp*511+140*(b-1)/b)+80*(comp+3*(b-1)/b)
    read+=f_read(rows[-1])+frontend
    read*=1.05*b/ACTIVE
    build=np.zeros(M)
    for i,r in enumerate(rows):
        work=1.05*(r['rebuild_unframed_bytes']-80*r['rebuild_payload_swaps']-4096)/ACTIVE
        if i<L: build[(1<<i)-1::1<<(i+1)]=work
        else: build[-1]=work
    return read,build

def run(s,read,build,S,totalworkers,cycles):
    M=len(read); K=totalworkers/S; count=int(M*cycles)
    states=[(0.,j,j*M//S) for j in range(S)]
    heapq.heapify(states)
    waits=np.empty(count); response=np.empty(count)
    hit_top=0; last_completion=0
    for j in range(count):
        available,ident,counter=heapq.heappop(states)
        arrival=j*ARR; start=max(arrival,available)
        done=start+read[counter]/K
        ready=done+build[counter]/K
        waits[j]=start-arrival; response[j]=done-arrival
        hit_top+=counter==M-1
        heapq.heappush(states,(ready,ident,(counter+1)%M))
        last_completion=max(last_completion,done)
    return dict(logn=s['log_records'],leaf=s['child_z'],states=S,totalworkers_per_party=totalworkers,
                workers_per_state=K,events=count,initial_counters='evenly offset',top_builds=hit_top,
                horizon_seconds=count*ARR,waiting_mean_s=float(np.mean(waits)),waiting_max_s=float(np.max(waits)),
                waiting_p99_s=float(np.quantile(waits,.99)),waiting_p999_s=float(np.quantile(waits,.999)),
                response_mean_s=float(np.mean(response)),response_max_s=float(np.max(response)),
                response_p99_s=float(np.quantile(response,.99)),response_p999_s=float(np.quantile(response,.999)),
                finish_backlog_s=max(0,last_completion-(count-1)*ARR))

out=[]
for s in data['primary']:
    if s['child_z']!=64: continue
    read,build=prepare(s); K=28 if s['log_records']==28 else 38
    print('prepared',s['log_records'],'mean pooled batch service',float(np.mean(read+build))/K,flush=True)
    for S in (1,2,4,8):
        for mode in ('constant','full'):
            if S==1 and mode=='full': continue
            total=K if mode=='constant' else K*S
            # A full logical-counter cycle worth of arrivals. Offset replicas
            # expose at least one top event without warming every replica.
            result=run(s,read,build,S,total,2)
            result['allocation']=mode
            out.append(result)
            print(json.dumps(result),flush=True)
Path('tmp/hier_schedule_sim_results.json').write_text(json.dumps(out,indent=2)+'\n')
