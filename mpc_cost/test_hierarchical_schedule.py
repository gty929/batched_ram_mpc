"""Conservation and scheduling checks independent of published traces."""
import unittest

import numpy as np

from .hierarchical_split_cost import scenario
from .hierarchical_schedule import Schedule, arrays, provision, simulate
from .hierarchical_latency import ready_latency
from .hierarchical_throughput import directions
from .hierarchical_address import current_case


class ScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=current_case(scenario(18,64,512))
        cls.s=Schedule(replicas=5,foreground_workers_per_party=12,
            background_workers_per_party=40,preload_all_stash_prf=True,
            intraparty_remote_fraction=1,cold_bucket_load_seconds=.0005)
        cls.a=arrays(cls.c,cls.s)

    def test_each_carry_has_correct_frequency(self):
        c,a=self.c,self.a
        for i,row in enumerate(c['rows']):
            expected=a['period_batches']*c['batch']//row['accesses_per_rebuild']
            self.assertEqual(int(np.count_nonzero(a['carry']==i)),expected)

    def test_cache_lifecycle_and_total_directional_conservation(self):
        c,s,a=self.c,self.s,self.a
        ready=ready_latency(c,s.foreground_workers_per_party,cache_all_aux=True,
            rtt=s.rtt_seconds,ebs_fixed=s.cold_bucket_load_seconds,
            intraparty_remote_fraction=s.intraparty_remote_fraction)
        waste=a['cache']['skip_final_refill_waste_bytes_per_query']*127/134
        refill=float(a['background_refill_bytes'].mean())/c['batch']
        self.assertAlmostEqual(refill,ready['cached_forward_material_bytes_per_query']+waste,places=5)
        self.assertAlmostEqual(float(a['background_refill_reverse_bytes'].mean())/c['batch'],
            ready['cached_input_reverse_bytes_per_query'])
        actual=float((a['foreground_forward_bytes']+a['background_forward_bytes']).mean())/c['batch']
        internal=float((a['foreground_internal_bytes']+a['background_internal_bytes']).mean())/c['batch']
        expected=directions(c)['forward']+waste+ready['bridge_bytes_per_query']+internal
        self.assertAlmostEqual(actual,expected,places=5)
        reverse=float((a['foreground_reverse_bytes']+a['background_reverse_bytes']).mean())/c['batch']
        self.assertAlmostEqual(reverse,directions(c)['backward']+internal,places=5)

    def test_stagewise_mean_matches_independent_ready_model(self):
        c,s,a=self.c,self.s,self.a
        ready=ready_latency(c,s.foreground_workers_per_party,cache_all_aux=True,
            rtt=s.rtt_seconds,ebs_fixed=s.cold_bucket_load_seconds,
            intraparty_remote_fraction=s.intraparty_remote_fraction)
        self.assertAlmostEqual(float(a['foreground_seconds'].mean()),
            ready['mean_ready_batch_service_seconds'],places=12)

    def test_first_batch_and_pool_headroom(self):
        c=self.c
        s=provision(c,replicas=5,intraparty_remote_fraction=1,
            cold_bucket_load_seconds=.0005,preload_all_stash_prf=True)
        a=arrays(c,s)
        trace=simulate(c,s,batches=1)
        fill=(c['batch']-1)/(2*s.qps)
        self.assertAlmostEqual(trace['mean_query_seconds'],a['foreground_seconds'][0]+fill)
        self.assertEqual(trace['mean_queue_seconds'],0)
        self.assertFalse(trace['no_queue_assumption'])
        self.assertLessEqual(trace['foreground_utilization'],.70)
        self.assertLessEqual(trace['background_utilization'],.70)


if __name__=='__main__':
    unittest.main()
