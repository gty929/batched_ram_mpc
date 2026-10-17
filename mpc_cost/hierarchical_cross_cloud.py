"""Cross-cloud planning budget using the current hierarchical ORAM ledger.

Run: python -m mpc_cost.hierarchical_cross_cloud

AWS hosts the garbler; Google hosts the evaluator. The private path combines
AWS flat-rate Direct Connect and Google Cross-Cloud Interconnect. Network
capacity covers both worker pools' entire modeled active NIC bandwidth at
once, so the existing scheduler need not assume extra WAN pacing. This is
a conservative sufficient bandwidth reservation, not a minimum-cost design.
Both parties' compute and storage use the existing AWS-equivalent price proxy.
"""
from math import ceil
from pathlib import Path
import json

from .hierarchical_address import current_case
from .hierarchical_annual import annual_case
from .hierarchical_communication_audit import audit
from .hierarchical_schedule import provision, simulate
from .hierarchical_split_cost import scenario
from .hierarchical_throughput import Deployment

ROOT = Path(__file__).resolve().parent
HOURS_YEAR = 8760
SECONDS_YEAR = HOURS_YEAR * 3600


def network_budget(c, prices, workers_per_party=None, qps=10_000,
                   average_utilization=.70, burst_utilization=.90):
    """Charge cross-party sends only, once, in their respective directions."""
    dep = Deployment(qps=qps)
    wire = audit(c)['deployment']
    forward = dep.framing * wire['unframed_interparty_forward']
    reverse = dep.framing * wire['unframed_interparty_reverse']
    queries = qps * SECONDS_YEAR
    rate = prices['derived_redundant_bundle']
    google = prices['google_cross_cloud_interconnect']
    bundle_bps = rate['usable_capacity_gbps'] * 1e9
    average_bps = max(forward, reverse) * qps * 8
    average_bundles = ceil(average_bps / average_utilization / bundle_bps)
    # This also covers intra-party bandwidth even though it never uses the
    # WAN. Reserving this upper bound avoids assuming favorable burst overlap.
    burst_bps = (workers_per_party * dep.nic_active * 8
                 if workers_per_party is not None else None)
    bundles = max(average_bundles,
                  ceil(burst_bps / burst_utilization / bundle_bps)
                  if burst_bps is not None else 0)
    fixed = bundles * rate['usd_per_hour'] * HOURS_YEAR
    reverse_cost = (reverse * queries / google['egress_billing_unit_bytes']
                    * google['egress_usd_per_gib'])
    return dict(
        framed_forward_bytes_per_query=forward,
        framed_reverse_bytes_per_query=reverse,
        framed_total_bytes_per_query=forward+reverse,
        forward_bits_second=forward*qps*8,
        reverse_bits_second=reverse*qps*8,
        forward_bytes_year=forward*queries,
        reverse_bytes_year=reverse*queries,
        average_link_utilization_target=average_utilization,
        burst_link_utilization_limit=burst_utilization,
        worker_pool_burst_bits_second=burst_bps,
        average_only_100gbps_bundles=average_bundles,
        provisioned_100gbps_bundles=bundles,
        fixed_link_year=fixed, google_reverse_egress_year=reverse_cost,
        total_network_year=fixed+reverse_cost,
        average_only_network_year=(average_bundles*rate['usd_per_hour']
                                   *HOURS_YEAR+reverse_cost),
        average_only_note='Average-traffic budget only; does not establish latency or burst capacity.',
        capacity_policy=('Entire active NIC bandwidth of foreground and background pools simultaneously'
                         if burst_bps is not None else 'Average traffic only; no WAN schedule claimed'))


def main():
    prices = json.loads((ROOT/'data/cross_cloud_prices_2026-10-17.json').read_text())
    result = dict(
        prices=prices, qps=10_000, record_key_bytes=32, record_value_bytes=32,
        policy=dict(
            garbler='AWS us-east-1', evaluator='Google us-east4',
            independent_states=7, pool_utilization_target=.90,
            pricing_proxy='Both parties use existing AWS instance/gp3 prices for compute and storage',
            cpu_model='Existing model: CPU cost is assumed hidden by transfer/loading, not benchmarked',
            latency='Assumed RTT; finite deterministic scheduler traces, not measurements',
            workload='Flat private key-value reads; no application-write replication or MPT traversal',
            bandwidth='Full simultaneous modeled NIC bursts reserved; 10% link-capacity headroom',
            excluded='Initial construction, client transport, taxes, support, optional middleboxes and third-party fees'),
        batch2048_traffic_reference=[], scheduled_scenarios=[])
    for log_n in (28, 32):
        c = current_case(scenario(log_n, 64, 2048))
        result['batch2048_traffic_reference'].append(dict(
            log_records=log_n, batch=2048, network=network_budget(c, prices)))
    for batch, rtt in ((16384, .005), (32768, .010)):
        for log_n in (28, 32):
            c = current_case(scenario(log_n, 64, batch))
            s = provision(c, replicas=7, utilization=.90, rtt_seconds=rtt,
                          intraparty_remote_fraction=1.,
                          cold_bucket_load_seconds=.0005,
                          preload_all_stash_prf=True)
            trace = simulate(c, s, cycles=2)
            infra = annual_case(c, trace)
            net = network_budget(c, prices, infra['workers_per_party'])
            total = infra['total_year'] + net['total_network_year']
            row = dict(log_records=log_n, batch=batch, rtt_seconds=rtt,
                       infrastructure=infra, network=net, total_year=total,
                       dollars_per_million_queries=total/infra['queries_per_year']*1e6)
            # Check that priced WAN bandwidth cannot constrain either modeled
            # pool, even when both consume their full active NIC rates.
            usable = net['provisioned_100gbps_bundles']*100e9*.90
            assert usable >= net['worker_pool_burst_bits_second']
            assert abs(net['framed_total_bytes_per_query']
                       - audit(c)['deployment']['framed_interparty_total']) < 1e-6
            result['scheduled_scenarios'].append(row)
            print(json.dumps(dict(logN=log_n, batch=batch, rtt_ms=rtt*1000,
                  workers_per_party=infra['workers_per_party'],
                  mean_seconds=trace['mean_query_seconds'],
                  p99_seconds=trace['p99_query_seconds'],
                  max_queue_seconds=trace['max_queue_seconds'],
                  bundles=net['provisioned_100gbps_bundles'],
                  infrastructure_million=infra['total_year']/1e6,
                  network_million=net['total_network_year']/1e6,
                  total_million=total/1e6)), flush=True)
    path = ROOT/'results/hierarchical_cross_cloud.json'
    path.write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
