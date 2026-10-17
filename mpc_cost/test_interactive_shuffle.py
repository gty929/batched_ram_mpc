"""Independent small-kernel semantics and directional resource accounting.

These tests do not establish security or correctness of a complete OPRAM.
"""
from functools import lru_cache
from itertools import permutations, product
import unittest

from .interactive_shuffle_cost import (
    circuit_case, pool_shuffle_ledger, price_case, sweep, waksman_switches,
)
from .two_party_batch import batch_lookup
from .two_party_cost import Deployment


class InteractiveShuffleTests(unittest.TestCase):
    def test_arbitrary_waksman_count_against_recursive_decomposition(self):
        @lru_cache(None)
        def direct(n):
            return 0 if n == 1 else direct(n//2)+direct(n-n//2)+n-1
        for n in range(1, 1000):
            self.assertEqual(waksman_switches(n), direct(n))
        self.assertEqual(waksman_switches(8), 17)
        with self.assertRaises(ValueError):
            waksman_switches(0)

    def test_tag_multiset_hides_hit_pattern_and_permutations_restore_answers(self):
        # Distinct representative addresses; missing and nonrepresentative
        # requests receive a tagged dummy. Unselected pool slots have tag0.
        for present in product((False, True), repeat=2):
            for reps in product((False, True), repeat=2):
                records = [(j, 10+j) for j in range(2) if present[j]]
                records += [(99, 99)]*(2-len(records))
                tagged, expected = [], {}
                for uid, value in records:
                    hits = [j for j in range(2) if reps[j] and uid == j]
                    tagged.append((hits[0]+1 if hits else 0, value))
                for j in range(2):
                    hit = present[j] and reps[j]
                    tagged.append((0 if hit else j+1, 0))
                    expected[j+1] = 10+j if hit else 0
                self.assertEqual(sorted(t for t, _ in tagged), [0, 0, 1, 2])
                for order in permutations(range(4)):
                    shuffled = [tagged[i] for i in order]
                    answers = {t: value for t, value in shuffled if t}
                    self.assertEqual(answers, expected)
                    self.assertEqual(len([1 for t, _ in shuffled if not t]), 2)

    def test_fused_parallel_exchange_agrees_with_unique_reference_writes(self):
        old = [3, 7, 5]
        for addresses in permutations(range(3), 2):
            new = [6, 1]
            deltas = [[(old[i] ^ new[j]) if i == addresses[j] else 0
                       for j in range(2)] for i in range(3)]
            updated = [old[i] ^ deltas[i][0] ^ deltas[i][1] for i in range(3)]
            returned = [new[j] ^ deltas[0][j] ^ deltas[1][j] ^ deltas[2][j]
                        for j in range(2)]
            expected = old.copy()
            for j, address in enumerate(addresses):
                expected[address] = new[j]
            self.assertEqual(updated, expected)
            self.assertEqual(returned, [old[i] for i in addresses])
        # Duplicate requests require one representative write, followed by
        # private fanout of its returned old value; two simultaneous writes
        # to the same slot are deliberately not claimed to be valid here.

    def test_gc_color_outputs_are_local_xor_shares(self):
        for zero_color, value in product((0, 1), repeat=2):
            active_color = zero_color ^ value  # delta color is one
            self.assertEqual(active_color ^ zero_color, value)

    def test_pool_byte_rounding_ot_and_reinput_roles(self):
        p = pool_shuffle_ledger(7, 19, 2, 5)
        self.assertEqual(p['shuffle_items'], 7)
        self.assertEqual(p['tag_bits'], 2)
        self.assertEqual(p['packed_row_bytes'], 3)
        self.assertEqual(p['match_ands'], 2*5*9)
        self.assertEqual(p['two_shuffle_record_bytes'], 42)
        self.assertEqual(p['two_shuffle_switch_bytes'], 4*14*3)
        self.assertEqual(p['tag_opening_bytes'], 4)
        self.assertEqual(p['two_shuffle_ot_extension_bytes'], 32*14)
        self.assertEqual(p['symmetric_forward_bytes'], p['symmetric_backward_bytes'])
        self.assertEqual(p['reinput_forward_bytes']+p['reinput_backward_bytes'], 64*7*19)
        self.assertEqual(p['reinput_forward_bytes'], 3*p['reinput_backward_bytes'])
        self.assertEqual(p['tag_reinput_bits'], 0)

    def test_shuffle_reference_and_row_width_scaling(self):
        # N28/B32 top tree:572 record bits+6 tag bits occupy73 bytes.
        # Every transmitted switch correction is a FULL row, not one byte.
        top = pool_shuffle_ledger(29, 572, 32, 317)
        self.assertEqual(top['shuffle_items'], 349)
        self.assertEqual(top['packed_row_bytes'], 73)
        self.assertEqual(top['switches_per_permutation'], 2630)
        shuffle = sum(top[k] for k in ('two_shuffle_record_bytes',
                                      'two_shuffle_switch_bytes',
                                      'two_shuffle_ot_extension_bytes'))
        self.assertEqual(shuffle, 903074)
        self.assertEqual(top['tag_opening_bytes'], 524)
        narrow = pool_shuffle_ledger(7, 19, 2, 5)
        wide = pool_shuffle_ledger(7, 27, 2, 5)
        self.assertEqual(wide['packed_row_bytes']-narrow['packed_row_bytes'], 1)
        self.assertEqual(wide['two_shuffle_record_bytes']-narrow['two_shuffle_record_bytes'], 2*7)
        self.assertEqual(wide['two_shuffle_switch_bytes']-narrow['two_shuffle_switch_bytes'], 4*14)
        self.assertEqual(wide['two_shuffle_ot_extension_bytes'], narrow['two_shuffle_ot_extension_bytes'])
        self.assertEqual(wide['tag_opening_bytes'], narrow['tag_opening_bytes'])

    def test_substitution_retains_all_unmodified_work(self):
        for n in (28, 32):
            c = circuit_case(n, 32, 4, 2048)
            base = batch_lookup(n, 32, 4, 2048)
            original = base['ands_per_batch']
            removed = 2*sum(t['parts']['pool_fetch']['ands'] for t in base['trees_per_table'])
            matched = 2*sum(32*t['pool_records']*(t['address_bits']+2)
                            for t in base['trees_per_table'])
            fused = 2*32*base['base_cells']*base['base_label_bits']
            self.assertEqual(c['ands_per_batch'], original-removed+matched-fused+32*10240)
            self.assertEqual(c['ands_per_batch'], sum(c['and_components_per_batch'].values()))
            self.assertEqual(c['state_bits'], base['state_bits'])
            self.assertEqual(c['label_state_read_write_bytes_per_party_batch'],
                             base['label_state_read_write_bytes_per_party_batch'])

    def test_shared_query_input_no_private_indices_or_plaintext_output(self):
        c = circuit_case(28, 32, 4, 2048)
        t = c['unframed_traffic_bytes_per_query']
        self.assertEqual(t['query_share_input_forward'], 256*(16+32))
        self.assertEqual(t['query_share_input_backward'], 256*16)
        self.assertEqual(t['plaintext_answer_decoding'], 0)
        self.assertEqual(t['answer_share_conversion_network'], 0)
        self.assertEqual(c['output_bits_shared_between_parties'], 257)
        self.assertEqual(t['public_old_paths_forward'], c['public_path_bits_per_query']/8)
        self.assertEqual(t['public_old_paths_backward'], c['public_path_bits_per_query']/8)
        self.assertGreater(t['public_old_paths_forward'], 0)

    def test_directional_traffic_reconstructs_complete_accounted_stream(self):
        c = circuit_case(28, 32, 4, 2048)
        t = c['unframed_traffic_bytes_per_query']
        symmetric = sum(value for key, value in t.items() if key.endswith('each_direction'))
        forward = symmetric+sum(value for key, value in t.items() if key.endswith('_forward'))
        backward = symmetric+sum(value for key, value in t.items() if key.endswith('_backward'))
        self.assertEqual(c['unframed_forward_bytes_per_query'], forward)
        self.assertEqual(c['unframed_backward_bytes_per_query'], backward)
        self.assertEqual(c['unframed_total_bytes_per_query'], forward+backward)
        p = price_case(c, dep=Deployment(framing=1))
        self.assertEqual(p['forward_wire_bytes_per_query'], forward)
        self.assertEqual(p['backward_wire_bytes_per_query'], backward)

    def test_replicas_change_capacity_not_aggregate_traffic(self):
        c = circuit_case(28, 32, 4, 2048)
        a, b = price_case(c), price_case(c, states=3)
        self.assertEqual(a['total_wire_bytes_per_query'], b['total_wire_bytes_per_query'])
        self.assertEqual(3*a['state_bytes_per_party'], b['state_bytes_per_party'])
        self.assertEqual(a['retained_program_bytes'], 0)
        self.assertAlmostEqual(a['one_state_max_batch_service_seconds_at_70pct_util'], .00224)
        self.assertTrue(all(not x['is_complete_cpu_budget']
                            for x in a['ordinary_and_cpu_sensitivities']))

    def test_bounded_sweep_selection_and_reported_anchors(self):
        for n, gates, hosts in ((28, 6997217.75, 298), (32, 8867375.5, 378)):
            row = sweep(n)
            c, p = row['selected']['circuit'], row['selected']['price']
            self.assertEqual((c['batch'], c['fanout'], c['base_cells']), (32, 4, 2048))
            self.assertEqual(c['ands_per_query'], gates)
            self.assertEqual(p['network_nodes_per_party'], hosts)
            self.assertEqual(len(row['all_points']), 6*4*9)
            self.assertEqual(len(row['best_by_batch']), 6)
            self.assertTrue(all(p['network_capacity_and_io_usd_year'] <= x['network_capacity_and_io_usd_year']
                                for x in row['all_points']))


if __name__ == '__main__':
    unittest.main()
