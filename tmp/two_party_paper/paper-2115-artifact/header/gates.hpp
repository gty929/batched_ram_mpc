#pragma once
#include "ctx.hpp"
#include "wire.hpp"

namespace nog {

void const_bit(GarblerCtx& ctx, bool v, GBit& g);
void const_bit(EvaluatorCtx& ctx, bool v, EBit& e);

void const_word(GarblerCtx& ctx, int w, uint64_t val, GWord& g);
void const_word(EvaluatorCtx& ctx, int w, uint64_t val, EWord& e);

void switch_zero(GarblerCtx& ctx, const GBit& ctrl, const GBit& x, GBit& y);
void switch_zero(EvaluatorCtx& ctx, const EBit& ctrl, const EBit& x, EBit& y);
void switch_zero_word(GarblerCtx& ctx, const GBit& ctrl, const GWord& x, GWord& y);
void switch_zero_word(EvaluatorCtx& ctx, const EBit& ctrl, const EWord& x, EWord& y);

void join_eq(GarblerCtx& ctx, const GBit& x, const GBit& y);
void join_eq(EvaluatorCtx& ctx, const EBit& x, EBit& y);
void join_eq_word(GarblerCtx& ctx, const GWord& x, const GWord& y);
void join_eq_word(EvaluatorCtx& ctx, const EWord& x, EWord& y);

}
