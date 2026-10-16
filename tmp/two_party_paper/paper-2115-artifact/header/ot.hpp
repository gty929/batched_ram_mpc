#pragma once
#include "ctx.hpp"
#include "wire.hpp"
#include <vector>

namespace nog {

void ot_send_bit_labels(GarblerCtx& ctx, const std::vector<GBit>& zero_labels);

void ot_recv_bit_labels(EvaluatorCtx& ctx, const std::vector<bool>& choice, std::vector<EBit>& out);

} 
