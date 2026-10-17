"""Executable correctness model for metadata-first 512-parent splitting."""
from random import Random


def compact_plan(m, z=0, base=0):
    n = len(m)
    if n == 2:
        return [(base, base + 1, ((1 - m[0]) * m[1]) ^ z)]
    half = n // 2
    left = sum(m[:half])
    threshold = (z + left) % half
    sign = ((z % half + left) >= half) ^ (z >= half)
    return (compact_plan(m[:half], z % half, base)
            + compact_plan(m[half:], threshold, base + half)
            + [(base+i, base+half+i, int(sign ^ (i >= threshold)))
               for i in range(half)])


def apply(items, schedule):
    out = list(items)
    for i, j, s in schedule:
        if s:
            out[i], out[j] = out[j], out[i]
    return out


def overflow_flags(items, z):
    n = len(items)
    flags = [0] * n
    for leaf in range(n // z):
        marks = [int(x is not None and x[1] == leaf) for x in items]
        plan = compact_plan(marks)
        first = apply([1] * z + [0] * (n-z), reversed(plan))
        flags = [o ^ (m & (1-f)) for o, m, f in zip(flags, marks, first)]
    return flags


def split(items, z, low_leaf=0):
    n = len(items)
    if n == z:
        assert all(x is None or x[1] == low_leaf for x in items)
        return items
    middle = low_leaf + n // (2*z)
    real_left = sum(x is not None and x[1] < middle for x in items)
    real_right = sum(x is not None and x[1] >= middle for x in items)
    assert real_left <= n//2 and real_right <= n//2
    quota = n//2 - real_left
    rank = 0
    marks = []
    for x in items:
        if x is None:
            marks.append(int(rank < quota))
            rank += 1
        else:
            marks.append(int(x[1] < middle))
    assert sum(marks) == n//2
    rearranged = apply(items, compact_plan(marks))
    return (split(rearranged[:n//2], z, low_leaf)
            + split(rearranged[n//2:], z, middle))


def verify(items, z, stash_capacity=64):
    flags = overflow_flags(items, z)
    expected = sum(max(sum(x is not None and x[1] == leaf for x in items)-z, 0)
                   for leaf in range(512//z))
    assert sum(flags) == expected
    if expected > stash_capacity:
        return False
    ordered = apply(items, compact_plan(flags))
    stash = [ordered[j] if j < expected else None for j in range(stash_capacity)]
    main = [None if j < expected else x for j, x in enumerate(ordered)]
    out = split(main, z)
    observed = sorted(x for x in out+stash if x is not None)
    assert observed == sorted(x for x in items if x is not None)
    for leaf in range(512//z):
        original = [x for x in items if x is not None and x[1] == leaf]
        expected_kept = set(original[:z])
        assert set(x for x in out[leaf*z:(leaf+1)*z] if x is not None) == expected_kept
    return True


if __name__ == '__main__':
    rng = Random(19462026)
    passed = 0
    for z in (64, 128):
        leaves = 512//z
        assert verify([None]*512, z)
        assert verify([(i, i//z) for i in range(512)], z)
        assert verify([(i, 0) for i in range(512)], z, 512-z)
        assert not verify([(i, 0) for i in range(512)], z)
        for excess in (0, 1, 63, 64, 65):
            items = [(i, 0) for i in range(z+excess)] + [None]*(512-z-excess)
            assert verify(items, z) == (excess <= 64)
        for live in (0.1, 0.5, 0.9, 1.0):
            for trial in range(100):
                items = [(i, rng.randrange(leaves)) if rng.random() < live else None
                         for i in range(512)]
                assert verify(items, z)
                passed += 1
    print(f'Passed {passed} random parent splits plus empty, full balanced, maximum skew, and stash-boundary cases.')
