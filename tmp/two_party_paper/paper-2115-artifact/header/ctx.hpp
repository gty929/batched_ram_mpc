#pragma once
#include <emp-tool/emp-tool.h>

using namespace emp;
namespace nog {

struct GarblerCtx {
  emp::NetIO* io;
  emp::PRG prg;
  emp::block DELTA;
  emp::block Hkey;
  uint64_t gid = 1;
  uint64_t DDH_count = 0;
  explicit GarblerCtx(int port);
  ~GarblerCtx();
  void sync();
  // inline uint64_t net_bytes() const { return (uint64_t)io->cnt; }
  inline emp::block H(const emp::block &k, uint64_t id) {
    emp::block seed = k ^ Hkey ^ emp::makeBlock(0, (long long)id);
    emp::PRG h(&seed, 16);
    emp::block out; 
    h.random_block(&out, 1); 
    return out;
  }
};

struct EvaluatorCtx {
  emp::NetIO* io;
  emp::PRG prg;
  emp::block DELTA;
  emp::block Hkey;
  uint64_t gid = 1;
  emp::block const_zero = emp::makeBlock(0,0);
  emp::block const_one  = emp::makeBlock(1,0);
  int hashingcount = 0;
  explicit EvaluatorCtx(const char* ip, int port);
  ~EvaluatorCtx();
  void sync();
  // inline uint64_t net_bytes() const { return (uint64_t)io->cnt; }
  inline emp::block H(const emp::block &k, uint64_t id) {
    emp::block seed = k ^ Hkey ^ emp::makeBlock(0, (long long)id);
    emp::PRG h(&seed, 16);
    emp::block out; 
    h.random_block(&out, 1); 
    hashingcount++;
    return out;
  }
};

}
