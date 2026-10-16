"""Independent arithmetic checks for the two-party resource estimate."""
import unittest

from mpc_cost.two_party_cost import capacity, Deployment, input_traffic, gram_case
from mpc_cost.two_party_merge import stack_grid
from mpc_cost.two_party_batch import batch_lookup
from mpc_cost.two_party_serial import required_states, serial_core


class TwoPartyAccountingTests(unittest.TestCase):
    def test_sequential_state_count_is_not_aggregate_core_capacity(self):
        self.assertEqual(required_states(.041),586)
        self.assertEqual(required_states(.1),1429)
        self.assertEqual(required_states(.5),7143)
        self.assertEqual(required_states(.07),1000)
        self.assertEqual(required_states(.05,batch=1024),1)

    def test_table_parallelism_preserves_total_work(self):
        c=serial_core(28)
        self.assertAlmostEqual(c['single_worker_core_seconds'],
                               2*c['one_probe_seconds']+c['final_match_seconds'])
        self.assertAlmostEqual(c['two_table_lane_core_seconds'],
                               c['one_probe_seconds']+c['final_match_seconds'])
        self.assertGreater(c['two_table_lane_core_seconds'],
                           c['single_worker_core_seconds']/2)

    def test_two_roles_both_need_full_directional_capacity(self):
        d = Deployment(framing=1)
        p = capacity(32e6, 0, 0, 0, dep=d)
        self.assertEqual(p['network_nodes_per_party'], 41)
        self.assertEqual(p['network_nodes_total'], 82)

    def test_joint_private_positions_not_public_coin_toss(self):
        self.assertEqual(input_traffic(0, 11), {'forward':528, 'backward':176})
        self.assertEqual(input_traffic(0, 11, joint=False), {'forward':176, 'backward':0})

    def test_replicas_multiply_storage_not_same_aggregate_request_traffic(self):
        a = capacity(1e6, 1024, 256, 64, program_epoch_bytes=1e9, epoch_copies=2)
        b = capacity(1e6, 1024, 256, 64, program_epoch_bytes=1e9, epoch_copies=2, states=8)
        self.assertEqual(a['network_nodes_total'], b['network_nodes_total'])
        self.assertEqual(b['storage_bytes_total'], 8*a['storage_bytes_total'])
        self.assertEqual(a['state_bytes_both_parties'], 2*16*1024*2)

    def test_merge_grid_closed_form_against_direct_enumeration(self):
        for T in range(1, 16):
            for n in range(1, T+1):
                S = sum(min(n, t)+1 for t in range(T))
                D = sum(min(n, t+1) for t in range(T))
                for W in (1, 2, 32):
                    x = stack_grid(T, n, W)
                    self.assertEqual(x['garbler_hashes'], 2*S+W*(S+D)+T*W)
                    self.assertEqual(x['garbled_bytes'], 16*T*(W+1)+8)

    def test_gram_retains_nonzero_merge_and_binding(self):
        c = gram_case(28)
        self.assertGreater(c['merge_per_query']['garbled_bytes'], 0)
        self.assertGreater(c['output_binding']['garbled_bytes_per_query'], 0)
        self.assertGreater(c['price']['tables_bytes_per_query'], 32*c['generated_nonmerge_ands'])

    def test_batch_state_and_io_units_include_both_table_probes(self):
        c = batch_lookup(28, 256, fanout=8)
        bits = 2*(sum(x['state_bits'] for x in c['trees_per_table'])
                  +c['base_cells']*c['base_label_bits'])+8*513
        self.assertEqual(c['state_bits'], bits)
        self.assertEqual(c['label_state_bytes_per_party'], 16*bits)
        self.assertEqual(c['label_state_read_write_bytes_per_party_batch'],
                         32*c['persistent_bits_touched_per_batch'])
        self.assertEqual(c['table_bytes_per_query']*256, 32*c['ands_per_batch'])
        self.assertEqual(c['path_reveal_barriers'], len(c['trees_per_table']))

    def test_public_routing_audit_preserves_existing_numerical_anchors(self):
        # Confirming an uncharged public operation is not a second discount
        # against the private sort/inverse allowances that the model contains.
        for n, cutoff, expected in ((28, 256, 12921206.34375),
                                    (32, 4096, 16007951.9375)):
            with self.subTest(log_records=n):
                c = batch_lookup(n, 256, fanout=8, base_cutoff=cutoff)
                audit = c['routing_audit']
                self.assertEqual(c['ands_per_query'], expected)
                for name in ('public_request_path_sort_ands',
                             'public_request_wire_permutation_ands',
                             'authorized_output_unpermutation_ands',
                             'savings_from_confirmed_optimization_ands_per_query'):
                    self.assertEqual(audit[name], 0)
                # Reconstruct the original total, independently of audit data.
                tree_work = sum(sum(p['ands'] for p in t['parts'].values())
                                for t in c['trees_per_table'])
                packed_work = sum(p['ands'] for p in c['packed_updates_per_table'])
                expected_batch = 2*(tree_work+packed_work+c['base_work_per_table']['ands'])
                expected_batch += c['application_ands']
                self.assertEqual(c['ands_per_batch'], expected_batch)

    def test_private_inverse_ledger_is_an_existing_subset_of_gates(self):
        # Independently count compare-exchanges stage by stage: each bitonic
        # level j has j stages, with padded_size/2 exchanges in each stage.
        def inverse_count(items, width):
            size, levels = 1, 0
            while size < items:
                size *= 2
                levels += 1
            return sum(size//2*j for j in range(1, levels+1))*width

        for n, batch, cutoff in ((28, 256, 256), (32, 256, 4096),
                                 (28, 1024, 4096)):
            with self.subTest(log_records=n, batch=batch):
                c = batch_lookup(n, batch, fanout=8, base_cutoff=cutoff)
                counts = dict(request_conflicts=0, pool_fetch=0,
                              eviction_select=0, pool_cleanup=0)
                for t in c['trees_per_table']:
                    items_by_phase = dict(request_conflicts=batch,
                                          pool_fetch=t['pool_records']+batch,
                                          eviction_select=t['pool_records']+3*batch)
                    for phase, items in items_by_phase.items():
                        value = inverse_count(items, t['record_bits'])
                        self.assertEqual(t['retained_private_inverse_ands'][phase], value)
                        self.assertLess(value, t['parts'][phase]['ands'])
                        counts[phase] += 2*value
                    self.assertEqual(t['retained_private_inverse_ands']['pool_cleanup'], 0)
                counts['flat_base_duplicates'] = 2*inverse_count(batch, c['base_label_bits'])
                audit = c['routing_audit']
                self.assertTrue(audit['counted_subset_of_total_ands'])
                self.assertEqual(audit['retained_private_inverse_ands_per_batch'], counts)
                self.assertEqual(audit['retained_private_inverse_ands_per_query'],
                                 {name: value/batch for name, value in counts.items()})
                self.assertEqual(audit['retained_private_inverse_total_ands_per_batch'], sum(counts.values()))
                self.assertEqual(audit['retained_private_inverse_total_ands_per_query'], sum(counts.values())/batch)
                self.assertGreater(sum(counts.values()), 0)
                self.assertLess(sum(counts.values()), c['ands_per_batch'])


if __name__ == '__main__':
    unittest.main()
