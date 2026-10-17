"""Independent communication conservation and label-interface witnesses."""
import json
from pathlib import Path
from random import Random
import unittest

from .hierarchical_communication_audit import audit
from .hierarchical_cost import compact
from .hierarchical_throughput import directions

ROOT=Path(__file__).resolve().parent


class CommunicationAuditChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data=json.loads((ROOT/'results/hierarchical_split_comparison.json').read_text())
        cls.cases=[c for c in data['batch_sweep'] if c['batch'] in(1024,2048) and c['child_z']==64]

    def test_complete_decomposition_and_prf_closed_forms(self):
        for c in self.cases:
            r=audit(c); ell=c['lower_levels']
            self.assertAlmostEqual(sum(r['useful'].values()),c['total_unframed_bytes_per_query'])
            self.assertAlmostEqual(r['prf']['lookup_aes_calls'],ell+2)
            self.assertAlmostEqual(r['prf']['rebuild_aes_calls'],ell/2+1)
            self.assertAlmostEqual(r['prf']['datapath_bytes'],163840*(1.5*ell+5))
            self.assertAlmostEqual(sum(x['total'] for x in r['rebuild_stages'].values()),
                                   c['rebuild_unframed_bytes_per_query'])

    def test_independently_count_all_key_swap_layers(self):
        for c in self.cases:
            independent=0
            for row in c['rows']:
                n=row['capacity']
                sw=compact((4 if row['top'] else 2)*n)['swaps']
                if row['source_stash_slots']:
                    sw+=compact(2*n)['swaps']
                sw+=10*n*row['parent_routing_stages']
                sw+=row['parent_buckets']*c['local_refinement']['payload_swaps']
                sw+=compact(row['parent_buckets']*c['local_stash'])['swaps']
                independent+=sw/row['accesses_per_rebuild']
            r=audit(c)
            self.assertAlmostEqual(r['rebuild_fields']['key_gc'],independent*128*32)
            self.assertAlmostEqual(r['rebuild_fields']['flags_gc'],independent*2*32)
            self.assertAlmostEqual(sum(r['rebuild_fields'][x] for x in ('key_gc','flags_gc','transient_tag_gc')),
                                   r['useful']['rebuild_boolean_movement'])

    def test_sends_are_not_double_counted_as_receives(self):
        for c in self.cases:
            r=audit(c); d=r['deployment']; original=directions(c)
            self.assertAlmostEqual(d['unframed_interparty_forward']+d['unframed_interparty_reverse'],
                r['useful_total']+d['cache_waste_forward']+d['query_bridges_forward'])
            self.assertAlmostEqual(d['unframed_interparty_reverse'],original['backward'])
            self.assertAlmostEqual(d['framed_network_total_sends'],d['framed_interparty_total']
                                   +1.05*2*d['internal_per_party_per_direction'])

    def test_shared_offset_relabel_and_local_color_shares(self):
        rng=Random(17102026)
        for _ in range(64):
            delta=rng.getrandbits(128)|1
            old0,new0=rng.getrandbits(128),rng.getrandbits(128)
            translation=old0^new0
            for bit in (0,1):
                active=old0^(delta if bit else 0)
                self.assertEqual(active^translation,new0^(delta if bit else 0))
                self.assertEqual((active&1)^(old0&1),bit)

    def test_optional_packed_key_conversions_include_dummy_output_slots(self):
        for c in self.cases:
            r=audit(c); p=r['optional_packed_fingerprint_rebuild']
            slots=sum((3*x['capacity']+x['global_stash']['capacity'])/x['accesses_per_rebuild']
                      for x in c['rows'])
            self.assertAlmostEqual(p['key_reinput'],slots*128*64)
            self.assertAlmostEqual(p['total'],r['useful_total']-p['removed_key_gc']+
                                   p['extra_word_ot']+p['key_reinput'])
            self.assertAlmostEqual(p['extra_word_ot'],c['rebuild_payload_swaps_per_query']*64)


if __name__=='__main__':
    unittest.main()
