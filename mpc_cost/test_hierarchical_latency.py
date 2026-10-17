"""Latency accounting and scheduling invariants, not AWS performance tests."""
from math import log2
import unittest

from .hierarchical_latency import ready_latency
from .hierarchical_split_cost import scenario
from .hierarchical_throughput import Deployment, directions
from .hierarchical_address import current_case, auxiliary


class HierarchicalLatencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {(ln, b): current_case(scenario(ln, 64, b))
                     for ln in (28, 32) for b in (512, 1024, 2048)}

    def test_directional_conservation_across_cache_and_distribution_modes(self):
        for key, c in self.cases.items():
            direction = directions(c)
            original_forward = direction['frontend_forward'] + direction['read_forward']
            original_reverse = direction['frontend_backward'] + direction['read_backward']
            for aux, cold in ((False, False), (True, False), (False, True), (True, True)):
                for rho in (0., .5, 1.):
                    with self.subTest(case=key, aux=aux, cold=cold, rho=rho):
                        r = ready_latency(c, 32, cache_all_aux=aux,
                                          cold_prefetch=cold, intraparty_remote_fraction=rho)
                        self.assertAlmostEqual(r['foreground_forward_after_cache_bytes_per_query'],
                            original_forward - r['cached_gc_bytes_per_query']
                            - r['cached_input_forward_bytes_per_query']
                            + r['bridge_bytes_per_query']
                            + r['intraparty_each_direction_bytes_per_query'], places=6)
                        self.assertAlmostEqual(r['foreground_reverse_bytes_per_query'],
                            original_reverse-r['cached_input_reverse_bytes_per_query']
                            + r['intraparty_each_direction_bytes_per_query'], places=6)
                        self.assertAlmostEqual(r['intraparty_each_direction_bytes_per_query'],
                            rho * r['cold_state_ebs_bytes_per_query'] / 2, places=6)
                        # Enabling auxiliary RAM caching adds no duplicate
                        # bridge if cold equality prefetch already has one.
                        if cold:
                            self.assertEqual(r['all_aux_additional_bridge_bytes_per_query'], 0)

    def test_independent_dependency_count_and_batch_fill(self):
        for key, c in self.cases.items():
            with self.subTest(case=key):
                r = ready_latency(c, 32)
                k = int(log2(c['batch']))
                # Up/down tree, inclusive pass, inverse bitonic, initial
                # input, one deferred all-table selection, address requests.
                count = 2*k + 1 + k*(k+1)//2 + 2 + c['average_occupied_tables']
                self.assertEqual(r['dependency_rtt_equivalent_units'], count)
                self.assertEqual(r['mean_batch_fill_seconds'], (c['batch']-1)/20000)
                self.assertAlmostEqual(r['mean_query_seconds_no_queue_or_rebuild'],
                    r['bandwidth_loading_service_seconds'] + count*.0002
                    + r['mean_batch_fill_seconds'])
        self.assertEqual(ready_latency(self.cases[28, 1024], 29)
                         ['dependency_rtt_equivalent_units'], 88)
        self.assertEqual(ready_latency(self.cases[32, 1024], 38)
                         ['dependency_rtt_equivalent_units'], 90)

    def test_stage_overlap_uses_maximum_not_resource_sum(self):
        dep = Deployment()
        c = self.cases[28, 1024]
        workers = 29
        b = c['batch']
        r = ready_latency(c, workers, ebs_fixed=.001, intraparty_remote_fraction=1)
        independently_summed_stages = r['frontend_service_seconds'] + r['packed_transfer_seconds']
        sum_without_overlap = independently_summed_stages
        for row in r['rows']:
            nic = dep.framing*b*max(row['online_forward_bytes_per_visit'],
                                  row['online_reverse_bytes_per_visit'])/(workers*dep.nic_active)
            disk = b*(row['state_ebs_bytes_per_visit'] + row['gc_ebs_bytes_per_visit'])/(
                workers*dep.ebs_raw*dep.ebs_efficiency)
            if row['has_ebs_stage']:
                disk += .001
            self.assertAlmostEqual(row['network_seconds'], nic)
            expected = max(nic, disk, row['dram_seconds'])
            self.assertAlmostEqual(row['service_seconds'], expected)
            independently_summed_stages += row['occupancy_weight']*expected
            sum_without_overlap += row['occupancy_weight']*(nic + disk + row['dram_seconds'])
        self.assertAlmostEqual(r['bandwidth_loading_service_seconds'], independently_summed_stages)
        self.assertLess(r['bandwidth_loading_service_seconds'], sum_without_overlap)
        # A fixed EBS delay hidden by a slower NIC is not blindly added.
        upper = r['bandwidth_loading_floor_seconds'] + .001*r['mean_cold_table_stages']
        self.assertLessEqual(r['bandwidth_loading_service_seconds'], upper + 1e-12)
        aggregate_nic_floor = dep.framing*b*max(
            r['foreground_forward_after_cache_bytes_per_query'],
            r['foreground_reverse_bytes_per_query'])/(workers*dep.nic_active)
        self.assertGreaterEqual(r['bandwidth_loading_floor_seconds'], aggregate_nic_floor - 1e-12)

    def test_zero_delays_worker_scaling_and_delay_sensitivities(self):
        for key, c in self.cases.items():
            with self.subTest(case=key):
                r = ready_latency(c, 32)
                zero = ready_latency(c, 32, rtt=0, ebs_fixed=0)
                more = ready_latency(c, 64)
                self.assertEqual(zero['mean_ready_batch_service_seconds'],
                                 zero['bandwidth_loading_floor_seconds'])
                self.assertLessEqual(more['mean_ready_batch_service_seconds'],
                                     r['mean_ready_batch_service_seconds'])
                for field in ('rtt_sensitivity', 'ebs_fixed_sensitivity'):
                    values = [x['mean_query_seconds'] for x in r[field]]
                    self.assertEqual(values, sorted(values))

    def test_auxiliary_cache_is_storage_and_bandwidth_accounted(self):
        for key, c in self.cases.items():
            with self.subTest(case=key):
                base = ready_latency(c, 32)
                aux = ready_latency(c, 32, cache_all_aux=True)
                self.assertLess(aux['foreground_forward_after_cache_bytes_per_query'],
                                base['foreground_forward_after_cache_bytes_per_query'])
                cold_rows = [r for r in c['rows'] if r['log_capacity'] > 16]
                gc = c['batch']*sum(auxiliary(r)['ram']
                                   for r in cold_rows)
                state = 2112*sum(r['global_stash']['capacity'] for r in cold_rows)
                self.assertEqual(aux['all_aux_additional_ram_bytes'], gc + state)
                self.assertAlmostEqual(aux['throughput_forward_bytes_per_query']
                    - base['throughput_forward_bytes_per_query'],
                    aux['all_aux_additional_bridge_bytes_per_query'])

    def test_bad_inputs(self):
        c = self.cases[28, 1024]
        for bad in (0, -1, True, 2.5):
            with self.assertRaises(ValueError):
                ready_latency(c, bad)
        for kwargs in ({'rtt': -1}, {'ebs_fixed': float('nan')},
                       {'intraparty_remote_fraction': 1.1}):
            with self.assertRaises(ValueError):
                ready_latency(c, 32, **kwargs)


if __name__ == '__main__':
    unittest.main()
