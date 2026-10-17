import json
import math

d = json.load(open('mpc_cost/results/hierarchical_throughput.json'))

def price_role(bytes_q, state_bytes, nodes, states=1):
    bps=bytes_q*10000/(.65*.70)
    t=bps/2**20
    i=max(bps/65536, 4*t)
    v_per_host=max(math.ceil(t/(nodes*2000)), math.ceil(i/(nodes*80000)),
                   math.ceil(states*state_bytes/(nodes*65536*2**30)),1)
    v=nodes*v_per_host
    tv=max(125,math.ceil(t/v))
    iv=max(3000,math.ceil(i/v),4*tv)
    gv=max(1,math.ceil(states*state_bytes/(v*2**30)),math.ceil(iv/500) if iv>3000 else 1)
    assert iv<=80000 and tv<=2000 and gv<=65536 and v_per_host<=25
    return dict(volumes=v,giB=gv*v,MiBps=tv*v,IOPS=iv*v,
        capacity_year=.96*gv*v,
        io_year=.48*(tv-125)*v+.06*(iv-3000)*v)

for r in d['primary']:
    if r['child_z']!=64:
        continue
    for mode in ('hot','cold'):
        hot=r['adaptive_cache']
        cold=r['tiered_all_bucket_prefetch']
        n=(hot['immutable_equality_variant']['network_nodes_per_party'] if mode=='hot'
            else cold['network_nodes_per_party'])
        state=r['persistent_state_bytes_per_party']
        io=hot['tiled_io_after_state_cache_bytes_per_query']
        for states in (1,8,16):
            g=price_role(io,state,n,states)
            e=price_role(io if mode=='hot' else cold['evaluator_ebs_bytes_per_query'],
                         state+(cold['evaluator_cold_gc_storage_bytes'] if mode=='cold' else 0),n,states)
            ec2=2*n*7.2576*8760
            print(json.dumps(dict(logN=r['log_records'],mode=mode,states=states,nodes_party=n,
                G=g,E=e,ec2_year=ec2,all_year=ec2+g['capacity_year']+g['io_year']+e['capacity_year']+e['io_year'])))
