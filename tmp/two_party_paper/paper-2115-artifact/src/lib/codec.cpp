#include "header/codec.hpp"

namespace nog {

static inline uint64_t mask_w(int w) {
  return (w == 64) ? ~0ULL : ((1ULL << w) - 1);
}
uint64_t PublicCodec::inv_mod_2k(uint64_t a, int k) {
  // Newton iteration for inverse mod 2^k; requires a odd
  uint64_t x = 1;
  uint64_t mod = mask_w(k);
  for (int i = 0; i < k; ++i) x = (x * (2 - a * x)) & mod;
  return x & mod;
}
PublicCodec::PublicCodec(uint64_t Akey, uint64_t Bkey, int ww)
: A(Akey | 1ULL), B(Bkey), w(ww), mask(mask_w(ww)), invA(inv_mod_2k(A, ww)) {}

uint64_t PublicCodec::encode(uint64_t v) const {
  return (A * (v & mask) + B) & mask;
}
uint64_t PublicCodec::decode(uint64_t c) const {
  return ((c - B) * invA) & mask;
}

} // namespace nog
