#include "switch_stack.hpp"

#include <algorithm>
#include <cstdint>
#include <numeric>
#include <vector>

namespace PicoGRAM {

namespace {

constexpr uint64_t NONCE_RE = 0x5353575f52450000ULL;
constexpr uint64_t NONCE_WRITE0 = 0x5353575f57300000ULL;
constexpr uint64_t NONCE_WRITE1 = 0x5353575f57310000ULL; 

inline uint64_t gid_state(uint64_t diag_t, uint64_t row_i, uint64_t n) {
  return diag_t * (n + 1) + row_i;
}

inline uint64_t gid_word_base(uint64_t diag_t, uint64_t row_i, uint64_t n,
                              uint64_t W) {
  return gid_state(diag_t, row_i, n) * W;
}

inline void flatten_labels(const std::vector<Word>& words,
                           std::vector<Label>& out) {
  uint64_t total = 0;
  for (const Word& w : words) total += w.width();
  out.clear();
  out.reserve(total);
  for (const Word& w : words) {
    for (uint i = 0; i < w.width(); ++i) {
      out.push_back(w[i].get_label());
    }
  }
  Assert_eq(out.size(), total);
}

inline void flatten_k0_labels(const std::vector<Word>& words,
                              std::vector<Label>& out) {
  
  flatten_labels(words, out);
}

inline void assign_labels(std::vector<Word>& words,
                          const std::vector<Label>& labels) {
  uint64_t idx = 0;
  for (Word& w : words) {
    for (uint i = 0; i < w.width(); ++i) {
      Assert_less(idx, labels.size());
      w[i].get_label() = labels[idx++];
    }
  }
  Assert_eq(idx, labels.size());
}

inline Bit zero_bit(Gadget* owner) {
  return Bit(owner, key_manager.get_rand_encoding(), 0, false, false);
}

inline Bit one_bit(Gadget* owner) {
  return Bit(owner, key_manager.get_neg_rand_encoding(), 1, false, false);
}

inline Label control_zero_label(const Bit& control_e) {
  
  
  Label k0 = control_e.get_label();
  if (control_e.get_value()) {
    k0 ^= key_manager.get_Delta();
  }
  return k0;
}

}  

static inline Label switch_hash(const Bit& control, uint64_t nonce_base,
                                uint64_t gate_id) {
  return Hash(control.get_label(), nonce_base, gate_id);
}

Bit switch_zero_bit(const Bit& control, const Bit& input, uint64_t nonce_base,
                    uint64_t gate_id) {
  Bit out = input;
  out.get_label() ^= switch_hash(control, nonce_base, gate_id);
  out.set_pub_g(false);
  out.set_pub_e(false);
  return out;
}

Word switch_zero_word(const Bit& control, const Word& input, uint64_t nonce_base,
                      uint64_t gate_id) {
  Word out = input;
  for (uint64_t b = 0; b < out.width(); ++b) {
    out[b].get_label() ^= switch_hash(control, nonce_base, gate_id + b);
    out[b].set_pub_g(false);
    out[b].set_pub_e(false);
  }
  return out;
}

void switch_stack_init_state(SwitchStackState& state, Gadget* caller,
                             Gadget* callee, uint64_t T, uint64_t W) {
  Assert(T);
  Assert(callee);
  state.T = T;
  state.n = callee->get_T();
  Assert(state.n <= T);
  state.m = T;
  state.W = W;

  state.time = 0;
  state.real_count = 0;
  state.caller = caller;
  state.callee = callee;

  state.q_diag.clear();
  state.q_diag.emplace_back(one_bit(caller));  

  state.up_row_de.assign(state.m + 1, zero_bit(caller));
  state.curr_row_de.assign(state.m + 1, zero_bit(caller));

  state.row_acc.assign(W, Label());
  state.step_mask.assign(W, Label());
  state.step_time = static_cast<uint64_t>(-1);
}

void switch_stack_garble(GCPtr& gc, const std::vector<Bit>& controls,
                         std::vector<std::vector<Word>>& port_words,
                         Gadget* caller, Gadget* callee) {
  const uint64_t T = controls.size();
  Assert(T);
  Assert(callee);
  const uint64_t n = callee->get_T();
  Assert(n <= T);
  Assert_eq(port_words.size(), T);
  Assert(!port_words.empty());

  const uint64_t W = std::accumulate(
      port_words[0].begin(), port_words[0].end(), 0ULL,
      [](uint64_t sum, const Word& w) { return sum + w.width(); });
  Assert(W);
  for (uint64_t t = 1; t < T; ++t) {
    const uint64_t wt = std::accumulate(
        port_words[t].begin(), port_words[t].end(), 0ULL,
        [](uint64_t sum, const Word& w) { return sum + w.width(); });
    Assert_eq(wt, W);
  }

  const Bit z = zero_bit(caller);

  
  std::vector<Label> diag_control_masks(T);
  {
    std::vector<Bit> q_diag;
    q_diag.emplace_back(zero_bit(caller));  
    for (uint64_t t = 0; t < T; ++t) {
      const uint64_t i_max = std::min<uint64_t>(n, t);
      const uint64_t diag_len = i_max + 1;
      Assert_eq(q_diag.size(), diag_len);

      Label agg;
      std::vector<Bit> re_bits(diag_len, z);
      for (uint64_t i = 0; i <= i_max; ++i) {
        const Bit& q = q_diag[i];
        Bit re = (i == n) ? switch_zero_bit(z, q, NONCE_RE, gid_state(t, i, n))
                          : switch_zero_bit(q, z, NONCE_RE, gid_state(t, i, n));
        re_bits[i] = re;
        agg = (i == 0) ? re.get_label() : (agg ^ re.get_label());
      }
      const Label s_k0 = controls[t].get_label();
      diag_control_masks[t] = agg ^ s_k0;

      
      const uint64_t next_i_max = std::min<uint64_t>(n, t + 1);
      const uint64_t next_len = next_i_max + 1;
      std::vector<Bit> next_diag(next_len, z);

      for (uint64_t i = 0; i <= i_max; ++i) {
        const Bit& q = q_diag[i];
        const Bit& re = re_bits[i];
        next_diag[i] = next_diag[i] ^ re;
        if (i < n) {
          const Bit de = q ^ re;
          next_diag[i + 1] = next_diag[i + 1] ^ de;
        }
      }
      q_diag.swap(next_diag);
    }
  }

  for (uint64_t t = 0; t < T; ++t) {
    gc.write_label(diag_control_masks[t]);
  }

  std::vector<std::vector<Label>> x0_bits(n, std::vector<Label>(W, Label()));
  {
    std::vector<Bit> q_diag;
    q_diag.emplace_back(zero_bit(caller));  

    for (uint64_t t = 0; t < T; ++t) {
      const uint64_t i_max = std::min<uint64_t>(n, t);
      const uint64_t diag_len = i_max + 1;
      Assert_eq(q_diag.size(), diag_len);

      const uint64_t next_i_max = std::min<uint64_t>(n, t + 1);
      const uint64_t next_len = next_i_max + 1;
      std::vector<Bit> next_diag(next_len, z);

      std::vector<Label> y_bits;
      flatten_k0_labels(port_words[t], y_bits);
      Assert_eq(y_bits.size(), W);

      std::vector<Label> diag_sum0(W, Label());
      for (uint64_t i = 0; i <= i_max; ++i) {
        const Bit& q = q_diag[i];
        const uint64_t base = gid_word_base(t, i, n, W);

        
        Bit re = (i == n) ? switch_zero_bit(z, q, NONCE_RE, gid_state(t, i, n)) 
                          : switch_zero_bit(q, z, NONCE_RE, gid_state(t, i, n));
        for (uint64_t b = 0; b < W; ++b) {
          diag_sum0[b] ^= Hash(re.get_label(), NONCE_WRITE1, base + b);
        }

        if (i < n) {
          const Bit de = q ^ re;
          for (uint64_t b = 0; b < W; ++b) {
            const Label w0 = Hash(de.get_label(), NONCE_WRITE0, base + b);
            diag_sum0[b] ^= w0;
            x0_bits[i][b] ^= w0;
          }
          next_diag[i + 1] = next_diag[i + 1] ^ de;
        }

        next_diag[i] = next_diag[i] ^ re;
      }

      for (uint64_t b = 0; b < W; ++b) {
        gc.write_label(diag_sum0[b] ^ y_bits[b]);
      }

      q_diag.swap(next_diag);
    }
  }

  std::vector<std::vector<Word>> compact(n);
  compact.reserve(n);
  for (uint64_t i = 0; i < n; ++i) {
    compact[i].reserve(port_words[0].size());
    for (size_t word_idx = 0; word_idx < port_words[0].size(); ++word_idx) {
      const Word& tmpl = port_words[0][word_idx];
      Word w = tmpl;           
      w.set_owner(callee);     
      w.set_pub_g(false);      
      compact[i].emplace_back(std::move(w));
    }
    assign_labels(compact[i], x0_bits[i]);
  }

  port_words.swap(compact);
}

void switch_stack_step(GCPtr& gc, SwitchStackState& state,
                       const Bit& control_e) {
  Assert(state.caller && state.callee);
  Assert(state.T);
  Assert(state.W);
  Assert(state.n <= state.T);

  const uint64_t t = state.time;
  const uint64_t n = state.n;
  const uint64_t m = state.m;
  const uint64_t W = state.W;
  Assert_less(t, state.T);

  if (state.q_diag.empty()) {
    state.q_diag.emplace_back(one_bit(state.caller));
  }
  if (state.up_row_de.empty()) {
    state.up_row_de.assign(m + 1, zero_bit(state.caller));
  }
  if (state.curr_row_de.empty()) {
    state.curr_row_de.assign(m + 1, zero_bit(state.caller));
  }
  if (state.row_acc.empty()) {
    state.row_acc.assign(W, Label());
  }

  const Bit z = zero_bit(state.caller);

  const uint64_t active_row = state.real_count;
  const uint64_t active_col = t - active_row;
  Assert(active_row <= n);
  Assert(active_row <= t);
  Assert(active_col <= t);
  Assert(active_col <= m);

  const uint64_t i_max = std::min<uint64_t>(n, t);
  const uint64_t diag_len = i_max + 1;
  Assert_eq(state.q_diag.size(), diag_len);
  Assert(active_row <= i_max);

  
  std::vector<Bit> re_bits(diag_len, z);
  Label agg;
  for (uint64_t i = 0; i <= i_max; ++i) {
    const Bit& q = state.q_diag[i];
    Bit re = (i == n) ? switch_zero_bit(z, q, NONCE_RE, gid_state(t, i, n))
                      : switch_zero_bit(q, z, NONCE_RE, gid_state(t, i, n));
    re_bits[i] = re;
    agg = (i == 0) ? re.get_label() : (agg ^ re.get_label());
  }

  
  Label diag_mask;
  gc.peak_default(diag_mask, t);
  const Label agg_in_s = agg ^ diag_mask;
  const Label corr = control_e.get_label() ^ agg_in_s;
  re_bits[active_row].get_label() ^= corr;

  
  const uint64_t next_i_max = std::min<uint64_t>(n, t + 1);
  const uint64_t next_len = next_i_max + 1;
  std::vector<Bit> next_diag(next_len, z);

  
  std::vector<Bit> de_bits(diag_len, z);

  for (uint64_t i = 0; i <= i_max; ++i) {
    const Bit& q = state.q_diag[i];
    const Bit& re = re_bits[i];
    next_diag[i] = next_diag[i] ^ re;
    if (i < n) {
      const Bit de = q ^ re;
      de_bits[i] = de;
      next_diag[i + 1] = next_diag[i + 1] ^ de;
    }
  }

  
  if (active_row < n) {
    const Bit& q_active = state.q_diag[active_row];
    const Bit re_active = re_bits[active_row];
    const Bit de_active = q_active ^ re_active;
    state.curr_row_de[active_col] = de_active;

    if (control_e.get_value()) {
      
      const uint64_t base = gid_word_base(t, active_row, n, W);
      for (uint64_t b = 0; b < W; ++b) {
        state.row_acc[b] ^= Hash(de_active.get_label(), NONCE_WRITE0, base + b);
      }
    } else {
      Bit R = re_active;  
      const uint64_t col_max = state.T - 1 - active_row;
      for (uint64_t col = active_col + 1; col <= col_max; ++col) {
        const uint64_t diag_t = active_row + col;
        const Bit q_tail =
            (active_row == 0) ? R : (state.up_row_de[col] ^ R);
        const Bit re_tail =
            switch_zero_bit(q_tail, z, NONCE_RE, gid_state(diag_t, active_row, n));
        const Bit de_tail = q_tail ^ re_tail;
        state.curr_row_de[col] = de_tail;
        const uint64_t base = gid_word_base(diag_t, active_row, n, W);
        for (uint64_t b = 0; b < W; ++b) {
          state.row_acc[b] ^=
              Hash(de_tail.get_label(), NONCE_WRITE0, base + b);
        }

        R = re_tail;
      }
      
      std::vector<Label> diag_zero(W, Label());
      for (uint64_t i = 0; i <= i_max; ++i) {
        const uint64_t base = gid_word_base(t, i, n, W);
        const Bit& re = re_bits[i];
        for (uint64_t b = 0; b < W; ++b) {
          diag_zero[b] ^= Hash(re.get_label(), NONCE_WRITE1, base + b);
        }
        if (i < n) {
          if (i == active_row) {
            continue;  
          }
          const Bit& de = de_bits[i];
          for (uint64_t b = 0; b < W; ++b) {
            diag_zero[b] ^= Hash(de.get_label(), NONCE_WRITE0, base + b);
          }
        }
      }
      std::vector<Label> dm(W);
      gc.peak_default(dm, state.T + t * W);
      state.step_mask.resize(W);
      for (uint64_t b = 0; b < W; ++b) {
        state.step_mask[b] = dm[b] ^ diag_zero[b] ^ state.row_acc[b];
      }
      state.step_time = t;
      state.up_row_de = state.curr_row_de;
      state.curr_row_de.assign(m + 1, z);
      state.row_acc.assign(W, Label());
      ++state.real_count;
      if (state.real_count < n && active_col) {
        const uint64_t row = state.real_count;
        Bit re_prev = z;
        for (uint64_t col = 0; col < active_col; ++col) {
          const uint64_t diag_t = row + col;
          const Bit q = (col == 0) ? state.up_row_de[col] : (state.up_row_de[col] ^ re_prev);
          const Bit re = switch_zero_bit(q, z, NONCE_RE, gid_state(diag_t, row, n));
          const Bit de = q ^ re;
          state.curr_row_de[col] = de;

          const uint64_t base = gid_word_base(diag_t, row, n, W);
          for (uint64_t b = 0; b < W; ++b) {
            state.row_acc[b] ^= Hash(de.get_label(), NONCE_WRITE0, base + b);
          }
          re_prev = re;
        }
      }
    }
  } else {
    Assert(control_e.get_value());
  }

  state.q_diag.swap(next_diag);
  ++state.time;
}

std::vector<Word> switch_stack_translate(
    GCPtr&, const std::vector<Word>& chunk, const Bit& control_e,
    uint64_t caller_time, uint64_t word_width_sum, SwitchStackState& state,
    uint64_t& curr_bit_offset) {
  Assert(state.caller && state.callee);
  Assert_eq(state.W, word_width_sum);
  Assert_eq(state.step_time, caller_time);
  Assert(!control_e.get_value()); 

  if (chunk.empty()) {
    return {};
  }

  const bool caller_to_callee = chunk[0].get_owner() == state.caller;
  std::vector<Word> output = chunk;

  uint64_t chunk_bits = 0;
  for (const Word& w : output) chunk_bits += w.width();
  Assert(chunk_bits);
  Assert(curr_bit_offset + chunk_bits <= word_width_sum);

  const Label ctl0 = control_zero_label(control_e);

  std::vector<Label> bits;
  flatten_labels(output, bits);
  Assert_eq(bits.size(), chunk_bits);

  for (uint64_t idx = 0; idx < chunk_bits; ++idx) {
    const uint64_t bit_off = curr_bit_offset + idx;
    const Label buf = Hash(ctl0, caller_time, bit_off);
    if (caller_to_callee) {
      bits[idx] ^= buf;
      bits[idx] ^= state.step_mask[bit_off];
    } else {
      bits[idx] ^= state.step_mask[bit_off];
      bits[idx] ^= buf;
    }
  }

  assign_labels(output, bits);

  for (Word& w : output) {
    w.set_pub_g(false);
    if (caller_to_callee) {
      w.set_owner(state.callee);
    } else {
      w.set_owner(state.caller);
      w.set_pub_e(false);
    }
  }

  curr_bit_offset = (curr_bit_offset + chunk_bits) % word_width_sum;
  return output;
}

}
