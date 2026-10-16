#include "header/check.hpp"
#include <cstring>

namespace nog {

void send_ref_inputs_offline(GarblerCtx& ctx, const RefInputs& R) {
  uint64_t n = R.x0_ids.size(), m = R.x1_ids.size();
  // for (auto x : R.x0_ids) std::cout << x << " "  << std::endl; // Debug print
  // for (auto x : R.x1_ids) std::cout << x << " " << std::endl; // Debug print
  ctx.io->send_data(&n, sizeof(n));
  ctx.io->send_data(&m, sizeof(m));
  if (n) ctx.io->send_data(R.x0_ids.data(), n*sizeof(uint64_t));
  if (m) ctx.io->send_data(R.x1_ids.data(), m*sizeof(uint64_t));
}

RefInputs recv_ref_inputs_offline(EvaluatorCtx& ctx) {
  RefInputs R; uint64_t n=0, m=0;
  ctx.io->recv_data(&n, sizeof(n));
  ctx.io->recv_data(&m, sizeof(m));
  R.x0_ids.resize(n); R.x1_ids.resize(m);
  if (n) ctx.io->recv_data(R.x0_ids.data(), n*sizeof(uint64_t));
  if (m) ctx.io->recv_data(R.x1_ids.data(), m*sizeof(uint64_t));
  return R;
}

bool verify_merge_ids(const std::vector<uint64_t>& x0_ids,
                      const std::vector<uint64_t>& x1_ids,
                      const std::vector<bool>& s,
                      const std::vector<uint64_t>& y_ids) { 
  size_t n = x0_ids.size(), m = x1_ids.size();
  if (y_ids.size() != n+m || s.size() != n+m) return false;
  size_t i0=0, i1=0;
  for (size_t k = 0; k < n+m; ++k) {
    uint64_t expect = s[k] ? x1_ids[i1++] : x0_ids[i0++];
    if (y_ids[k] != expect) return false;
  }
  return true;
}

}