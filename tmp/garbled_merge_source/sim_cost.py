import numpy as np
from scipy.stats import norm
import math

simd_threshold = 1
k = 128
sigma = 64
comm_and = 1.5 * k + 5
comm_half_and = k
pack = 2

pack_factor = 2**pack / pack
# the average cost of doing an encode and an ungroup operation on a bit in pack
# each pack costs 2**pack ciphertexts in G_q to encode, and (2**pack - 1) * pack ciphertexts in {0,1}^lambda to ungroup, along with 2**pack - 1 hashs of length sigma for the evaluator to determine the number of rows to decrypt
comm_translation = ((pack_factor * 2) + (2**pack - 1)) * k + (
    (2**pack - 1) / pack
) * sigma
comm_join = k + 1
comm_simd_join = 2 * k

# us per op using openssl and 2.2 ghz cpu
cpu_freq = 2.2e3  # MHz
time_exp = 53.249
time_gen_exp = 7.807
time_hash = 0.0178423
time_mult = 0.0603047
time_inv = 13.7456
time_xor = 0.006322  # using __m128i
time_inv_batch = 3 * time_mult

print(time_exp * cpu_freq)
print(time_gen_exp * cpu_freq)
print(time_hash * cpu_freq)
print(time_mult * cpu_freq)
print(time_inv * cpu_freq)

time_g_and = 0.144348
time_e_and = 0.0532583
time_g_half_and = time_hash
time_e_half_and = time_hash
time_g_join = time_xor
# in expectation half of the join gates are actually evaluated
time_e_join = time_xor * 0.5
time_g_simd_join = time_inv_batch
time_e_simd_join = time_mult
time_g_buffer = time_hash
time_e_buffer = time_hash
time_g_simd_buffer = time_hash * 2 + time_mult
time_e_simd_buffer = time_hash * 2 + time_mult
time_g_translation = pack_factor * (
    time_gen_exp
    + (pack - 1 + 2) * time_hash  # for encode
    + time_gen_exp
    + (time_hash + 1) * pack  # for ungroup
)
time_e_translation = (
    (pack - 1 + 2) * time_hash  # for encode
    + time_exp
    + (pack + 1) * time_hash  # for ungroup
)


# include counts of full and, half and, join, buffer, simd join, simd buffer, translation, and translation eval
class Cost:

    def __init__(
        self,
        and_g=0,
        half_and_g=0,
        join_g=0,
        boolean_join_g=0,  # join gates that does not count into the stack
        simd_join_g=0,
        buffer_g=0,
        simd_buffer_g=0,
        translation_g=0,
        and_e=0,
        half_and_e=0,
        join_e=0,
        simd_join_e=0,
        boolean_join_e=0,  # join gates that does not count into the stack
        buffer_e=0,
        simd_buffer_e=0,
        translation_e=0,
        inv_g=0,  # additional numbers of modular inversions
        inv_e=0,
    ):
        self.and_g = and_g
        self.half_and_g = half_and_g
        self.join_g = join_g
        self.boolean_join_g = boolean_join_g
        self.simd_join_g = simd_join_g
        self.buffer_g = buffer_g
        self.simd_buffer_g = simd_buffer_g
        self.translation_g = translation_g
        self.and_e = and_e
        self.half_and_e = half_and_e
        self.join_e = join_e
        self.boolean_join_e = boolean_join_e
        self.simd_join_e = simd_join_e
        self.buffer_e = buffer_e
        self.simd_buffer_e = simd_buffer_e
        self.translation_e = translation_e
        self.inv_g = inv_g
        self.inv_e = inv_e

    def __add__(self, other):
        return Cost(
            self.and_g + other.and_g,
            self.half_and_g + other.half_and_g,
            self.join_g + other.join_g,
            self.boolean_join_g + other.boolean_join_g,
            self.simd_join_g + other.simd_join_g,
            self.buffer_g + other.buffer_g,
            self.simd_buffer_g + other.simd_buffer_g,
            self.translation_g + other.translation_g,
            self.and_e + other.and_e,
            self.half_and_e + other.half_and_e,
            self.join_e + other.join_e,
            self.boolean_join_e + other.boolean_join_e,
            self.simd_join_e + other.simd_join_e,
            self.buffer_e + other.buffer_e,
            self.simd_buffer_e + other.simd_buffer_e,
            self.translation_e + other.translation_e,
            self.inv_g + other.inv_g,
            self.inv_e + other.inv_e,
        )

    # scalar multiplication
    def __mul__(self, other):
        return Cost(
            self.and_g * other,
            self.half_and_g * other,
            self.join_g * other,
            self.boolean_join_g * other,
            self.simd_join_g * other,
            self.buffer_g * other,
            self.simd_buffer_g * other,
            self.translation_g * other,
            self.and_e * other,
            self.half_and_e * other,
            self.join_e * other,
            self.boolean_join_e * other,
            self.simd_join_e * other,
            self.buffer_e * other,
            self.simd_buffer_e * other,
            self.translation_e * other,
            self.inv_g * other,
            self.inv_e * other,
        )

    # mult
    def __rmul__(self, other):
        return self.__mul__(other)

    # scalar division
    def __truediv__(self, other):
        return self.__mul__(1 / other)

    def get_bool_cost(self):
        # copy the cost
        return Cost(
            and_g=self.and_g,
            and_e=self.and_e,
        )

    def get_stack_cost(self):
        return Cost(
            half_and_g=self.half_and_g,
            join_g=self.join_g,
            simd_join_g=self.simd_join_g,
            buffer_g=self.buffer_g,
            simd_buffer_g=self.simd_buffer_g,
            translation_g=self.translation_g,
            inv_g=self.inv_g,
            half_and_e=self.half_and_e,
            join_e=self.join_e,
            simd_join_e=self.simd_join_e,
            buffer_e=self.buffer_e,
            simd_buffer_e=self.simd_buffer_e,
            translation_e=self.translation_e,
            inv_e=self.inv_e,
        )

    def comm_bits(self):
        return (
            self.and_g * comm_and
            + self.half_and_g * comm_half_and
            + self.join_g * comm_join
            + self.boolean_join_g * comm_join
            + self.simd_join_g * comm_simd_join
            + self.translation_g * comm_translation
        )

    def __lt__(self, other):
        return self.comm_bits() < other.comm_bits()

    def comm_MB(self):
        return self.comm_bits() / 8 / 1024 / 1024

    def eval_time(self):
        return (
            self.and_e * time_e_and
            + self.half_and_e * time_e_half_and
            + self.join_e * time_e_join
            + self.boolean_join_e * time_e_join
            + self.simd_join_e * time_e_simd_join
            + self.buffer_e * time_e_buffer
            + self.simd_buffer_e * time_e_simd_buffer
            + self.translation_e * time_e_translation
            + self.inv_e * time_inv
        )

    def eval_cycles(self):
        return self.eval_time() * cpu_freq * 1e-9

    def gen_time(self):
        return (
            self.and_g * time_g_and
            + self.half_and_g * time_g_half_and
            + self.join_g * time_g_join
            + self.boolean_join_g * time_g_join
            + self.simd_join_g * time_g_simd_join
            + self.buffer_g * time_g_buffer
            + self.simd_buffer_g * time_g_simd_buffer
            + self.translation_g * time_g_translation
            + self.inv_g * time_inv
        )

    def gen_cycles(self):
        return self.gen_time() * cpu_freq * 1e-9

    # to string
    def __str__(self):
        return f"and_g: {self.and_g}, half_and_g: {self.half_and_g}, join_g: {self.join_g + self.boolean_join_g}, simd_join_g: {self.simd_join_g}, buffer_g: {self.buffer_g}, simd_buffer_g: {self.simd_buffer_g}, translation_g: {self.translation_g},  inv_g: {self.inv_g}, and_e: {self.and_e}, half_and_e: {self.half_and_e}, join_e: {self.join_e + self.boolean_join_e}, simd_join_e: {self.simd_join_e}, buffer_e: {self.buffer_e}, simd_buffer_e: {self.simd_buffer_e}, translation_e: {self.translation_e}, inv_e: {self.inv_e}"

    def print_breakdowns(self):
        print("Comm. (MB)", self.comm_MB())
        print("Bool Circ. Comm. (MB)", self.get_bool_cost().comm_MB())
        print("Stack Comm. (MB)", self.get_stack_cost().comm_MB())
        print("Garbler CPU cycles (1e9)", self.gen_cycles())
        print("Evaluator CPU cycles (1e9)", self.eval_cycles())


cost_and = Cost(and_g=1, and_e=1)
cost_half_and = Cost(half_and_g=1, half_and_e=1)
cost_buffer = Cost(buffer_g=1, buffer_e=1)
cost_simd_buffer = Cost(simd_buffer_g=1, simd_buffer_e=1)
cost_join = Cost(join_g=1, join_e=1)
cost_boolean_join = Cost(boolean_join_g=1, boolean_join_e=1)
cost_simd_join = Cost(simd_join_g=1, simd_join_e=1)
cost_translation = Cost(translation_g=1, translation_e=1)


def cost_node(T, Z, addr_w, data_w, reset=False):
    read_and_per_offset = 0
    # matchk ← ¬vack ∧ (addr ?= addr k)
    read_and_per_offset += 1 + (addr_w - 1)
    # val ← matchk ? val k : val
    read_and_per_offset += data_w
    # vack ← matchk ? 1 : vack
    read_and_per_offset += 1

    read_and = read_and_per_offset * Z

    scan1_and = 0
    # extra bit for ⊥
    if addr_w == 0:
        log_addr_w = 0
    else:
        log_addr_w = np.ceil(np.log2(addr_w)) + 1
    # goal ≥ i
    scan1_and += log_addr_w
    # deepest ←
    scan1_and += log_addr_w

    # ℓ ← deepest level that a local element can legally reside
    scan1_and += log_addr_w * (Z - 1) * 3

    # ℓ > goal
    scan1_and += log_addr_w

    # goal ′, src′ ←
    scan1_and += log_addr_w * 2

    scan2_and = 0
    scan2_and += log_addr_w - 1  # i = src
    scan2_and += log_addr_w * 3  # target, dest′, src′

    # can-drop ← (dest′ = ⊥) and there is a vacancy in local storage
    scan2_and += Z

    # (can-drop ∨ (target̸ = ⊥)) ∧ (deepest̸ = ⊥)
    scan2_and += 2

    # src′′, dest′′
    scan2_and += 2 * log_addr_w

    evict_and = 0
    # hold̸ = ⊥ ∧ (i = dest)
    evict_and += log_addr_w

    # to-write, hold ′, dest′
    evict_and += 2 * data_w + log_addr_w

    # # write
    evict_and += Z * data_w

    # hold ′′, dest′′
    evict_and += data_w + log_addr_w

    and_per_timestep = read_and + scan1_and + scan2_and + evict_and

    and_e_per_timestamp = read_and / 3 + (scan1_and + scan2_and + evict_and) * 2 / 3

    total_and_g = and_per_timestep * T
    total_and_e = and_e_per_timestamp * T
    total_boolean_join = read_and * T  # need to merge read and evict circuits
    if reset:
        # also need to merge the dummy output
        total_boolean_join += read_and * T

    return (
        Cost(and_g=total_and_g, and_e=total_and_e)
        + total_boolean_join * cost_boolean_join
    )


def tsc_stack_cost_helper(m, w, T):
    if m <= 0:
        assert T <= 0
        return Cost()
    num_join = m * 3 + m // 2 * 4 + m * w * 4  # line14  # line 19 and 20  # line 29-32
    num_buffer_g = (
        m * w * 8
    )  # line 28 - 33 (we omit the buffer for metadata and give prior work some advantange)
    num_buffer_e = m * w * 3
    return Cost(
        join_g=num_join, join_e=num_join, buffer_g=num_buffer_g, buffer_e=num_buffer_e
    ) + tsc_stack_cost_helper(m // 2, w * 2, (T - 3) // 2)


def tsc_stack_cost(T, w):
    # half real & half dummy
    return tsc_stack_cost_helper(T, w, T // 2)


def cost_switch(T, bw, no_trans_bw, no_eval_trans_bw, way, mode):
    depth = np.ceil(np.log2(T))
    num_and_ctrl_per_way = T * (depth - 1)
    cost_ctrl = num_and_ctrl_per_way * cost_half_and * way  # same in both works
    num_join_per_way = T * (depth - 1)
    num_buffer_g_per_way = 2 * T * depth
    # the evaluator only evaluates half of the buffer in one of the ways
    num_buffer_e_per_way = T * depth
    if mode == "picogram":
        if T > simd_threshold:
            num_translations_eval = (
                T * (bw - no_trans_bw - no_eval_trans_bw) + pack - 1
            ) // pack
            num_translations = T * (bw - no_trans_bw)
            cost_buffers = (
                Cost(
                    simd_buffer_g=way * num_buffer_g_per_way,
                    simd_buffer_e=num_buffer_e_per_way,
                )
                / pack
            )
            cost_stacks = (
                num_join_per_way / pack * cost_simd_join * way
                + cost_buffers
                + Cost(inv_e=T)
            )
            # the evaluator performs one actual inversion at each timestep
        else:
            num_translations_eval = 0
            num_translations = 0
            cost_buffers = (
                Cost(buffer_g=way * num_buffer_g_per_way, buffer_e=num_buffer_e_per_way)
                * bw
            )
            cost_stacks = num_join_per_way * cost_join * way * bw + cost_buffers
    else:
        num_translations_eval = 0
        num_translations = 0
        cost_stacks = tsc_stack_cost(T, bw) * way

    return (
        cost_ctrl
        + Cost(translation_g=num_translations, translation_e=num_translations_eval)
        + cost_stacks
    )


def calc_bw(addr_w, data_w):
    if addr_w == 0:
        log_addr_w = 0
    else:
        log_addr_w = np.ceil(np.log2(addr_w)) + 1
    # src, goal, dest
    return 2 * data_w + addr_w + log_addr_w * 3


def cost_tree_per_access(N, T_access, data_w, way, mode, level=0):
    # two deterministic eviction
    T = int(T_access * 3 + N)
    if level == 0:
        T = int(T_access * 3)
        if way == 4:
            Z = 18
        else:
            assert way == 2
            Z = 22
    else:
        if way == 4:
            Z = 8
        else:
            Z = 4
    addr_w = np.ceil(np.log2(N))
    cost = cost_node(T, Z, addr_w, data_w)
    if N > 1:
        actual_way = min(way, N)
        bw = calc_bw(addr_w - 1, data_w)
        # on average, 2/3 of upload data bw is not evaluated
        switch_cost = cost_switch(T, bw, addr_w - 1, data_w * 2 / 3, actual_way, mode)
        cost += switch_cost
        N_child = (N + actual_way - 1) // actual_way
        T_access_child = (T_access + actual_way - 1) // actual_way
        cost += T_access * cost_tree_per_access(
            N_child, T_access_child, data_w, way, mode, level + 1
        )
    return cost / T_access


def cost_butterfly_per_access(N, bkt_size, T_access, data_w, way, mode, level=0):
    T = int(T_access * 2 * 3)
    if T_access < bkt_size:
        # due to inbalance
        T = int(T_access * 3 * 2 + N)
    # two deterministic eviction
    # pad to 2T

    if level == 0:
        if way == 4:
            Z = 18
        else:
            assert way == 2
            Z = 22
    else:
        if way == 4:
            Z = 8
        else:
            Z = 4

    addr_w = np.ceil(np.log2(N))
    cost = cost_node(T, Z, addr_w, data_w)
    if N > 1:
        actual_way = min(way, N)
        bw = calc_bw(addr_w - 1, data_w)
        # on average, 2/3 of upload data bw is not evaluated
        if T > bkt_size:
            switch_cost = np.ceil(T / bkt_size) * cost_switch(
                bkt_size, bw, addr_w - 1, data_w * 2 / 3, actual_way, mode
            )
        else:
            switch_cost = cost_switch(
                T, bw, addr_w - 1, data_w * 2 / 3, actual_way, mode
            )

        cost += switch_cost
        N_child = (N + actual_way - 1) // actual_way
        T_access_child = (T_access + actual_way - 1) // actual_way
        cost += T_access * cost_butterfly_per_access(
            N_child, bkt_size, T_access_child, data_w, way, mode, level + 1
        )
    return cost / T_access


def cost_adaptive_per_access(N, T_access, data_w, way, mode):
    bkt_size = 187
    tree_cost = cost_tree_per_access(N, T_access, data_w, way, mode)
    butterfly_cost = cost_butterfly_per_access(N, bkt_size, T_access, data_w, way, mode)
    return min(tree_cost, butterfly_cost)


print("For Non-recursive ORAM")
for logT in [16, 20, 24, 30]:
    T = 2**logT
    print(
        f"tsc tree T = 2^{logT}:",
        cost_tree_per_access(T, T, 64, 2, "tsc").comm_MB(),
    )
    print(
        f"tsc butterfly T = 2^{logT}:",
        cost_butterfly_per_access(T, 187, T, 64, 2, "tsc").comm_MB(),
    )


def cost_linear(N, data_w):
    # read and write can be done with a single swap
    # return np.array([N * data_w * comm_and * 2, 0])
    return 2 * N * data_w * cost_and


def cost_recursive(N, T_access, data_w, way, mode, enable_butterfly=True):
    if not enable_butterfly:
        cost = cost_tree_per_access(N, T_access, data_w, way, mode)
    else:
        cost = cost_adaptive_per_access(N, T_access, data_w, way, mode)
    addr_w = np.ceil(np.log2(N))

    remain_addr_w = addr_w - 2
    while True:
        pos_map_w_width = 4 * remain_addr_w
        if not enable_butterfly:
            cost_each_pos_map = cost_tree_per_access(
                2**remain_addr_w, T_access, pos_map_w_width, way, mode
            )
        else:
            cost_each_pos_map = cost_adaptive_per_access(
                2**remain_addr_w, T_access, pos_map_w_width, way, mode
            )

        linear_cost = cost_linear(2**remain_addr_w, pos_map_w_width)

        if linear_cost < cost_each_pos_map:
            # print(remain_addr_w)
            cost += linear_cost
            break
        # print("addr_width", remain_addr_w, cost_each_pos_map.comm_MB())
        cost += cost_each_pos_map
        remain_addr_w -= 2
    return cost


print("For Recursive ORAM")
for logT in [16, 20, 24, 30]:
    T = 2**logT
    print(
        f"tsc rec tree T = 2^{logT}:",
        cost_recursive(T, T, 64, 2, "tsc", False).comm_MB(),
    )
    print(
        f"tsc rec butterfly T = 2^{logT}:",
        cost_recursive(T, T, 64, 2, "tsc").comm_MB(),
    )


log_N = 16

picogram = cost_recursive(2**log_N, 2**log_N, 64, 4, "picogram")
print("Picogram")
picogram.print_breakdowns()

simd_threshold = 1e12
picogram_no_simd = cost_recursive(2**log_N, 2**log_N, 64, 4, "picogram")
simd_threshold = 32
print("Picogram (no SIMD)")
picogram_no_simd.print_breakdowns()


tristate = cost_recursive(2**log_N, 2**log_N, 64, 2, "tsc")
print("TSC")
tristate.print_breakdowns()

# import package for computing binomial distribution
from scipy.stats import binom


def binom_log_overflow_prob(N, Np, bkt_size):
    assert N < Np
    num_bkt = Np // bkt_size
    p_each = 1 / num_bkt
    # probability there are more than Z elements in a bucket
    return binom.logsf(bkt_size, N, p_each) + math.log(num_bkt)


print(binom_log_overflow_prob(2**24, 2**24 * 2, 256))


def binom_pad_ratio(N, bkt_size_real, sigma):
    # perform a binary search to find the optimal padding ratio such that overflow prob < sigma
    range_ratio = [1.0, 100.0]
    precision = 1e-5
    while range_ratio[1] - range_ratio[0] > precision:
        ratio = (range_ratio[0] + range_ratio[1]) / 2
        Np = int(N * ratio)
        if binom_log_overflow_prob(N, Np, bkt_size_real * ratio) < math.log(sigma):
            range_ratio[1] = ratio
        else:
            range_ratio[0] = ratio

    return range_ratio[0]


print(binom_pad_ratio(2**24, 16, 2**-40))


def binom_bkt_size(N, pad_ratio, sigma):
    # perform a binary search to find the optimal bucket size such that overflow prob < sigma
    range_bkt_size = [1, 65536]
    precision = 1
    while range_bkt_size[1] - range_bkt_size[0] > precision:
        bkt_size = (range_bkt_size[0] + range_bkt_size[1]) // 2
        Np = int(N * pad_ratio)
        if binom_log_overflow_prob(N, Np, bkt_size) < math.log(sigma):
            range_bkt_size[1] = bkt_size
        else:
            range_bkt_size[0] = bkt_size
    return range_bkt_size[0]


print(binom_bkt_size(2**24, 2, 2**-40))
