"""Sequential evaluator correction to the two-party capacity study.

Run python -m mpc_cost.two_party_serial. The independently evolving state
count is DERIVED from per-state service time, never from aggregate gate/NIC
throughput. Inputs below are paper anchors or explicitly unmeasured scenarios.
No small-reset implementation or measured large-merge latency is asserted.
"""
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import json

from .two_party_cost import core_layout, gram_case
from .two_party_merge import visited_evaluator_merge

ROOT = Path(__file__).resolve().parent


def required_states(service_seconds, qps=10_000, utilization=.7, batch=1):
    if service_seconds <= 0 or qps <= 0 or not 0 < utilization <= 1 or batch < 1:
        raise ValueError('Positive service, rate and batch; utilization in (0,1]')
    # Decimal prevents an exact boundary such as70ms from rounding to1001 states.
    amount = Decimal(str(service_seconds))*Decimal(str(qps))
    amount /= Decimal(str(utilization))*Decimal(str(batch))
    return int(amount.to_integral_value(rounding=ROUND_CEILING))


def serial_core(n, and_ns=53.2583, xor_ns=6.322):
    """Old2.2GHz artifact scalar microkernel proxy, NOT a measured service.

    Two table lanes run the independent probes concurrently; their final exact
    KV matching circuit follows. No64-core speedup of one state is presumed.
    Omitted merge, bindings, label I/O, runtime and renewal can be substantial.
    Finer vectorization/parallelism could reduce these scalar-kernel times.
    """
    c = core_layout(n)
    a, x = c['visited_ands'], c['visited_xors']
    pa, px = c['probe']['visited_ands'], c['probe']['visited_xors']
    app_a, app_x = a-2*pa, x-2*px
    total = (a*and_ns+x*xor_ns)*1e-9
    per_probe = (pa*and_ns+px*xor_ns)*1e-9
    app = (app_a*and_ns+app_x*xor_ns)*1e-9
    return dict(log_records=n, visited_ands=a, visited_xors=x,
                scalar_microkernel_and_ns=and_ns, scalar_microkernel_xor_ns=xor_ns,
                one_probe_seconds=per_probe, final_match_seconds=app,
                single_worker_core_seconds=total,
                two_table_lane_core_seconds=per_probe+app,
                scalar_core_seconds_per_query=total,
                complete_service_time=False, is_hardware_lower_bound=False,
                missing=['merge evaluation','output language bindings','state and program I/O',
                         'runtime overhead','input handling','epoch transition'])


def optimize_conditional_capacity(n, service_seconds, min_log_horizon=8):
    """Fixed service-time SCENARIO, then optimize existing retention policy.

    True implementation optimization must supply service_seconds(T, variant).
    This sensitivity holds time fixed acrossT and does not certify that a
    reset/epoch implementation achieves it. Two full epochs and label-state
    snapshots remain the previous retention policy, not a space lower bound.
    """
    states = required_states(service_seconds)
    candidates = [gram_case(n, 1 << t, states=states)
                  for t in range(min_log_horizon, n+5)]
    chosen = min(candidates, key=lambda c:c['price']['network_plus_capacity_usd_year'])
    # One serial evaluator worker per active state can share a64-core host.
    # For scenarios that include I/O waits, wall time is NOT CPU-active time;
    # consequently evaluator CPU is explicitly not inferred here.
    return dict(assumed_state_service_seconds=service_seconds,
                required_independent_states=states,
                maximum_allowed_seconds=states*.7/10_000,
                selected_horizon=chosen['horizon'],
                horizon_log_grid=[min_log_horizon,n+4],
                optimum_at_grid_boundary=chosen['horizon'] in (1<<min_log_horizon,1<<(n+4)),
                epoch_duration_seconds_per_state=chosen['epoch_duration_seconds'],
                price=chosen['price'],
                does_not_establish_latency_achievability=True,
                horizon_dependent_service_time_not_yet_implemented=True)


def scalar_merge_sensitivity(n, window, lanes=1, min_log_horizon=8):
    """Horizon-dependent ACTIVE-path workload sensitivity, not a benchmark.

    The paper reports about40 cycles/hash on2.2GHz. Multiplying hash count by
    this scalar time models a scalar executor, not a proved circuit-span lower
    bound: word-level SIMD/finer parallelism could improve it. The hypothetical
    reset's phase distribution, full child capacity and missing reset gates
    are documented in visited_evaluator_merge. I/O is excluded.
    """
    if lanes not in (1,2):
        raise ValueError('Choose one worker or two independent table lanes')
    core_proxy = serial_core(n)
    core_seconds = core_proxy['single_worker_core_seconds' if lanes == 1
                               else 'two_table_lane_core_seconds']
    hash_seconds = 40/2.2e9
    choices = []
    for t in range(min_log_horizon,n+5):
        c = core_layout(n,1 << t)
        merge = visited_evaluator_merge(c,window)
        hashes = merge['expected_hashes_per_query' if lanes == 1
                       else 'expected_hashes_per_probe']
        service = core_seconds+hashes*hash_seconds
        states = required_states(service)
        priced = gram_case(n,1 << t,states)
        choices.append(dict(window=window,independent_table_lanes=lanes,
                            horizon=1 << t,modeled_core_seconds=core_seconds,
                            modeled_merge_seconds=hashes*hash_seconds,
                            modeled_state_service_seconds=service,
                            required_independent_states=states,
                            scalar_hash_seconds=hash_seconds,
                            parallel_lane_time_model=('equal-lane mean-work approximation; '
                                                      'E[max(lane times)] can be larger' if lanes == 2
                                                      else 'single evaluator lane'),
                            visited_merge_count=merge,price=priced['price'],
                            is_measurement=False,is_parallel_span_bound=False,
                            hypothetical_reset_phase_model=True,
                            excludes_reset_cost_and_io=True))
    return min(choices,key=lambda c:c['price']['network_plus_capacity_usd_year'])


def main():
    rows = []
    for n in (28,32):
        core = serial_core(n)
        core_rows = {}
        for variant,key in [('one_worker','single_worker_core_seconds'),
                            ('two_table_lanes','two_table_lane_core_seconds')]:
            core_rows[variant] = optimize_conditional_capacity(n,core[key])
            core_rows[variant]['excludes_merge_and_io'] = True
        scenarios = [optimize_conditional_capacity(n,t)
                     for t in (.05,.1,.5,1.,5.)]
        merge_scenarios = [scalar_merge_sensitivity(n,k,lanes)
                           for k in (64,256) for lanes in (1,2)]
        rows.append(dict(log_records=n,core_proxy=core,core_only_sensitivities=core_rows,
                         complete_service_time_scenarios=scenarios,
                         scalar_active_merge_sensitivities=merge_scenarios))
    paper_anchors = []
    for logn,ms,source in [(16,9.73,'reported small-instance timing'),
                           (24,25.,'paper extrapolation'),(30,41.,'paper extrapolation')]:
        paper_anchors.append(dict(ram_address_bits=logn,word_bits=64,
                                  per_ram_access_seconds=ms/1000,source_kind=source,
                                  variant='online optimized; no SIMD/DDH',
                                  one_probe_states=required_states(ms/1000),
                                  two_serial_probes_states=required_states(2*ms/1000)))
    result = dict(as_of='2026-10-14',qps=10_000,utilization=.7,
                  paper='https://eprint.iacr.org/2025/1479',
                  local_paper='2025-1479.pdf',paper_pages=[6,33,34,35,64,66],
                  main_correction='Aggregate evaluator work capacity does not supply parallelism within one state.',
                  previous_small_replica_scenarios_are_not_throughput_estimates=True,
                  paper_anchors=paper_anchors,rows=rows,
                  source_warnings=['Paper timing/communication columns optimize different variants.',
                                   '41ms is64-bit single-probe PicoGRAM, not a512-bit KV or Garbled Merge measurement.',
                                   '8-core platform does not establish8x symmetric evaluator speedup.',
                                   'Core scalar microkernels are unvalidated on current EC2 hardware.',
                                   'Capacity costs omit full CPU, initialization, secure renewal and I/O.'])
    (ROOT/'results'/'two_party_serial_comparison.json').write_text(
        json.dumps(result,indent=2)+'\n',encoding='utf-8')
    for row in rows:
        print(f'N=2^{row["log_records"]}')
        for v in row['complete_service_time_scenarios']:
            p=v['price']
            print(f'  t={v["assumed_state_service_seconds"]:.3f}s, '
                  f'states={v["required_independent_states"]:,}, '
                  f'T=2^{v["selected_horizon"].bit_length()-1}, '
                  f'network+retention=${p["network_plus_capacity_usd_year"]/1e9:.3f}B/year')


if __name__ == '__main__':
    main()
