#include "three_halves.hpp"

#include "hash.hpp"
#include "key_manager.hpp"
#include "rand.hpp"
#include "util.hpp"
namespace PicoGRAM {
namespace ThreeHalves {
typedef uint64_t control_t;
// assume arr in row-major
control_t arr_to_control_col_major(const bool* arr, size_t n_row,
                                   size_t n_col) {
  control_t result = 0;
  for (size_t i = 0; i < n_col; ++i) {
    for (size_t j = 0; j < n_row; ++i) {
      result = (result << 1) | arr[j * n_col + i];
    }
  }
  return result;
}

control_t arr_to_control_row_major(const bool* arr, size_t n_row,
                                   size_t n_col) {
  control_t result = 0;
  for (size_t i = 0; i < n_row; ++i) {
    for (size_t j = 0; j < n_col; ++i) {
      result = (result << 1) | arr[i * n_col + j];
    }
  }
  return result;
}

bool access_bit_row_major(control_t x, size_t n_row, size_t n_col, size_t row,
                          size_t col) {
  return (x >> (n_row * n_col - row * n_col - col - 1)) & 1;
}

bool access_bit_col_major(control_t x, size_t n_row, size_t n_col, size_t row,
                          size_t col) {
  return (x >> (n_row * n_col - col * n_row - row - 1)) & 1;
}

void print_control_row_major(control_t x, size_t n_row, size_t n_col) {
  for (size_t i = 0; i < n_row; ++i) {
    for (size_t j = 0; j < n_col; ++j) {
      std::cout << access_bit_row_major(x, n_row, n_col, i, j);
    }
    std::cout << std::endl;
  }
}

void print_control_col_major(control_t x, size_t n_row, size_t n_col) {
  for (size_t i = 0; i < n_row; ++i) {
    for (size_t j = 0; j < n_col; ++j) {
      std::cout << access_bit_col_major(x, n_row, n_col, i, j);
    }
    std::cout << std::endl;
  }
}

static const control_t R_a = 0b000110110011011000110110001011010011100100100111;
static const control_t R_b = 0b001101100010110100101101000110110010011100011110;
static const control_t R_d_base_1 =
    0b111111111010101010101010010101010010110100011011;
static const control_t R_d_base_2 =
    0b101010100101010101010101111111110001101100110110;
static const control_t R_p = 0b000000000100010010100000000000000010000000000100;

control_t sampleR(bool a, bool b, uint8_t r[8]) {
  //   static const control_t R_a =
  //       0b000000000000011111111010100110011101111001100111;
  //   static const control_t R_b =
  //       0b000000000000111010100101011101111011100111011110;
  //   static const control_t R_d_base_1 =
  //       0b111000100100111010100101111011100110111001100111;
  //   static const control_t R_d_base_2 =
  //       0b100100011100100101011111100110011101100111011110;
  //   static const control_t R_p =
  //       0b001000010000001010000000000000010001000000000000;

  const uint8_t rand_multiplier = rand_bit_pool.get_rand_bits(2);
  const bool rand_base_1 = rand_multiplier & 1;
  const bool rand_base_2 = rand_multiplier >> 1;
  // static const control_t R_bar = R_a_bar * a + R_b_bar * b + (rand_multiplier
  // & 1) * R_d_bar_base_0 + (rand_multiplier >> 1) * R_d_bar_base_1;
  const control_t R = R_a * a ^ R_b * b ^ R_d_base_1 * rand_base_1 ^
                      R_d_base_2 * rand_base_2 ^ R_p;

  r[0] = rand_base_1;
  r[1] = rand_base_2;

  r[2] = a ^ b ^ rand_base_1;
  r[3] = a ^ rand_base_2;

  r[4] = b ^ rand_base_1;
  r[5] = a ^ b ^ rand_base_2;

  r[6] = a ^ rand_base_1;
  r[7] = b ^ rand_base_2;

  return R;
}

/**
 * @brief The garble function
 * nonce should increment by at least 3 for each call
 */
Label Garble(Label A0, Label B0, uint64_t nonce, uint8_t material[3 * 8 + 1]) {
  const bool pi_A = A0.LSB();
  const bool pi_B = B0.LSB();
  // follow the convention in the paper
  if (pi_A) {
    A0 ^= key_manager.get_Delta();
  }
  if (pi_B) {
    B0 ^= key_manager.get_Delta();
  }
  uint8_t r[8];
  const control_t R = sampleR(!pi_A, !pi_B, r);
  const control_t t = 0b1000000001 << (pi_A * 2 + pi_B) * 2;
  const control_t R_t = R ^ t;
  // Note: V_inv is in row-major
  const control_t V_inv = 0b1000000001000000110011001111000000001010;
  uint64_t non_full_H_vec[6] = {0};
  const __m128i& A0_raw = A0.get_m128i();
  const __m128i& B0_raw = B0.get_m128i();
  const Label& Delta = key_manager.get_Delta();
  const __m128i& Delta_raw = Delta.get_m128i();
  // copy A0 to non_full_H_vec[0..1]
  _mm_storeu_si128(reinterpret_cast<__m128i*>(non_full_H_vec), A0_raw);
  // copy B0 to non_full_H_vec[2..3]
  _mm_storeu_si128(reinterpret_cast<__m128i*>(non_full_H_vec + 2), B0_raw);
  // copy Delta to non_full_H_vec[4..5]
  _mm_storeu_si128(reinterpret_cast<__m128i*>(non_full_H_vec + 4), Delta_raw);

  uint64_t non_H_prod[8] = {0};
  for (size_t i = 0; i < 8; ++i) {
    for (size_t j = 0; j < 6; ++j) {
      non_H_prod[i] ^=
          non_full_H_vec[j] * access_bit_col_major(R_t, 8, 6, i, j);
    }
  }

  // compute full_H_vec
  uint64_t full_H_vec[6] = {0};
  uint8_t H_r_vec[6] = {0};
  Label full_full_H_vec[6];
  full_full_H_vec[0] = Hash(A0, nonce);
  full_full_H_vec[1] = Hash(A0 ^ Delta, nonce);
  full_full_H_vec[2] = Hash(B0, nonce + 1);
  full_full_H_vec[3] = Hash(B0 ^ Delta, nonce + 1);
  full_full_H_vec[4] = Hash(A0 ^ B0, nonce + 2);
  full_full_H_vec[5] = Hash(A0 ^ B0 ^ Delta, nonce + 2);
  for (size_t i = 0; i < 6; ++i) {
    const __m128i& H_raw = full_full_H_vec[i].get_m128i();
    uint64_t tmp[2];
    _mm_storeu_si128(reinterpret_cast<__m128i*>(tmp), H_raw);
    full_H_vec[i] = tmp[0];
    H_r_vec[i] = tmp[1] & 1;  // last d / 2 = 1 bit
  }

  // M is in row-major
  static const control_t M = 0b100010001010100001000101010001001001010010000110;

  // compute M * (full_H_vec || H_r_vec)
  uint64_t M_H_prod[8] = {0};
  uint8_t M_H_r_prod[8] = {0};
  uint control_bit_idx = 48;
  for (size_t i = 0; i < 8; ++i) {
    for (size_t j = 0; j < 6; ++j) {
      bool control_bit = (M >> (--control_bit_idx)) & 1;
      M_H_prod[i] ^= full_H_vec[j] * control_bit;
      M_H_r_prod[i] ^= H_r_vec[j] * control_bit;
    }
  }
  uint64_t masked_prod[8];
  uint8_t masked_r[8];
  for (size_t i = 0; i < 8; ++i) {
    masked_prod[i] = non_H_prod[i] ^ M_H_prod[i];
    masked_r[i] = r[i] ^ M_H_r_prod[i];
  }

  // compute V_inv * (masked_prod || masked_r)
  uint64_t full_material[5] = {0};
  uint8_t z_k_vec[5] = {0};
  control_bit_idx = 40;
  for (size_t i = 0; i < 5; ++i) {
    for (size_t j = 0; j < 8; ++j) {
      bool bit_V_inv = (V_inv >> (--control_bit_idx)) & 1;
      full_material[i] ^= masked_prod[j] * bit_V_inv;
      z_k_vec[i] ^= masked_r[j] * bit_V_inv;
    }
  }
  // pack z_k_vec to z_k
  uint8_t z_k = 0;
  for (size_t i = 0; i < 5; ++i) {
    z_k = (z_k << 1) | z_k_vec[i];
  }

  Label C;
  // set C to be the first two 64-bit blocks
  C.set_m128i(_mm_loadu_si128(reinterpret_cast<__m128i*>(full_material)));
  // bool pi_C = C.LSB();
  // Label W_k = pi_C ? C ^ Delta : C;
  // copy the last 3 64-bit blocks to material
  memcpy(material, full_material + 2, 3 * 8);
  material[3 * 8] = z_k;
  return C;
}

control_t DecodeR(uint8_t r[2], bool i, bool j) {
  static const control_t S_1 = 0b11101001;
  static const control_t S_2 = 0b10010111;
  control_t R_ij = r[0] * S_1 ^ r[1] * S_2;
  static const control_t R_p_vec[2][2] = {{0b00100100, 0b00100000},
                                          {0b00000100, 0b00000000}};
  return R_ij ^ R_p_vec[i][j];
}

Label Eval(Label A, Label B, uint64_t nonce,
           const uint8_t material[3 * 8 + 1]) {
  bool i = A.LSB();
  bool j = B.LSB();
  Label full_H_vec[3];
  full_H_vec[0] = Hash(A, nonce);
  full_H_vec[1] = Hash(B, nonce + 1);
  full_H_vec[2] = Hash(A ^ B, nonce + 2);
  Label full_H_prod[2];
  full_H_prod[0] = full_H_vec[0] ^ full_H_vec[2];
  full_H_prod[1] = full_H_vec[1] ^ full_H_vec[2];
  uint64_t H_prod[2] = {0};
  uint8_t H_r_prod[2] = {0};
  for (size_t i = 0; i < 2; ++i) {
    const __m128i& H_raw = full_H_prod[i].get_m128i();
    uint64_t tmp[2];
    _mm_storeu_si128(reinterpret_cast<__m128i*>(tmp), H_raw);
    H_prod[i] = tmp[0];
    H_r_prod[i] = tmp[1] & 1;  // last d / 2 = 1 bit
  }
  static const control_t V[2][2] = {{0b1000001000, 0b1000101011},
                                    {0b1010101001, 0b1010001010}};

  uint64_t non_H_prod[2] = {0};
  uint8_t non_H_r[2] = {0};
  control_t V_active = V[i][j];
  uint8_t z_vec[5];
  for (size_t row = 0; row < 5; ++row) {
    z_vec[row] = (material[3 * 8] >> (4 - row)) & 1;
  }
  uint control_bit_idx = 10;
  for (size_t row = 0; row < 2; ++row) {
    for (size_t col = 0; col < 5; ++col) {
      bool bit_V = (V_active >> (--control_bit_idx)) & 1;
      if (col >= 2) {
        uint64_t G;
        memcpy(&G, material + (col - 2) * 8, 8);
        non_H_prod[row] ^= G * bit_V;
      }
      non_H_r[row] ^= z_vec[col] * bit_V;
    }
  }

  uint64_t X_ij[2] = {0};
  uint8_t r[2] = {0};
  for (size_t i = 0; i < 2; ++i) {
    X_ij[i] = non_H_prod[i] ^ H_prod[i];
    r[i] = non_H_r[i] ^ H_r_prod[i];
  }
  control_t R_ij = DecodeR(r, i, j);
  uint64_t E_k[2] = {0};
  control_bit_idx = 7;
  for (size_t i = 0; i < 2; ++i) {
    uint64_t A_vec[2] = {0};
    uint64_t B_vec[2] = {0};
    const __m128i& A_raw = A.get_m128i();
    const __m128i& B_raw = B.get_m128i();
    _mm_storeu_si128(reinterpret_cast<__m128i*>(A_vec), A_raw);
    _mm_storeu_si128(reinterpret_cast<__m128i*>(B_vec), B_raw);
    E_k[i] = X_ij[i] ^ ((R_ij >> control_bit_idx) & 1) * A_vec[0] ^
             ((R_ij >> (control_bit_idx - 1)) & 1) * A_vec[1] ^
             ((R_ij >> (control_bit_idx - 2)) & 1) * B_vec[0] ^
             ((R_ij >> (control_bit_idx - 3)) & 1) * B_vec[1];
    control_bit_idx = 3;
  }
  Label C;
  C.set_m128i(_mm_loadu_si128(reinterpret_cast<__m128i*>(E_k)));
  return C;
}
}  // namespace ThreeHalves

}  // namespace PicoGRAM