"""Independent price units, peak provisioning, and replica-accounting checks."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from .hierarchical_annual import prices, role_budget, annual_case
from .hierarchical_address import current_case, LEGACY

ROOT=Path(__file__).resolve().parent


class AnnualChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data=json.loads((ROOT/'results/hierarchical_split_comparison.json').read_text())
        cls.c=current_case(next(c for c in data['primary'] if c['child_z']==64 and c['log_records']==32))
        cls.s=next(s for s in json.loads((ROOT/'results/hierarchical_schedule.json').read_text())
                   if s['batch']==1024 and s['log_records']==32)

    def test_official_units_and_full_peak_bandwidth(self):
        p=prices()
        self.assertAlmostEqual(p['throughput_mib_second_month'],.04)
        r=role_budget(1,0)
        self.assertAlmostEqual(r['ec2_year'],63576.576)
        self.assertAlmostEqual(r['io_year'],15249.6)
        self.assertEqual(r['gib_per_volume'],48)
        self.assertEqual(r['throughput_mib_second_per_volume'],1491)
        self.assertEqual(r['iops_per_volume'],23842)
        self.assertGreaterEqual(r['provisioned_raw_ebs_bytes_second_per_worker'],12.5e9)
        self.assertLessEqual(8*r['iops_per_volume'],400000)
        self.assertGreaterEqual(8*r['iops_per_volume']*65536,12.5e9)

    def test_both_roles_and_states_charged_without_replicating_worker_pools(self):
        s=deepcopy(self.s)
        one=annual_case(self.c,dict(s,replicas=1))
        five=annual_case(self.c,dict(s,replicas=5))
        self.assertEqual(one['ec2_year'],five['ec2_year'])
        self.assertEqual(one['ebs_io_year'],five['ebs_io_year'])
        self.assertAlmostEqual(five['garbler']['required_bytes'],5*one['garbler']['required_bytes'])
        self.assertEqual(five['garbler']['total_year'],five['evaluator']['total_year'])
        self.assertAlmostEqual(five['total_year'],2*five['garbler']['total_year'])
        self.assertEqual(five['queries_per_year'],315360000000)

    def test_cold_queues_are_evaluator_only_and_capacity_rounding_is_bounded(self):
        hot=annual_case(self.c,self.s)
        cold=annual_case(self.c,self.s,cold_prefetch=True)
        self.assertEqual(hot['garbler'],cold['garbler'])
        self.assertEqual(hot['evaluator']['io_year'],cold['evaluator']['io_year'])
        ideal=.96*5*cold['cold_gc_bytes_per_state_evaluator']/2**30
        actual=cold['ebs_capacity_year']-hot['ebs_capacity_year']
        self.assertLessEqual(abs(actual-ideal),.96*cold['evaluator']['volumes'])
        self.assertGreater(cold['ready_latency']['cold_gc_ebs_read_bytes_per_query'],0)

    def test_25_volume_sensitivity_preserves_limits_and_reduces_bill(self):
        base=annual_case(self.c,self.s)
        many=annual_case(self.c,self.s,volumes_per_worker=25)
        self.assertEqual(base['ec2_year'],many['ec2_year'])
        self.assertLess(many['total_year'],base['total_year'])
        self.assertGreaterEqual(many['garbler']['provisioned_raw_ebs_bytes_second_per_worker'],12.5e9)
        self.assertGreaterEqual(many['garbler']['provisioned_gib']*2**30,
                                many['garbler']['required_bytes'])

    def test_stale_protocol_schedule_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'different address protocols'):
            annual_case(self.c,dict(self.s,address_scheme=LEGACY))


if __name__=='__main__':
    unittest.main()
