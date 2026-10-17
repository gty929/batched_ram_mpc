"""Resource conservation and independent cache-probability checks."""
import json
from math import comb
from pathlib import Path
import unittest

from .hierarchical_cache import lookahead_statistics, adaptive_plan, cache_plan
from .hierarchical_throughput import analyze, directions, Deployment
from .hierarchical_address import current_case

ROOT=Path(__file__).resolve().parent


class ThroughputChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=json.loads((ROOT/'results/hierarchical_split_comparison.json').read_text())['primary']
        cls.cases += [current_case(c) for c in cls.cases]

    def test_directions_conserve_original_protocol_traffic(self):
        for c in self.cases:
            d=directions(c)
            self.assertAlmostEqual(d['forward']+d['backward'],c['total_unframed_bytes_per_query'],places=5)
            self.assertAlmostEqual(d['read_forward']+d['read_backward'],c['read_unframed_bytes_per_query'],places=5)
            self.assertAlmostEqual(d['rebuild_forward']+d['rebuild_backward'],c['rebuild_unframed_bytes_per_query'],places=5)

    def test_utilization_is_not_charged_twice_to_active_service(self):
        dep=Deployment()
        for c in self.cases:
            r=analyze(c,dep)
            self.assertAlmostEqual(r['top_rebuild_active_seconds']/dep.utilization,
                                   r['top_rebuild_reserved_rate_seconds'])
            rate=r['network_qps_at_selected_fleet']
            self.assertGreaterEqual(rate,dep.qps)
            self.assertLess((r['network_nodes_per_party']-1)*r['network_qps_per_worker_pair'],dep.qps)

    def test_independent_tiled_reconstruction_and_spill_ordering(self):
        for c in self.cases:
            r=analyze(c)
            io=r['io_scenarios']
            helper=r['state_io']['per_party_read_plus_write_bytes_per_query']
            self.assertAlmostEqual(io['tiled']['bytes_per_query'],helper['tiled_small_kernels_global_layers_spilled'],places=6)
            self.assertLess(io['resident_scratch']['bytes_per_query'],io['tiled']['bytes_per_query'])
            self.assertLess(io['tiled']['bytes_per_query'],io['every_switch_spilled']['bytes_per_query'])

    def test_binomial_expected_shortfall_against_explicit_distribution(self):
        for b in range(1,14):
            for m in range(1,10):
                p=1/m
                for w in range(b+1):
                    direct=sum(max(x-w,0)*comb(b,x)*p**x*(1-p)**(b-x)
                               for x in range(b+1))*m/b
                    self.assertAlmostEqual(lookahead_statistics(b,m,w)['expected_miss_fraction'],direct,places=12)

    def test_adaptive_windows_meet_performance_budget_and_base_burst(self):
        c=self.cases[0]
        fixed=cache_plan(c)
        self.assertAlmostEqual(fixed['rows'][0]['maximum_hit_fraction_from_capacity'],.125)
        plan=adaptive_plan(c)
        self.assertLessEqual(plan['batch_any_miss_probability_upper_bound'],1e-3)
        for r in plan['rows']:
            self.assertGreater(lookahead_statistics(c['batch'],r['buckets'],r['lookahead']-1)
                               ['batch_any_miss_probability_upper_bound'],plan['per_table_any_miss_budget'])
        self.assertLess(plan['skip_final_refill_waste_bytes_per_query'],
                        plan['full_window_retirement_waste_bytes_per_query'])


if __name__=='__main__':
    unittest.main()
