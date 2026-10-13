"""Size-study accounting guards, without asserting a fixed optimized bill.

These verify units, all-party billing, feasibility, and the meaning of the
memory-removal counterfactual. They do not validate MPC security or throughput.
Run: python -m unittest mpc_cost.test_size_study -v
"""
from dataclasses import replace
import json
from math import ceil, isclose
from pathlib import Path
import unittest

from mpc_cost.compare_scans import capacity_equivalent, scan_circuit
from mpc_cost.model import Backend, Deployment, Design, GIB, circuit, provision
from mpc_cost.run import load_skus


ROOT = Path(__file__).resolve().parent


class SizeStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {}
        skus = load_skus(ROOT / 'data/aws_prices_2026-10-12.json')
        for exponent, subdir in ((28, ''), (32, 'size_2p32')):
            folder = ROOT / 'results' / subdir
            summary = json.loads((folder / 'summary.json').read_text())
            saved = next(x for x in summary['scenarios'] if x['scenario'] == 'central')
            comparison = json.loads((folder / 'bottleneck_scan_comparison.json').read_text())
            design = Design(**saved['design'])
            sku = next(x for x in skus if x['name'] == saved['result']['instance'])
            cls.cases[exponent] = dict(saved=saved, comparison=comparison,
                                      design=design, sku=sku, circuit=circuit(design),
                                      deployment=Deployment(**saved['deployment']),
                                      backend=Backend(**saved['backend']))

    def assert_close(self, actual, expected):
        self.assertTrue(isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-8),
                        f'{actual!r} != {expected!r}')

    def test_database_size_and_shared_scan_storage_scale(self):
        small, large = (self.cases[e]['design'] for e in (28, 32))
        self.assertEqual(large.records, 16 * small.records)
        self.assertEqual((small.key_bytes + small.value_bytes) * small.records, 16 * GIB)
        self.assertEqual((large.key_bytes + large.value_bytes) * large.records, 256 * GIB)
        for mode in ('full_key', 'indexed_2d'):
            a, b = scan_circuit(small, mode), scan_circuit(large, mode)
            # The fixed cuckoo stash belongs to each database, not to every row.
            stash = ((small.cuckoo_stash * 6 * small.field_bytes * small.share_words)
                     if mode == 'indexed_2d' else 0)
            self.assertEqual(b['state_bytes_party'] - stash,
                             16 * (a['state_bytes_party'] - stash))
            # Concurrent query tiling never implies another immutable database.
            other_batch = scan_circuit(replace(large, batch=64), mode)
            self.assertEqual(b['state_bytes_party'], other_batch['state_bytes_party'])

    def test_saved_design_and_recursion_stop_are_consistent(self):
        for exponent, case in self.cases.items():
            with self.subTest(exponent=exponent):
                d, c = case['design'], case['circuit']
                self.assertEqual(d.records, 1 << exponent)
                self.assertEqual(c['dense_cells'], 4 * d.records)
                self.assertEqual(c['actual_cuckoo_load'], .25)
                self.assertEqual(c['base_cells'], c['levels'][-1]['records'])
                requests_per_table = 2 * d.batch // d.cuckoo_tables
                next_records = ceil(c['base_cells'] / d.fanout)
                self.assertTrue(c['base_cells'] <= d.base_cutoff
                                or next_records < 2 * requests_per_table)
                self.assert_close(c['state_bytes_party'] / GIB,
                                  case['saved']['result']['state_gib_per_party_per_replica'])

    def test_all_party_bill_and_target_capacity(self):
        for exponent, case in self.cases.items():
            with self.subTest(exponent=exponent):
                d, dep, sku = case['design'], case['deployment'], case['sku']
                saved = case['saved']['result']
                result = provision(case['circuit'], sku,
                                   saved['nodes_per_party_per_replica'], dep, case['backend'])
                self.assertIsNotNone(result)
                expected_instances = d.parties * result['replicas'] * result['nodes_per_party_per_replica']
                self.assertEqual(result['total_instances'], expected_instances)
                self.assert_close(result['compute_usd_year'], expected_instances * sku['hourly_usd'] * 8760)
                self.assertGreaterEqual(result['aggregate_capacity_qps'] * dep.utilization, d.rate)
                self.assertLessEqual(result['model_mean_seconds'], dep.mean_latency_limit)
                self.assert_close(result['total_usd_year'], saved['total_usd_year'])
                self.assert_close(result['usd_per_million'], result['total_usd_year'] * 1e6
                                  / (d.rate * 365 * 24 * 3600))

    def test_large_case_memory_minimum_and_counterfactual(self):
        case = self.cases[32]
        c, sku, dep, backend = (case[x] for x in ('circuit', 'sku', 'deployment', 'backend'))
        selected_k = case['saved']['result']['nodes_per_party_per_replica']
        fits = [k for k in range(1, selected_k + 1)
                if provision(c, sku, k, dep, backend) is not None]
        self.assertTrue(fits)
        minimum = min(fits)
        lower_from_state = ceil(c['state_bytes_party'] * (1 + dep.scratch_fraction)
                                / (sku['memory_gib'] * GIB * dep.memory_usable))
        self.assertGreaterEqual(minimum, lower_from_state)
        self.assertLessEqual(minimum, selected_k)
        self.assertIsNone(provision(c, sku, minimum - 1, dep, backend))
        sufficient = provision(c, sku, minimum, dep, backend)
        self.assertLessEqual(sufficient['memory_required_gib_per_party_per_replica'],
                             minimum * sku['memory_gib'] * dep.memory_usable)

        without_memory = case['comparison']['oram_without_storage_constraint']
        unbounded_sku = dict(sku, memory_gib=1e20)
        counter_k = without_memory['nodes_per_party_per_replica']
        result = provision(c, unbounded_sku, counter_k, dep, backend)
        self.assert_close(result['total_usd_year'], without_memory['total_usd_year'])
        self.assertLess(counter_k, minimum)
        self.assertIsNone(provision(c, sku, counter_k, dep, backend))
        self.assertTrue(result['meets_mean_limit'])
        # Removing capacity must preserve cryptographic work, traffic, and depth.
        for key in ('reductions_per_read', 'random_bits_per_read',
                    'sent_mb_per_party_read', 'state_gib_per_party_per_replica', 'phases'):
            self.assert_close(result[key], case['saved']['result'][key])
        # Independently search integer K, without hardcoding the selected bill/K.
        candidates = [provision(c, unbounded_sku, k, dep, backend)
                      for k in range(1, 2 * selected_k + 1)]
        feasible = [x for x in candidates if x['meets_mean_limit']]
        best = min(feasible, key=lambda x: x['total_usd_year'])
        self.assert_close(result['total_usd_year'], best['total_usd_year'])

    def test_common_capacity_envelope_is_separate_from_replica_schedule(self):
        for exponent, case in self.cases.items():
            with self.subTest(exponent=exponent):
                c, sku, dep, backend = (case[x] for x in ('circuit', 'sku', 'deployment', 'backend'))
                result = capacity_equivalent(c, sku, dep, backend)
                k = result['resource_nodes_per_party']
                self.assertEqual(k, max(result[name] for name in
                                        ('cpu_nodes_per_party', 'network_nodes_per_party',
                                         'ram_bandwidth_nodes_per_party', 'memory_nodes_per_party_one_shared_copy')))
                self.assert_close(result['annual_resource_equivalent_usd'],
                                  k * case['design'].parties * sku['hourly_usd'] * 8760)
                saved = case['comparison']['rows'][0]['capacity_equivalent']
                self.assert_close(result['annual_resource_equivalent_usd'],
                                  saved['annual_resource_equivalent_usd'])
                # Resource-only accounting is not silently reported as the
                # memory- and latency-constrained dedicated replica fleet.
                self.assertLess(result['annual_resource_equivalent_usd'],
                                case['saved']['result']['compute_usd_year'])


if __name__ == '__main__':
    unittest.main()
