#pragma once

#include "gadget_group.hpp"
#include "waksman.hpp"

namespace PicoGRAM {

/**
 * @brief Data block used when initializing the ORAM
 *
 */
struct PlaintextBlock {
  uint64_t position;       // the position of the block
  uint64_t v_addr;         // the virtual address of the block
  std::vector<bool> data;  // the data of the block

  PlaintextBlock(uint64_t position, uint64_t v_addr,
                 const std::vector<bool>& data)
      : position(position), v_addr(v_addr), data(data) {}

  PlaintextBlock(uint64_t position, uint64_t v_addr, uint64_t data,
                 uint64_t data_width)
      : position(position), v_addr(v_addr) {
    this->data.resize(data_width);
    for (uint i = 0; i < data_width; ++i) {
      this->data[i] = (data >> i) & 1;
    }
  }
};

struct Block {
  Bit valid;
  Word position;
  Word v_addr;
  Word data;

  static void cond_swap(const Bit& control_bit, Block& a, Block& b) {
    Bit::cond_swap(control_bit, a.valid, b.valid);
    Word::cond_swap(control_bit, a.position, b.position);
    Word::cond_swap(control_bit, a.v_addr, b.v_addr);
    Word::cond_swap(control_bit, a.data, b.data);
  }
};

// a vector of blocks in the same position
using PlaintextBlocksInPos = std::vector<PlaintextBlock>;

using PlaintextBlocksInPosIter = std::vector<PlaintextBlocksInPos>::iterator;

struct ORAMConstParams {
  uint stash_size;
  uint bkt_size;
  uint evict_freq;
  uint max_log_way;
  uint64_t simd_link_threshold;

  ORAMConstParams() = delete;

  static ORAMConstParams dbg_params() { return {20u, 3u, 2u, 2u, 8ul}; }

  static ORAMConstParams dbg_no_simd_params() {
    return {20u, 3u, 2u, 2u, UINT32_MAX};
  }

  static ORAMConstParams compute_friendly_params(uint memory_space_width) {
    if (memory_space_width < 16) {
      return {42u, 7u, 1u, 2u, 32ul};
    } else {
      return {50u, 6u, 1u, 2u, 32ul};
    }
  }

  static ORAMConstParams comm_friendly_params(uint memory_space_width) {
    if (memory_space_width < 8) {
      return {17u, 5u, 2u, 2u, 8ul};
    } else if (memory_space_width < 26) {
      return {21u, 4u, 2u, 2u, 8ul};
    } else {
      return {34u, 3u, 2u, 2u, 8ul};
    }
  }

  static ORAMConstParams recommended_params(uint memory_space_width,
                                            uint64_t simd_link_threshold) {
    ORAMConstParams params = compute_friendly_params(memory_space_width);
    params.simd_link_threshold = simd_link_threshold;
    return params;
  }

  // cout
  friend std::ostream& operator<<(std::ostream& os, const ORAMConstParams& p) {
    os << "stash_size: " << p.stash_size << ", bkt_size: " << p.bkt_size
       << ", evict_freq: " << p.evict_freq << ", max_log_way: " << p.max_log_way
       << ", simd_link_threshold: " << p.simd_link_threshold;
    return os;
  }
};

/**
 * @brief A k-ary circuit ORAM tree (or sub-tree). The data structure accepts
 * either a read or evict request at each time step. To maximize efficiency,
 * eviction is also performed during a read request on the read path. If the
 * element to read is found in a bucket, no other element will be evicted from
 * the same bucket.
 *
 */
struct CircuitORAMTree : Gadget {
  enum Op { READ, EVICT };

 private:
  uint v_addr_width;    // the width of the virtual address word
  uint word_width;      // the width of the data word
  uint level_width;     // the width of the total level of the tree
  uint position_width;  // the width of the position word
  uint level;           // the level in the tree (root has level 0)
  Word level_word;      // the level in the tree as a Word
  uint remain_level;    // the remaining level in the tree, i.e., total_level -
                        // level
  uint bkt_size;    // the capacity of the bucket (or stash if this is the root)
  uint log_way;     // the log of the number of ways at the current level
  Word bkt_valids;  // a bit vector indicating whether each slot in the bucket
                    // is valid (i.e. occupied)
  std::vector<Word> bkt_positions;  // the positions of the data in the bucket,
                                    // if level > 0, the repetitive bits in
                                    // position is trimmed
  std::vector<Word> bkt_v_addrs;    // the virtual addresses of the data in the
                                    // bucket
  std::vector<Word> bkt_datas;      // the data in the bucket

  Group<CircuitORAMTree, uint, uint, uint, uint, uint, uint,
        ORAMConstParams>* children =
      NULL;  // the children (sub-tree) of the current node

  /**
   * @brief Find the data in the bucket that can be evicted to the deepest
   * level, or if it's a read request, the one that matches v_addr if exists. If
   * multiple addresses can go to the last level and none of them matches the
   * input virtual address, the one with the largest index will be chosen.
   * @param position the path to evict
   * @param is_read whether the operation is a read
   * @param v_addr the virtual address to match. If there is a match, treat it
   * as deepest.
   * @return FuncOutput[0] the max level an address can go to
   *        FuncOutput[1] a one-hot word indicating the location of the deepest
   * address FuncOutput[2] a bit indicating whether the deepest address
   * perfectly matches the input address
   */
  FuncOutput get_local_deepest(const Word& position, const Bit& is_read,
                               const Word& v_addr) {
    Word max_common_suffix_len = Word::constant(self, 1, (uint64_t)0);
    Word is_deepest_one_hot = Word::constant(self, bkt_size, (uint64_t)0);
    // whether the deepest address perfectly matches
    // the input address
    Bit has_match = Bit::constant(self, (uint64_t)0);

    for (uint i = 0; i < bkt_size; ++i) {
      Bit is_valid = bkt_valids[i];
      const Word& position_xor = bkt_positions[i] ^ position;
      Assert(position_xor.width() == position_width);

      const Word& common_suffix_len = position_xor.trailing_zeros(log_way);
      // if there's a match before, we should not consider it as the deepest

      Bit is_deepest =
          is_valid & (common_suffix_len >= max_common_suffix_len) & !has_match;

      Word::cond_mov(is_deepest, max_common_suffix_len, common_suffix_len);

      has_match |= is_valid & is_read & (!(bkt_v_addrs[i] ^ v_addr));
      is_deepest_one_hot.set_bit(i, is_deepest);
    }
    // remove 1 in one-hot encoding except the last one
    is_deepest_one_hot = is_deepest_one_hot.ms_one();
    const Word& deepest_level = level_word + max_common_suffix_len;

    return FuncOutput({deepest_level, is_deepest_one_hot, Word(has_match)});
  }

  // below are temporary variables used at each time step
  Word op;        // the operation to perform in the current time step
  Word position;  // the path to read / evict in the current time step
  Word v_addr;  // the virtual address to read from in the current time step, or
                // 0 if it's an evict operation
  Word local_deepest_one_hot;  // marks which location in bkt can be evicted
                               // deepest
  Bit local_has_match;  // whether there's a match for read in the current
                        // bucket
  Bit should_send;      // whether the current level should send an element to a
                        // level below
  Bit should_drop;      // whether the current level should receive an element
                        // from a level above
  Bit is_local_deeper;  // whether there's an element in the bucket deeper than
  // the element from level above
  Bit goal_valid;

  Word deepest_src;  // the deepest source level of the element above

  Word to_swap_data;  // the data to swap / swapped with a bucket entry

  // a reference to the sub-tree corresponding to the position
  GroupEntry<CircuitORAMTree, uint, uint, uint, uint, uint, uint,
             ORAMConstParams>
      child_entry;

  // meta scan to decide evict schedule
  // we perform several optimizations over the pseudo code in the tri-state
  // paper
  // 1. We perform eviction on read path almost for free. Compared to a full
  // eviction, we skip evicting elements from a bucket with the element to read,
  // since we want to scan each bucket only once.
  // 2. In the pseudo code, a level remembers a target level to send element to
  // here, we let each level remember whether it should receive an element.
  // Therefore, we don't need to pass the "dest" from children to parents, and
  // during the actual eviction, we don't need to pass this "dest" from parents
  // to children.
  // 3. We avoid some unnecessary operations for invalidating variables that
  // store level information
  FuncOutput compute_child_deepest_src_and_goal(FuncInput inputs) {
    // an element currently residing higher up a path passing through this node
    deepest_src = inputs[0];  // corresponds to src in metascan 1
    // the maximum tree depth that an element currently residing above the
    // considered node can legally reside
    const Word& goal = inputs[1];

    goal_valid = goal >= level_word;
    if (!remain_level) {
      // last level
      local_has_match = Bit::constant(self, 0);
      local_deepest_one_hot = Word::constant(self, bkt_size, (uint64_t)0);
      for (uint i = 0; i < bkt_size; ++i) {
        Bit is_valid = bkt_valids[i];
        Bit is_match = is_valid & (bkt_v_addrs[i] == v_addr);
        local_deepest_one_hot.set_bit(i, is_match);
        local_has_match |= is_match;
      }
      local_has_match &= (op == READ);
      // can drop an element if there's a vacancy or there's a match for read
      Bit can_drop = (!!~bkt_valids) | local_has_match;
      // there's an element above that can move to this level
      should_drop = can_drop & goal_valid;
      return FuncOutput({});
    }
    FuncOutput local_deepest_info =
        get_local_deepest(position, op == READ, v_addr);
    const Word& local_deepest_level = local_deepest_info[0];

    local_has_match = local_deepest_info[2][0];
    // if there's a match for read, do not evict from this level
    is_local_deeper = (local_deepest_level > goal) | local_has_match;

    local_deepest_one_hot = local_deepest_info[1];

    // whether to replace the deepest element with the current element
    Bit replace_flag = (!local_has_match) & is_local_deeper;

    const Word& deepest_src_child =
        Word::mux(replace_flag, deepest_src, level_word);
    const Word& goal_child = Word::mux(replace_flag, goal, local_deepest_level);

    // FuncOutput child_output =
    //     child_entry.call("meta_scan", {deepest_src_child, goal_child});
    // a level which should evict an element
    return FuncOutput({deepest_src_child, goal_child});
  }

  /**
   * @brief A helper function for meta scan that takes in the output of the
   * child meta scan and outputs the meta scan result for the parent.
   *
   * @param child_output
   * @return FuncOutput
   */
  FuncOutput compute_parent_src_and_has_dest(FuncInput child_output) {
    // a level which should evict an element
    const Word& src = child_output[0];
    // whether there is a level below wanting to receive an element
    // i.e. src <= level_word
    const Bit& has_dest = child_output[1][0];

    Bit level_eq_src_flag = level_word == src;

    // whether an element should be sent from this level
    should_send = has_dest & level_eq_src_flag;
    Bit has_vacancy = !!(~bkt_valids);
    // whether an element should be sent from a level above to a level below
    Bit should_skip = has_dest & !level_eq_src_flag;

    // compared to original code, we treat the slot to read as an empty slot
    Bit can_drop =
        ((!should_skip) & (has_vacancy | local_has_match)) | should_send;

    should_drop = can_drop & goal_valid;

    // Here we don't need to set src or deepest_src as invalid like in the
    // tri-state paper. If goal_valid is false, then should_drop is false
    // and deepest_src is not used. If level == src, then src will not match any
    // level above.
    const Word& src_parent = Word::mux(should_drop, src, deepest_src);

    Bit parent_has_dest = should_skip | should_drop;
    return FuncOutput({src_parent, Word(parent_has_dest)});
  }

  /**
   * @brief The bit bandwidth consumed by "from_words" at this level.
   *
   * @return uint
   */
  uint bit_bw() const {
    return level_width * 3   // deepest_src, goal, src_parent
           + 1               // parent_has_dest
           + 1               // hold_valid
           + position_width  // hold_position
           + v_addr_width    // hold_v_addr
           + word_width      // hold_data
           + word_width;     // return data
  }

  /**
   * @brief A SIMD version of the meta_scan function.
   *
   */
  std::function<SIMDFuncOutput(SIMDFuncInput)> meta_scan_simd_func =
      [&](SIMDFuncInput simd_inputs) {
        const SIMDWord& simd_op = simd_inputs[0];
        SIMDWord simd_position = simd_inputs[1];
        const SIMDWord& simd_v_addr = simd_inputs[2];
        FuncInput inputs = SIMDWord::to_words(simd_inputs);
        op = inputs[0];
        position = inputs[1];
        v_addr = inputs[2];
        FuncInput child_deepest_src_goal_inputs =
            compute_child_deepest_src_and_goal({inputs[3], inputs[4]});
        uint64_t output_begin_bit_offset =
            simd_inputs.back().bit_offset + simd_inputs.back().width();

        uint64_t child_input_begin_bit_offset =
            simd_inputs[3].bit_offset + bit_bw();
        if (remain_level) {
          const Word& child_idx = position.slice(log_way);
          child_entry = (*children)[child_idx];
          if (children->get_link_type() == SIMD_COND) {
            simd_position >>= log_way;
            SIMDFuncInput child_simd_deepest_src_goal_inputs =
                SIMDWord::from_words(child_deepest_src_goal_inputs,
                                     child_input_begin_bit_offset);
            const SIMDFuncOutput& child_simd_outputs = child_entry.call_simd(
                "meta_scan_simd", {simd_op, simd_position, simd_v_addr,
                                   child_simd_deepest_src_goal_inputs[0],
                                   child_simd_deepest_src_goal_inputs[1]});
            const FuncOutput& child_outputs =
                SIMDWord::to_words(child_simd_outputs);
            const FuncOutput& outputs =
                compute_parent_src_and_has_dest(child_outputs);
            return SIMDWord::from_words(outputs, output_begin_bit_offset);
          } else {
            const FuncOutput& child_outputs = child_entry.call(
                "meta_scan", {op, position >> log_way, v_addr,
                              child_deepest_src_goal_inputs[0],
                              child_deepest_src_goal_inputs[1]});
            const FuncOutput& outputs =
                compute_parent_src_and_has_dest(child_outputs);
            return SIMDWord::from_words(outputs, output_begin_bit_offset);
          }
        } else {
          const Word& src_parent =
              Word::mux(should_drop, level_word, deepest_src);
          should_send = Bit::constant(self, 0);
          return SIMDWord::from_words({src_parent, Word(should_drop)},
                                      output_begin_bit_offset);
        }
      };

  /**
   * @brief The meta_scan function. The function decides whether to read an
   * element in the current node, send an element to a level below, receive an
   * element from a level above, or do nothing.
   *
   */
  std::function<FuncOutput(FuncInput)> meta_scan_func = [&](FuncInput inputs) {
    op = inputs[0];
    position = inputs[1];
    v_addr = inputs[2];
    FuncInput child_deepest_src_goal_inputs =
        compute_child_deepest_src_and_goal({inputs[3], inputs[4]});

    if (remain_level) {
      const Word& child_idx = position.slice(log_way);
      FuncInput child_inputs = {op, position >> log_way, v_addr,
                                child_deepest_src_goal_inputs[0],
                                child_deepest_src_goal_inputs[1]};
      child_entry = (*children)[child_idx];
      if (children->get_link_type() == SIMD_COND) {
        SIMDFuncInput child_simd_inputs = SIMDWord::from_words(child_inputs, 0);
        const SIMDFuncOutput& child_simd_outputs =
            child_entry.call_simd("meta_scan_simd", child_simd_inputs);
        const FuncOutput& child_outputs =
            SIMDWord::to_words(child_simd_outputs);
        const FuncOutput& outputs =
            compute_parent_src_and_has_dest(child_outputs);
        return outputs;
      } else {
        const FuncOutput& child_outputs =
            child_entry.call("meta_scan", child_inputs);
        const FuncOutput& outputs =
            compute_parent_src_and_has_dest(child_outputs);
        return outputs;
      }
    } else {
      const Word& src_parent = Word::mux(should_drop, level_word, deepest_src);
      should_send = Bit::constant(self, 0);
      return FuncOutput({src_parent, Word(should_drop)});
    }
  };

  FuncOutput access_local(FuncInput inputs) {
    const Bit& hold_valid = inputs[0][0];
    const Word& hold_position = inputs[1];
    const Word& hold_v_addr = inputs[2];
    const Word& hold_data = inputs[3];
    // whether we should read the deepest slot
    Bit should_read = should_send | local_has_match;
    // whether we should swap with a dummy slot
    Bit replace_dummy_flag = should_drop & !should_read;

    Bit to_swap_valid = hold_valid & should_drop;
    Word to_swap_position = hold_position;
    Word to_swap_v_addr = hold_v_addr;
    to_swap_data = hold_data;
    // whether we should read from the bucket
    Bit should_read_from_bkt = should_read;
    if (level == 0) {
      // to avoid swapping the new element to evict and the element in the
      // stash since they are both in level 0
      should_read_from_bkt &= is_local_deeper;
    }
#ifdef FAST_MEASURE
    uint64_t begin_gc_offset = 0;
    Gadget* owner = local_has_match.get_owner();
    Mode mode = owner->get_mode();
#endif
    for (uint i = 0; i < bkt_size; ++i) {
      Bit is_deepest = local_deepest_one_hot[i];
      Bit read_and_remove_flag = is_deepest & should_read_from_bkt;
      Bit write_to_dummy_flag = (!bkt_valids[i]) & replace_dummy_flag;
      // we might swap with multiple dummy slots when write to dummy flag is
      // true, but it is fine since swapping dummy with dummy is a
      // effectively no-op
      Bit swap_flag = read_and_remove_flag | write_to_dummy_flag;
      Bit::cond_swap(swap_flag, bkt_valids[i], to_swap_valid);
      Word::cond_swap(swap_flag, bkt_positions[i], to_swap_position);
      Word::cond_swap(swap_flag, bkt_v_addrs[i], to_swap_v_addr);
      Word::cond_swap(swap_flag, bkt_datas[i], to_swap_data);
#ifdef FAST_MEASURE
      if (mode == MEASURE && owner->get_time() > 1) {
        uint64_t end_gc_offset = owner->get_gc().get_offset();
        if (i == 0) {
          // the cost of the first timestep may be different, so we measure the
          // second timestep
          begin_gc_offset = end_gc_offset;
        } else {
          Assert(i == 1);
          uint64_t gc_cost_per_timestamp = end_gc_offset - begin_gc_offset;
          owner->get_gc().skip_data(gc_cost_per_timestamp * (bkt_size - 2));
          // skip the rest
          break;
        }
      }
#endif
    }
    if (op.to_int() == EVICT) {
      local_has_match.skip();  // skip the return value
    }
    if (!remain_level) {
      to_swap_data *= local_has_match;
      return {};
    }
    // case 1: should_drop = false, should_read = false
    // => valid = hold_valid, addr/data = hold_addr/hold_data

    // case 2: should_drop = true, should_read = false
    // => hold_valid = false

    // case 3: should_drop = true, should_read = true =>
    // => hold_valid = should_send, hold_addr data = to_swap_addr/data

    // case 4: should_drop = false, should_read = true, should_send = true
    // =>
    // => hold_valid = true, hold_addr/data = to_swap_addr/data

    // case 5: should_drop = false, should_read = true, should_send = false
    // =>
    // => hold_valid = hold_valid, hold_addr/data = hold_addr/data
    Bit child_hold_valid = should_send | (hold_valid & !should_drop);
    const Word& child_hold_position = Word::mux(
        should_send, hold_position >> log_way, to_swap_position >> log_way);
    const Word& child_hold_v_addr =
        Word::mux(should_send, hold_v_addr, to_swap_v_addr);
    const Word& child_hold_data =
        Word::mux(should_send, hold_data, to_swap_data);
    to_swap_data *= local_has_match;
    return {Word(child_hold_valid), child_hold_position, child_hold_v_addr,
            child_hold_data};
  }

  /**
   * @brief Get the bit offsets of the same return value in different
   * levels of the tree. Used for aggregating outputs from different levels
   *
   * @param bit_offsets the bit offsets of the levels above, must not be empty
   */
  void get_bit_offsets_recursive(std::vector<uint>& bit_offsets) {
    Assert(bit_offsets.size() > 0);
    if (remain_level && children->get_link_type() == SIMD_COND) {
      uint bit_offset = bit_offsets.back() + children->get_child(0)->bit_bw();
      bit_offsets.push_back(bit_offset);
      children->get_child(0)->get_bit_offsets_recursive(bit_offsets);
    }
  }

  /**
   * @brief Actually evict the data or read the data from the bucket
   *
   */
  std::function<FuncOutput(FuncInput)> access_func = [&](FuncInput inputs) {
    FuncInput child_inputs = access_local(inputs);
    if (!remain_level) {
      return FuncOutput({to_swap_data});
    }
    if (children->get_link_type() == SIMD_COND) {
      uint64_t child_inputs_begin_offset = 1 + position_width + v_addr_width +
                                           2 * level_width;  // bw of meta_scan
      SIMDFuncInput child_simd_inputs =
          SIMDWord::from_words(child_inputs, child_inputs_begin_offset);
      SIMDFuncOutput child_simd_output =
          child_entry.call_simd("access_simd", child_simd_inputs);
      if (get_mode() == GARBLE || get_mode() == MEASURE) {
        // we need to include the aggregated bit offset before converting to
        // words
        std::vector<uint> bit_offsets = {child_simd_output[0].bit_offset};
        children->get_child(0)->get_bit_offsets_recursive(bit_offsets);
        child_simd_output[0].bit_offsets_to_aggr = bit_offsets;
      }
      FuncInput child_output = SIMDWord::to_words(child_simd_output);
      const Word& output_data = child_output[0] ^ to_swap_data;
      return FuncOutput({output_data});
    } else {
      FuncInput child_output = child_entry.call("access", child_inputs);
      const Word& output_data = child_output[0] ^ to_swap_data;
      return FuncOutput({output_data});
    }
  };

  /**
   * @brief A SIMD version of the access function
   *
   */
  std::function<SIMDFuncOutput(SIMDFuncInput)> access_func_simd =
      [&](SIMDFuncInput simd_inputs) {
        FuncInput inputs = SIMDWord::to_words(simd_inputs);
        FuncInput child_inputs = access_local(inputs);
        uint64_t output_begin_bit_offset =
            simd_inputs.back().bit_offset + simd_inputs.back().width();
        if (!remain_level) {
          const std::vector<SIMDWord>& output =
              SIMDWord::from_words({to_swap_data}, output_begin_bit_offset);
          return SIMDFuncOutput{SIMDWord::new_aggr_word(output[0])};
        }

        if (children->get_link_type() == SIMD_COND) {
          uint64_t child_inputs_begin_offset =
              simd_inputs[0].bit_offset + bit_bw();
          SIMDFuncInput child_simd_inputs =
              SIMDWord::from_words(child_inputs, child_inputs_begin_offset);
          SIMDFuncOutput child_simd_output =
              child_entry.call_simd("access_simd", child_simd_inputs);
          // FuncOutput child_output = SIMDWord::to_words(child_simd_output);
          const std::vector<SIMDWord>& read_results =
              SIMDWord::from_words({to_swap_data}, output_begin_bit_offset);
          child_simd_output[0].aggregate_with(read_results[0]);
          // const Word& output_data = child_output[0] ^ to_swap_data;
          return child_simd_output;
        } else {
          FuncOutput child_output = child_entry.call("access", child_inputs);
          const Word& output_data = child_output[0] ^ to_swap_data;
          const std::vector<SIMDWord>& simd_outputs =
              SIMDWord::from_words({output_data}, output_begin_bit_offset);
          return SIMDFuncOutput{SIMDWord::new_aggr_word(simd_outputs[0])};
        }
      };

  /**
   * @brief Fill bkts with blocks and return the overflow blocks
   *
   * @param blocks the blocks to fill the bucket
   * @param position_shift the position in blocks should be right shifted by
   * this
   * @return std::vector<PlaintextBlock>
   */
  std::vector<PlaintextBlock> fill_bkt_g(const PlaintextBlocksInPos& blocks,
                                         uint position_shift) {
    for (uint i = 0; i < bkt_size; ++i) {
      if (i < blocks.size()) {
        bkt_valids.set_bit(i, Bit::input_g(self, 1));
        bkt_positions[i] = Word::input_g(self, position_width,
                                         blocks[i].position >> position_shift);
        bkt_v_addrs[i] = Word::input_g(self, v_addr_width, blocks[i].v_addr);
        bkt_datas[i] = Word::input_g(self, word_width, blocks[i].data);
      } else {
        bkt_valids.set_bit(i, Bit::input_g(self, 0));
        bkt_positions[i] = Word::input_g(self, position_width, (uint64_t)0);
        bkt_v_addrs[i] = Word::input_g(self, v_addr_width, (uint64_t)0);
        bkt_datas[i] = Word::input_g(self, word_width, (uint64_t)0);
      }
    }
    if (blocks.size() < bkt_size) {
      return std::vector<PlaintextBlock>();
    }
    // overflows
    return std::vector<PlaintextBlock>(blocks.begin() + bkt_size, blocks.end());
  }

 public:
  DEFINE_FUNC(meta_scan, std::vector<uint>({level_width, 1}), meta_scan_func);

  DEFINE_SIMDFUNC(meta_scan_simd, std::vector<uint>({level_width, 1}),
                  meta_scan_simd_func);

  DEFINE_FUNC(access, std::vector<uint>({word_width}), access_func);

  DEFINE_SIMDFUNC(access_simd, std::vector<uint>({word_width}),
                  access_func_simd);

  void print_tree() {
    std::cout << "level: " << level << std::endl;
    for (uint i = 0; i < bkt_size; ++i) {
      uint64_t bkt_valid_val = bkt_valids[i].to_int();
      uint64_t bkt_positions_val = bkt_positions[i].to_int();
      uint64_t bkt_addrs_val = bkt_v_addrs[i].to_int();
      uint64_t bkt_datas_val = bkt_datas[i].to_int();
      if (bkt_valid_val) {
        std::cout << " position: " << bkt_positions_val
                  << " v_addr: " << bkt_addrs_val << " data: " << bkt_datas_val
                  << std::endl;
      }
    }
    if (children) {
      for (uint way = 0; way < 1u << log_way; ++way) {
        children->get_child(way)->print_tree();
      }
    }
  }

  uint get_level_width() const { return level_width; }

  /**
   * @brief Initialize the ORAM tree
   *
   * @param begin
   * @param end
   * @param position_shift
   * @return std::vector<PlaintextBlock>
   */
  std::vector<PlaintextBlock> init_ram_g(PlaintextBlocksInPosIter begin,
                                         PlaintextBlocksInPosIter end,
                                         uint position_shift = 0) {
#ifdef FAST_MEASURE
    if (get_measure_multiplier() == 0) {
      return fill_bkt_g({}, position_shift);
    }
#endif
    if (std::distance(begin, end) == 1L) {
      // leaf node
      const PlaintextBlocksInPos& blocks = *begin;
      return fill_bkt_g(blocks, position_shift);
    }
    Assert_eq(std::distance(begin, end), 1L << position_width);
    std::vector<PlaintextBlock> overflow_blocks;
    uint64_t child_memory_space = 1UL << (position_width - log_way);
    Assert(child_memory_space);
    // recursively initialize children
    for (uint64_t i = 0; i < (1UL << log_way); ++i) {
      std::vector<PlaintextBlock> child_overflow_blocks =
          children->get_child(i)->init_ram_g(
              begin + i * child_memory_space,
              begin + (i + 1) * child_memory_space, position_shift + log_way);
      overflow_blocks.insert(overflow_blocks.end(),
                             child_overflow_blocks.begin(),
                             child_overflow_blocks.end());
    }
    return fill_bkt_g(overflow_blocks, position_shift);
  }

  using SrcOfPos = std::vector<std::vector<uint64_t*>>;
  using SrcOfPosIter = SrcOfPos::const_iterator;

 private:
  std::vector<uint64_t*> set_slot_indices_for_bkt(
      const std::vector<uint64_t*>& srcs,
      std::vector<uint64_t>& dummy_slot_indices, uint64_t& start_idx) {
    for (uint i = 0; i < bkt_size; ++i) {
      if (i < srcs.size()) {
        *srcs[i] = start_idx++;
      } else {
        dummy_slot_indices.push_back(start_idx++);
      }
    }
    if (srcs.size() < bkt_size) {
      return {};
    }
    // overflows
    return std::vector<uint64_t*>(srcs.begin() + bkt_size, srcs.end());
  }

 public:
  uint64_t num_slots() const {
    if (remain_level) {
      return bkt_size + children->get_child(0)->num_slots() * (1UL << log_way);
    } else {
      return bkt_size;
    }
  }

  std::vector<uint64_t*> set_slot_indicies(
      SrcOfPosIter begin, SrcOfPosIter end,
      std::vector<uint64_t>& dummy_slot_indices, uint64_t& start_idx) {
#ifdef FAST_MEASURE
    if (get_measure_multiplier() == 0) {
      return set_slot_indices_for_bkt({}, dummy_slot_indices, start_idx);
    }
#endif
    if (std::distance(begin, end) == 1L) {
      // leaf node
      Assert(!remain_level);
      return set_slot_indices_for_bkt(*begin, dummy_slot_indices, start_idx);
    }
    Assert_eq(std::distance(begin, end), 1L << position_width);
    std::vector<uint64_t*> overflow_srcs;
    uint64_t child_memory_space = 1UL << (position_width - log_way);
    Assert(child_memory_space);
    // recursively initialize children
    for (uint64_t i = 0; i < (1UL << log_way); ++i) {
      std::vector<uint64_t*> child_overflow_srcs =
          children->get_child(i)->set_slot_indicies(
              begin + i * child_memory_space,
              begin + (i + 1) * child_memory_space, dummy_slot_indices,
              start_idx);
      overflow_srcs.insert(overflow_srcs.end(), child_overflow_srcs.begin(),
                           child_overflow_srcs.end());
    }
    return set_slot_indices_for_bkt(overflow_srcs, dummy_slot_indices,
                                    start_idx);
  }

  void fill_tree(std::vector<Block>::iterator& iter, uint position_shift = 0) {
    if (remain_level) {
      // recursively initialize children
      for (uint64_t i = 0; i < (1UL << log_way); ++i) {
        children->get_child(i)->fill_tree(iter, position_shift + log_way);
      }
    }
    for (uint i = 0; i < bkt_size; ++i) {
      bkt_valids[i] = iter->valid;
      bkt_valids[i].set_owner(self);
      bkt_positions[i] = iter->position >> position_shift;
      bkt_positions[i].set_owner(self);
      bkt_v_addrs[i] = iter->v_addr;
      bkt_v_addrs[i].set_owner(self);
      bkt_datas[i] = iter->data;
      bkt_datas[i].set_owner(self);
      ++iter;
    }
  }

  /**
   * @brief Find the number of log_way <= max_log_way that minimizes the number
   * of levels and keeps the log_ways in all the remaining levels are evenly
   * distributed.
   *
   * @param max_log_way
   * @param position_width
   * @return uint
   */
  static uint optimal_log_way(uint max_log_way, uint position_width) {
    uint num_level = (position_width + max_log_way - 1) / max_log_way;
    if (num_level == 0) {
      return 1;
    }
    uint log_way = (position_width + num_level - 1) / num_level;
    Assert(log_way > 0);
    return log_way;
  }

  /**
   * @brief Construct a new Circuit ORAM Tree object recursively
   *
   * @param caller the caller of the (sub)tree's root
   * @param link_type the type of the link between this and the caller
   * @param T the number of operations the Circuit ORAM tree is scheduled to
   * handle, including both read and eviction
   * @param v_addr_width the width of the virtual addresses, which serves as a
   * unique id for entries in the tree
   * @param word_width the width of the ORAM data word
   * @param position_width the width of a word that stores a position (path id)
   * in the tree
   * @param level_width the width of a word that stores a level number in the
   * tree
   * @param level the level of the (sub)tree's root in the tree
   * @param stash_size the capacity of the root bucket
   * @param bkt_size the capacity of all other buckets
   * @param log_way the log2 of the tree's fan-out
   */
  CircuitORAMTree(Gadget* caller, LinkType link_type, uint64_t T,
#ifdef FAST_MEASURE
                  uint64_t measure_multiplier,
#endif
                  uint v_addr_width, uint word_width, uint position_width,
                  uint level_width, uint level, uint log_way,
                  const ORAMConstParams& params)
      :
#ifdef FAST_MEASURE
        Gadget(caller, link_type, T, measure_multiplier),
#else
        Gadget(caller, link_type, T),
#endif
        v_addr_width(v_addr_width),
        word_width(word_width),
        level_width(level_width),
        position_width(position_width),
        level(level),
        level_word(Word::constant(self, level_width, level)),
        remain_level((position_width + log_way - 1) / log_way),
        bkt_size(level == 0 ? params.stash_size : params.bkt_size),
        log_way(log_way) {
    bkt_valids = Word::constant(self, this->bkt_size, (uint64_t)0);
    for (uint64_t i = 0; i < this->bkt_size; ++i) {
      bkt_positions.push_back(
          Word::constant(self, position_width, (uint64_t)0));
      bkt_v_addrs.push_back(Word::constant(self, v_addr_width, (uint64_t)0));
      bkt_datas.push_back(Word::constant(self, word_width, (uint64_t)0));
    }

    uint64_t T_child = (T + (1UL << log_way) - 1) >> log_way;
    if (level == 0) {
      // the maximum number of accesses to each child is the sum of
      // initially
      // and newly assigned elements to the physical memory space of the
      // child
      // plus the number of deterministic evictions to the child
      T_child += 1UL << (position_width - log_way);
    }
    T_child = std::min(T, T_child);

    if (remain_level) {
      uint child_position_width = position_width - log_way;
      uint child_log_way = optimal_log_way(log_way, child_position_width);
      children = new Group<CircuitORAMTree, uint, uint, uint, uint, uint, uint,
                           ORAMConstParams>(
          self, std::vector<uint64_t>(1UL << log_way, T_child),
          params.simd_link_threshold, v_addr_width, word_width,
          child_position_width, level_width, level + 1, child_log_way, params);
    }
    set_name("Circuit ORAM Tree level " + std::to_string(level));
  }

  ~CircuitORAMTree() {
    if (children) {
      delete children;
    }
  }
};

/**
 * @brief The interface of the Circuit ORAM. Connected with the CircuitORAMTree
 * through a direct link. For each access request, perform a read request to the
 * ORAM tree followed by one or more additional evictions.
 *
 */
struct CircuitORAM : DataType {
  CircuitORAMTree* oram;
  uint64_t memory_space;
  uint64_t num_leaves;
  uint position_width;  // the width of the position word
  uint v_addr_width;    // the width of the virtual address word
  uint word_width;      // the width of the data word
  uint level_width;     // the width of the total level of the tree
  uint evict_freq;      // the frequency of additional eviction per read
  uint log_way;  // the maximum log of the number of children at each level
  uint64_t evict_counter;  // the counter for the number of evictions

  using UpdateFuncType = std::function<Word(const Word&)>;

  /**
   * @brief Perform an access to the ORAM that calls a custom update function.
   *
   * @param position the current position of the word
   * @param v_addr the virtual address of the word
   * @param new_position the new position of the word
   * @param update_func the update function to apply to the data
   */
  void access(const Word& position, const Word& v_addr,
              const Word& new_position, const UpdateFuncType& update_func) {
    Assert(new_position.is_pub_g());
    uint level_width = oram->get_level_width();
    const Word& read_op = Word::constant(owner, 1, CircuitORAMTree::Op::READ);
    const Word& evict_op = Word::constant(owner, 1, CircuitORAMTree::Op::EVICT);

    const Word& read_init_deepest =
        Word::constant(owner, level_width, (uint64_t)0);
    const Word& read_init_goal = Word::input_g(owner, level_width, (uint64_t)0);

    oram->inc_time();
    // oram->set_addr({read_op, position, v_addr});
    FuncOutput read_meta_scan_output = oram->meta_scan(
        {read_op, position, v_addr, read_init_deepest, read_init_goal});
    // TODO: add check on read_meta_scan_output

    const Word& read_init_hold_valid = Word(Bit::constant(owner, 0));
    const Word& read_init_hold_position =
        Word::input_g(owner, position_width, (uint64_t)0);
    const Word& read_init_hold_v_addr =
        Word::input_g(owner, v_addr_width, (uint64_t)0);
    const Word& read_init_hold = Word::input_g(owner, word_width, (uint64_t)0);
    FuncInput read_access_input = {read_init_hold_valid,
                                   read_init_hold_position,
                                   read_init_hold_v_addr, read_init_hold};
    FuncOutput read_output_data = oram->access(read_access_input);
    for (uint i = 0; i < evict_freq; ++i) {
      oram->inc_time();
      const Word& evict_position =
          Word::input_g(owner, position_width, evict_counter);
      const Word& evict_v_addr =
          Word::input_g(owner, v_addr_width, (uint64_t)0);
      if (i == 0) {
        const Word& evict_init_deepest =
            Word::constant(owner, level_width, (uint64_t)0);
        const Word& position_xor = evict_position ^ new_position;
        Assert_eq(position_xor.width(), position_width);
        const Word& common_suffix_len = position_xor.trailing_zeros(log_way);
        Assert_eq(common_suffix_len.width(), level_width);
        const Word& evict_init_goal = common_suffix_len;

        FuncOutput evict_meta_scan_output =
            oram->meta_scan({evict_op, evict_position, evict_v_addr,
                             evict_init_deepest, evict_init_goal});

        const Word& to_write_valid = Word::constant(owner, 1, (uint64_t)1);
        const Word& to_write_data = update_func(read_output_data[0]);

        FuncInput to_write_input = {to_write_valid, new_position, v_addr,
                                    to_write_data};
        FuncOutput to_write_output = oram->access(to_write_input);
      } else {
        const Word& evict_init_deepest =
            Word::constant(owner, level_width, (uint64_t)0);
        const Word& evict_init_goal =
            Word::input_g(owner, level_width, (uint64_t)0);
        FuncOutput evict_meta_scan_output =
            oram->meta_scan({evict_op, evict_position, evict_v_addr,
                             evict_init_deepest, evict_init_goal});
        const Word& evict_init_hold_valid = Word(Bit::constant(owner, 0));
        const Word& evict_init_hold_position =
            Word::input_g(owner, position_width, (uint64_t)0);
        const Word& evict_init_hold_v_addr =
            Word::input_g(owner, v_addr_width, (uint64_t)0);
        const Word& evict_init_hold =
            Word::input_g(owner, word_width, (uint64_t)0);
        FuncInput evict_access_input = {
            evict_init_hold_valid, evict_init_hold_position,
            evict_init_hold_v_addr, evict_init_hold};
        FuncOutput evict_output_data = oram->access(evict_access_input);
      }
      ++evict_counter;
    }
  }

  /**
   * @brief Read or write a word from the ORAM
   *
   * @param position the current position of the word
   * @param v_addr the virtual address of the word
   * @param new_position the new position of the word
   * @param is_write whether the operation is a write
   * @param new_data the new data to write
   * @return Word the old data read from the ORAM
   */
  Word read_or_write(const Word& position, const Word& v_addr,
                     const Word& new_position, const Bit& is_write,
                     const Word& new_data) {
    Word old_data_copy;
    UpdateFuncType update_func = [&](const Word& old_data) {
      old_data_copy = old_data;
      return Word::mux(is_write, old_data, new_data);
    };
    access(position, v_addr, new_position, update_func);
    return old_data_copy;
  }

  /**
   * @brief Allows the garbler to initialize the ORAM with a set of blocks.
   * The garbler inputs the blocks assigned to each position in the oram tree.
   * The evaluator inputs an empty vector.
   * The function is optional. If not called, the garbler and evaluator agree
   * that the ORAM is empty.
   *
   * @param begin
   * @param end
   */
  void init_ram_g(PlaintextBlocksInPosIter begin,
                  PlaintextBlocksInPosIter end) {
    Assert(begin < end);
    std::vector<PlaintextBlock> overflow_blocks = oram->init_ram_g(begin, end);
    Assert(overflow_blocks.empty());
  }

 private:
  uint64_t get_total_slots() const { return oram->num_slots(); }

  std::vector<uint64_t> to_target_slot_indices(
      const std::vector<uint64_t>& target_positions) const {
    Assert_eq(target_positions.size(), memory_space);
    // the slot indices in the tree for target_positions
    std::vector<uint64_t> target_slot_indices(memory_space);
    // the slot indices in the tree for dummy positions
    std::vector<uint64_t> dummy_slot_indices;

    // pointers to the target slot indices so that the helper function can
    // modify them
    std::vector<std::vector<uint64_t*>> src_of_positions(num_leaves);

    for (uint64_t i = 0; i < memory_space; ++i) {
      src_of_positions[reverse_bits(target_positions[i], position_width)]
          .push_back(&target_slot_indices[i]);
    }
    uint64_t start_idx = 0;
    oram->set_slot_indicies(src_of_positions.begin(), src_of_positions.end(),
                            dummy_slot_indices, start_idx);
    target_slot_indices.insert(target_slot_indices.end(),
                               dummy_slot_indices.begin(),
                               dummy_slot_indices.end());
    Assert_eq(target_slot_indices.size(), get_total_slots());
    return target_slot_indices;
  }

 public:
  void init_ram(const std::vector<Word>& data,
                const std::vector<uint64_t>& target_positions = {}) {
    uint64_t total_slots = get_total_slots();
    Assert_eq(data.size(), memory_space);
    Gadget* data_owner = data[0].get_owner();
    std::vector<uint64_t> target_slot_indices;
    if (!target_positions.empty()) {
      target_slot_indices = to_target_slot_indices(target_positions);
    }
    // add constant zeros to the end of the data
    std::vector<Block> to_permute(total_slots);
    for (uint64_t i = 0; i < data.size(); ++i) {
      to_permute[i] = {
          Bit::constant(data_owner, 1),
          Word::input_g(data_owner, position_width,
                        target_positions.empty() ? 0 : target_positions[i]),
          Word::constant(data_owner, v_addr_width, i), data[i]};
    }
    for (uint64_t i = data.size(); i < total_slots; ++i) {
      to_permute[i] = {Bit::constant(data_owner, 0),
                       Word::constant(data_owner, position_width, (uint64_t)0),
                       Word::constant(data_owner, v_addr_width, (uint64_t)0),
                       Word::constant(data_owner, word_width, (uint64_t)0)};
    }
    const auto cond_swap_func = [&](bool cond, Block& a, Block& b) {
      Bit control_bit = Bit::input_g(owner, cond);
      Block::cond_swap(control_bit, a, b);
    };
    std::vector<Block> permuted_data =
        waksman_permute_vector(to_permute, target_slot_indices, cond_swap_func);
    std::vector<Block>::iterator iter = permuted_data.begin();
    oram->fill_tree(iter);
  }

  void init_evict_counter(uint64_t evict_counter) {
    this->evict_counter = evict_counter;
  }

  CircuitORAM(Gadget* owner, uint64_t memory_space, uint word_width, uint64_t T,
              const ORAMConstParams& params)
      : DataType(owner),
        memory_space(memory_space),
        num_leaves(memory_space),
        position_width(log2ceil(memory_space)),
        v_addr_width(log2ceil(memory_space)),
        word_width(word_width),
        evict_freq(params.evict_freq),
        evict_counter(0) {
    log_way =
        CircuitORAMTree::optimal_log_way(params.max_log_way, position_width);
    uint total_level = (position_width + log_way - 1) / log_way;
    level_width = bit_width(total_level);
    oram = new CircuitORAMTree(owner, DIRECT, T * (1 + evict_freq),
#ifdef FAST_MEASURE
                               1,
#endif
                               v_addr_width, word_width, position_width,
                               level_width, 0, log_way, params);
  }

  void print_tree() { oram->print_tree(); }

  ~CircuitORAM() { delete oram; }
};
}  // namespace PicoGRAM