"""Constructive routing and independent probability witnesses for split tables.

These cleartext witnesses test conservation, overflow selection, fixed routing,
and the saved analytic bounds. They are not an MPC implementation/security proof.
Run: python -m unittest mpc_cost.test_hierarchical_split -v
"""
from decimal import Decimal, localcontext
from itertools import product
import json
from math import factorial, log2
from pathlib import Path
from random import Random
import unittest

from mpc_cost.hierarchical_split_cost import residual_logmgf


def compact_plan(marks, offset=0, base=0):
    """Figure 1 of 2022-1333, without inspecting/moving record payloads."""
    n = len(marks)
    if n == 2:
        return [(base, base+1, ((1-marks[0])*marks[1]) ^ offset)]
    half = n//2
    left = sum(marks[:half])
    threshold = (offset+left) % half
    sign = ((offset % half+left) >= half) ^ (offset >= half)
    return (compact_plan(marks[:half], offset % half, base)
            + compact_plan(marks[half:], threshold, base+half)
            + [(base+i, base+half+i, int(sign ^ (i >= threshold)))
               for i in range(half)])


def apply_schedule(items, schedule):
    out = list(items)
    for i, j, swap in schedule:
        if swap:
            out[i], out[j] = out[j], out[i]
    return out


def overflow_flags(items, leaf_capacity):
    n = len(items)
    flags = [0]*n
    for leaf in range(n//leaf_capacity):
        membership = [int(x is not None and x[1] == leaf) for x in items]
        schedule = compact_plan(membership)
        selected = apply_schedule([1]*leaf_capacity+[0]*(n-leaf_capacity),
                                  reversed(schedule))
        flags = [o ^ (member & (1-keep))
                 for o, member, keep in zip(flags, membership, selected)]
    return flags


def feasible_recursive_split(items, leaf_capacity, first_leaf=0):
    n = len(items)
    if n == leaf_capacity:
        if any(x is not None and x[1] != first_leaf for x in items):
            raise AssertionError('An entry reached the wrong leaf')
        return items
    middle = first_leaf+n//(2*leaf_capacity)
    left = sum(x is not None and x[1] < middle for x in items)
    right = sum(x is not None and x[1] >= middle for x in items)
    if max(left, right) > n//2:
        raise AssertionError('An intermediate child overflowed')
    quota = n//2-left
    dummy_rank = 0
    marks = []
    for item in items:
        if item is None:
            # Exclusive rank stays below n, including the all-dummy case.
            marks.append(int(dummy_rank < quota))
            dummy_rank += 1
        else:
            marks.append(int(item[1] < middle))
    if sum(marks) != n//2:
        raise AssertionError('Dummy padding failed to produce exact half')
    routed = apply_schedule(items, compact_plan(marks))
    return (feasible_recursive_split(routed[:n//2], leaf_capacity, first_leaf)
            + feasible_recursive_split(routed[n//2:], leaf_capacity, middle))


def split_parent(items, leaf_capacity, stash_capacity=64):
    flags = overflow_flags(items, leaf_capacity)
    residual = sum(flags)
    if residual > stash_capacity:
        return None, None, residual
    routed = apply_schedule(items, compact_plan(flags))
    # Public data copies; only occupied bits choose which copy remains live.
    stash = [routed[j] if j < residual else None
             for j in range(stash_capacity)]
    main = [None if j < residual else item for j, item in enumerate(routed)]
    return feasible_recursive_split(main, leaf_capacity), stash, residual


def positive_poisson_logmgf(z, tilt):
    """Independent 80-digit positive series, no scipy tail/tilting formula."""
    with localcontext() as ctx:
        ctx.prec = 80
        mu, t = Decimal(z)/2, Decimal(str(tilt))
        alpha = t.exp()
        k = z+1
        probability = (-mu).exp()*mu**k/Decimal(factorial(k))
        weight = alpha
        delta = Decimal(0)
        for _ in range(2048):
            term = probability*(weight-1)
            delta += term
            if k > 2*mu*alpha and term < delta*Decimal('1e-70'):
                return (1+delta).ln()
            k += 1
            probability *= mu/k
            weight *= alpha
        raise AssertionError('Positive Poisson series failed to converge')


class HierarchicalSplitTests(unittest.TestCase):
    def assert_parent(self, items, z, stash_capacity=64):
        counts = [sum(x is not None and x[1] == leaf for x in items)
                  for leaf in range(len(items)//z)]
        expected = sum(max(count-z, 0) for count in counts)
        main, stash, residual = split_parent(items, z, stash_capacity)
        self.assertEqual(residual, expected)
        if expected > stash_capacity:
            self.assertIsNone(main)
            self.assertIsNone(stash)
            return
        self.assertEqual(sorted(x for x in main+stash if x is not None),
                         sorted(x for x in items if x is not None))
        for leaf in range(len(items)//z):
            originals = [x for x in items if x is not None and x[1] == leaf]
            self.assertEqual(set(x for x in main[leaf*z:(leaf+1)*z]
                                 if x is not None), set(originals[:z]))

    def test_compactor_stable_selected_order_and_inverse_controls(self):
        for n in (2, 4, 8):
            for marks in product((0, 1), repeat=n):
                schedule = compact_plan(marks)
                originals = list(range(n))
                routed = apply_schedule(originals, schedule)
                self.assertEqual(routed[:sum(marks)],
                                 [i for i, marked in enumerate(marks) if marked])
                self.assertEqual(apply_schedule(routed, reversed(schedule)), originals)

    def test_parent_extremes_and_stash_boundaries(self):
        for z in (64, 128):
            self.assert_parent([None]*512, z)
            self.assert_parent([(i, i//z) for i in range(512)], z)
            skew = [(i, 0) for i in range(512)]
            self.assert_parent(skew, z, 512-z)
            self.assert_parent(skew, z)
            for excess in (0, 1, 63, 64, 65):
                self.assert_parent([(i, 0) for i in range(z+excess)]
                                   + [None]*(512-z-excess), z)

    def test_random_parent_conservation_and_intermediate_feasibility(self):
        rng = Random(19462026)
        for z in (64, 128):
            for occupancy in (.1, .5, .9, 1.):
                for _ in range(20):
                    items = [(i, rng.randrange(512//z))
                             if rng.random() < occupancy else None for i in range(512)]
                    self.assert_parent(items, z)

    def test_double_compaction_readmits_source_stashes(self):
        rng = Random(20261017)
        n = 32
        for _ in range(30):
            total = rng.randrange(n+1)
            stashed = rng.randrange(min(total, 24)+1)
            main = list(range(total-stashed))+[None]*(4*n-total+stashed)
            rng.shuffle(main)
            first = apply_schedule(main, compact_plan([int(x is not None) for x in main]))[:n]
            old_stash = list(range(total-stashed, total))+[None]*(n-stashed)
            combined = first+old_stash
            retained = apply_schedule(combined, compact_plan([int(x is not None)
                                                              for x in combined]))[:n]
            self.assertEqual(sorted(x for x in retained if x is not None), list(range(total)))

    def test_local_excess_has_a_subset_witness(self):
        # Exhaustively exercise the event inclusion used by the subset union.
        for counts in product(range(9), repeat=4):
            if sum(counts) > 8:
                continue
            excess = sum(max(count-2, 0) for count in counts)
            if excess > 1:
                overloaded = [count for count in counts if count > 2]
                self.assertGreaterEqual(sum(overloaded), 2*len(overloaded)+2)

    def test_poisson_mgf_and_published_capacity_tilt_witnesses(self):
        for z in (64, 128):
            for tilt in (.43, .7, 1.05, 1.22):
                independent = float(positive_poisson_logmgf(z, tilt))
                self.assertAlmostEqual(residual_logmgf(z, tilt)/independent, 1., places=10)
        path = Path(__file__).parent/'results/hierarchical_split_comparison.json'
        cases = json.loads(path.read_text(encoding='utf-8'))['primary']
        checked = set()
        for case in cases:
            lifetime = 0.
            total_builds = 0.
            for row in case['rows']:
                witness = row['global_stash']
                n, z = row['capacity'], case['child_z']
                key = (n, z, witness['capacity'], witness['chernoff_tilt'])
                if key not in checked:
                    with localcontext() as ctx:
                        ctx.prec = 80
                        t = Decimal(str(witness['chernoff_tilt']))
                        ln2 = Decimal(2).ln()
                        bound = (ln2+Decimal(2*n//z)*positive_poisson_logmgf(z, t)
                                 -Decimal(witness['capacity']+1)*t)/ln2
                    self.assertLessEqual(float(bound), witness['per_build_target_log2']+1e-8)
                    self.assertAlmostEqual(float(bound), witness['per_build_log2'], places=8)
                    checked.add(key)
                builds = 2**32/row['accesses_per_rebuild']
                total_builds += builds
                lifetime += builds*2**witness['per_build_log2']
            self.assertEqual(total_builds, 2**32/case['batch'])
            self.assertAlmostEqual(log2(lifetime), case['global_stash_lifetime_failure_log2'])
            for event in ('global_stash', 'local_stash', 'parent_routing'):
                self.assertLess(case[event+'_lifetime_failure_log2'], -66)


if __name__ == '__main__':
    unittest.main()
