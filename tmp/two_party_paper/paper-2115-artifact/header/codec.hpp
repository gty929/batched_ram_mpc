#pragma once
#include <cstdint>

namespace nog {

// enc(v) = (A*v + B) mod 2^w, with odd A; dec(c) = (c - B) * A^{-1} mod 2^w
struct PublicCodec {
  uint64_t A, B; int w;
  uint64_t mask, invA; // invA = A^{-1} mod 2^w

  PublicCodec(uint64_t Akey, uint64_t Bkey, int w);
  uint64_t encode(uint64_t v) const;
  uint64_t decode(uint64_t c) const;

private:
  static uint64_t inv_mod_2k(uint64_t a, int k);
};

} // namespace nog
