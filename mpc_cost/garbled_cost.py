"""Multiparty garbled-RAM communication and SSD capacity estimates.

Run: python -m mpc_cost.garbled_cost
Network is the throughput bottleneck by the requested modeling assumption.
No CPU or SSD-throughput prediction is made. Correlation realization, joint
initialization and the multiparty stack migration remain explicit assumptions.
"""
from dataclasses import dataclass, asdict, replace
from math import ceil
from pathlib import Path
import json
from .garbled_circuit import kv_lookup

ROOT=Path(__file__).resolve().parent
GIB=2**30


@dataclass(frozen=True)
class GarblingBackend:
    parties: int=10
    threshold: int=4
    kappa_bits: int=128
    outer_pack: int=5
    superpack_epsilon: float=.4
    repair_multiplication_count: bool=True
    # A sensitivity, not a measured PCG/VOLE implementation coefficient.
    extra_correlation_fraction: float=0.


@dataclass(frozen=True)
class GarbledDeployment:
    rate: int=10_000
    nic_efficiency: float=.65
    distributed_efficiency: float=.70
    utilization: float=.70
    framing_factor: float=1.05
    epoch_copies: int=2  # complete current and next epoch; no streaming claim
    independent_states: int=1
    az_fraction: float=0.
    transfer_usd_per_decimal_gb: float=.02
    internal_hashes: int=0  # main frontend accepts client-supplied private indices
    extra_setup_ands_per_table_cell: float=0.  # explicit unpriced setup sensitivity
    include_routing_only_setup: bool=False


def backend_coefficients(b: GarblingBackend=GarblingBackend()) -> dict:
    """Appendix H, finite outer ell=5 and inner SP k=3, corrected Eq(8).

    Eq(6),(7) give the arithmetic input/output counts. The exact first line
    of Eq(8) gives 3I+5A, whereas its approximation gives 2I+5A and Eq(10)
    uses 2I+4A. Default repairs that arithmetic; printed Eq(10) is a sensitivity.
    These leading communication counts EXCLUDE concrete correlation generation.
    """
    if (b.parties,b.threshold,b.kappa_bits,b.outer_pack,b.superpack_epsilon)!=(10,4,128,5,.4):
        raise ValueError('Finite coefficients audited only for n10,t4,kappa128,outer5,innerepsilon.4.')
    if b.extra_correlation_fraction < 0:
        raise ValueError('Correlation overhead must be nonnegative.')
    n=b.parties;e=b.outer_pack/n;s=b.superpack_epsilon;f=b.kappa_bits/8
    ci=6*n+43/s;co=4*n+55/s;cm=6*n+45/s
    mi,ma=(3,5) if b.repair_multiplication_count else (2,4)
    pi=(2/e+2*(1-e)/e**2)*ci+(2/e)*co+mi*cm+8*(n-1)/e+(n-1)/e**2
    pa=(2/e+4*(1-e)/e**2)*ci+(4/e)*co+ma*cm+11*(n-1)/e+(3*(n-1)+e*n)/e**2
    po=2*(n-1)/e
    c=ceil(n/b.outer_pack)
    table_one=4*(c+1)*f  # row's additive mask share is a FIELD element, not one bit
    return dict(preprocessing_field_words_input=pi,preprocessing_field_words_and=pa,
        preprocessing_field_words_output=po,preprocessing_constant_field_words=16*n*(n-1),
        field_bytes=f,table_bytes_per_and_per_garbler=table_one,
        table_bytes_per_and_evaluator=(n-1)*table_one,
        input_delivery_bytes_global=(3*(n-1)*b.kappa_bits+2*(n-1))/8,
        output_delivery_bytes_global=2*(n-1)*b.kappa_bits/8,
        evaluator_state_bytes_per_bit=(n+4)*f,
        garbler_state_bytes_per_bit=4*f,
        note='Boolean-garbling H.2 leading communication, finite SP packing; correlation realization additional.')


def fleet_bounds(global_bytes_per_query: float, effective_bytes_per_node_second: float,
                 rate: int=10_000, parties: int=10) -> dict:
    """Role-independent full-duplex fleet envelope, including integer rounding.

    sum max(tx_i,rx_i) = V + sum(abs(tx_i-rx_i))/2 is in [V,2V].
    At most n-1 extra machines cover separate per-party ceilings. This is a
    capacity envelope, not a concrete assignment of VMs or a latency proof.
    """
    if global_bytes_per_query < 0 or effective_bytes_per_node_second <= 0 or rate<=0:
        raise ValueError('Invalid traffic/capacity/rate.')
    load=rate*global_bytes_per_query/effective_bytes_per_node_second
    return dict(minimum_total_nodes=max(parties,ceil(load)),
                conservative_total_nodes=max(parties,ceil(2*load)+parties-1),
                continuous_one_way_capacity_nodes=load)


def price(c: dict, sku: dict, ssd_usd_per_gib_month: float,
          b: GarblingBackend=GarblingBackend(), dep: GarbledDeployment=GarbledDeployment()) -> dict:
    if dep.epoch_copies < 1 or dep.independent_states < 1:
        raise ValueError('Need at least one epoch and independent state.')
    coeff=backend_coefficients(b);T=c['horizon'];n=b.parties
    if dep.internal_hashes not in (0,1,2):raise ValueError('Choose zero, one or two Keccak permutations.')
    if dep.extra_setup_ands_per_table_cell<0:raise ValueError('Negative setup allowance.')
    hash_a=dep.internal_hashes*24*1600
    setup_a=dep.extra_setup_ands_per_table_cell*c['table_count']*c['table_slots']/T
    if dep.include_routing_only_setup:
        setup_a+=c['routing_setup_ands_per_epoch']/T
    A=c['generated_ands']+hash_a+setup_a
    # Initial state is re-input once per epoch. Treating every physical slot bit
    # as secret is conservative; this does not compute a hidden valid permutation.
    I=c['functionality_input_bits_per_query']+c['initial_state_bits']/T
    if dep.internal_hashes:
        I-=c['private_index_input_bits']
    if dep.include_routing_only_setup:
        I+=c['routing_setup_control_bits_per_epoch']/T
    O=257
    pre_words=(I*coeff['preprocessing_field_words_input']+A*coeff['preprocessing_field_words_and']
               +O*coeff['preprocessing_field_words_output']+coeff['preprocessing_constant_field_words']/T)
    base_pre=pre_words*coeff['field_bytes']
    pre=base_pre*(1+b.extra_correlation_fraction)
    tables=A*coeff['table_bytes_per_and_evaluator']
    io=I*coeff['input_delivery_bytes_global']+O*coeff['output_delivery_bytes_global']
    # Client traffic and networking inside each party are not included. The
    # distributed-efficiency factor is the same engineering assumption as before.
    wire=(pre+tables+io)*dep.framing_factor
    nic=sku['network_gbps']*1e9/8*dep.nic_efficiency*dep.distributed_efficiency*dep.utilization
    fleet=fleet_bounds(wire,nic,dep.rate,n)
    compute_min=fleet['minimum_total_nodes']*sku['hourly_usd']*8760
    compute_upper=fleet['conservative_total_nodes']*sku['hourly_usd']*8760
    program_one=tables*T
    state_eval=c['retained_bits']*coeff['evaluator_state_bytes_per_bit']
    state_g=c['retained_bits']*coeff['garbler_state_bytes_per_bit']
    # Full packs for all parties are a conservative retention policy. Some
    # garbler state can be retired during generation, but no saving is assumed.
    state_one=state_eval+(n-1)*state_g
    storage=(program_one+state_one)*dep.epoch_copies*dep.independent_states
    storage_year=storage/GIB*ssd_usd_per_gib_month*12
    transfer=wire*dep.rate*365*24*3600/1e9*dep.az_fraction*dep.transfer_usd_per_decimal_gb
    return dict(backend=asdict(b),deployment=asdict(dep),coefficients=coeff,instance=sku,
        ands_per_query=A,hash_ands_per_query=hash_a,extra_setup_ands_per_query=setup_a,
        input_bits_per_query_including_epoch_state=I,output_bits_per_query=O,
        base_preprocessing_bytes_global_per_query=base_pre,
        preprocessing_bytes_global_per_query=pre,table_bytes_global_per_query=tables,
        input_output_bytes_global_per_query=io,wire_bytes_global_per_query=wire,
        average_sent_bytes_party_query=wire/n,
        preprocessing_fraction_before_framing=pre/(pre+tables+io),
        effective_nic_bytes_second=nic,network_fleet=fleet,
        network_ec2_min_usd_year=compute_min,network_ec2_upper_usd_year=compute_upper,
        epoch_queries=T,epoch_duration_seconds=T*dep.independent_states/dep.rate,
        program_bytes_one_epoch=program_one,evaluator_state_bytes=state_eval,
        garbler_state_bytes_each=state_g,state_bytes_all_parties_one_epoch=state_one,
        ssd_bytes_all_epochs_and_states=storage,ssd_usd_year=storage_year,
        transfer_usd_year=transfer,
        total_min_usd_year=compute_min+storage_year+transfer,
        total_upper_usd_year=compute_upper+storage_year+transfer,
        interpretation='Conditional network+SSD capacity envelope, not CPU benchmark or SLA. '
            'Concrete correlations and malicious epoch initialization remain explicit sensitivities; '
            'stack and stack-associated adaptor cost is zero under the requested migration assumption; '
            'any non-stack representation adapters remain unpriced compiler work.')


def main():
    prices=json.loads((ROOT/'data/aws_garbled_prices_2026-10-13.json').read_text())['normalized']
    sku=next(s for s in prices['ec2'] if s['name']=='c6in.32xlarge')
    ssd=prices['gp3']['capacity_usd_per_gib_month']
    backend=GarblingBackend();dep=GarbledDeployment();results=[];frontier=[]
    for exponent in (28,32):
        candidates=[]
        for f in (2,4,8,16,32,64,128):
            for base in (16,32,64,128,256,512,1024,2048,4096):
                for family in ('compute','communication'):
                    c=kv_lookup(exponent,fanout=f,base_cells=base,family=family)
                    p=price(c,sku,ssd,backend,dep)
                    candidates.append((p,c))
        p,c=min(candidates,key=lambda item:item[0]['total_upper_usd_year'])
        cases={}
        for label,be,dp in (
            ('printed_multiplication_algebra',replace(backend,repair_multiplication_count=False),dep),
            ('correlation_plus_25_percent',replace(backend,extra_correlation_fraction=.25),dep),
            ('correlation_plus_100_percent',replace(backend,extra_correlation_fraction=1.),dep),
            ('one_epoch_copy',backend,replace(dep,epoch_copies=1)),
            ('ten_independent_states',backend,replace(dep,independent_states=10)),
            ('two_internal_keccak',backend,replace(dep,internal_hashes=2)),
            ('setup_100k_ands_per_table_cell',backend,replace(dep,extra_setup_ands_per_table_cell=100_000)),
            ('setup_200k_ands_per_table_cell',backend,replace(dep,extra_setup_ands_per_table_cell=200_000)),
            ('routing_only_setup',backend,replace(dep,include_routing_only_setup=True)),
            ('all_cross_az',backend,replace(dep,az_fraction=1.))):
            cases[label]=price(c,sku,ssd,be,dp)
        # Reoptimize the same finite layout grid at each horizon. Epoch renewal
        # and continuously arriving client inputs still need a concrete protocol.
        for shift in range(-8,5):
            horizon_candidates=[]
            for f in (2,4,8,16,32,64,128):
                for base in (16,32,64,128,256,512,1024,2048,4096):
                    for family in ('compute','communication'):
                        cc=kv_lookup(exponent,horizon=2**(exponent+1+shift),fanout=f,
                                     base_cells=base,family=family)
                        pp=price(cc,sku,ssd,backend,dep)
                        horizon_candidates.append((pp,cc))
            pp,cc=min(horizon_candidates,key=lambda item:item[0]['total_upper_usd_year'])
            frontier.append(dict(log_records=exponent,horizon_shift=shift,circuit=cc,price=pp))
        results.append(dict(log_records=exponent,circuit=c,price=p,sensitivities=cases))
        print(f"2^{exponent}: {p['ands_per_query']:,.0f} AND/query; "
              f"{p['average_sent_bytes_party_query']/1e9:.2f} GB/query/party average; "
              f"network ${p['network_ec2_min_usd_year']/1e9:.2f}-{p['network_ec2_upper_usd_year']/1e9:.2f}B/year; "
              f"SSD ${p['ssd_usd_year']/1e9:.2f}B/year; "
              f"total ${p['total_min_usd_year']/1e9:.2f}-{p['total_upper_usd_year']/1e9:.2f}B/year")
    out=dict(status='Conditional source-derived accounting; additional correlation/setup costs unresolved',
        date='2026-10-13',price_source='data/aws_garbled_prices_2026-10-13.json',
        main_policy='T=2N logical queries per independent epoch; two complete epochs on SSD',
        cases=results,horizon_sensitivity=frontier)
    (ROOT/'results/garbled_ram_comparison.json').write_text(json.dumps(out,indent=2)+'\n')


if __name__=='__main__':main()
