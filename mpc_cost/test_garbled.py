"""Independent checks of garbled workload dimensions and byte accounting."""
import unittest
from dataclasses import replace
from math import ceil, isclose

from mpc_cost import garbled_circuit as circuit
from mpc_cost import garbled_cost as cost


class GarbledCircuitTests(unittest.TestCase):
    def test_flat_base_is_map_of_last_actual_tree(self):
        # 2^12 data records -> 2^10 packed map records.  The last actual
        # tree's scalar position map has 1024 entries, not another 256.
        work = circuit.recursive_probe(12, fanout=4, base_cells=1024)
        self.assertEqual([t['address_bits'] for t in work['trees']], [12, 10])
        self.assertEqual(work['flat_base_cells'], 1024)
        self.assertEqual(work['flat_base_position_bits'], 10)
        self.assertEqual(work['trees'][1]['payload_bits'], 4 * 12)
        tree_state = sum(t['retained_bits'] for t in work['trees'])
        self.assertEqual(work['retained_bits'] - tree_state, 1024 * 10)

    def test_nondivisible_recursive_address_width(self):
        # An eight-way map drops three address bits each time. The base
        # stops at 2^9, with all nine position bits for each of its entries.
        work = circuit.recursive_probe(12, fanout=8, base_cells=1024)
        self.assertEqual([t['address_bits'] for t in work['trees']], [12, 9])
        self.assertEqual(work['flat_base_cells'], 512)
        self.assertEqual(work['flat_base_position_bits'], 9)

    def test_horizon_amortizes_generated_material_not_online_path(self):
        short = circuit.recursive_probe(12, horizon=1 << 12)
        long = circuit.recursive_probe(12, horizon=1 << 14)
        self.assertGreater(short['generated_ands'], long['generated_ands'])
        self.assertGreaterEqual(long['generated_ands'], long['visited_ands'])
        self.assertEqual(short['visited_ands'], long['visited_ands'])
        self.assertEqual(short['retained_bits'], long['retained_bits'])
        self.assertEqual(short['fresh_position_bits'], long['fresh_position_bits'])

    def test_tree_state_counts_every_physical_bucket_once(self):
        # h=3 gives an arity-4 root then arity-2 children, hence 1+4+8
        # buckets. The root has42 slots; all other buckets have7.
        tree = circuit.tree_template(3, 8, horizon=8, family='compute')
        self.assertEqual([r['nodes'] for r in tree['node_levels']], [1, 4, 8])
        expected = 42 * (8 + 3 + 3 + 1)
        expected += 4 * 7 * (8 + 3 + 1 + 1)
        expected += 8 * 7 * (8 + 3 + 0 + 1)
        self.assertEqual(tree['retained_bits'], expected)

    def test_stash_is_scanned_once_per_kv_query(self):
        empty = circuit.kv_lookup(8, cuckoo_stash=0)
        one = circuit.kv_lookup(8, cuckoo_stash=1)
        # Additional candidate: 255 equality ANDs, occupancy AND,
        # 256 output-mask ANDs, and one OR for the public membership result.
        self.assertEqual(one['generated_ands'] - empty['generated_ands'], 513)
        self.assertEqual(one['visited_ands'] - empty['visited_ands'], 513)
        self.assertEqual(one['retained_bits'] - empty['retained_bits'], 513)
        self.assertEqual(one['query_input_bits'], empty['query_input_bits'])
        self.assertEqual(one['query_input_bits'] - one['private_index_input_bits'], 256)

    def test_user_stack_exclusion_does_not_erase_ram_work(self):
        work = circuit.kv_lookup(8)
        self.assertEqual(work['stack_ands'], 0)
        self.assertEqual(work['stack_joins'], 0)
        self.assertEqual(work['stack_buffers'], 0)
        self.assertGreater(work['generated_ands'], 0)
        self.assertGreater(work['retained_bits'], 0)
        self.assertGreater(work['fresh_position_bits'], 0)
        self.assertIsNone(work['hash_ands_external'])
        self.assertIsNone(work['malicious_initialization_cost_external'])

    def test_invalid_map_fanout_and_horizon_rejected(self):
        for fanout in (0, 1, 3, 6):
            with self.subTest(fanout=fanout), self.assertRaises(ValueError):
                circuit.recursive_probe(12, fanout=fanout)
        for horizon in (0, -1):
            with self.subTest(horizon=horizon), self.assertRaises(ValueError):
                circuit.recursive_probe(12, horizon=horizon)

    def test_benes_routing_counts_padding_and_secret_switches(self):
        single = circuit.benes_routing_setup(1, 8)
        self.assertEqual(single['ands'], 0)
        # Three real slots pad to four. The regular network has three
        # stages of two switches: six full 9-bit conditional swaps.
        route = circuit.benes_routing_setup(3, 9)
        self.assertEqual(route['padded_slots'], 4)
        self.assertEqual(route['padding_slots'], 1)
        self.assertEqual(route['switches'], 6)
        self.assertEqual(route['control_bits'], 6)
        self.assertEqual(route['ands'], 54)
        self.assertEqual(route['xors'], 162)
        for slots, width in ((0, 8), (4, 0), (-1, 8)):
            with self.subTest(slots=slots, width=width), self.assertRaises(ValueError):
                circuit.benes_routing_setup(slots, width)

    def test_initial_routing_uses_full_positions_and_each_tree_once(self):
        probe = circuit.recursive_probe(3, payload_bits=8, horizon=8,
                                        base_cells=8, family='compute')
        # 42 root slots + (4+8)*7 other slots =126; pad to128.
        # Initial positions are full3-bit labels even for leaf slots.
        route = circuit.probe_routing_setup(probe)
        self.assertEqual(len(route['trees']), 1)
        row = route['trees'][0]
        self.assertEqual(row['physical_slots'], 126)
        self.assertEqual(row['padded_slots'], 128)
        self.assertEqual(row['block_bits'], 8 + 3 + 3 + 1)
        self.assertEqual(row['ands'], 64 * 13 * 15)
        self.assertFalse(route['includes_layout_generation'])
        self.assertFalse(route['includes_control_generation_or_validation'])
        self.assertFalse(route['included_in_default_generated_ands'])

    def test_routing_is_epoch_cost_and_does_not_depend_on_query_horizon(self):
        a = circuit.kv_lookup(12, horizon=1 << 13, fanout=8)
        b = circuit.kv_lookup(12, horizon=1 << 15, fanout=8)
        self.assertEqual(a['routing_setup_ands_per_epoch'],
                         b['routing_setup_ands_per_epoch'])
        self.assertEqual(a['routing_setup_control_bits_per_epoch'],
                         b['routing_setup_control_bits_per_epoch'])
        per_table = circuit.probe_routing_setup(a['probe'])
        self.assertEqual(a['routing_setup_ands_per_epoch'], 2*per_table['ands'])
        self.assertEqual(a['routing_setup_xors_per_epoch'], 2*per_table['xors'])
        # This independent reconstruction verifies setup is not silently
        # added to default generated gates (two probes plus ten candidates).
        self.assertEqual(a['generated_ands'],
                         2*a['probe']['generated_ands'] + 10*512 + 9)


class GarbledBackendTests(unittest.TestCase):
    SKU = dict(name='test-full-duplex', network_gbps=100, hourly_usd=10)

    def setUp(self):
        self.work = circuit.kv_lookup(8, horizon=512)
        self.deployment = cost.GarbledDeployment(epoch_copies=1)

    def price(self, backend=cost.GarblingBackend(), deployment=None):
        return cost.price(self.work, self.SKU, .08, backend,
                          self.deployment if deployment is None else deployment)

    def test_finite_coefficients_match_independent_paper_ledger(self):
        fixed = cost.backend_coefficients()
        printed = cost.backend_coefficients(
            replace(cost.GarblingBackend(), repair_multiplication_count=False))
        for field, repaired_value, printed_value in (
            ('input', 2747.5, 2575), ('and', 4618.5, 4446), ('output', 36, 36)
        ):
            with self.subTest(field=field):
                key = 'preprocessing_field_words_' + field
                self.assertEqual(fixed[key], repaired_value)
                self.assertEqual(printed[key], printed_value)
        self.assertEqual(fixed['preprocessing_constant_field_words'], 1440)

    def test_table_and_tsc_pack_byte_widths(self):
        coeff = cost.backend_coefficients()
        # Four AND rows each contain THREE 128-bit field elements. There
        # are nine sending garblers; P1 does not send itself a tenth table.
        self.assertEqual(coeff['field_bytes'], 16)
        self.assertEqual(coeff['table_bytes_per_and_per_garbler'], 192)
        self.assertEqual(coeff['table_bytes_per_and_evaluator'], 1728)
        self.assertEqual(coeff['evaluator_state_bytes_per_bit'], 224)
        self.assertEqual(coeff['garbler_state_bytes_per_bit'], 64)
        self.assertEqual(coeff['input_delivery_bytes_global'], 434.25)
        self.assertEqual(coeff['output_delivery_bytes_global'], 288)

    def test_global_nic_bounds_cover_directional_loads_and_party_ceilings(self):
        n, rate, capacity = 10, 7, 3
        graphs = [[], [(i, (i+1) % n, 1) for i in range(n)],
                  [(i, 0, 1) for i in range(1, n)],
                  [(0, i, i/7) for i in range(1, n)],
                  [(i, j, (i+2*j+1)/11) for i in range(n)
                   for j in range(n) if i != j]]
        for graph in graphs:
            tx, rx = [0.] * n, [0.] * n
            for src, dst, amount in graph:
                tx[src] += amount
                rx[dst] += amount
            volume = sum(amount for _, _, amount in graph)
            bound = cost.fleet_bounds(volume, capacity, rate, n)
            actual = sum(max(1, ceil(rate*max(a, b)/capacity))
                         for a, b in zip(tx, rx))
            with self.subTest(edges=len(graph)):
                self.assertLessEqual(bound['minimum_total_nodes'], actual)
                self.assertGreaterEqual(bound['conservative_total_nodes'], actual)
                self.assertTrue(isclose(sum(tx), volume, abs_tol=1e-10))
                self.assertTrue(isclose(sum(rx), volume, abs_tol=1e-10))

    def test_more_epoch_copies_and_replicas_scale_ssd_not_total_query_work(self):
        base = self.price()
        for setting in ('epoch_copies', 'independent_states'):
            result = self.price(deployment=replace(self.deployment, **{setting: 3}))
            with self.subTest(setting=setting):
                self.assertEqual(result['ssd_bytes_all_epochs_and_states'],
                                 3 * base['ssd_bytes_all_epochs_and_states'])
                self.assertTrue(isclose(result['ssd_usd_year'], 3*base['ssd_usd_year']))
                self.assertEqual(result['network_fleet'], base['network_fleet'])
                self.assertEqual(result['wire_bytes_global_per_query'],
                                 base['wire_bytes_global_per_query'])

    def test_program_storage_is_one_aggregate_evaluator_copy(self):
        result = self.price()
        expected_program = result['ands_per_query'] * 1728 * 512
        self.assertEqual(result['program_bytes_one_epoch'], expected_program)
        # Each state bit has one evaluator pack and nine garbler packs.
        expected_state = self.work['retained_bits'] * (224 + 9*64)
        self.assertEqual(result['state_bytes_all_parties_one_epoch'], expected_state)
        self.assertEqual(result['ssd_bytes_all_epochs_and_states'],
                         expected_program + expected_state)

    def test_correlation_overhead_is_applied_once_and_only_to_preprocessing(self):
        base = self.price()
        changed = self.price(replace(cost.GarblingBackend(),
                                     extra_correlation_fraction=.25))
        for key in ('table_bytes_global_per_query', 'input_output_bytes_global_per_query',
                    'base_preprocessing_bytes_global_per_query', 'program_bytes_one_epoch'):
            self.assertEqual(base[key], changed[key])
        self.assertTrue(isclose(changed['preprocessing_bytes_global_per_query'],
                                base['preprocessing_bytes_global_per_query'] * 1.25))
        extra_wire = (.25 * base['base_preprocessing_bytes_global_per_query']
                      * self.deployment.framing_factor)
        self.assertTrue(isclose(changed['wire_bytes_global_per_query']
                                - base['wire_bytes_global_per_query'], extra_wire))

    def test_cross_az_price_counts_global_wire_once(self):
        result = self.price(deployment=replace(self.deployment, az_fraction=1))
        expected = (result['wire_bytes_global_per_query'] * self.deployment.rate
                    * 365 * 24 * 3600 / 1e9 * .02)
        self.assertTrue(isclose(result['transfer_usd_year'], expected))

    def test_unsupported_security_parameters_rejected(self):
        for changed in (dict(parties=3, threshold=1), dict(threshold=5),
                        dict(kappa_bits=64), dict(superpack_epsilon=.5)):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                cost.backend_coefficients(replace(cost.GarblingBackend(), **changed))


if __name__ == '__main__':
    unittest.main()
