"""Regression checks for the cost model and executable algebraic witnesses.

The witnesses verify mathematical building blocks underlying the estimates.
They are cleartext tests, not an MPC implementation or a security proof.
Run with ``python -m unittest mpc_cost.test_model -v``.
"""
from dataclasses import replace
import math
import random
import unittest

from mpc_cost.model import (
    Design, Deployment, SECONDS_YEAR, circuit, provision,
    queue_simulation, traffic,
)


def one_hot_witness(index: int, bits: int, valid: int = 1):
    """A gated binary decoder using one product per internal tree node."""
    selectors = [valid]
    products = 0
    for offset in range(bits - 1, -1, -1):
        bit = (index >> offset) & 1
        children = []
        for parent in selectors:
            right = parent * bit
            products += 1
            children.extend((parent - right, right))
        selectors = children
    return selectors, products


def compare_witness(x: int, y: int, bits: int):
    """Balanced (equal, less-than) arithmetic-bit comparison."""
    nodes = []
    products = 0
    for offset in range(bits - 1, -1, -1):
        a, b = (x >> offset) & 1, (y >> offset) & 1
        ab = a * b
        products += 1
        nodes.append((1 - a - b + 2 * ab, b - ab))
    while len(nodes) > 1:
        combined = []
        for i in range(0, len(nodes), 2):
            if i + 1 == len(nodes):
                combined.append(nodes[i])
                continue
            equal_hi, less_hi = nodes[i]
            equal_lo, less_lo = nodes[i + 1]
            combined.append((equal_hi * equal_lo,
                             less_hi + equal_hi * less_lo))
            products += 2
        nodes = combined
    return (*nodes[0], products)


def fermat_witness(x: int):
    """Evaluate x^(p-1), p=2^127-1, using the stated 135-product chain."""
    prime = (1 << 127) - 1
    values = {1: x % prime}
    products = 0
    # A_(a+b) = A_a^(2^b) * A_b; A_k = x^(2^k-1).
    for a, b in ((1, 1), (2, 1), (3, 3), (6, 1), (7, 7),
                 (14, 14), (28, 28), (56, 7), (63, 63)):
        value = values[a]
        for _ in range(b):
            value = value * value % prime
            products += 1
        values[a + b] = value * values[b] % prime
        products += 1
    power = values[126] * values[126] % prime
    return 1 - power, products + 1


class ArithmeticWitnessTests(unittest.TestCase):
    def test_gated_decoder_selects_exactly_one_slot(self):
        for bits in range(1, 7):
            for index in range(1 << bits):
                for valid in (0, 1):
                    selectors, count = one_hot_witness(index, bits, valid)
                    self.assertEqual(selectors,
                                     [int(i == index) * valid for i in range(1 << bits)])
                    self.assertEqual(count, (1 << bits) - 1)

    def test_aggregated_updates_require_duplicate_representatives(self):
        old = [11, 23, 37, 41, 53, 67, 79, 83]
        requests = [(5, 101), (2, 103), (5, 107), (0, 109), (2, 113)]
        expected = old.copy()
        for index, value in requests:
            expected[index] = value
        # Reference last-write-wins representatives; the circuit must hide this
        # grouping. Test the algebra after those valid bits have been computed.
        selectors = []
        deltas = []
        for i, (index, value) in enumerate(requests):
            valid = int(not any(j == index for j, _ in requests[i + 1:]))
            selected, _ = one_hot_witness(index, 3, valid)
            selectors.append(selected)
            deltas.append(value - old[index])
        actual = [value + sum(s[j] * delta for s, delta in zip(selectors, deltas))
                  for j, value in enumerate(old)]
        self.assertEqual(actual, expected)
        ungated = old.copy()
        for index, value in requests:
            ungated[index] += value - old[index]
        self.assertNotEqual(ungated, expected)

    def test_bit_comparator_exhaustive_including_non_power_of_two_widths(self):
        for bits in range(1, 6):
            for x in range(1 << bits):
                for y in range(1 << bits):
                    equal, less, products = compare_witness(x, y, bits)
                    self.assertEqual((equal, less), (int(x == y), int(x < y)))
                    self.assertEqual(products, 3 * bits - 2)

    def test_exact_fermat_chain_has_135_products(self):
        prime = (1 << 127) - 1
        rng = random.Random(20261012)
        cases = [0, 1, 2, prime - 1, prime, 2 * prime]
        cases += [rng.randrange(prime) for _ in range(32)]
        for x in cases:
            result, products = fermat_witness(x)
            self.assertEqual(result, int(x % prime == 0))
            self.assertEqual(result, 1 - pow(x, prime - 1, prime))
            self.assertEqual(products, 135)


class CircuitRegressionTests(unittest.TestCase):
    def test_flat_base_is_position_map_of_last_real_tree(self):
        d = Design(records=2**16, batch=32, fanout=8, base_cutoff=128)
        c = circuit(d)
        self.assertEqual([level['records'] for level in c['levels']],
                         [131072, 16384, 2048, 256])
        self.assertEqual(c['base_cells'], 256)
        self.assertEqual(c['base_cells'], c['levels'][-1]['records'])
        # Another recursive tree would have fewer leaves than 2*batch. Its
        # record count is NOT the correct size of the current flat position map.
        self.assertLess(c['base_cells'] // d.fanout, 2 * d.batch)
        self.assertNotEqual(c['base_cells'], c['levels'][-1]['records'] // d.fanout)

    def test_bit_metadata_costs_memory_and_record_movement(self):
        d = Design(records=2**12, batch=8, fanout=8, base_cutoff=128,
                   sort_method='bitonic')
        compact = circuit(d)
        bits = circuit(replace(d, metadata='bits'))
        self.assertGreater(bits['state_bytes_party'], compact['state_bytes_party'])
        self.assertLess(bits['work']['random_bits'], compact['work']['random_bits'])
        # Cleanup needs no A2B in either mode. More stored metadata must also
        # increase circuit movement, not just the advertised memory footprint.
        for a, b in zip(compact['levels'], bits['levels']):
            self.assertGreater(b['pool_phases']['pool_cleanup']['reductions'],
                               a['pool_phases']['pool_cleanup']['reductions'])

    def test_fermat_chain_count_is_used_for_each_additional_stash_key(self):
        d = Design(records=1024, batch=8, fanout=8, base_cutoff=64,
                   cuckoo_stash=0)
        empty, one = circuit(d), circuit(replace(d, cuckoo_stash=1))
        # 256-bit keys need three injective <=126-bit field limbs. Each limb
        # uses the independently checked chain above, then two AND products.
        expected_extra = d.batch * (3 * 135 + 2)
        self.assertAlmostEqual(one['work']['reductions'] - empty['work']['reductions'],
                               expected_extra)

    def test_supported_parameter_grid_has_finite_nonnegative_work(self):
        for batch in (1, 8, 32):
            for metadata in ('compact', 'bits'):
                c = circuit(Design(records=4096, batch=batch, metadata=metadata,
                                   fanout=16, base_cutoff=64))
                self.assertGreater(c['state_bytes_party'], 0)
                self.assertLess(c['actual_cuckoo_load'], .5)
                for key, value in c['work'].items():
                    with self.subTest(batch=batch, metadata=metadata, quantity=key):
                        self.assertTrue(math.isfinite(value))
                        self.assertGreaterEqual(value, 0)
                for level in c['levels']:
                    self.assertGreaterEqual(level['tree_bytes'], 0)

    def test_backend_rejects_unmodeled_corruption_threshold(self):
        with self.assertRaises(ValueError):
            circuit(Design(parties=10, threshold=3))
        with self.assertRaises(ValueError):
            circuit(Design(parties=3, threshold=1))


class PricingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = circuit(Design(records=1024, batch=8, fanout=8, base_cutoff=64))
        # Synthetic hardware removes memory-fit ambiguity from billing tests;
        # these numbers are not an AWS instance or a performance prediction.
        cls.sku = dict(name='test-machine', memory_gib=1_000_000, vcpu=64,
                       network_gbps=100, hourly_usd=3.25)
        cls.dep = Deployment(az_fraction=.5, prep_buffer_seconds=0,
                             local_products_per_sec_64vcpu=2e9)

    def test_compute_pays_all_ten_parties_and_every_replica(self):
        p = provision(self.c, self.sku, 2, self.dep)
        self.assertIsNotNone(p)
        expected_machines = p['replicas'] * 2 * 10
        self.assertEqual(p['total_instances'], expected_machines)
        self.assertAlmostEqual(p['compute_usd_year'],
                               expected_machines * 3.25 * 8760)
        self.assertGreaterEqual(p['aggregate_capacity_qps'], self.c['design']['rate'])

    def test_transfer_counts_each_wire_send_once_and_all_parties(self):
        p = provision(self.c, self.sku, 1, self.dep)
        sent = traffic(self.c)['sent_bytes_party_batch']
        batches_per_year = (self.c['design']['rate'] * SECONDS_YEAR
                            / self.c['design']['batch'])
        expected = sent * batches_per_year * 10 / 1e9 * .5 * .02
        self.assertTrue(math.isclose(p['transfer_usd_year'], expected, rel_tol=1e-12))
        free = provision(self.c, self.sku, 1, replace(self.dep, az_fraction=0))
        self.assertEqual(free['transfer_usd_year'], 0)
        self.assertEqual(free['compute_usd_year'], p['compute_usd_year'])

    def test_extra_replicas_do_not_charge_same_query_traffic_again(self):
        normal = provision(self.c, self.sku, 1, self.dep)
        extra = provision(self.c, self.sku, 1, replace(self.dep, utilization=.1))
        self.assertGreater(extra['replicas'], normal['replicas'])
        self.assertGreater(extra['compute_usd_year'], normal['compute_usd_year'])
        self.assertEqual(extra['transfer_usd_year'], normal['transfer_usd_year'])

    def test_annual_and_per_million_prices_are_consistent(self):
        p = provision(self.c, self.sku, 1, self.dep)
        millions = self.c['design']['rate'] * SECONDS_YEAR / 1e6
        self.assertTrue(math.isclose(p['usd_per_million'] * millions,
                        p['compute_usd_year'] + p['transfer_usd_year'], rel_tol=1e-12))


class QueueRegressionTests(unittest.TestCase):
    def test_light_load_includes_batch_formation_wait(self):
        q = queue_simulation(batch=8, rate=80, service=.01, replicas=1,
                             batches=3000, seed=11, service_cv=0,
                             response_seconds=0)
        expected = .01 + (8 - 1) / (2 * 80)
        self.assertAlmostEqual(q['mean_seconds'], expected, delta=.003)
        self.assertLess(q['mean_dispatch_queue_seconds'], .001)
        self.assertGreaterEqual(q['p99_seconds'], q['p95_seconds'])

    def test_insufficient_capacity_accumulates_dispatch_queue(self):
        args = dict(batch=8, rate=100, service=.1, batches=1600,
                    seed=29, service_cv=0, response_seconds=0)
        overloaded = queue_simulation(replicas=1, **args)  # capacity80 QPS
        provisioned = queue_simulation(replicas=2, **args)  # capacity160 QPS
        self.assertGreater(overloaded['mean_dispatch_queue_seconds'], 1)
        self.assertLess(provisioned['mean_dispatch_queue_seconds'], .05)
        self.assertGreater(overloaded['mean_seconds'], 5 * provisioned['mean_seconds'])
        self.assertGreaterEqual(provisioned['p95_seconds'], .1)


if __name__ == '__main__':
    unittest.main()
