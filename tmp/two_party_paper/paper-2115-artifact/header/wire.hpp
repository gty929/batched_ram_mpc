#pragma once
#include <vector>
#include <emp-tool/emp-tool.h>

namespace nog {
struct GBit { emp::block z; };
struct EBit { emp::block a; };

struct GWord { std::vector<GBit> b; };
struct EWord { std::vector<EBit> b; };

inline void xorb(const GBit& x, const GBit& y, GBit& z) { z.z = x.z ^ y.z; }
inline void xorb(const EBit& x, const EBit& y, EBit& z) { z.a = x.a ^ y.a; }

inline void xorw(const GWord& x, const GWord& y, GWord& z) {
  size_t w = x.b.size(); z.b.resize(w);
  for (size_t i=0;i<w;i++) xorb(x.b[i], y.b[i], z.b[i]);
}
inline void xorw(const EWord& x, const EWord& y, EWord& z) {
  size_t w = x.b.size(); z.b.resize(w);
  for (size_t i=0;i<w;i++) xorb(x.b[i], y.b[i], z.b[i]);
}
}
