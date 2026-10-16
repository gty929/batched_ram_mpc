#pragma once

#include "bit.hpp"
#include "gadget.hpp"
#include "word.hpp"

namespace PicoGRAM {

struct SwitchStackState {
  uint64_t T = 0;
  uint64_t n = 0;  // max #down steps (callee T)
  uint64_t m = 0;  // max column index (caller timeline), used for arrays
  uint64_t W = 0;

  // Evaluator-only streaming state.
  uint64_t time = 0;       // current caller time (diagonal index)
  uint64_t real_count = 0; // number of down-steps seen so far

  Gadget* caller = nullptr;
  Gadget* callee = nullptr;

  // One-hot state along current diagonal k, as q_{i,k-i} for i in [i_min..i_max].
  std::vector<Bit> q_diag;

  // Down-edge labels of the previously completed row (row = real_count-1).
  // Indexed by column j in [0..m], stored as Bit labels (semantic 0/1 hidden).
  std::vector<Bit> up_row_de;

  // Down-edge labels for the current row (row = real_count), filled online.
  std::vector<Bit> curr_row_de;

  // XOR accumulator of all forced-zero write0 cell labels in the current row,
  // excluding the eventual active down-transition cell.
  std::vector<Label> row_acc;

  // Translation mask for the most recent real (down) step: for each bit offset b,
  // callee_label[b] = buffered_caller_label[b] XOR step_mask[b].
  std::vector<Label> step_mask;
  uint64_t step_time = static_cast<uint64_t>(-1);
};


Bit switch_zero_bit(const Bit& control, const Bit& input, uint64_t nonce_base,
                    uint64_t gate_id);


Word switch_zero_word(const Bit& control, const Word& input,
                      uint64_t nonce_base, uint64_t gate_id);

// Garbler-side construction of the switch-based stack. This transforms port_words in place so that entries 0..n-1 correspond to the compacted real records in the callee language, and writes GC payload in deterministic order.
void switch_stack_garble(GCPtr& gc, const std::vector<Bit>& controls,
                         std::vector<std::vector<Word>>& port_words,
                         Gadget* caller, Gadget* callee);

// Evaluator-side translation for one caller chunk at the current timestep.
// Returns words in the callee language for the next real call when control=0.
std::vector<Word> switch_stack_translate(
    GCPtr& gc, const std::vector<Word>& caller_chunk, const Bit& control_e,
    uint64_t caller_time, uint64_t word_width_sum, SwitchStackState& state,
    uint64_t& curr_bit_offset);

// Advance the evaluator state by one timestep. Records the q/de for the current step so translate can use it when active.
void switch_stack_step(GCPtr& gc, SwitchStackState& state, const Bit& control_e);

// Initialize evaluator state (call once before evaluation begins).
void switch_stack_init_state(SwitchStackState& state, Gadget* caller,
                             Gadget* callee, uint64_t T, uint64_t W);

}
