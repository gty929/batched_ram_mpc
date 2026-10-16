#pragma once
#include <vector>
#include <cstdint>
#include "header/ctx.hpp"

namespace nog {

struct RefInputs {
  std::vector<uint64_t> x0_ids; // [1..n]
  std::vector<uint64_t> x1_ids; // [n+1..n+m]
};

void send_ref_inputs_offline(GarblerCtx& ctx, const RefInputs& R);
RefInputs recv_ref_inputs_offline(EvaluatorCtx& ctx);

// Verify that y_ids is the stable merge of (x0_ids, x1_ids) according to s
bool verify_merge_ids(const std::vector<uint64_t>& x0_ids,
                      const std::vector<uint64_t>& x1_ids,
                      const std::vector<bool>& s,
                      const std::vector<uint64_t>& y_ids);

} // namespace nog
