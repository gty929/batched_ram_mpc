#include "header/ctx.hpp"
#include "header/gates.hpp"
#include "header/wire.hpp"
#include "header/ot.hpp"
#include "header/check.hpp"
#include "header/merge_boolean.hpp"

#include <algorithm>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <random>
#include <vector>

using std::vector;
using namespace emp;

namespace nog {

static inline int ceil_log2(int n) {
  int k = 0; int v = (n <= 1) ? 1 : (n-1);
  while (v) { v >>= 1; ++k; }
  return k;
}

static inline void const_Lword(GarblerCtx& ctx, int L, uint64_t v, GWord& out) {
  out.b.resize(L);
  for (int i = 0; i < L; ++i) const_bit(ctx, ((v>>i)&1ULL)!=0ULL, out.b[i]);
}
static inline void const_Lword(EvaluatorCtx& ctx, int L, uint64_t v, EWord& out) {
  out.b.resize(L);
  for (int i = 0; i < L; ++i) const_bit(ctx, ((v>>i)&1ULL)!=0ULL, out.b[i]);
}

static inline void andw(GarblerCtx& ctx, const GBit& sel, const GWord& x, GWord& y);
static inline void andw(EvaluatorCtx& ctx, const EBit& sel, const EWord& x, EWord& y);

static inline void cswap_word(GarblerCtx& ctx, const GWord& x, const GWord& y, const GBit& c, GWord& o0, GWord& o1) {
  GWord d, t, tmp;
  xorw(x, y, d);
  andw(ctx, c, d, t);
  xorw(x, t, tmp); o0 = std::move(tmp);
  xorw(y, t, tmp); o1 = std::move(tmp);
  ctx.DDH_count += 256 * 2;
}
static inline void cswap_word(EvaluatorCtx& ctx, const EWord& x, const EWord& y, const EBit& c, EWord& o0, EWord& o1) {
  EWord d, t, tmp;
  xorw(x, y, d);
  andw(ctx, c, d, t);
  xorw(x, t, tmp); o0 = std::move(tmp);
  xorw(y, t, tmp); o1 = std::move(tmp);
}

// c[k]=1 means filler, c[k]=0 means real
static inline void build_compaction_controls(const vector<uint8_t>& c, int N,
                                             vector<vector<uint8_t>>& s) {
  const int L = ceil_log2(std::max(1, N));
  s.assign(L, vector<uint8_t>(N, 0));
  vector<int> S(N, 0);
  int acc = 0;
  for (int tau = 0; tau < N; ++tau) { 
    S[tau] = acc; 
    acc += (c[tau] != 0); 
  }
  for (int l = 0; l < L; ++l) {
    int stride = 1 << l, blk = 1 << (l+1);
    for (int base = 0; base < N; base += blk) {
      int mid = base + stride;
      int end = std::min(base + blk, N);
      for (int tau = mid; tau < end; ++tau) {
        s[l][tau] = (uint8_t)((S[tau] >> l) & 1);
      }
    }
  }
}

// Flatten s[l][tau] into a linear vector in the exact order the network will consume
static inline void flatten_controls(const vector<vector<uint8_t>>& s, int N, vector<uint8_t>& out) {
  out.clear();
  for (int l = (int)s.size()-1; l >= 0; --l) {
    int stride = 1<<l, blk = 1<<(l+1);
    for (int base = 0; base < N; base += blk) {
      int mid = base + stride, end = std::min(base + blk, N);
      for (int tau = mid; tau < end; ++tau) out.push_back(s[l][tau]);
    }
  }
}
template<class Ctx, class Word, class Bit>
static inline void apply_distribution(Ctx& ctx, int N, const vector<Bit>& C, vector<Word>& wires) {
  size_t q = 0;
  const int L = ceil_log2(std::max(1, N));
  for (int l = L-1; l >= 0; --l) {
    int stride = 1 << l, blk = 1 << (l+1);
    for (int base = 0; base < N; base += blk) {
      int mid = base + stride, end = std::min(base + blk, N);
      for (int tau = mid; tau < end; ++tau) {
        int i = tau - stride, j = tau;
        Word o0, o1;
        cswap_word(ctx, wires[i], wires[j], C[q++], o0, o1);
        wires[i] = std::move(o0);
        wires[j] = std::move(o1);
      }
    }
  }
  assert(q == C.size());
}

static inline void mux_word(GarblerCtx& ctx, const GWord& a0, const GWord& a1, const GBit& b, GWord& y) {
  GWord d, t, tmp;
  xorw(a0, a1, d);
  andw(ctx, b, d, t);
  xorw(a0, t, tmp); y = std::move(tmp);
}

static inline void mux_word(EvaluatorCtx& ctx, const EWord& a0, const EWord& a1, const EBit& b, EWord& y) {
  EWord d, t, tmp;
  xorw(a0, a1, d);
  andw(ctx, b, d, t);
  xorw(a0, t, tmp); y = std::move(tmp);
}

static inline uint64_t count_pairs_one_pass(int N) {
  uint64_t total = 0;
  const int L = ceil_log2(std::max(1, N));
  for (int l = 0; l < L; ++l) {
    int stride = 1 << l, blk = 1 << (l+1);
    int full = N / blk;
    int rem  = N % blk;
    total += (uint64_t)full * stride + (rem > stride ? (rem - stride) : 0);
  }
  return total;
}

static inline void send_const_keys(const GBit& G0b, const GBit& G1b, GarblerCtx& ctx) {
  ctx.io->send_block(&G0b.z, 1);
  block one_active = G1b.z ^ ctx.DELTA;
  ctx.io->send_block(&one_active, 1);
}

static inline void recv_const_keys(EvaluatorCtx& ctx, EBit& E0b, EBit& E1b) {
  ctx.io->recv_block(&E0b.a, 1);  // session const_zero label
  ctx.io->recv_block(&E1b.a, 1);  // session const_one  label
  ctx.const_zero = E0b.a;
  ctx.const_one  = E1b.a;
}


struct BooleanPayload {
  std::vector<block> HG;
};

static inline void send_payload_bool(GarblerCtx& ctx, const BooleanPayload& P) {
  if (!P.HG.empty()) {
    ctx.io->send_block(P.HG.data(), (int)P.HG.size());
  } 
}
static inline void recv_payload_bool(EvaluatorCtx& ctx, size_t rows, BooleanPayload& P) {
  P.HG.resize(rows);
  if (rows) {
    ctx.io->recv_block(P.HG.data(), (int)rows);
  }
}

static thread_local std::vector<block> __HG_send_buf;
static thread_local const block*       __HG_recv_ptr;
static thread_local size_t             __HG_recv_idx;

static inline void __hg_reset_for_run() {
  __HG_send_buf.clear();
  __HG_recv_ptr = nullptr;
  __HG_recv_idx = 0;
}

static inline void andb_halfgate(GarblerCtx& ctx, const GBit& a, const GBit& b, GBit& out) {
  ctx.prg.random_block(&out.z, 1);
  uint64_t gid_g = ctx.gid++, gid_e = ctx.gid++;

  block HA0 = ctx.H(a.z, gid_g);
  block HA1 = ctx.H(a.z ^ ctx.DELTA, gid_g);
  block HB0 = ctx.H(b.z, gid_e);
  block HB1 = ctx.H(b.z ^ ctx.DELTA, gid_e);

  int pa = getLSB(a.z);
  int pb = getLSB(b.z);

  block TG = (HA0 ^ HA1) ^ (pb ? ctx.DELTA : makeBlock(0,0));
  block TE = (HB0 ^ HB1) ^ (pa ? ctx.DELTA : makeBlock(0,0));

  TG ^= out.z; TE ^= out.z;

  __HG_send_buf.push_back(TG);
  __HG_send_buf.push_back(TE);
}

static inline void andb_halfgate(EvaluatorCtx& ctx, const EBit& a, const EBit& b, EBit& out) {
  block TG = __HG_recv_ptr[__HG_recv_idx++];
  block TE = __HG_recv_ptr[__HG_recv_idx++];
  uint64_t gid_g = ctx.gid++, gid_e = ctx.gid++;

  block J = ctx.H(a.a, gid_g);
  block K = ctx.H(b.a, gid_e);

  out.a = J ^ K ^ TG ^ TE;
}

static inline void andw(GarblerCtx& ctx, const GBit& sel, const GWord& x, GWord& y) {
  int w = (int)x.b.size(); y.b.resize(w);
  for (int i = 0; i < w; ++i) { 
    GBit t; 
    andb_halfgate(ctx, sel, x.b[i], t); 
    y.b[i]=t; 
  }
}
static inline void andw(EvaluatorCtx& ctx, const EBit& sel, const EWord& x, EWord& y) {
  int w = (int)x.b.size(); y.b.resize(w);
  for (int i = 0; i < w; ++i) { 
    EBit t; 
    andb_halfgate(ctx, sel, x.b[i], t); 
    y.b[i]=t; 
  }
}


void run_garbler_compaction_boolean_gc(const Args& A) {
  GarblerCtx ctx(A.port); ctx.sync();
  __hg_reset_for_run();

  const int n = A.n, m = A.m, w = A.w;
  const int N = n + m;
  uint64_t net0 = ctx.io->counter;

  vector<GBit> Gb(N); 
  for (int i=0;i<N;++i) {
    const_bit(ctx, false, Gb[i]);
  }
  ot_send_bit_labels(ctx, Gb);
  ctx.sync();

  vector<GWord> X0g(n), X1g(m);
  vector<GBit> zeros_data; 
  zeros_data.reserve((size_t)w * N);
  for (int i = 0; i < n; ++i) { 
    X0g[i].b.resize(w); 
    for (int t=0;t<w;++t) { 
      const_bit(ctx, false, X0g[i].b[t]); 
      zeros_data.push_back(X0g[i].b[t]); 
    } 
  }
  for (int j = 0; j < m; ++j) { 
    X1g[j].b.resize(w); 
    for (int t=0;t<w;++t) { 
      const_bit(ctx, false, X1g[j].b[t]); 
      zeros_data.push_back(X1g[j].b[t]); 
    } 
  }
  ot_send_bit_labels(ctx, zeros_data); 
  ctx.sync();

  // Control streams for compaction (unchanged semantics)
  uint64_t pairs_per_pass = count_pairs_one_pass(N);
  vector<GBit> C0g(pairs_per_pass), C1g(pairs_per_pass);
  for (uint64_t t=0;t<pairs_per_pass;++t) {
    const_bit(ctx, false, C0g[(size_t)t]);
  }
  for (uint64_t t=0;t<pairs_per_pass;++t) {
    const_bit(ctx, false, C1g[(size_t)t]);
  }
  ot_send_bit_labels(ctx, C0g);
  ot_send_bit_labels(ctx, C1g);
  ctx.sync();

  uint64_t net_after_ots = ctx.io->counter;
  uint64_t ots_bits = 8ull * (net_after_ots - net0);

  GBit G0b, G1b; 
  const_bit(ctx,false,G0b); 
  const_bit(ctx,true,G1b);
  send_const_keys(G0b, G1b, ctx); 
  ctx.sync();
  GWord G0w; const_word(ctx, w, 0, G0w);


  vector<GWord> W0(N), W1(N);
  for (int i = 0; i < n; ++i) {
    W0[i] = X0g[i];
  }
  for (int i = n; i < N; ++i) {
    const_Lword(ctx, w, 0, W0[i]);
  }
  for (int j = 0; j < m; ++j) {
    W1[j] = X1g[j];
  }
  for (int j = m; j < N; ++j) {
    const_Lword(ctx, w, 0, W1[j]);
  }

  auto t_construct_start = std::chrono::steady_clock::now();
  apply_distribution(ctx, N, C0g, W0);
  apply_distribution(ctx, N, C1g, W1);
  vector<GWord> Y(N);
  for (int k=0;k<N;++k) mux_word(ctx, W0[k], W1[k], Gb[k], Y[k]);
  auto t_construct_end = std::chrono::steady_clock::now();
  double garble_construct_ms = std::chrono::duration<double, std::milli>(t_construct_end - t_construct_start).count();

  BooleanPayload P; P.HG.swap(__HG_send_buf);
  auto t_send_start = std::chrono::steady_clock::now();
  send_payload_bool(ctx, P);
  ctx.sync();
  auto t_send_end = std::chrono::steady_clock::now();
  double garble_send_ms = std::chrono::duration<double, std::milli>(t_send_end - t_send_start).count();

  const uint64_t pairs0 = pairs_per_pass, pairs1 = pairs_per_pass;
  const uint64_t and_count_structural = (pairs0 + pairs1) * (uint64_t)w + (uint64_t)N * (uint64_t)w;
  const uint64_t expected_rows = 2ull * and_count_structural; 
  const uint64_t nonOT_bits = 8ull * (ctx.io->counter - net_after_ots);

  std::cout << "[G-CompNet-Payload] "
            << "n="<<n<<" m="<<m<<" w="<<w<<" N="<<N
            << " pairs/pass="<<pairs_per_pass
            << " ANDs(struct)="<<and_count_structural
            << " rows(sent)="<<P.HG.size()<<" (exp="<<expected_rows<<")"
            << " ots_bits="<<ots_bits
            << " nonOT_bits="<<nonOT_bits
            << " garble_construct_ms="<<garble_construct_ms
            << " garble_send_ms="<<garble_send_ms
            << "\n";
}


void run_evaluator_compaction_boolean_gc(const Args& A) {
  EvaluatorCtx ctx(A.ip.c_str(), A.port); ctx.sync();
  __hg_reset_for_run();

  const int n = A.n, m = A.m, w = A.w;
  const int N = n + m;
  std::random_device rd; std::mt19937_64 gen(rd());
  const uint64_t maskw = (w == 64) ? ~0ULL : ((1ULL<<w) - 1ULL);
  vector<uint64_t> x0_ids(n), x1_ids(m);
  for (int i=0;i<n;++i) {
    x0_ids[i] = (gen() & maskw);
  }
  for (int j=0;j<m;++j) {
    x1_ids[j] = (gen() & maskw);
  }

  vector<uint8_t> b_bytes(N, 0);
  for (int t = 0; t < m; ++t) {
    b_bytes[t] = 1;
  }
  std::shuffle(b_bytes.begin(), b_bytes.end(), std::mt19937{std::random_device{}()});

  vector<uint8_t> c0(N), c1(N);
  for (int k=0;k<N;++k) { c0[k]=b_bytes[k]; c1[k]=(uint8_t)(1 ^ b_bytes[k]); }
  vector<vector<uint8_t>> s0, s1;
  build_compaction_controls(c0, N, s0);
  build_compaction_controls(c1, N, s1);
  vector<uint8_t> flat0, flat1;
  for (int l=(int)s0.size()-1; l>=0; --l) {
    int stride = 1<<l, blk = 1<<(l+1);
    for (int base=0;base<N;base+=blk) {
      int mid=base+stride, end=std::min(base+blk,N);
      for (int tau=mid;tau<end;++tau) { flat0.push_back(s0[l][tau]); flat1.push_back(s1[l][tau]); }
    }
  }
  assert(flat0.size()==flat1.size());

  auto t_inputs_start = std::chrono::steady_clock::now();

  vector<bool> b_choices(N); for (int i=0;i<N;++i) b_choices[i]=(b_bytes[i]!=0);
  vector<EBit> Eb; ot_recv_bit_labels(ctx, b_choices, Eb); ctx.sync();

  vector<bool> data_choices; data_choices.reserve((size_t)w * N);
  for (int i=0;i<n;++i) {
    for (int t=0;t<w;++t) {
      data_choices.push_back(((x0_ids[i]>>t)&1ULL)!=0ULL);
    }
  }
  for (int j=0;j<m;++j) {
    for (int t=0;t<w;++t) {
      data_choices.push_back(((x1_ids[j]>>t)&1ULL)!=0ULL);
    }
  }
  vector<EBit> DataBits; 
  ot_recv_bit_labels(ctx, data_choices, DataBits);
  ctx.sync();

  vector<bool> ch0(flat0.begin(), flat0.end());
  vector<bool> ch1(flat1.begin(), flat1.end());
  vector<EBit> C0e, C1e;
  ot_recv_bit_labels(ctx, ch0, C0e);
  ot_recv_bit_labels(ctx, ch1, C1e);
  ctx.sync();

  EBit E0b, E1b; recv_const_keys(ctx, E0b, E1b); ctx.sync();

  const uint64_t pairs_per_pass = count_pairs_one_pass(N);
  const uint64_t and_count_structural = (pairs_per_pass + pairs_per_pass) * (uint64_t)w + (uint64_t)N * (uint64_t)w;
  const uint64_t rows = 2ull * and_count_structural;

  BooleanPayload P;
  auto t_prefetch_start = std::chrono::steady_clock::now();
  recv_payload_bool(ctx, rows, P);
  ctx.sync();
  auto t_prefetch_end = std::chrono::steady_clock::now();
  double prefetch_ms = std::chrono::duration<double, std::milli>(t_prefetch_end - t_prefetch_start).count();

  vector<EWord> X0e(n), X1e(m); size_t idx=0;
  for (int i=0;i<n;++i){ 
    X0e[i].b.resize(w); 
    for(int t=0;t<w;++t) {
      X0e[i].b[t]=DataBits[idx++]; 
    }
  }
  for (int j=0;j<m;++j){ 
    X1e[j].b.resize(w); 
    for(int t=0;t<w;++t) {
      X1e[j].b[t]=DataBits[idx++]; 
    }
  }

  vector<EWord> W0(N), W1(N);
  for (int i=0;i<n;++i) {
    W0[i]=X0e[i];
  }
  for (int i=n;i<N;++i) {
    const_Lword(ctx, w, 0, W0[i]);
  }
  for (int j=0;j<m;++j) {
    W1[j]=X1e[j];
  }
  for (int j=m;j<N;++j) {
    const_Lword(ctx, w, 0, W1[j]);
  }
  __HG_recv_ptr = P.HG.data(); __HG_recv_idx = 0;

  auto t_eval_cpu_start = std::chrono::steady_clock::now();
  apply_distribution(ctx, N, C0e, W0);
  apply_distribution(ctx, N, C1e, W1);
  vector<EWord> Y(N);
  for (int k=0;k<N;++k) mux_word(ctx, W0[k], W1[k], Eb[k], Y[k]);
  auto t_eval_cpu_end = std::chrono::steady_clock::now();

  double inputs_ms = std::chrono::duration<double, std::milli>(t_prefetch_start - t_inputs_start).count();
  double evaluate_cpu_ms = std::chrono::duration<double, std::milli>(t_eval_cpu_end - t_eval_cpu_start).count();
  double e2e_eval_ms = prefetch_ms + evaluate_cpu_ms;

  vector<uint64_t> y_ids(N);
  size_t i0=0, i1=0;
  for (int k=0;k<N;++k) y_ids[k] = (b_bytes[k]? x1_ids[i1++] : x0_ids[i0++]);
  bool ok = verify_merge_ids(x0_ids, x1_ids, vector<bool>(b_choices.begin(), b_choices.end()), y_ids);

  std::cout << "[E-CompNet-Payload] "
            << "n="<<n<<" m="<<m<<" w="<<w<<" N="<<N
            << " inputs_ms="<<inputs_ms
            << " prefetch_ms="<<prefetch_ms
            << " evaluate_cpu_ms="<<evaluate_cpu_ms
            << " e2e_eval_ms="<<e2e_eval_ms
            << " outputs="<<N
            << " check="<<(ok?"OK":"FAIL")
            << "\n";
}

} 