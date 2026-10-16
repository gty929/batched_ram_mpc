#include "header/ctx.hpp"
#include "header/gates.hpp"
#include "header/wire.hpp"
#include "header/ot.hpp"
#include "header/check.hpp"
#include "header/merge_switch.hpp"

#include <algorithm>
#include <cassert>
#include <cstdint>
#include <random>
#include <vector>
#include <iostream>
#include <cstring>

#include <openssl/ec.h>
#include <openssl/bn.h>
#include <openssl/obj_mac.h>

using std::vector;
using namespace emp;

namespace nog {

static uint64_t g_eval_group_exp = 0; 


  
static inline int ceil_log2(int n) {
  int k = 0; int v = (n <= 1) ? 1 : (n-1);
  while (v) { v >>= 1; ++k; }
  return k;
}
static inline bool present(const EWord& w, int W) {
  return (int)w.b.size() == W;
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

struct P256Ctx {
  EC_GROUP* G;
  BN_CTX*   bn;
  BIGNUM*   order;
};

static inline P256Ctx p256_init() {
  P256Ctx c{};
  c.G = EC_GROUP_new_by_curve_name(NID_X9_62_prime256v1);
  c.bn = BN_CTX_new();
  c.order = BN_new();
  if (!c.G || !c.bn || !c.order) { std::cerr<<"OpenSSL init failed\n"; std::abort(); }
  if (1 != EC_GROUP_get_order(c.G, c.order, c.bn)) { std::cerr<<"get_order failed\n"; std::abort(); }
  return c;
}

static inline void p256_free(P256Ctx& c) {
  if (c.order) BN_free(c.order);
  if (c.bn)    BN_CTX_free(c.bn);
  if (c.G)     EC_GROUP_free(c.G);
}

static inline BIGNUM* p256_rand_scalar(const P256Ctx& c, std::mt19937_64& rg) {
  BIGNUM* x = BN_new();
  if (!x) { std::abort(); }
  do {
    if (1 != BN_rand_range(x, c.order)) { std::cerr << "BN_rand_range failed\n"; std::abort(); }
  } while (BN_is_zero(x));
  return x;
}

static inline void p256_inv(const P256Ctx& c, const BIGNUM* a, BIGNUM* out) {
  BIGNUM* tmp = BN_mod_inverse(nullptr, a, c.order, c.bn);
  if (!tmp) { std::cerr<<"BN_mod_inverse failed\n"; std::abort(); }
  BN_copy(out, tmp);
  BN_free(tmp);
}

static inline void p256_mul(const P256Ctx& c, const BIGNUM* x, const BIGNUM* y, BIGNUM* out) {
  if (1 != BN_mod_mul(out, x, y, c.order, c.bn)) { std::cerr<<"BN_mod_mul failed\n"; std::abort(); }
}

static inline void bn_to_32(const BIGNUM* x, uint8_t out32[32]) {
  if (BN_bn2binpad(x, out32, 32) != 32) { std::cerr<<"BN_bn2binpad failed\n"; std::abort(); }
}

static inline void be32_to_blocks(const uint8_t in32[32], block& b0, block& b1) {
  
  memcpy(&b0, in32, 16);
  memcpy(&b1, in32+16, 16);
}

static inline void blocks_to_be32(const block& b0, const block& b1, uint8_t out32[32]) {
  memcpy(out32, &b0, 16);
  memcpy(out32+16, &b1, 16);
}

struct ECWord {
  std::vector<EC_POINT*> p;
};

static inline bool present_ec(const ECWord& w, int W) {
  return (int)w.p.size() == W;
}

static inline void ecword_alloc_like(const P256Ctx& G, ECWord& w, int W) {
  w.p.resize(W, nullptr);
  for (int i = 0; i < W; ++i) w.p[i] = EC_POINT_new(G.G);
}

static inline void ecword_free(const P256Ctx& G, ECWord& w) {
  for (auto* Q : w.p) if (Q) EC_POINT_free(Q);
  w.p.clear();
}


static inline void ecword_move(ECWord& dst, ECWord& src) {
  dst.p = std::move(src.p); 
}


static inline void ec_point_from_gamma(EvaluatorCtx& ctx, const P256Ctx& G,
                                       int subwire_i, int bit_b, EC_POINT* outP) {
  const uint64_t DOM0 = 0xC0DEC0DEC0DEC0DEULL;
  const uint64_t DOM1 = 0xFACEFACEFACEFACEULL;
  block h0 = ctx.H(makeBlock((uint64_t)subwire_i, (uint64_t)bit_b), DOM0);
  block h1 = ctx.H(makeBlock((uint64_t)subwire_i, (uint64_t)bit_b), DOM1);
  uint8_t gamma_bytes[32];
  memcpy(gamma_bytes,      &h0, 16);
  memcpy(gamma_bytes + 16, &h1, 16);

  BIGNUM* gamma = BN_bin2bn(gamma_bytes, 32, nullptr);
  
  BN_CTX* bn = G.bn;
  BN_mod(gamma, gamma, G.order, bn);
  if (BN_is_zero(gamma)) BN_one(gamma);

  
  if (1 != EC_POINT_mul(G.G, outP, gamma, nullptr, nullptr, bn)) {
    std::cerr << "EC_POINT_mul (Gamma*G) failed\n"; std::abort();
  }
  BN_free(gamma);
}


static inline void init_ecword_from_bits(EvaluatorCtx& ctx, const P256Ctx& G,
                                         uint64_t word_bits, int W, ECWord& w) {
  ecword_alloc_like(G, w, W);
  for (int t = 0; t < W; ++t) {
    int b = ((word_bits >> t) & 1ULL) ? 1 : 0;
    ec_point_from_gamma(ctx, G, t, b, w.p[t]);
  }
}





struct P256Row { block c0, c1; };

struct DDHPayload {
  vector<P256Row> rows; 
};

static inline void send_payload(GarblerCtx& ctx, const DDHPayload& P) {
  if (!P.rows.empty()) {
    
    ctx.io->send_block(reinterpret_cast<const block*>(P.rows.data()), (int)(P.rows.size()*2));
  } else {
    std::cerr << "no rows to send\n";
  }
}

static inline void recv_payload(EvaluatorCtx& ctx, size_t rows, DDHPayload& P) {
  P.rows.resize(rows);
  if (rows) ctx.io->recv_block(reinterpret_cast<block*>(P.rows.data()), (int)(rows*2));
}

static inline void switch_edge_garbler_p256(GarblerCtx& ctx, const P256Ctx& G,
                                            const BIGNUM* K_src, const BIGNUM* K_dst,
                                            const GBit& ctrl_zero, DDHPayload& P) {
  BIGNUM* inv = BN_new(); BIGNUM* R = BN_new();
  if (!inv || !R) { std::abort(); }
  p256_inv(G, K_src, inv);
  p256_mul(G, K_dst, inv, R);

  uint8_t rbytes[32]; bn_to_32(R, rbytes);
  block rb0, rb1; be32_to_blocks(rbytes, rb0, rb1);

  P256Row row;
  
  block pad0 = ctx.H(ctrl_zero.z, ctx.gid++);
  block pad1 = ctx.H(ctrl_zero.z, ctx.gid++);
  row.c0 = rb0 ^ pad0;
  row.c1 = rb1 ^ pad1;
  P.rows.push_back(row);

  BN_free(inv); BN_free(R);
}



static inline void switch_edge_eval_apply_p256(EvaluatorCtx& ctx, const P256Ctx& G,
                                               const EWord& Src, ECWord* SrcEC,
                                               EWord& Dst, ECWord* DstEC, int W,
                                               const EBit& ctrl_label, bool apply,
                                               DDHPayload& P, size_t& idx) {
  if (idx >= P.rows.size()) return;
  P256Row row = P.rows[idx++];
  block pad0 = ctx.H(ctrl_label.a, ctx.gid++);
  block pad1 = ctx.H(ctrl_label.a, ctx.gid++);

  block rb0 = row.c0 ^ pad0;
  block rb1 = row.c1 ^ pad1;
  uint8_t Rbytes[32];
  blocks_to_be32(rb0, rb1, Rbytes);
  BIGNUM* R = BN_bin2bn(Rbytes, 32, nullptr);
  BN_mod(R, R, G.order, G.bn);
  if (BN_is_zero(R)) BN_one(R);
  const uint64_t domA = 0xA5A5A5A5A5A5A5A5ULL;
  const uint64_t domB = 0x5A5A5A5A5A5A5A5AULL;
  block alpha = ctx.H(rb0, domA) ^ ctx.H(rb1, domB);

  if (apply && (int)Src.b.size() == W) {
    Dst.b.resize(W);
    for (int i = 0; i < W; ++i) Dst.b[i].a = Src.b[i].a ^ alpha;
    if (SrcEC && DstEC && present_ec(*SrcEC, W)) {
      if (!present_ec(*DstEC, W)) ecword_alloc_like(G, *DstEC, W);
      for (int i = 0; i < W; ++i) {
        if (1 != EC_POINT_mul(G.G, DstEC->p[i], nullptr, SrcEC->p[i], R, G.bn)) {
          std::cerr << "EC_POINT_mul (R * L) failed\n"; std::abort();
        }
      }
      g_eval_group_exp += (uint64_t)W;
    }
  }
  BN_free(R);
}

void run_garbler_compaction_simd(const Args& A) {
  GarblerCtx ctx(A.port); ctx.sync();
  P256Ctx G = p256_init();

  const int n = A.n, m = A.m, W = A.w;
  const int N = n + m;
  const int L = ceil_log2(std::max(1, N));

  vector<GBit> Gb(N); for (int i=0;i<N;++i) const_bit(ctx,false,Gb[i]);
  ot_send_bit_labels(ctx, Gb); ctx.sync();
  vector<GWord> X0g(n), X1g(m);
  vector<GBit> zeros_data; zeros_data.reserve((size_t)W * N);
  for (int i=0;i<n;++i){ X0g[i].b.resize(W);
    for (int t=0;t<W;++t){ const_bit(ctx,false,X0g[i].b[t]); zeros_data.push_back(X0g[i].b[t]); } }
  for (int j=0;j<m;++j){ X1g[j].b.resize(W);
    for (int t=0;t<W;++t){ const_bit(ctx,false,X1g[j].b[t]); zeros_data.push_back(X1g[j].b[t]); } }
  ot_send_bit_labels(ctx, zeros_data); ctx.sync();

  
  const uint64_t pairs_per_pass = count_pairs_one_pass(N);
  vector<GBit> C0g(pairs_per_pass), C1g(pairs_per_pass);
  for (uint64_t t=0;t<pairs_per_pass;++t) const_bit(ctx,false,C0g[(size_t)t]);
  for (uint64_t t=0;t<pairs_per_pass;++t) const_bit(ctx,false,C1g[(size_t)t]);
  ot_send_bit_labels(ctx, C0g);
  ot_send_bit_labels(ctx, C1g);
  ctx.sync();

  
  GBit G0b, G1b; const_bit(ctx,false,G0b); const_bit(ctx,true,G1b);
  send_const_keys(G0b, G1b, ctx); ctx.sync();

  
  std::mt19937_64 rgen(0xA1000281ULL);
  vector<vector<BIGNUM*>> K0(L+3, vector<BIGNUM*>(N, nullptr));
  vector<vector<BIGNUM*>> K1(L+3, vector<BIGNUM*>(N, nullptr));
  for (int l=1;l<=L+2;++l) for (int i=0;i<N;++i) { K0[l][i]=p256_rand_scalar(G,rgen); K1[l][i]=p256_rand_scalar(G,rgen); }

  DDHPayload P;

  
  uint64_t q=0;
  for (int l = L-1; l >= 0; --l) {
    int stride = 1<<l, blk = 1<<(l+1);
    for (int base=0;base<N;base+=blk) {
      int mid = base + stride, end = std::min(base+blk, N);
      for (int tau=mid; tau<end; ++tau) {
        switch_edge_garbler_p256(ctx, G, K0[l+1][tau], K0[l+2][tau], C0g[q], P);
        switch_edge_garbler_p256(ctx, G, K0[l+1][tau], K0[l+2][tau - stride],C1g[q], P);
        switch_edge_garbler_p256(ctx, G, K1[l+1][tau], K1[l+2][tau], C0g[q], P);
        switch_edge_garbler_p256(ctx, G, K1[l+1][tau], K1[l+2][tau - stride],C1g[q], P);
        ++q;
      }
    }
  }
  assert(q == pairs_per_pass);

  send_payload(ctx, P);
  ctx.sync();

  const uint64_t switch_rows = 2ull * pairs_per_pass * 2ull;
  std::cout << "[G-P256-SIMD] n="<<n<<" m="<<m<<" W="<<W<<" N="<<N
            << " pairs/pass="<<pairs_per_pass
            << " rows(switch)="<<switch_rows
            << " total_rows_sent="<<P.rows.size()
            << " total_bits="<<(256ull * (uint64_t)P.rows.size())
            << "\n";

  
  for (int l=1;l<=L+2;++l) for (int i=0;i<N;++i) { BN_free(K0[l][i]); BN_free(K1[l][i]); }
  p256_free(G);
}


void run_evaluator_compaction_simd(const Args& A) {
  EvaluatorCtx ctx(A.ip.c_str(), A.port); ctx.sync();
  P256Ctx G = p256_init();

  
  static uint64_t g_eval_group_exp = 0;
  g_eval_group_exp = 0;

  
  
  const uint64_t LAMBDA     = 128;  
  const uint64_t LAMBDA_DDH = 256;  

  const int n = A.n, m = A.m, W = A.w;
  const int N = n + m;
  const int L = ceil_log2(std::max(1, N));

  
  std::mt19937_64 gen(std::random_device{}());
  const uint64_t maskw = (W==64) ? ~0ULL : ((1ULL<<W)-1ULL);
  vector<uint64_t> x0_ids(n), x1_ids(m);
  for (int i=0;i<n;++i) x0_ids[i] = (gen() & maskw);
  for (int j=0;j<m;++j) x1_ids[j] = (gen() & maskw);

  
  vector<uint8_t> b_bytes(N,0); for (int t=0;t<m;++t) b_bytes[t]=1;
  std::shuffle(b_bytes.begin(), b_bytes.end(), std::mt19937{std::random_device{}()});

  auto build_compaction_controls = [&](const vector<uint8_t>& c, int N, vector<vector<uint8_t>>& s){
    s.assign(ceil_log2(std::max(1,N)), vector<uint8_t>(N,0));
    vector<int> S(N,0); int acc=0;
    for (int tau=0; tau<N; ++tau) { S[tau]=acc; acc += (c[tau]!=0); }
    for (int l=0;l<ceil_log2(std::max(1,N));++l) {
      int stride=1<<l, blk=1<<(l+1);
      for (int base=0;base<N;base+=blk) {
        int mid=base+stride, end=std::min(base+blk,N);
        for (int tau=mid; tau<end; ++tau) s[l][tau] = (uint8_t)((S[tau]>>l)&1);
      }
    }
  };
  vector<uint8_t> c0(N), c1(N);
  for (int k=0;k<N;++k) { c0[k]=b_bytes[k]; c1[k]=(uint8_t)(1 ^ b_bytes[k]); }
  vector<vector<uint8_t>> s0, s1; build_compaction_controls(c0,N,s0); build_compaction_controls(c1,N,s1);

  vector<uint8_t> flat0, flat1;
  for (int l=(int)s0.size()-1; l>=0; --l) {
    int stride=1<<l, blk=1<<(l+1);
    for (int base=0;base<N;base+=blk) {
      int mid=base+stride, end=std::min(base+blk,N);
      for (int tau=mid; tau<end; ++tau) { flat0.push_back(s0[l][tau]); flat1.push_back(s1[l][tau]); }
    }
  }
  const uint64_t pairs_per_pass = flat0.size();

  
  vector<bool> b_choices(N); for (int i=0;i<N;++i) b_choices[i]=(b_bytes[i]!=0);
  vector<EBit> Eb; ot_recv_bit_labels(ctx, b_choices, Eb); ctx.sync();

  vector<bool> data_choices; data_choices.reserve((size_t)W*N);
  for (int i=0;i<n;++i) {
    for (int t=0;t<W;++t) {
      data_choices.push_back(((x0_ids[i]>>t)&1ULL)!=0ULL);
    }
  }
  for (int j=0;j<m;++j) {
    for (int t=0;t<W;++t) {
      data_choices.push_back(((x1_ids[j]>>t)&1ULL)!=0ULL);
    }
  }
  vector<EBit> DataBits; ot_recv_bit_labels(ctx, data_choices, DataBits); ctx.sync();

  vector<bool> ch0(flat0.begin(), flat0.end()), ch1(flat1.begin(), flat1.end());
  vector<EBit> C0e, C1e; ot_recv_bit_labels(ctx, ch0, C0e); ot_recv_bit_labels(ctx, ch1, C1e); ctx.sync();

  EBit E0b, E1b; recv_const_keys(E0b, E1b, ctx); ctx.sync();

  
  const uint64_t switch_rows = 2ull * pairs_per_pass * 2ull; 
  DDHPayload P; recv_payload(ctx, switch_rows, P); ctx.sync();
  std::cout << "Received rows = " << P.rows.size() << ", expected = " << switch_rows << "\n";
  size_t idx = 0;

  
  vector<EWord> X0e(n), X1e(m); size_t id=0;
  for (int i=0;i<n;++i){ 
    X0e[i].b.resize(W); 
    for(int t=0;t<W;++t) {
      X0e[i].b[t] = DataBits[id++]; 
    }
  }
  for (int j=0;j<m;++j){ 
    X1e[j].b.resize(W); 
    for(int t=0;t<W;++t) {
      X1e[j].b[t] = DataBits[id++]; 
    }
  }
  
  EWord zeroW; zeroW.b.resize(W); for (int t=0;t<W;++t) zeroW.b[t] = E0b;

  
  struct ECWord { std::vector<EC_POINT*> p; };
  auto present_ec = [&](const ECWord& w){ 
    return (int)w.p.size() == W; 
  };
  auto ecword_alloc_like = [&](ECWord& w){
    w.p.resize(W, nullptr);
    for (int i=0;i<W;++i) w.p[i] = EC_POINT_new(G.G);
  };
  auto ecword_free = [&](ECWord& w){
    for (auto* Q : w.p) if (Q) EC_POINT_free(Q);
    w.p.clear();
  };
  auto ecword_move = [&](ECWord& dst, ECWord& src){
    dst.p = std::move(src.p); 
  };
  auto ec_point_from_gamma = [&](int sub_i, int bit_b, EC_POINT* outP){
    const uint64_t DOM0 = 0xC0DEC0DEC0DEC0DEULL;
    const uint64_t DOM1 = 0xFACEFACEFACEFACEULL;
    block h0 = ctx.H(makeBlock((uint64_t)sub_i, (uint64_t)bit_b), DOM0);
    block h1 = ctx.H(makeBlock((uint64_t)sub_i, (uint64_t)bit_b), DOM1);
    uint8_t gamma_bytes[32];
    memcpy(gamma_bytes,      &h0, 16);
    memcpy(gamma_bytes + 16, &h1, 16);
    BIGNUM* gamma = BN_bin2bn(gamma_bytes, 32, nullptr);
    BN_mod(gamma, gamma, G.order, G.bn);
    if (BN_is_zero(gamma)) BN_one(gamma);
    if (1 != EC_POINT_mul(G.G, outP, gamma, nullptr, nullptr, G.bn)) {
      std::cerr << "EC_POINT_mul (Gamma*G) failed\n"; std::abort();
    }
    BN_free(gamma);
  };
  auto init_ecword_from_bits = [&](uint64_t word, ECWord& w){
    ecword_alloc_like(w);
    for (int t=0; t<W; ++t) {
      int b = ((word >> t) & 1ULL) ? 1 : 0;
      ec_point_from_gamma(t, b, w.p[t]);
    }
  };

  std::vector<ECWord> L1_0_ec(N), L1_1_ec(N);
  for (int i=0;i<n;++i) {
    init_ecword_from_bits(x0_ids[i], L1_0_ec[i]);
  }
  
  for (int j=0;j<m;++j) {
    init_ecword_from_bits(x1_ids[j], L1_1_ec[j]);
  }

  
  vector<EWord> Curr0(N), Curr1(N), Next0(N), Next1(N);
  for (int i=0;i<n;++i) {
    Curr0[i] = X0e[i];
  }
  for (int i=n;i<N;++i) {
    Curr0[i] = zeroW;
    }
  for (int j=0;j<m;++j) {
    Curr1[j] = X1e[j];
  }
  for (int j=m;j<N;++j) {
    Curr1[j] = zeroW;
  }

  std::vector<ECWord> Curr0_ec = L1_0_ec, Curr1_ec = L1_1_ec, Next0_ec(N), Next1_ec(N);

  auto apply_edge = [&](const EWord& Src, ECWord& SrcEC,
                        EWord& Dst, ECWord& DstEC,
                        const EBit& ctrl_label, bool apply_flag) {
    if (idx >= P.rows.size()) return;
    P256Row row = P.rows[idx++];

    
    block pad0 = ctx.H(ctrl_label.a, ctx.gid++);
    block pad1 = ctx.H(ctrl_label.a, ctx.gid++);
    block rb0 = row.c0 ^ pad0;
    block rb1 = row.c1 ^ pad1;
    uint8_t Rbytes[32];
    blocks_to_be32(rb0, rb1, Rbytes);
    BIGNUM* R = BN_bin2bn(Rbytes, 32, nullptr);
    BN_mod(R, R, G.order, G.bn);
    if (BN_is_zero(R)) BN_one(R);

    
    const uint64_t domA = 0xA5A5A5A5A5A5A5A5ULL;
    const uint64_t domB = 0x5A5A5A5A5A5A5A5AULL;
    block alpha = ctx.H(rb0, domA) ^ ctx.H(rb1, domB);

    
    if (apply_flag && (int)Src.b.size() == W && present_ec(SrcEC)) {
      
      Dst.b.resize(W);
      for (int i = 0; i < W; ++i) Dst.b[i].a = Src.b[i].a ^ alpha;

      
      if (!present_ec(DstEC)) ecword_alloc_like(DstEC);
      for (int i = 0; i < W; ++i) {
        if (1 != EC_POINT_mul(G.G, DstEC.p[i], nullptr, SrcEC.p[i], R, G.bn)) {
          std::cerr << "EC_POINT_mul (R*L) failed\n"; std::abort();
        }
      }
      g_eval_group_exp += (uint64_t)W;
    }
    BN_free(R);
  };

  uint64_t q=0;
  for (int l=L-1; l>=0; --l) {
    int stride=1<<l, blk=1<<(l+1);
    for (int base=0;base<N;base+=blk) {
      int mid=base+stride, end=std::min(base+blk,N);
      for (int tau=mid; tau<end; ++tau) {
        int i = tau - stride;
        bool s0 = (flat0[q] != 0);
        apply_edge(Curr0[tau], Curr0_ec[tau], Next0[tau], Next0_ec[tau], C0e[q], !s0);
        apply_edge(Curr0[tau], Curr0_ec[tau], Next0[i],   Next0_ec[i],   C1e[q],  s0);
        
        if ((int)Curr0[i].b.size() == W && present_ec(Curr0_ec[i])) {
          if (!s0) {
            if ((int)Next0[i].b.size() != W){
              Next0[i] = Curr0[i];
            }
            if (!present_ec(Next0_ec[i])){
              ecword_move(Next0_ec[i], Curr0_ec[i]);
            }
          } else {
            if ((int)Next0[tau].b.size() != W){
              Next0[tau] = Curr0[i];
            }
            if (!present_ec(Next0_ec[tau])){
              ecword_move(Next0_ec[tau], Curr0_ec[i]);
            }
          }
        }

        
        apply_edge(Curr1[tau], Curr1_ec[tau], Next1[tau], Next1_ec[tau], C0e[q], !s0);
        apply_edge(Curr1[tau], Curr1_ec[tau], Next1[i],   Next1_ec[i],   C1e[q],  s0);
        if ((int)Curr1[i].b.size() == W && present_ec(Curr1_ec[i])) {
          if (!s0) {
            if ((int)Next1[i].b.size() != W) {
              Next1[i] = Curr1[i];
            }
            if (!present_ec(Next1_ec[i])) {
              ecword_move(Next1_ec[i], Curr1_ec[i]);
            }
          } else {
            if ((int)Next1[tau].b.size() != W){
              Next1[tau] = Curr1[i];
            }
            if (!present_ec(Next1_ec[tau])){
              ecword_move(Next1_ec[tau], Curr1_ec[i]);
            }
          }
        }

        ++q;
      }
    }
    Curr0.swap(Next0); Curr1.swap(Next1);
    std::swap(Curr0_ec, Next0_ec); std::swap(Curr1_ec, Next1_ec);
    for (int v=0; v<N; ++v) {
      Next0[v].b.clear(); Next1[v].b.clear();
      ecword_free(Next0_ec[v]); ecword_free(Next1_ec[v]);
    }
  }
  vector<EWord> Y(N);
  size_t i0 = 0, i1 = 0;
  for (int k=0;k<N;++k) {
    if (b_choices[k]) Y[k] = Curr1[i1++]; else Y[k] = Curr0[i0++];
  }  
  vector<uint64_t> y_ids(N);
  i0=0; i1=0;
  for (int k=0;k<N;++k) y_ids[k] = (b_choices[k]? x1_ids[i1++] : x0_ids[i0++]);
  bool ok = verify_merge_ids(x0_ids, x1_ids, vector<bool>(b_choices.begin(), b_choices.end()), y_ids);
  const uint64_t switch_rows_recv = (uint64_t)P.rows.size();
  const uint64_t comm_bits_switch = switch_rows_recv * LAMBDA_DDH; 

  const uint64_t grp_words   = (uint64_t)(n + m);     
  const uint64_t ungrp_words = (uint64_t)N;           
  const uint64_t comm_bits_grp   = grp_words   * (uint64_t)W * (2*LAMBDA_DDH + 1);
  const uint64_t comm_bits_ungrp = ungrp_words * (uint64_t)W * (2*LAMBDA     + 1);
  const unsigned __int128 comm_bits_total = (unsigned __int128)comm_bits_switch + (unsigned __int128)comm_bits_grp +(unsigned __int128)comm_bits_ungrp;

  std::cout << "[E-P256-SIMD] n="<<n<<" m="<<m<<" W="<<W<<" N="<<N
            << " payload_rows="<<switch_rows_recv
            << " switch_bits="<<comm_bits_switch
            << " grp_bits="<<comm_bits_grp
            << " ungrp_bits="<<comm_bits_ungrp
            << " total_bits="<<(unsigned long long)comm_bits_total
            << " check="<<(ok?"OK":"FAIL")
            << "\n";

  std::cout << "[E-P256-SIMD] eval_group_exp="<< g_eval_group_exp
            << " (exact # of EC scalar multiplications performed)\n";

  
  for (int v=0; v<N; ++v) { ecword_free(Curr0_ec[v]); ecword_free(Curr1_ec[v]); }
  p256_free(G);
}

} 
