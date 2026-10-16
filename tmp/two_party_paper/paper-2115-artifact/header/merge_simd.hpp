#pragma once
#include "args.hpp"

namespace nog {

void run_garbler_compaction_simd(const Args& A);
void run_evaluator_compaction_simd(const Args& A);

} // namespace nog
