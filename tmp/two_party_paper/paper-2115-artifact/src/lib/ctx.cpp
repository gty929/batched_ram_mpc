#include "header/ctx.hpp"
using namespace emp;

namespace nog {

static PRG fixed_prg() {
  uint64_t seed = 0xdecafbadcafef00dULL;
  return PRG((const void*)&seed, 8);
}

GarblerCtx::GarblerCtx(int port)
: io(new NetIO(nullptr, port)), prg(fixed_prg()) {
  prg.random_block(&DELTA, 1);
  DELTA = DELTA ^ makeBlock(1,0); // LSB 1 for P&P if desired (not revealed)
  prg.random_block(&Hkey, 1);
  io->send_block(&Hkey, 1);
}
GarblerCtx::~GarblerCtx(){ delete io; }
void GarblerCtx::sync() {
  uint8_t b=0; io->send_data(&b,1); 
  io->recv_data(&b,1);
}

EvaluatorCtx::EvaluatorCtx(const char* ip, int port)
: io(new NetIO(ip, port)), prg(fixed_prg()) {
  io->recv_block(&Hkey, 1);
}
EvaluatorCtx::~EvaluatorCtx(){ 
  delete io; 
  std::cout << "Hashing count:" << hashingcount << std::endl;  
}
void EvaluatorCtx::sync() {
  uint8_t b=0; io->recv_data(&b,1);
  io->send_data(&b,1);
}

} // namespace nog
