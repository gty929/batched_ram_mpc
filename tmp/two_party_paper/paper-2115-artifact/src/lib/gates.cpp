#include "header/gates.hpp"
using namespace emp;

namespace nog {

// constants / inputs
void const_bit(GarblerCtx& ctx, bool v, GBit& g) {
  ctx.prg.random_block(&g.z, 1);
  if (v) g.z = g.z ^ ctx.DELTA;
  // std::cout << g.z << std::endl;
}
void const_bit(EvaluatorCtx& ctx, bool v, EBit& e) {
  e.a = v ? ctx.const_one : ctx.const_zero;
}

void const_word(GarblerCtx& ctx, int w, uint64_t val, GWord& g) {
  g.b.resize(w);
  for (int i=0;i<w;i++) const_bit(ctx, ((val>>i)&1)!=0, g.b[i]);
}
void const_word(EvaluatorCtx& ctx, int w, uint64_t val, EWord& e) {
  e.b.resize(w);
  for (int i=0;i<w;i++) const_bit(ctx, ((val>>i)&1)!=0, e.b[i]);
}

// switch (zero-comm)
void switch_zero(GarblerCtx& ctx, const GBit& ctrl, const GBit& x, GBit& y) {
  y.z = x.z ^ ctx.H(ctrl.z, ctx.gid++);
}
void switch_zero(EvaluatorCtx& ctx, const EBit& ctrl, const EBit& x, EBit& y) {
  y.a = x.a ^ ctx.H(ctrl.a, ctx.gid++);
}
void switch_zero_word(GarblerCtx& ctx, const GBit& ctrl, const GWord& x, GWord& y) {
  int w = (int)x.b.size(); y.b.resize(w);
  for (int i=0;i<w;i++) switch_zero(ctx, ctrl, x.b[i], y.b[i]);
}
void switch_zero_word(EvaluatorCtx& ctx, const EBit& ctrl, const EWord& x, EWord& y) {
  int w = (int)x.b.size(); y.b.resize(w);
  for (int i=0;i<w;i++) switch_zero(ctx, ctrl, x.b[i], y.b[i]);
}

// join
void join_eq(GarblerCtx& ctx, const GBit& x, const GBit& y) {
  block d = x.z ^ y.z;
  ctx.io->send_block(&d, 1);
}
void join_eq(EvaluatorCtx& ctx, const EBit& x, EBit& y) {
  block d; ctx.io->recv_block(&d, 1);
  y.a = x.a ^ d;
}
void join_eq_word(GarblerCtx& ctx, const GWord& x, const GWord& y) {
  int w = (int)x.b.size();
  for (int i=0;i<w;i++) join_eq(ctx, x.b[i], y.b[i]);
}
void join_eq_word(EvaluatorCtx& ctx, const EWord& x, EWord& y) {
  int w = (int)x.b.size();
  for (int i=0;i<w;i++) join_eq(ctx, x.b[i], y.b[i]);
}

} // namespace nog
