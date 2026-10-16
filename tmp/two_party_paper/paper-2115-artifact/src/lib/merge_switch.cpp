#include "header/merge_switch.hpp"
#include "header/ctx.hpp"
#include "header/gates.hpp"
#include "header/wire.hpp"
#include "header/ot.hpp"
#include "header/check.hpp"
#include "header/codec.hpp"

#include <algorithm>
#include <chrono>
#include <iostream>
#include <random>
#include <vector>
#include <cmath>
#include <cassert>  

static inline int compute_delta_lambda(int n, int lambda_bits = 128) {
  const double LN2 = 0.6931471805599453094;
  const double t   = (double)std::max(1, n);
  const double val = 4 * t * (22 + std::log(4*t));
  std::cout << "Delta lambda for n=" << n << " is " << (int)std::ceil(std::sqrt(val)) << "\n";
  return (int)std::ceil(std::sqrt(val));
  
}

static inline bool in_band(int i, int j, int delta) {
  return std::abs(i - j) <= delta;
}

static inline bool up_in_band(int i, int j, int delta){ 
  return (i-1)>=0 && in_band(i-1,j,delta); 
}
static inline bool left_in_band(int i, int j, int delta){ 
  return (j-1)>=0 && in_band(i,j-1,delta); 
}


#define debug(x) std::cerr << #x << " = " << (x) << std::endl;

using namespace emp;
using std::vector;

namespace nog {

struct GarbledPayload {
  std::vector<emp::block> diag_masks;
  std::vector<std::vector<emp::block>> row_masks;
  std::vector<std::vector<emp::block>> col_masks;
};


void send_const_keys(const GBit& G0b, const GBit& G1b, GarblerCtx& ctx) {
  ctx.io->send_block(&G0b.z, 1);
  ctx.io->send_block(&G1b.z, 1);
}

void recv_const_keys(EBit& E0b, EBit& E1b, EvaluatorCtx& ctx) {
  ctx.io->recv_block(&E0b.a, 1);
  ctx.io->recv_block(&E1b.a, 1);
  ctx.const_zero = E0b.a;
  ctx.const_one  = E1b.a;
}

static inline size_t payload_blocks(int n, int m, int w) {
  return (size_t)(n + m) + (size_t)n * (size_t)w + (size_t)m * (size_t)w;
}

static inline void send_payload(GarblerCtx& ctx, const GarbledPayload& P,
                                     int n, int m, int w) {

  const size_t total = payload_blocks(n, m, w);
  
  std::vector<emp::block> buf;
  buf.reserve(total);

  buf.insert(buf.end(), P.diag_masks.begin(), P.diag_masks.end());
  for (int i = 0; i < n; ++i)
    for (int b = 0; b < w; ++b)
      buf.push_back(P.row_masks[i][b]);
  for (int j = 0; j < m; ++j)
    for (int b = 0; b < w; ++b)
      buf.push_back(P.col_masks[j][b]);

  if (!buf.empty()) {
    ctx.io->send_block(buf.data(), (int)buf.size());
  }
}

static inline GarbledPayload recv_payload(EvaluatorCtx& ctx, int n, int m, int w) {
  const size_t total = payload_blocks(n, m, w);
  GarbledPayload P;
  std::vector<emp::block> buf(total);
  if (total) ctx.io->recv_block(buf.data(), (int)total);
  size_t off = 0;
  P.diag_masks.resize(n+m);
  for (int k = 0; k < n + m; ++k) {
    P.diag_masks[k] = buf[off++];
  }

  P.row_masks.assign(n, std::vector<emp::block>(w));
  for (int i = 0; i < n; ++i)
    for (int b = 0; b < w; ++b)
      P.row_masks[i][b] = buf[off++];

  P.col_masks.assign(m, std::vector<emp::block>(w));
  for (int j = 0; j < m; ++j)
    for (int b = 0; b < w; ++b)
      P.col_masks[j][b] = buf[off++];
  return P;

}



static inline uint64_t nswitch_count(int n, int m, int w) {
  return (uint64_t)n*(uint64_t)m + (uint64_t)w*(uint64_t)n*(uint64_t)(m+1);
}
static inline uint64_t njoin_count(int n, int m, int w) {
  return (uint64_t)m + (uint64_t)n + (uint64_t)w*(uint64_t)n + (uint64_t) w * (uint64_t) m;
}

void run_garbler(const Args& A) {
  GarblerCtx ctx(A.port);
  ctx.sync();

  int n = A.n, m = A.m, w = A.w;

  auto t_inputs_start = std::chrono::steady_clock::now();

  vector<GWord> X0g(n), X1g(m);
  for (int i = 0; i < n; ++i) const_word(ctx, w, 0, X0g[i]);
  for (int j = 0; j < m; ++j) const_word(ctx, w, 0, X1g[j]);

  vector<GBit> Sg(n + m);
  for (int k = 0; k < n + m; ++k) const_bit(ctx, false, Sg[k]);
  ot_send_bit_labels(ctx, Sg);
  ctx.sync();
  std::vector<GBit> Xzero_bits; Xzero_bits.reserve((size_t)w * (n + m));
  for (int i = 0; i < n; ++i){
    for (int b = 0; b < w; ++b) {
      Xzero_bits.push_back(X0g[i].b[b]);
    }
  }
    
  for (int j = 0; j < m; ++j){
    for (int b = 0; b < w; ++b) {
      Xzero_bits.push_back(X1g[j].b[b]);
      }
  }
    
  ot_send_bit_labels(ctx, Xzero_bits);
  ctx.sync();
  

  auto t_inputs_end = std::chrono::steady_clock::now();
  auto t_garble_start = std::chrono::steady_clock::now();
  // std::cout << "[G] Garbling started." << std::endl;
  GBit G0b, G1b; 
  const_bit(ctx, false, G0b); 
  const_bit(ctx, true,  G1b);
  send_const_keys(G0b, G1b, ctx);
  std::cout << "G0b: " << G0b.z << std::endl;
  ctx.sync();
  GWord G0w;     
  const_word(ctx, w, 0, G0w);

  vector<vector<GBit>> qg(n+1, vector<GBit>(m+1));
  vector<vector<GBit>> rg(n+1, vector<GBit>(m));
  vector<vector<GBit>> dg(n, vector<GBit>(m+1));
  vector<vector<GWord>> R0g(n, vector<GWord>(m+1));
  vector<vector<GWord>> R1g(n+1,vector<GWord>(m));
  qg[0][0] = G1b;

  vector<GBit>  diag_agg0(n + m);
  vector<bool>  diag_has(n + m, false);
  vector<GWord> row_agg0(n), col_agg0(m);

  for (int k = 0; k <= n + m - 1; ++k) {
    for (int i = 0; i <= n; ++i) {
      int j = k - i; if (j < 0 || j > m) continue;
      if (j < m) {
        if (i == n) switch_zero(ctx, G0b, qg[i][j], rg[i][j]);        // re := q
        else switch_zero(ctx, qg[i][j], G0b, rg[i][j]);        // 0 := re <= q ?= 0
        switch_zero_word(ctx, rg[i][j], G0w, R1g[i][j]);              // read1 on q^1 (Eq.(4))
      }

      if (i < n) {
        if (j == m) dg[i][j] = qg[i][j];
        else { 
          GBit t; 
          xorb(qg[i][j], rg[i][j], t); 
          dg[i][j] = t; 
        }  
        switch_zero_word(ctx, dg[i][j], G0w, R0g[i][j]);              // read0 on q^0 (Eq.(4))
      }
    }
    bool have=false; 
    GBit agg0;
    for (int i = 0; i <= n; ++i) {
      int j = k - i; 
      if (j < 0 || j >= m) continue;
      if (!have) { 
        agg0 = rg[i][j]; 
        have=true; 
      } else { 
        GBit t; 
        xorb(agg0, rg[i][j], t); 
        agg0=t; 
      }
    }
    diag_has[k] = have; 
    if (have) diag_agg0[k] = agg0;

    int kk = k + 1;
    for (int i = 0; i <= n; ++i) {
      int j = kk - i; if (j < 0 || j > m) continue;
      if (i == 0 && j == 0) continue;
      if (i == 0) qg[i][j] = rg[i][j - 1];
      else if (j == 0) qg[i][j] = dg[i - 1][j];
      else { 
        GBit t; 
        xorb(dg[i - 1][j], rg[i][j - 1], t); 
        qg[i][j] = t; }
    }
  }

  for (int i = 0; i < n; ++i) {
    row_agg0[i] = R0g[i][0];
    for (int j = 1; j <= m; ++j) { 
      GWord t; 
      xorw(row_agg0[i], R0g[i][j], t); 
      row_agg0[i] = std::move(t); 
    }
  }
  for (int j = 0; j < m; ++j) {
    col_agg0[j] = R1g[0][j];
    for (int i = 1; i <= n; ++i) { 
      GWord t; 
      xorw(col_agg0[j], R1g[i][j], t); 
      col_agg0[j] = std::move(t); 
    }
  }
  std::vector<GWord> Y0g(n + m);
  for (int k = 0; k <= n + m - 1; ++k) {
    bool init = false;
    int i_lo = std::max(0, k - m);
    int i_hi = std::min(n, k);
    for (int i = i_lo; i <= i_hi; ++i) {
      int j = k - i;
      GWord tmp; bool have = false;
      if (i < n) { 
        tmp = R0g[i][j]; 
        have = true; 
      }
      if (j < m) {
        if (!have) { 
          tmp = R1g[i][j]; 
          have = true; 
        } else { 
          GWord t; 
          xorw(tmp, R1g[i][j], t); 
          tmp = std::move(t); 
        }
      }
      if (!init) { 
        Y0g[k] = std::move(tmp); 
        init = true; 
      } else { 
        GWord t; 
        xorw(Y0g[k], tmp, t); 
        Y0g[k] = std::move(t); 
      }
    }
  }

  GarbledPayload P;
  P.diag_masks.resize(n+m);
  for (int k = 0; k < n + m; ++k) {
    P.diag_masks[k] = diag_has[k] ? (diag_agg0[k].z ^ Sg[k].z) : emp::makeBlock(0,0);
  }
  P.row_masks.assign(n, std::vector<emp::block>(w));
  for (int i=0;i<n;++i) {
    for (int b=0;b<w;++b) {
      P.row_masks[i][b] = row_agg0[i].b[b].z ^ X0g[i].b[b].z;
    }
  }
  P.col_masks.assign(m, std::vector<emp::block>(w));
  for (int j=0;j<m;++j) {
    for (int b=0;b<w;++b) {
      P.col_masks[j][b] = col_agg0[j].b[b].z ^ X1g[j].b[b].z;
    }
  }
  auto t_garble_construct_end = std::chrono::steady_clock::now();
  // std::cout << "[G] Garbling done, sending." << std::endl;
  auto t_garble_send_start = std::chrono::steady_clock::now();
  int counter_OT = ctx.io->counter;
  send_payload(ctx, P, n, m, w);
  int counter_payload = ctx.io->counter - counter_OT;
  ctx.sync();
  auto t_garble_send_end = std::chrono::steady_clock::now();
  


  const uint64_t nswitch = nswitch_count(n, m, w);
  const uint64_t njoin   = njoin_count(n, m, w);
  double inputs_ms           = std::chrono::duration<double, std::milli>(t_inputs_end - t_inputs_start).count();
  double garble_construct_ms = std::chrono::duration<double, std::milli>(t_garble_construct_end - t_garble_start).count();
  double garble_send_ms      = std::chrono::duration<double, std::milli>(t_garble_send_end - t_garble_send_start).count();

  std::cout << "[G] n="<<n<<" m="<<m<<" w="<<w
            << " nswitch="<<nswitch<<" njoin="<<njoin
            << " inputs_ms="<<inputs_ms
            << " garble_construct_ms="<<garble_construct_ms
            << " garble_send_ms="<<garble_send_ms
            << " Communication (bits)="<<ctx.io->counter * 8ull
            << " (OT="<<counter_OT<<" Payload="<<counter_payload * 8ull<<")"
            << "\n";
  return;
}

void run_evaluator(const Args& A) {
  using std::vector;
  EvaluatorCtx ctx(A.ip.c_str(), A.port);
  ctx.sync();

  auto t_inputs_start = std::chrono::steady_clock::now();

  const int n = A.n, m = A.m, w = A.w;
  vector<EWord> X0e(n), X1e(m);
  for (int i = 0; i < n; ++i) X0e[i].b.resize(w);
  for (int j = 0; j < m; ++j) X1e[j].b.resize(w);
  std::random_device rd;
  std::mt19937_64 gen(rd());
  uint64_t mask = (w == 64 ? std::numeric_limits<uint64_t>::max() : ((1ULL << w) - 1));
  std::vector<uint64_t> x0_ids(n), x1_ids(m);     // kept for local verification
  for (int i = 0; i < n; ++i) {
    x0_ids[i] = (gen() & mask);
  }
  for (int j = 0; j < m; ++j) {
    x1_ids[j] = (gen() & mask);
  }

  vector<bool> s(n + m, false);
  for (int t = 0; t < m; ++t) {
    s[t] = true;    
  }        
  std::shuffle(s.begin(), s.end(), std::mt19937{std::random_device{}()});

  vector<EBit> Se;
  ot_recv_bit_labels(ctx, s, Se);
  ctx.sync();

  std::vector<bool> x_choices; x_choices.reserve((size_t)w*(n+m));
  for (int i = 0; i < n; ++i) {
    for (int b = 0; b < w; ++b) {
      x_choices.push_back(((x0_ids[i] >> b) & 1ULL) != 0ULL);
    }
  }
  for (int j = 0; j < m; ++j) {
    for (int b = 0; b < w; ++b) {
      x_choices.push_back(((x1_ids[j] >> b) & 1ULL) != 0ULL);
    }
  }
  std::vector<EBit> Xbits;
  ot_recv_bit_labels(ctx, x_choices, Xbits);
  ctx.sync();
  size_t idx = 0;
  for (int i = 0; i < n; ++i) {
    for (int b = 0; b < w; ++b) {
      X0e[i].b[b] = Xbits[idx++];
    }
  }
  for (int j = 0; j < m; ++j) {
    for (int b = 0; b < w; ++b) {
      X1e[j].b[b] = Xbits[idx++];
    }
  }
  EBit E0b, E1b; 
  recv_const_keys(E0b, E1b, ctx);
  ctx.sync();
  std::cout << "E0b: " << E0b.a << std::endl;


  EWord E0w;     
  const_word(ctx, w, 0, E0w);
  GarbledPayload P = recv_payload(ctx, n, m, w);
  ctx.sync();

  auto t_inputs_end = std::chrono::steady_clock::now();

  auto t_eval_start = std::chrono::steady_clock::now();


  vector<vector<EBit>>  qe(n+1, vector<EBit>(m+1));
  vector<vector<EBit>>  re(n+1, vector<EBit>(m));     // q^1
  vector<vector<EBit>>  de(n,   vector<EBit>(m+1));   // q^0 
  vector<vector<EWord>> R0e(n,  vector<EWord>(m+1));
  vector<vector<EWord>> R1e(n+1,vector<EWord>(m));
  qe[0][0] = E1b;
  std::vector<int> row_pos(n, -1);
  std::vector<int> col_pos(m, -1);
  int cnt0 = 0, cnt1 = 0;
  for (int k = 0; k < n + m; ++k) {
    if (!s[k]) {            // down step -> row i = cnt0
      row_pos[cnt0] = cnt1; // column j is current #ones
      ++cnt0;
    } else {                 // right step -> column j = cnt1
      col_pos[cnt1] = cnt0;  // row i is current #zeros
      ++cnt1;
    }
  }

  for (int k = 0; k <= n + m - 1; ++k) {
    // Build edges & reads on diagonal k (Eq.(2), Eq.(4))
    for (int i = 0; i <= n; ++i) {
      int j = k - i; if (j < 0 || j > m) continue;
      // Right edge q^1_{i,j}
      if (j < m) {
        if (i == n) {
          switch_zero(ctx, E0b, qe[i][j], re[i][j]);
        } else {
          switch_zero(ctx, qe[i][j], E0b, re[i][j]);
        }
        switch_zero_word(ctx, re[i][j], E0w, R1e[i][j]);
      }
      // Down edge q^0_{i,j}
      if (i < n) {
        if (j == m) de[i][j] = qe[i][j];
        else{ 
          EBit t; 
          xorb(qe[i][j], re[i][j], t); 
          de[i][j] = t; 
        } // q^0 = q+q^1
        // read0 := 0^w ⇐= (q^0 ?= 0)
        switch_zero_word(ctx, de[i][j], E0w, R0e[i][j]); // Eq.(4)
      }
    }
    // Diagonal JOIN (Eq.(3)): +re(i,k-i) = s_k
    bool have=false; 
    EBit agg; 
    int ip=-1, jp=-1;
    for (int i = 0; i <= n; ++i) {
      int j = k - i; if (j < 0 || j >= m) continue;
      if (!have) { agg = re[i][j]; ip=i; jp=j; have=true; }
      else { EBit t; xorb(agg, re[i][j], t); agg=t; }
    }
    if (have) {
      // std::cout << "[E] Diagonal " << k << " join at (" << ip << "," << jp << ")\n";
      emp::block agg_in_s = agg.a ^ P.diag_masks[k];   
      emp::block corr     = Se[k].a ^ agg_in_s;      
      re[ip][jp].a        = re[ip][jp].a ^ corr;
    }

    // Next states (Eq.(1))
    int kk = k + 1;
    for (int i = 0; i <= n; ++i) {
      int j = kk - i; if (j < 0 || j > m) continue;
      if (i == 0 && j == 0) {
        continue;
      }
      if (i == 0) {
        qe[i][j] = re[i][j-1];
      }
      else if (j == 0) {
        qe[i][j] = de[i-1][j];
      }
      else { 
        EBit t; 
        xorb(de[i-1][j], re[i][j-1], t); 
        qe[i][j] = t; 
      }
    }
  }
  // Row JOINs for x0
  for (int i = 0; i < n; ++i) {
    // XOR all read0 on row i
    EWord row = R0e[i][0];
    for (int j = 1; j <= m; ++j) { EWord t; xorw(row, R0e[i][j], t); row = std::move(t); }
    int jp = row_pos[i];            
    for (int b = 0; b < w; ++b) {
      emp::block row_in_x0 = row.b[b].a ^ P.row_masks[i][b];
      emp::block corr = X0e[i].b[b].a ^ row_in_x0;
      R0e[i][jp].b[b].a ^= corr;      
    }
  }

  // Column JOINs for x1
  for (int j = 0; j < m; ++j) {
    // XOR all read1 on column j
    EWord col = R1e[0][j];
    for (int i = 1; i <= n; ++i) { EWord t; xorw(col, R1e[i][j], t); col = std::move(t); }
    int ip = col_pos[j];           
    for (int b = 0; b < w; ++b) {
      emp::block col_in_x1 = col.b[b].a ^ P.col_masks[j][b];
      emp::block corr = X1e[j].b[b].a ^ col_in_x1;
      R1e[ip][j].b[b].a ^= corr;    
    }
  }

  std::vector<EWord> Ye(n + m);
  for (int k = 0; k <= n + m - 1; ++k) {
    bool init = false;
    int i_lo = std::max(0, k - m);
    int i_hi = std::min(n, k);
    for (int i = i_lo; i <= i_hi; ++i) {
      int j = k - i;
      EWord tmp; bool have = false;
      if (i < n) { 
        tmp = R0e[i][j]; 
        have = true; 
      }
      if (j < m) {
        if (!have) { 
          tmp = R1e[i][j]; 
          have = true; 
        }
        else { 
          EWord t; 
          xorw(tmp, R1e[i][j], t); 
          tmp = std::move(t); 
        }
      }
      if (!init) { Ye[k] = std::move(tmp); init = true; }
      else { EWord t; xorw(Ye[k], tmp, t); Ye[k] = std::move(t); }
    }
  }
  auto beq = [](const emp::block &a, const emp::block &b)->bool {
    return memcmp(&a, &b, 16) == 0;
  };

  auto t_eval_end = std::chrono::steady_clock::now();

  const uint64_t nswitch = nswitch_count(n, m, w);
  const uint64_t njoin   = njoin_count(n, m, w);
  double inputs_ms   = std::chrono::duration<double, std::milli>(t_inputs_end - t_inputs_start).count();
  double evaluate_ms = std::chrono::duration<double, std::milli>(t_eval_end   - t_eval_start).count();

  std::cout << "[E] n="<<n<<" m="<<m<<" w="<<w
            << " nswitch="<<nswitch<<" njoin="<<njoin
            << " inputs_ms="<<inputs_ms
            << " evaluate_ms="<<evaluate_ms
            << " outputs="<<(n+m)
            << "\n";
  return;
}

void run_garbler_randomized(const Args& A) {
  GarblerCtx ctx(A.port);
  ctx.sync();
  const int n = A.n, m = A.m, w = A.w;
  const int N = n + m;
  const int t_sym = std::min(n, m);
  const int delta = compute_delta_lambda(t_sym, 128);
  auto t_inputs_start = std::chrono::steady_clock::now();

  std::vector<GWord> X0g(n), X1g(m);
  for (int i = 0; i < n; ++i) const_word(ctx, w, 0, X0g[i]);
  for (int j = 0; j < m; ++j) const_word(ctx, w, 0, X1g[j]);

  std::vector<GBit> Sg(N);               
  for (int k = 0; k < N; ++k) const_bit(ctx, false, Sg[k]);
  ot_send_bit_labels(ctx, Sg);
  ctx.sync();

  std::vector<GBit> Xzero_bits; Xzero_bits.reserve((size_t)w * (n + m));
  for (int i = 0; i < n; ++i) {
    for (int b = 0; b < w; ++b) {
      Xzero_bits.push_back(X0g[i].b[b]);
    }
  }
  for (int j = 0; j < m; ++j) {
    for (int b = 0; b < w; ++b) {
      Xzero_bits.push_back(X1g[j].b[b]);
    }
  }
  ot_send_bit_labels(ctx, Xzero_bits);
  ctx.sync();
  std::cout << "[G] Inputs done.\n";

  auto t_inputs_end = std::chrono::steady_clock::now();

  auto t_garble_start = std::chrono::steady_clock::now();

  GBit G0b, G1b; 
  const_bit(ctx, false, G0b); 
  const_bit(ctx, true, G1b);
  send_const_keys(G0b, G1b, ctx); 
  ctx.sync();
  GWord G0w; const_word(ctx, w, 0, G0w);

  std::vector<std::vector<GBit>>  q (n+1, std::vector<GBit>(m+1));
  std::vector<std::vector<GBit>>  r1(n+1, std::vector<GBit>(m));     // q^1
  std::vector<std::vector<GBit>>  r0(n, std::vector<GBit>(m+1));   // q^0
  std::vector<std::vector<GWord>> R0(n,   std::vector<GWord>(m+1));  // read0
  std::vector<std::vector<GWord>> R1(n+1, std::vector<GWord>(m));    // read1
  for (int i = 0; i < n; ++i) {
    for (int j = 0; j <= m; ++j) {
      const_word(ctx, w, 0, R0[i][j]);
    }
  }
  for (int i = 0; i <= n; ++i) {
    for (int j = 0; j <  m; ++j) {
      const_word(ctx, w, 0, R1[i][j]);
    }
  }
  std::cout << "[G] Grids allocated.\n";

  // Start state
  q[0][0] = G1b;

  std::vector<GBit>  diag_agg0(N);
  std::vector<bool>  diag_has(N, false);

  // Diagonals k = 0..N-1
  for (int k = 0; k <= N - 1; ++k) {
    for (int i = 0; i <= n; ++i) {
      int j = k - i; if (j < 0 || j > m) continue;
      if (!in_band(i, j, delta)) {
        // std::cout << "[G] Diagonal " << k << " cell ("<<i<<","<<j<<") out of band\n";
        continue;
      }
      if (j < m) {
        if (i == n){
          switch_zero(ctx, G0b, q[i][j], r1[i][j]);
        }
        else {
          switch_zero(ctx, q[i][j], G0b, r1[i][j]);
        }
        switch_zero_word(ctx, r1[i][j], G0w, R1[i][j]); // Eq. (9) read1
      }
      if (i < n) {
        if (j == m) {
          r0[i][j] = q[i][j];
        } else { 
          GBit t; 
          xorb(q[i][j], r1[i][j], t); 
          r0[i][j] = t; 
        }
        switch_zero_word(ctx, r0[i][j], G0w, R0[i][j]); // Eq. (9) read0
      }
    }
    bool have = false; GBit agg;
    int ip = -1, jp = -1;
    for (int i = 0; i <= n; ++i) {
      int j = k - i; 
      if (j < 0 || j >= m) {
        continue;
      }
      if (!in_band(i, j, delta)) {
        continue;
      }
      if (!have) { 
        agg = r1[i][j]; 
        ip=i; jp=j; 
        have = true; }
      else { 
        GBit t; 
        xorb(agg, r1[i][j], t); 
        agg = t; 
      }
    }
    diag_has[k] = have;
    if (have) diag_agg0[k] = agg;

    int kk = k + 1;
    for (int i = 0; i <= n; ++i) {
      int j = kk - i; 
      if (j < 0 || j > m) {
        continue;
      }
      if (!in_band(i, j, delta)) {
        continue;
      }
      if (i == 0 && j == 0) {
        continue;
      }

      const bool up_ok   = up_in_band(i,j,delta);
      const bool left_ok = left_in_band(i,j,delta);
      if (i == 0) {
        q[i][j] = r1[i][j-1];
      } else if (j == 0) {
        q[i][j] = r0[i-1][j];
      } else if (up_ok && left_ok) {
        GBit t; xorb(r0[i-1][j], r1[i][j-1], t); q[i][j] = t;           
      } else if (up_ok) {
        q[i][j] = r0[i-1][j];                                            
      } else if (left_ok) {
        q[i][j] = r1[i][j-1];                                           
      } 
    }
  }

  
  std::vector<GWord> row_agg0(n), col_agg0(m);
  for (int i = 0; i < n; ++i) {
    row_agg0[i] = R0[i][0];
    for (int j = 1; j <= m; ++j) { 
      GWord t; 
      xorw(row_agg0[i], R0[i][j], t); 
      row_agg0[i] = std::move(t); 
    }
  }
  for (int j = 0; j < m; ++j) {
    col_agg0[j] = R1[0][j];
    for (int i = 1; i <= n; ++i) { 
      GWord t; 
      xorw(col_agg0[j], R1[i][j], t); 
      col_agg0[j] = std::move(t); 
    }
  }

  GarbledPayload P;
  P.diag_masks.resize(N);
  for (int k = 0; k < N; ++k) {
    P.diag_masks[k] = diag_has[k] ? (diag_agg0[k].z ^ Sg[k].z) : emp::makeBlock(0,0);
  }
  P.row_masks.assign(n, std::vector<emp::block>(w));
  for (int i = 0; i < n; ++i) {
    for (int b = 0; b < w; ++b) {
      P.row_masks[i][b] = row_agg0[i].b[b].z ^ X0g[i].b[b].z;
    }
  }
  P.col_masks.assign(m, std::vector<emp::block>(w));
  for (int j = 0; j < m; ++j) {
    for (int b = 0; b < w; ++b) {
      P.col_masks[j][b] = col_agg0[j].b[b].z ^ X1g[j].b[b].z;
    }
  }

  auto t_garble_construct_end = std::chrono::steady_clock::now();

  const int64_t net_before = ctx.io->counter;

  send_payload(ctx, P, n, m, w);    
  ctx.sync();
  auto t_garble_send_end = std::chrono::steady_clock::now();

  double inputs_ms = std::chrono::duration<double,std::milli>(t_inputs_end - t_inputs_start).count();
  double garble_construct_ms = std::chrono::duration<double,std::milli>(t_garble_construct_end - t_garble_start).count();
  double garble_send_ms = std::chrono::duration<double,std::milli>(t_garble_send_end - t_garble_construct_end).count();
  uint64_t payload_bits = 8ull * (ctx.io->counter - net_before);

  std::cout << "[G-RandMerge] n="<<n<<" m="<<m<<" w="<<w
            << " delta="<<delta
            << " payload_bits="<<payload_bits
            << " inputs_ms="<<inputs_ms
            << " garble_construct_ms="<<garble_construct_ms
            << " garble_send_ms="<<garble_send_ms
            << "\n";
}

void run_evaluator_randomized(const Args& A) {
  EvaluatorCtx ctx(A.ip.c_str(), A.port);
  ctx.sync();

  const int n = A.n, m = A.m, w = A.w;
  const int N = n + m;
  const int t_sym = std::min(n, m);
  const int delta = compute_delta_lambda(t_sym, 128);

  auto t_inputs_start = std::chrono::steady_clock::now();

  std::random_device rd; std::mt19937_64 gen(rd());
  uint64_t mask = (w==64 ? std::numeric_limits<uint64_t>::max() : ((1ULL<<w)-1ULL));
  std::vector<uint64_t> x0_ids(n), x1_ids(m);
  for (int i=0;i<n;++i) x0_ids[i] = (gen() & mask);
  for (int j=0;j<m;++j) x1_ids[j] = (gen() & mask);

  std::vector<bool> s(N,false);
  for (int t=0;t<m;++t) s[t] = true;
  std::shuffle(s.begin(), s.end(), std::mt19937{std::random_device{}()});

  std::vector<EBit> Se; 
  ot_recv_bit_labels(ctx, s, Se); 
  ctx.sync();
  std::vector<bool> x_choices; x_choices.reserve((size_t)w*(n+m));
  for (int i=0;i<n;++i) {
    for (int b=0;b<w;++b) {
      x_choices.push_back(((x0_ids[i]>>b) & 1ULL) != 0ULL);
    }
  }
  for (int j=0;j<m;++j) {
    for (int b=0;b<w;++b) {
      x_choices.push_back(((x1_ids[j]>>b) & 1ULL) != 0ULL);
    }
  }
  std::vector<EBit> Xbits; 
  ot_recv_bit_labels(ctx, x_choices, Xbits); ctx.sync();

  std::vector<EWord> X0e(n), X1e(m); size_t idx=0;
  for (int i=0;i<n;++i){ 
    X0e[i].b.resize(w); 
    for (int b=0;b<w;++b) {
      X0e[i].b[b] = Xbits[idx++]; 
    }
  }
  for (int j=0;j<m;++j){ 
    X1e[j].b.resize(w); 
    for (int b=0;b<w;++b) {
      X1e[j].b[b] = Xbits[idx++]; 
    }
  }
  EBit E0b, E1b; 
  recv_const_keys(E0b, E1b, ctx);
  ctx.sync();
  EWord E0w;     
  const_word(ctx, w, 0, E0w);

  GarbledPayload P = recv_payload(ctx, n, m, w); ctx.sync();
  auto t_inputs_end = std::chrono::steady_clock::now();

  std::vector<int> row_pos(n,-1), col_pos(m,-1);
  int cnt0=0, cnt1=0;
  for (int k=0;k<N;++k) {
    if (!s[k]) { 
      row_pos[cnt0] = cnt1; ++cnt0; 
    } else { 
      col_pos[cnt1] = cnt0; ++cnt1; 
    }
  }

  auto t_eval_start = std::chrono::steady_clock::now();


  std::vector<std::vector<EBit>> q (n+1, std::vector<EBit>(m+1));
  std::vector<std::vector<EBit>> r1(n+1, std::vector<EBit>(m));
  std::vector<std::vector<EBit>> r0(n,   std::vector<EBit>(m+1));
  std::vector<std::vector<EWord>> R0(n,   std::vector<EWord>(m+1));
  std::vector<std::vector<EWord>> R1(n+1, std::vector<EWord>(m));

  for (int i = 0; i < n; ++i) {
    for (int j = 0; j <= m; ++j) {
      const_word(ctx, w, 0, R0[i][j]);
    }
  }
  for (int i = 0; i <= n; ++i) {
    for (int j = 0; j <  m; ++j) {
      const_word(ctx, w, 0, R1[i][j]);
    }
  }

  q[0][0] = E1b;

  for (int k = 0; k <= N-1; ++k) {
    for (int i = 0; i <= n; ++i) {
      int j = k - i; 
      if (j < 0 || j > m) {
        continue;
      }
      if (!in_band(i,j,delta)) {
      }
      if (j < m) {
        if (i == n) {
          switch_zero(ctx, E0b, q[i][j], r1[i][j]);
        } else {
          switch_zero(ctx, q[i][j], E0b, r1[i][j]);
        }
        switch_zero_word(ctx, r1[i][j], E0w, R1[i][j]);
      }
      if (i < n) {
        if (j == m) {
          r0[i][j] = q[i][j];
        } else { 
          EBit t; 
          xorb(q[i][j], r1[i][j], t); 
          r0[i][j] = t; 
        }
        switch_zero_word(ctx, r0[i][j], E0w, R0[i][j]);
      }
    }

    bool have=false; EBit agg; int ip=-1, jp=-1;
    for (int i = 0; i <= n; ++i) {
      int j = k - i; if (j < 0 || j >= m) {
        continue;
      }
      if (!in_band(i,j,delta)) {
        continue;
      }
      if (!have) { 
        agg = r1[i][j]; 
        ip=i; jp=j; 
        have=true; 
      }
      else { 
        EBit t; 
        xorb(agg, r1[i][j], t); 
        agg=t; 
      }
    }
    if (have) {
      emp::block agg_in_s = agg.a ^ P.diag_masks[k];
      emp::block corr = Se[k].a ^ agg_in_s;
      r1[ip][jp].a ^= corr; 
    }

    int kk = k + 1;
    for (int i = 0; i <= n; ++i) {
      int j = kk - i; if (j < 0 || j > m) continue;
      if (!in_band(i,j,delta)) {
        continue;
      }
      if (i == 0 && j == 0) {
        continue;
      }

      const bool up_ok = up_in_band(i,j,delta);
      const bool left_ok = left_in_band(i,j,delta);

      if (i == 0) {
        q[i][j] = r1[i][j-1];
      }
      else if (j == 0) {
        q[i][j] = r0[i-1][j];
      }
      else if (up_ok && left_ok) { 
        EBit t; 
        xorb(r0[i-1][j], r1[i][j-1], t); 
        q[i][j] = t; 
      }
      else if (up_ok) {
        q[i][j] = r0[i-1][j];
      }
      else if (left_ok) {
        q[i][j] = r1[i][j-1];
      }
    }
  }

  for (int i = 0; i < n; ++i) {
    EWord row = R0[i][0];
    for (int j = 1; j <= m; ++j) { EWord t; xorw(row, R0[i][j], t); row = std::move(t); }
    int jp = row_pos[i];
    for (int b = 0; b < w; ++b) {
      emp::block row_in_x0 = row.b[b].a ^ P.row_masks[i][b];
      emp::block corr = X0e[i].b[b].a ^ row_in_x0;
      R0[i][jp].b[b].a ^= corr;
    }
  }
  for (int j = 0; j < m; ++j) {
    EWord col = R1[0][j];
    for (int i = 1; i <= n; ++i) { EWord t; xorw(col, R1[i][j], t); col = std::move(t); }
    int ip = col_pos[j];
    for (int b = 0; b < w; ++b) {
      emp::block col_in_x1 = col.b[b].a ^ P.col_masks[j][b];
      emp::block corr = X1e[j].b[b].a ^ col_in_x1;
      R1[ip][j].b[b].a ^= corr;
    }
  }

  auto t_eval_end = std::chrono::steady_clock::now();
  double inputs_ms = std::chrono::duration<double,std::milli>(t_inputs_end - t_inputs_start).count();
  double evaluate_ms = std::chrono::duration<double,std::milli>(t_eval_end   - t_eval_start).count();
  std::cout << "[E-RandMerge] n="<<n<<" m="<<m<<" w="<<w
            << " delta="<<delta
            << " inputs_ms="<<inputs_ms
            << " evaluate_ms="<<evaluate_ms
            << "\n";
}


}