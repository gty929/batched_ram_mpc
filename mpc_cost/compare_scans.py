"""Attribute the saved ORAM cost and compare exact parallel scans.

Run: python -m mpc_cost.compare_scans
No MPC execution. Preserves the previously priced circuit and backend assumptions.
Scan prices are resource-capacity equivalents, not feasible AWS deployment quotes.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
from math import ceil, log2
import json
from pathlib import Path
from .model import (Work, Design, Backend, Deployment, circuit, traffic, provision,
                    decoder_shape, pow2, clog2, GIB, SECONDS_YEAR)
from .run import load_skus

ROOT = Path(__file__).resolve().parent


def phase_split(c: dict, backend: Backend = Backend()) -> dict:
    """Potential offline generation, with current-source CPU operation placement.

    Not a trace: source buffers can be generated lazily. More local randomness
    work can be hoisted offline; total arithmetic and priced resources are fixed.
    Requires the default source-proxy backend for the split constants below.
    """
    if backend != Backend():
        raise ValueError('Offline split coefficients are pinned to the default SY backend.')
    w = c['work']; t = traffic(c, backend)
    outputs = w['reductions'] + w['dot_outputs']
    masks = w.get('canonical_masks', 0)
    prep_reductions = (c['design']['field_bits'] - 1) * masks
    prep_openings = masks
    factor = c['design']['field_bytes'] * backend.framing_factor
    # All products need 5/6 words of fresh check randomness. The 9-word online
    # part of a mask-acceptance product happens in preprocessing as well.
    off_words = outputs * (5/6) + 9 * prep_reductions
    off_words += backend.bit_words * w['random_bits'] + 8 * prep_openings
    off_words += (5/6) * t['checks']
    off_bytes = off_words * factor
    # 83=15 query-independent check randomness +68 main/checked scalar work.
    off_cpu = 15 * outputs + 68 * prep_reductions
    off_cpu += backend.random_bit_local_products * w['random_bits'] + 35 * prep_openings
    # Potential source optimization: precompute random polynomial contributions
    # for scalar reductions. Exclude the already-offline products and dot terms.
    hoistable = 48 * max(0, w['reductions'] - prep_reductions)
    total_cpu = t['local_products_party_batch']
    result = dict(offline_sent_bytes=off_bytes,
                  online_sent_bytes=t['sent_bytes_party_batch']-off_bytes,
                  total_sent_bytes=t['sent_bytes_party_batch'],
                  offline_cpu_operations=off_cpu, online_cpu_operations=total_cpu-off_cpu,
                  total_cpu_operations=total_cpu,
                  offline_cpu_if_scalar_randomness_hoisted=off_cpu+hoistable,
                  online_cpu_if_scalar_randomness_hoisted=total_cpu-off_cpu-hoistable,
                  canonical_masks=masks, offline_reduction_outputs=prep_reductions,
                  offline_openings=prep_openings)
    result['offline_traffic_fraction'] = off_bytes/result['total_sent_bytes']
    result['offline_cpu_fraction'] = off_cpu/total_cpu
    return result


def scan_circuit(d: Design, mode: str = 'full_key', split_bits: int | None = None) -> dict:
    """Exact full-key scan, and a stronger indexed matrix-contraction scan.

    Full key: three field limbs, exact norm-to-zero over p=2^127-1 ==3 mod4.
    u=d0²+d1²; v=u²+d2²; e=1-v^(p-1). Each norm is a length2 dot output,
    Fermat uses135 scalar products. Reduction outputs=137N+3 per query.

    Indexed matrix scan: keep two cuckoo tables, public row-major D=A*C layout.
    Form private one-hots a[A],b[C], compute z_i=sum_j b_j X_ij (A*W dot outputs),
    then y=sum_i a_i z_i (W dot outputs). O(DW) local work, O(AW+C) reductions.
    No ORAM state updates and no per-worker full database replication are needed.
    """
    if (d.field_bits,d.field_bytes,d.parties,d.threshold)!=(127,16,10,4):
        raise ValueError('Scan templates use the same p127 ten-party SY backend.')
    kw=ceil(8*d.key_bytes/(d.field_bits-1)); vw=ceil(8*d.value_bytes/(d.field_bits-1))
    if kw != 3:
        raise ValueError('Exact norm template expects three key limbs.')
    q=d.batch; w=Work(); extra={}; index_validity_bits=0
    if mode == 'full_key':
        n=d.records
        w.dots(n*q,2,depth=2)  # first norm, all rows and requests parallel
        w.dots(n*q,2,depth=2)  # second norm
        w.products(135*n*q,135)
        w.dots(q*vw,n)
        stored=n*(kw+vw)*d.field_bytes*d.share_words
        # Best-case database reuse across all requests in a batch. Tiling avoids
        # storing the N*q equality matrix. Intermediate arithmetic stays in CPU
        # buffers; its detailed RAM traffic is not asserted by this lower estimate.
        w.ram_bytes=stored
        extra=dict(equality_outputs_per_row=137, equality='exact nested sum-of-squares norm and Fermat',
                   stored_records=n, intermediate_memory='stream row/query tiles; never materialize N*batch masks')
    elif mode == 'indexed_2d':
        total_cells=pow2(ceil(d.records/d.cuckoo_load_ceiling))
        cells=total_cells//2
        h=clog2(cells)
        index_validity_bits=2*h
        # Communication optimum (A*W+A+C) near A=sqrt(D/(W+1)).
        if split_bits is None:
            split_bits=round(log2((cells/(kw+vw+1))**.5))
        if not 1 <= split_bits < h:
            raise ValueError('Invalid matrix split')
        a=2**split_bits; cols=cells//a; words=kw+vw
        per=Work()
        ca,da=decoder_shape(clog2(a)); cb,db=decoder_shape(clog2(cols))
        # Secret-valid decoder costs are conservative; normal queries have valid=1.
        per.products(q*(ca+cb),max(da,db))
        per.dots(q*a*words,cols)
        per.dots(q*words,a)
        for name in ('reductions','dot_outputs','local_products','ram_bytes'):
            setattr(per,name,getattr(per,name)*2)
        w.add(per)
        # Exact stored full-key checks for both candidates + common cuckoo stash.
        matches=(2+d.cuckoo_stash)*q
        w.dots(matches,2); w.dots(matches,2); w.products(matches*135,135)
        w.dots(q*vw,2+d.cuckoo_stash)
        stored=(total_cells+d.cuckoo_stash)*(kw+vw)*d.field_bytes*d.share_words
        w.ram_bytes=stored
        extra=dict(stored_records=total_cells, matrix_rows=a,matrix_columns=cols,
                   words_per_cell=words, indexed=True,
                   scope='stronger scan-based comparator, not the naive full-key scan')
    else:
        raise ValueError('Unknown scan mode')
    w.products((256+index_validity_bits)*q,2)  # input-bit/range validity proxy
    w.phases+=5  # checked output-release barrier
    c=dict(design=asdict(d),work=asdict(w),state_bytes_party=stored,scan_mode=mode,**extra)
    return c


def capacity_equivalent(c: dict, sku: dict, dep: Deployment, backend: Backend) -> dict:
    """Steady-state resource envelope, not a latency-feasible deployment.

    Public row tiling/sharding permits shared immutable scan data. Round waits
    overlap across independent queries; no sequential ORAM replica schedule is
    imposed on scans. Giant fleet estimates cannot be advertised as AWS quotes.
    """
    t=traffic(c,backend); d=c['design']; batches_s=d['rate']/d['batch']
    effective=dep.distributed_efficiency*dep.utilization
    cpu_node=dep.local_products_per_sec_64vcpu*sku['vcpu']/64*effective
    nic_node=sku['network_gbps']*1e9/8*dep.nic_efficiency*effective
    ram_node=dep.ram_gbps_64vcpu*1e9*sku['vcpu']/64*effective
    cpu=ceil(t['local_products_party_batch']*batches_s/cpu_node)
    network=ceil(t['hottest_sent_bytes_batch']*batches_s/nic_node)
    ram=ceil(c['work']['ram_bytes']*batches_s/ram_node)
    memory=ceil(c['state_bytes_party']*(1+dep.scratch_fraction)/(sku['memory_gib']*GIB*dep.memory_usable))
    k=max(cpu,network,ram,memory)
    annual=k*d['parties']*sku['hourly_usd']*8760
    return dict(instance=sku['name'],cpu_nodes_per_party=cpu,network_nodes_per_party=network,
                ram_bandwidth_nodes_per_party=ram,memory_nodes_per_party_one_shared_copy=memory,
                resource_nodes_per_party=k,annual_resource_equivalent_usd=annual,
                resource_equivalent_usd_per_million=annual/(d['rate']*SECONDS_YEAR)*1e6,
                interpretation='Unmeasured aggregate resource-capacity equivalent; excludes distributed dot aggregation, queues and scratch provisioning; not a feasible fleet/SLA.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,default=ROOT/'results',
                        help='Directory containing a saved run summary; comparison is written here.')
    args=parser.parse_args()
    summary=json.loads((args.results/'summary.json').read_text())
    saved=next(s for s in summary['scenarios'] if s['scenario']=='central')
    d=Design(**saved['design']); dep=Deployment(**saved['deployment']); be=Backend(**saved['backend'])
    oram=circuit(d)
    sku=next(s for s in load_skus(ROOT/'data/aws_prices_2026-10-12.json') if s['name']==saved['result']['instance'])
    rows=[]
    for name,c in [('Circuit OPRAM reference',oram),('Naive full-key scan',scan_circuit(d)),
                   ('Indexed 2D dot scan',scan_circuit(d,'indexed_2d'))]:
        split=phase_split(c,be); cost=capacity_equivalent(c,sku,dep,be)
        rows.append(dict(name=name,circuit=c,phase_split_batch=split,capacity_equivalent=cost,
                         reductions_per_read=(c['work']['reductions']+c['work']['dot_outputs'])/d.batch,
                         cpu_operations_per_read=split['total_cpu_operations']/d.batch,
                         sent_bytes_party_per_read=split['total_sent_bytes']/d.batch,
                         storage_gib_per_party=c['state_bytes_party']/GIB,
                         exchange_depth_ms=c['work']['phases']*dep.round_ms,
                         ideal_batch_fill_mean_ms=(d.batch-1)/(2*d.rate)*1000))
    # Exact counterfactual within the old dedicated-replica policy: remove only
    # the capacity constraint and re-search K on the original selected instance.
    no_storage=dict(sku,memory_gib=1e20)
    candidates=[provision(oram,no_storage,k,dep,be) for k in range(1,129)]
    without_memory=min((v for v in candidates if v['meets_mean_limit']),key=lambda x:x['total_usd_year'])
    selected=provision(oram,sku,saved['result']['nodes_per_party_per_replica'],dep,be)
    # Preserve prior results and explicitly check diagnostics haven't changed costs.
    assert abs(selected['total_usd_year']-saved['result']['total_usd_year'])<.01
    result=dict(date='2026-10-13',status='Conditional analytical model; not measurements',
                assumptions=dict(backend=asdict(be),deployment=asdict(dep),instance=sku),
                oram_selected_deployment=selected,oram_without_storage_constraint=without_memory,
                rows=rows)
    (args.results/'bottleneck_scan_comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    for r in rows:
        s=r['phase_split_batch']
        print(f"{r['name']}: {r['reductions_per_read']:,.0f} outputs/read, "
              f"{r['sent_bytes_party_per_read']/1e6:,.1f} MB/read/party, "
              f"{r['cpu_operations_per_read']/1e6:,.1f}M CPU ops/read, "
              f"{r['storage_gib_per_party']:,.1f} GiB/party, "
              f"offline comm {s['offline_traffic_fraction']:.1%}, CPU {s['offline_cpu_fraction']:.1%}, "
              f"resource equivalent ${r['capacity_equivalent']['annual_resource_equivalent_usd']/1e9:,.2f}B/year")


if __name__=='__main__':
    main()
