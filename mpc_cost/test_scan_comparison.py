"""Algebraic witnesses and accounting regressions for the scan comparison.

These cleartext witnesses establish the formulas being priced, not MPC security
or distributed implementation performance. Run with:
    python -m unittest mpc_cost.test_scan_comparison -v
"""
from copy import deepcopy
from dataclasses import replace
from itertools import product
import json
import math
from pathlib import Path
import random
import unittest

from mpc_cost.compare_scans import phase_split, scan_circuit
from mpc_cost.model import (
    Backend, Deployment, Design, GIB, Work, canonical_bits, circuit,
    provision, traffic,
)
from mpc_cost.run import load_skus


PRIME = (1 << 127) - 1


def norm_equality_witness(x, y, prime=PRIME):
    """Three-limb equality: valid because -1 is nonsquare when p=3 mod4."""
    d0, d1, d2 = ((a - b) % prime for a, b in zip(x, y))
    first = (d0*d0 + d1*d1) % prime
    second = (first*first + d2*d2) % prime
    return 1 - pow(second, prime - 1, prime)


def tagged_key(key: int, occupied: int = 1):
    """Inject a 256-bit key and occupancy into three <=126-bit limbs."""
    mask = (1 << 126) - 1
    return (key & mask, (key >> 126) & mask,
            (key >> 252) + (occupied << 4))


def lookup_witness(rows, key):
    matches = [norm_equality_witness(stored_key, tagged_key(key))
               for stored_key, _ in rows]
    return sum(matches), sum(hit * value for hit, (_, value) in zip(matches, rows))


def two_dimensional_dot_witness(records, row_count, column_count, index):
    """Cleartext witness for high-bit row, low-bit column selection."""
    row, column = divmod(index, column_count)
    row_selector = [int(i == row) for i in range(row_count)]
    column_selector = [int(j == column) for j in range(column_count)]
    words = len(records[0])
    contracted = [
        [sum(column_selector[j] * records[i * column_count + j][w]
             for j in range(column_count)) for w in range(words)]
        for i in range(row_count)
    ]
    return tuple(sum(row_selector[i] * contracted[i][w]
                     for i in range(row_count)) for w in range(words))


class ScanComparisonTests(unittest.TestCase):
    def assert_close(self, actual, expected):
        self.assertTrue(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-8),
                        f'{actual!r} != {expected!r}')

    def test_nested_norm_exactness_and_prime_condition(self):
        for prime in (3, 7, 11, 19):
            for differences in product(range(prime), repeat=3):
                self.assertEqual(norm_equality_witness(differences, (0, 0, 0), prime),
                                 int(differences == (0, 0, 0)))
        rng = random.Random(20261013)
        cases = [(0, 0, 0), (1, 0, 0), (0, PRIME-1, 0), (0, 0, PRIME-1)]
        cases.extend(tuple(rng.randrange(PRIME) for _ in range(3)) for _ in range(64))
        for x in cases:
            self.assertEqual(norm_equality_witness(x, x), 1)
            self.assertEqual(norm_equality_witness(x, (0, 0, 0)), int(x == (0, 0, 0)))
        # A direct regression against silently using this norm over p=1 mod4.
        self.assertEqual(norm_equality_witness((1, 2, 0), (0, 0, 0), 5), 1)

    def test_missing_lookup_empty_slots_and_zero_keys(self):
        empty = (tagged_key(0, occupied=0), 0)
        rows = [empty, (tagged_key(7), 123), (tagged_key(2**255 + 9), 456), empty]
        self.assertEqual(lookup_witness(rows, 0), (0, 0))
        self.assertEqual(lookup_witness(rows, 8), (0, 0))
        self.assertEqual(lookup_witness(rows, 7), (1, 123))
        self.assertEqual(lookup_witness(rows, 2**255 + 9), (1, 456))
        self.assertEqual(lookup_witness(rows + [(tagged_key(0), 0)], 0), (1, 0))
        d = Design(records=4, batch=8)
        before, after = scan_circuit(d), scan_circuit(replace(d, records=5))
        outputs = lambda c: c['work']['reductions'] + c['work']['dot_outputs']
        self.assertEqual(outputs(after) - outputs(before), 137 * d.batch)

    def test_matrix_contraction_row_major_orientation(self):
        # Asymmetric shapes catch transposing the high/low index bits. More than
        # one payload word catches accidentally reusing a word's dot output.
        for rows, columns in ((2, 8), (8, 2), (4, 16)):
            records = [tuple(1000*i + 10*j + w for w in range(3))
                       for i in range(rows) for j in range(columns)]
            self.assertEqual(len(set(records)), rows * columns)
            snapshot = deepcopy(records)
            for index in range(rows * columns):
                self.assertEqual(two_dimensional_dot_witness(records, rows, columns, index),
                                 records[index])
            self.assertEqual(records, snapshot)

    def test_phase_sums_preserve_cost_and_saved_reference(self):
        root = Path(__file__).resolve().parent
        saved_path = root / 'results' / 'summary.json'
        captured = saved_path.read_bytes()
        saved = next(x for x in json.loads(captured)['scenarios'] if x['scenario'] == 'central')
        snapshot = deepcopy(saved)
        d = Design(**saved['design'])
        backend, dep = Backend(**saved['backend']), Deployment(**saved['deployment'])
        cases = [circuit(d), scan_circuit(d), scan_circuit(d, 'indexed_2d')]
        for c in cases:
            original = deepcopy(c)
            split = phase_split(c, backend)
            total = traffic(c, backend)
            self.assert_close(split['offline_sent_bytes'] + split['online_sent_bytes'],
                              total['sent_bytes_party_batch'])
            self.assert_close(split['offline_cpu_operations'] + split['online_cpu_operations'],
                              total['local_products_party_batch'])
            self.assert_close(split['offline_cpu_if_scalar_randomness_hoisted']
                              + split['online_cpu_if_scalar_randomness_hoisted'],
                              total['local_products_party_batch'])
            for key, value in split.items():
                self.assertGreaterEqual(value, 0, key)
            self.assertLessEqual(split['offline_traffic_fraction'], 1)
            self.assertLessEqual(split['offline_cpu_fraction'], 1)
            self.assertEqual(c, original)
        # The new mask attribution is diagnostic metadata, not an extra charge.
        without_tag = deepcopy(cases[0])
        without_tag['work'].pop('canonical_masks')
        self.assertEqual(traffic(without_tag, backend), traffic(cases[0], backend))
        skus = load_skus(root / 'data' / 'aws_prices_2026-10-12.json')
        sku = next(s for s in skus if s['name'] == saved['result']['instance'])
        selected = provision(cases[0], sku, saved['result']['nodes_per_party_per_replica'], dep, backend)
        self.assert_close(selected['total_usd_year'], saved['result']['total_usd_year'])
        self.assertEqual(saved, snapshot)
        self.assertEqual(saved_path.read_bytes(), captured)

    def test_canonical_mask_attribution_propagates_without_double_counting(self):
        d = Design(records=4096, batch=8, fanout=16, base_cutoff=64,
                   sort_method='bitonic')
        combined = Work()
        combined.add(canonical_bits(3, d), times=2)
        self.assertEqual(combined.canonical_masks, 6)
        self.assertEqual(combined.random_bits, 6 * 127)
        for metadata in ('compact', 'bits'):
            c = circuit(replace(d, metadata=metadata))
            fresh_label_bits = 2 * d.batch * sum(level['height'] for level in c['levels'])
            w = c['work']
            self.assert_close(w['random_bits'], fresh_label_bits + 127 * w['canonical_masks'])
            split = phase_split(c)
            self.assert_close(split['offline_reduction_outputs'], 126 * w['canonical_masks'])
            self.assert_close(split['offline_openings'], w['canonical_masks'])
            if metadata == 'bits':
                self.assertEqual(w['canonical_masks'], 0)

    def test_scan_batching_does_not_amortize_arithmetic_per_query(self):
        d = Design(records=1024, batch=1)
        backend = Backend()
        for mode in ('full_key', 'indexed_2d'):
            small = scan_circuit(d, mode)
            large = scan_circuit(replace(d, batch=16), mode)
            for field in ('reductions', 'dot_outputs', 'local_products', 'random_bits', 'openings'):
                self.assertEqual(large['work'][field], 16 * small['work'][field], (mode, field))
            self.assertEqual(large['work']['phases'], small['work']['phases'])
            self.assertEqual(large['state_bytes_party'], small['state_bytes_party'])
            # The optimistic tiled RAM pass is reused, while products are not.
            self.assertEqual(large['work']['ram_bytes'], small['work']['ram_bytes'])
            one, sixteen = traffic(small), traffic(large)
            self.assert_close(sixteen['local_products_party_batch'],
                              16 * one['local_products_party_batch'])
            # Constant active-check batches round up; remove only that fixed
            # overhead when comparing exact per-query communication.
            fixed_bytes = backend.check_words * d.field_bytes * backend.framing_factor
            variable_one = one['sent_bytes_party_batch'] - one['checks'] * fixed_bytes
            variable_sixteen = sixteen['sent_bytes_party_batch'] - sixteen['checks'] * fixed_bytes
            self.assert_close(variable_sixteen, 16 * variable_one)

    def test_scan_memory_uses_one_authenticated_database_copy(self):
        d = Design(records=2**28, cuckoo_stash=0)
        full = scan_circuit(d)
        indexed = scan_circuit(d, 'indexed_2d')
        self.assertEqual(full['state_bytes_party'], 48 * GIB)
        self.assertEqual(indexed['state_bytes_party'], 192 * GIB)
        self.assertEqual(indexed['matrix_rows'] * indexed['matrix_columns'], 2**29)
        with_stash = scan_circuit(replace(d, cuckoo_stash=8), 'indexed_2d')
        self.assertEqual(with_stash['state_bytes_party'] - indexed['state_bytes_party'],
                         8 * 6 * 16 * 2)

    def test_scan_rejects_incompatible_security_model(self):
        variants = (Design(parties=3, threshold=1), Design(threshold=3),
                    Design(field_bits=61, field_bytes=8))
        for mode in ('full_key', 'indexed_2d'):
            for d in variants:
                with self.subTest(mode=mode, parties=d.parties, threshold=d.threshold,
                                  field_bits=d.field_bits):
                    with self.assertRaises(ValueError):
                        scan_circuit(d, mode)
        with self.assertRaises(ValueError):
            phase_split(scan_circuit(Design()), replace(Backend(), reduction_words=4))


if __name__ == '__main__':
    unittest.main()
