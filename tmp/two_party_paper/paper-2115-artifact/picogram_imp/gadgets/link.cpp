#include "link.hpp"

namespace PicoGRAM {
SIMDLink::SIMDLink(Gadget* callee) : BaseConditionalLink(callee, SIMD_COND) {}

bool SIMDLink::update_link(const Bit& control, const BigInt& caller_label) {
  Assert(control.get_owner() == caller);
  if (last_caller_time == caller->get_time()) {
    return is_active;
  }
  last_caller_time = caller->get_time();
  inc_time();
#ifdef MEASURE_STACK_COST
  measure_stack_flag = true;
#endif

  Bit control_e = control.reveal();
  Assert_eq(control.get_mode(), mode);
  if (mode == GARBLE) {
    // only record the label
    Assert(caller_label.is_set());
    simd_labels.push_back(caller_label);
    controls.push_back(control_e);
    prefix_sum.emplace_back(prefix_sum.back() + control_e);
  } else if (mode == EVAL) {
    // update the relative label
    is_active = !control_e.get_value();
    if (is_active) {
      callee->inc_time();
      uint64_t tau = get_time();
      relative_label = HashZ(control_e.get_label(), tau);
      inv_relative_label.unset();
      // route through the compaction network
      for (uint i = 0;; ++i) {
        const Word& curr_sum = prefix_sum[tau];
        if (i < curr_sum.width()) {
          const Bit& curr_bit = curr_sum[i];
          Assert(curr_bit.is_pub_e());
          uint64_t index = index_calculator(i, tau);
          if (curr_bit.get_value()) {
            // SIMD Buffer
            // TODO check nonce uniqueness
            // relative_label *= HashZ((!curr_bit).get_label(), 2 * index);

            BigInt join_material;
            uint8_t join_material_bytes[BigInt::byte_length];
            gc.peak_data(join_material_bytes, BigInt::byte_length * index,
                         BigInt::byte_length);
            join_material.dec((!curr_bit).get_label(), join_material_bytes,
                              2 * index);
            // SIMD JOIN
            relative_label *= join_material;
            tau -= (1UL << i);
          } else {
            // only SIMD Buffer
            relative_label *= HashZ(curr_bit.get_label(), 2 * index + 1);
          }
        } else {
          break;
        }
      }
    }
    prefix_sum.emplace_back(prefix_sum.back() + control_e);
  } else if (mode == DEBUG) {
    is_active = !control_e.get_value();
    if (is_active) {
      callee->inc_time();
    }
    prefix_sum.emplace_back(prefix_sum.back() + control_e);
  } else if (mode == MEASURE) {
    prefix_sum[0] = prefix_sum[0] + control_e;
  }
#ifdef MEASURE_STACK_COST
  measure_stack_flag = false;
#endif

  return !control_e.get_value();
}

std::vector<SIMDWord> SIMDLink::translate(const std::vector<SIMDWord>& inputs) {
  for (const SIMDWord& input : inputs) {
    Assert(input.get_mode() == EVAL || input.get_mode() == DEBUG);
    Assert(input.get_owner() == caller || input.get_owner() == callee);
  }
  std::vector<SIMDWord> outputs = inputs;
  if (!inputs.empty()) {
    bool is_caller_to_callee = inputs[0].get_owner() == caller;
    for (SIMDWord& output : outputs) {
      Assert_eq(output.get_owner() == caller, is_caller_to_callee);
      output.set_owner(is_caller_to_callee ? callee : caller);
      if (relative_label.is_set()) {
        if (is_caller_to_callee) {
          for (SIMDWord::SIMDEncoding& encoding : output.encodings) {
            encoding.pow(relative_label);
          }
        } else {
          if (!inv_relative_label.is_set()) {
            inv_relative_label = relative_label.inv().to_montgomery();
          }
          for (SIMDWord::SIMDEncoding& encoding : output.encodings) {
            encoding.pow(inv_relative_label);
          }
          // the garbler cannot infer the pub_es of the callee's output,
          // assuming all return values are unknown to the evaluator
          std::fill(output.pub_es.begin(), output.pub_es.end(), false);
        }
      }
    }
  }
  return outputs;
}

GCPtr SIMDLink::garble(const GCPtr& gc_begin) {
  // std::cout << "garbling SIMDLink for " << T << " timesteps" << std::endl;
  const uint64_t inv_batch_size = std::min(32ul, T);
  std::vector<BigInt*> big_int_to_inv_ptrs(inv_batch_size);
  BaseGadget::garble(gc_begin);
  uint depth = log2ceil(T);
  Assert_eq(get_time() + 1, T);
  if (mode == GARBLE) {
    Assert_eq(controls.size(), T);
    Assert_eq(simd_labels.size(), T);
  }
  init_gc_ptr(gc_begin);
  if (mode == MEASURE) {
#ifdef MEASURE_STACK_COST
    measure_stack_flag = true;
#endif
    gc.skip_big_int(T * depth - (1UL << depth) + 1);
#ifdef MEASURE_STACK_COST
    measure_stack_flag = false;
#endif
    return gc;
  }
  // the language of wires joined with another wire whose language
  // hasn't been computed
  std::vector<std::queue<BigInt>> pending_joins;
  pending_joins.resize(depth);
  uint64_t index = -1;
  uint64_t index2 = -1;
  std::vector<std::vector<BigInt>> hashz_stack(inv_batch_size,
                                               std::vector<BigInt>(depth));
  uint64_t inv_batch_offset = 0;

  uint64_t batch_begin_t = 0;
  for (uint64_t t = 0; t < T; ++t) {
    simd_labels[t] *= HashZ(controls[t].get_label(), t);
    for (uint i = 0; i < depth; ++i) {
      if (i < prefix_sum[t].width()) {
        const BigInt& hashz =
            HashZ(prefix_sum[t][i].get_label(), 2 * index + 1);

        // Notice that the simd labels we use for computing the join
        // material forms a matrixes like this

        // h00            h01            h02          h03
        // h00*h10        h01*h11        h02*h12      h03*h13
        // h00*h10*h20    h01*h11*h21    h02*h12*h22  h03*h13*h23

        // The join materials can be computed once we know the inverse of
        // every entry of the matrix.
        // To compute the inverse of every entry in this matrix, we only
        // need to compute the inverse of the last row. The rest can be computed
        // with multiplication on the last row.

        // we could further optimize this by doing batch inversion
        // (by computing the prefix and suffix products of the last row)
        // however, this requires more memory to store the stacks and makes the
        // code more complex
        if (i == prefix_sum[t].width() - 1) {
          hashz_stack[inv_batch_offset][i] = simd_labels[t];
        } else {
          hashz_stack[inv_batch_offset][i] = hashz;
        }
        simd_labels[t] *= hashz;
        ++index;
      }
      if (t + (1UL << i) < T) {
        pending_joins[i].push(simd_labels[t]);
      }
    }
    ++inv_batch_offset;
    uint64_t actual_inv_batch_size =
        std::min(inv_batch_size, T - batch_begin_t);
    if (inv_batch_offset == actual_inv_batch_size) {
      // todo perform the inversions in batch
      for (uint64_t offset = 0; offset < actual_inv_batch_size; ++offset) {
        uint64_t tt = batch_begin_t + offset;
        BigInt& big_int_to_inv =
            hashz_stack[offset][prefix_sum[tt].width() - 1];
        big_int_to_inv_ptrs[offset] = &big_int_to_inv;
      }
      BigInt::inv_batch(big_int_to_inv_ptrs.data(), actual_inv_batch_size);
      for (uint64_t offset = 0; offset < actual_inv_batch_size; ++offset) {
        uint64_t tt = batch_begin_t + offset;
        Assert_less(prefix_sum[tt].width() - 1, depth);
        for (int i = prefix_sum[tt].width() - 2; i >= 0; --i) {
          hashz_stack[offset][i] *= hashz_stack[offset][i + 1];
        }
        for (uint i = 0; i < depth; ++i) {
          if (i < prefix_sum[tt].width()) {
            if (tt >= (1UL << i)) {
              // we can compute a pending join
              Bit neg_s = !prefix_sum[tt][i];
              // const BigInt& h_neg = HashZ(neg_s.get_label(), 2 * index);
              Assert(!pending_joins[i].empty());
              BigInt& pending_join = pending_joins[i].front();
              pending_join *= hashz_stack[offset][i];
              // }

              uint8_t encrypted_join_material[BigInt::byte_length];
              pending_join.enc(neg_s.get_label(), encrypted_join_material,
                               2 * index2);
              pending_joins[i].pop();
              // whenever the join material is computed, write to the GC
              // sequentially
              gc.write_data(encrypted_join_material, BigInt::byte_length);
            }
            ++index2;
          }
        }
      }
      Assert_eq(index, index2);
      inv_batch_offset = 0;
      batch_begin_t = t + 1;
    }
  }

  // free the memory
  clear_and_release(pending_joins);
  clear_and_release(prefix_sum);
  clear_and_release(controls);
  return gc;
}

Link::Link(Gadget* callee) : BaseConditionalLink(callee, COND) {
  switch_state.caller = caller;
  switch_state.callee = callee;
  switch_state.T = T;
  switch_state.n = callee->get_T();
  Assert(switch_state.n <= T);
  // `n` is an upper bound on the number of real (down) steps; we must allow
  // fewer real calls in practice, so size the column dimension to the full
  // caller timeline.
  switch_state.m = T;
  switch_state.W = 0;
  switch_state.time = 0;
  switch_state.real_count = 0;
}

bool Link::update_link(const Bit& control) {
  Assert(control.get_owner() == caller);
  if (last_caller_time == caller->get_time()) {
    return is_active;
  }
  last_caller_time = caller->get_time();
  inc_time();
#ifdef MEASURE_STACK_COST
  measure_stack_flag = true;
#endif
  // get_caller()->dbg_check_gc_sync();
  Bit control_e = control.reveal();
  curr_bit_offset = 0;
  Assert_eq(control.get_mode(), mode);
  if (mode == GARBLE) {
    // just record the input
    controls.push_back(control_e);
    port_words.emplace_back();
    prefix_sum.emplace_back(prefix_sum.back() + control_e);
  } else if (mode == EVAL || mode == DEBUG) {
    controls.resize(1);
    controls[0] = control_e;
    is_active = !control_e.get_value();
    curr_bit_offset = 0;
    if (is_active) {
      callee->inc_time();
      // uint64_t tau = get_time();
    }
    prefix_sum.emplace_back(prefix_sum.back() + control_e);
    if (mode == EVAL) {
      // The switch-stack state machine needs random access into the GC payload;
      // read the record width once so gc.offset points to the payload base.
      if (word_width_sum == (uint64_t)-1) {
        gc.read_default(word_width_sum);
      }
      if (!switch_state.W) {
        switch_stack_init_state(switch_state, caller, callee, T, word_width_sum);
      } else {
        Assert_eq(switch_state.W, word_width_sum);
        Assert_eq(switch_state.time, get_time());
      }
      switch_stack_step(gc, switch_state, control_e);
    }
  } else if (mode == MEASURE) {
    if (port_words.empty()) {
      port_words.emplace_back();
    }
    prefix_sum[0] = prefix_sum[0] + control_e;
  }
#ifdef MEASURE_STACK_COST
  measure_stack_flag = false;
#endif
  return !control_e.get_value();
}

void Link::add_caller_words(const std::vector<Word>& parent_words) {
  Assert(!port_words.empty());
  std::vector<Word>& latest_words = port_words.back();
  if (get_mode() == GARBLE) {
    latest_words.insert(latest_words.end(), parent_words.begin(),
                        parent_words.end());
  } else {
    Assert(get_mode() == MEASURE);
    if (last_caller_time == 0) {
      // only insert once
      latest_words.insert(latest_words.end(), parent_words.begin(),
                          parent_words.end());
    }
  }
}

std::vector<Word> Link::retrieve_callee_words(uint64_t num) {
  Assert(garbled);
  Assert(get_mode() == GARBLE || get_mode() == MEASURE);

  auto word_begin =
      port_words[curr_retrieved_t].begin() + curr_retrieved_word_idx;
  Assert_less(curr_retrieved_t, port_words.size());
  Assert(curr_retrieved_word_idx + num <= port_words[curr_retrieved_t].size());
  const std::vector<Word>& output =
      std::vector<Word>(word_begin, word_begin + num);
  curr_retrieved_word_idx += num;
  if (curr_retrieved_word_idx == port_words[curr_retrieved_t].size()) {
    if (get_mode() == GARBLE) {
      ++curr_retrieved_t;
    }
    curr_retrieved_word_idx = 0;
  }
  return output;
}

void Link::clear_callee_words() { clear_and_release(port_words); }

std::vector<Word> Link::translate(const std::vector<Word>& input) {
  Assert(is_active);
  if (input.empty()) {
    return {};
  }
  Assert(get_mode() == EVAL || get_mode() == DEBUG);
  Gadget* input_owner = input[0].get_owner();
  Assert(input_owner == caller || input_owner == callee);
  bool is_caller_to_callee = input_owner == caller;
  std::vector<Word> output = input;
  for (Word& word : output) {
    word.set_pub_g(false);
    if (!is_caller_to_callee) {
      word.set_pub_e(false);
    }
  }
  if (mode == EVAL) {
    if (word_width_sum == (uint64_t)-1) {
      gc.read_default(word_width_sum);
    }
    if (!switch_state.W) {
      switch_stack_init_state(switch_state, caller, callee, T, word_width_sum);
    }
    const Bit& control_e = controls[0];
    output = switch_stack_translate(gc, output, control_e, get_time(),
                                    word_width_sum, switch_state,
                                    curr_bit_offset);
  } else {
    for (Word& word : output) {
      word.set_owner(is_caller_to_callee ? callee : caller);
    }
  }
  return output;
}
#ifdef MEASURE_TSC_STACK
uint64_t tsc_stack_cost_helper(int64_t m, uint w, uint64_t T) {
  if (m <= 0) {
    Assert(T <= 0);
    return 0;
  }
  return (m * 3 + m / 2 * 4 + m * w * 4) * LAMBDA_BYTES +
         tsc_stack_cost_helper(m / 2, w * 2, (T - 3) / 2);
}

uint64_t tsc_stack_cost(uint64_t T, uint w) {
  return tsc_stack_cost_helper(T, w, T / 2);
}
#endif

GCPtr Link::garble(const GCPtr& gc_begin) {
  BaseGadget::garble(gc_begin);
  Assert(T);
  Assert_eq(get_time() + 1, T);
  if (mode == GARBLE) {
    Assert_eq(controls.size(), T);
    Assert_eq(port_words.size(), T);
  }
  init_gc_ptr(gc_begin);
  word_width_sum = std::accumulate(
      port_words[0].begin(), port_words[0].end(), 0,
      [](uint64_t sum, const Word& word) { return sum + word.width(); });
  if (mode == MEASURE) {
#ifdef MEASURE_STACK_COST
    measure_stack_flag = true;
#endif
    gc.skip_default<uint64_t>();
#ifdef MEASURE_TSC_STACK
    global_tsc_stack_cost += tsc_stack_cost(T, word_width_sum);
#endif
    gc.skip_label(T + T * word_width_sum);

#ifdef MEASURE_STACK_COST
    measure_stack_flag = false;
#endif
  } else {
    // the evaluator needs to learn this to peak data
    gc.write_default(word_width_sum);
    // Apply control buffer
    for (uint64_t t = 0; t < T; ++t) {
      uint64_t bit_offset = 0;
      for (uint64_t word_idx = 0; word_idx < port_words[t].size(); ++word_idx) {
        Word& word = port_words[t][word_idx];
        for (uint bit_idx = 0; bit_idx < word.width(); ++bit_idx) {
          word[bit_idx].get_label() ^=
              Hash(controls[t].get_label(), t, bit_offset++);
        }
      }
      Assert_eq(bit_offset, word_width_sum);
    }
    switch_stack_garble(gc, controls, port_words, caller, callee);
    clear_and_release(prefix_sum);
    clear_and_release(controls);
  }
  for (std::vector<Word>& words : port_words) {
    for (uint64_t word_idx = 0; word_idx < words.size(); ++word_idx) {
      // the garbler cannot predict the routing behavior
      words[word_idx].set_pub_g(false);
      words[word_idx].set_owner(callee);
    }
  }
  return gc;
}

uint64_t BaseConditionalLink::index_calculator(uint row, uint64_t col) {
  if (!row && !col) {
    return -1;
  }
  uint64_t log_col_group = log2ceil(col);
  uint64_t prev_pow2 = 1UL << (log_col_group - 1);
  uint64_t precede_col_group =
      prev_pow2 * (log_col_group - 2) + 1 + log_col_group * (col - prev_pow2);
  return precede_col_group + (uint64_t)row;
}
}  // namespace PicoGRAM
