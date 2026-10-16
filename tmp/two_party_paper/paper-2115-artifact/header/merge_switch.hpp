#pragma once
#include "args.hpp"
#include "ctx.hpp"
#include "wire.hpp"
#include "gates.hpp"

namespace nog {
void recv_const_keys(EBit& E0b, EBit& E1b, EvaluatorCtx& ctx);
void send_const_keys(const GBit& G0b, const GBit& G1b, GarblerCtx& ctx);
void run_garbler(const Args& A);
void run_evaluator(const Args& A);
void run_garbler_randomized(const Args& A);
void run_evaluator_randomized(const Args& A);
}
