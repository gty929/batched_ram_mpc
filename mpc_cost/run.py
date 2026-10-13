"""python -m mpc_cost.run --output mpc_cost/results [--full]

Standard-library-only sweep; all default throughput inputs are assumptions.
The exported JSON contains every design/deployment/backend parameter.
"""
from __future__ import annotations
import argparse
import csv
from dataclasses import asdict, replace
from itertools import product
import json
from pathlib import Path
from .model import Design, Backend, Deployment, circuit, provision, queue_simulation, GIB


def load_skus(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    result=[]
    names={'r6in.16xlarge','r6in.24xlarge','r6in.32xlarge','r7i.48xlarge','r8i.48xlarge'}
    for row in raw['selected_rows']:
        if row['Instance Type'] in names:
            network=row['Network Performance'].split()[0]
            result.append(dict(name=row['Instance Type'], vcpu=int(row['vCPU']),
                               memory_gib=float(row['Memory'].split()[0].replace(',','')),
                               network_gbps=float(network)/1000,
                               hourly_usd=float(row['PricePerUnit'])))
    return result


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('mpc_cost/results'))
    parser.add_argument('--prices', type=Path, default=Path(__file__).parent/'data/aws_prices_2026-10-12.json')
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--config', type=Path, help='JSON with design/backend/deployment parameter overrides')
    parser.add_argument('--queue-batches',type=int,default=1500)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    overrides=json.loads(args.config.read_text()) if args.config else {}
    initial=Design(**overrides.get('design',{}))
    backend=Backend(**overrides.get('backend',{}))
    dep=Deployment(**overrides.get('deployment',{}))
    skus=load_skus(args.prices)
    batches=[64,128,256,512,1024,2048] if args.full else [128,512,1024]
    fanouts=[4,8,16,32,64,128,256] if args.full else [8,16,64,256]
    cutoffs=[256,1024,4096,16384,65536] if args.full else [1024,4096,16384]
    nodes=[1,2,3,4,6,8,12,16,24,32,48,64,96,128,192,256,384,512,768,1024,1536,2048,4096,8192]
    best=[]; circuits={}; curve=[]
    scenarios=[('central',dep),('faster_cpu',replace(dep,local_products_per_sec_64vcpu=8e9)),
               ('slower_cpu',replace(dep,local_products_per_sec_64vcpu=.5e9)),
               ('low_exchange',replace(dep,round_ms=.05)),
               ('slow_exchange',replace(dep,round_ms=.5)),
               ('two_second_target',replace(dep,mean_latency_limit=2.0)),
               ('no_overlap',replace(dep,resource_overlap=False))]
    all_designs=[]
    for batch,fanout,cutoff,metadata,method in product(batches,fanouts,cutoffs,['compact','bits'],['bitonic','shuffle_quicksort']):
        d=replace(initial,batch=batch,fanout=fanout,base_cutoff=cutoff,metadata=metadata,sort_method=method)
        c=circuit(d)
        all_designs.append(c)
    for name,profile in scenarios:
        candidates=[]
        by_batch={}
        by_method={}
        for c in all_designs:
            winner=None
            for sku,k in product(skus,nodes):
                x=provision(c,sku,k,profile,backend)
                if x is None or not x['meets_mean_limit']:
                    continue
                if winner is None or (x['total_usd_year'],x['model_mean_seconds']) < (winner['total_usd_year'],winner['model_mean_seconds']):
                    winner=x
            if winner:
                candidates.append((winner,c))
                b=winner['batch']
                if b not in by_batch or winner['total_usd_year']<by_batch[b]['total_usd_year']:
                    by_batch[b]=winner
                method=winner['sort_method']
                if method not in by_method or winner['total_usd_year']<by_method[method]['total_usd_year']:
                    by_method[method]=winner
        if not candidates:
            best.append(dict(scenario=name,status='No feasible point in search grid',deployment=asdict(profile)))
            continue
        x,c=min(candidates,key=lambda pair:(pair[0]['total_usd_year'],pair[0]['model_mean_seconds']))
        q=queue_simulation(x['batch'],initial.rate,x['service_seconds'],x['replicas'],
                           batches=args.queue_batches,response_seconds=profile.fixed_response_ms/1000)
        record=dict(scenario=name,status='conditional model only',deployment=asdict(profile),
                    backend=asdict(backend),result=x,queue=q,design=c['design'],
                    method_best=by_method)
        best.append(record); circuits[name]=c
        curve.extend(dict(scenario=name,**v) for v in by_batch.values())
        print(f"{name}: ${x['total_usd_year']/1e6:,.2f}M/year, mean {q['mean_seconds']:.3f}s, "
              f"B={x['batch']}, F={x['fanout']}, base={x['base_cells']}, {x['metadata']}, "
              f"{x['sort_method']}, {x['total_instances']} instances",flush=True)
    (args.output/'summary.json').write_text(json.dumps(dict(
        warning='CONDITIONAL CIRCUIT/CAPACITY MODEL; no MPC implementation or benchmark.',
        price_file=str(args.prices), scenarios=best),indent=2)+'\n')
    (args.output/'circuits.json').write_text(json.dumps(circuits,indent=2)+'\n')
    if curve:
        with (args.output/'frontier.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(curve[0]));writer.writeheader();writer.writerows(curve)
    # Topology sensitivity uses each selected circuit's actual bytes; never charges receivers twice.
    topology=[]
    for rec in best:
        if 'result' not in rec: continue
        x=rec['result']
        for label,fraction in [('same_AZ',0),('three_AZ_4_3_3_all_to_all_proxy',66/90),('all_cross_AZ',1)]:
            billed=x['sent_mb_per_party_read']*1e6*initial.rate*initial.parties*365*24*3600/dep.billing_gb_bytes*dep.transfer_usd_per_gb*fraction
            topology.append(dict(scenario=rec['scenario'],placement=label,
                                 transfer_usd_year=billed,total_usd_year=x['compute_usd_year']+billed))
    (args.output/'topology.json').write_text(json.dumps(topology,indent=2)+'\n')


if __name__=='__main__':
    main()
