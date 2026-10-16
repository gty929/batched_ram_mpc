#pragma once
#include "gadget_group.hpp"

namespace PicoGRAM {
/**
 * @brief A simple access-reveal memory without position map.
 * The implementation avoids unnecessary translation between word
 * and SIMDWord at every level.
 *
 */
struct AccessRevealRAM : Gadget {
  uint addr_width;  // the remaining width of the address at the current level
  uint word_width;  // the width of the data word
  Word data;        // the data word (only used in the leaf nodes)
  uint log_way;
  // the children of the current node
  Group<AccessRevealRAM, uint, uint, uint>* children = NULL;

  std::function<SIMDFuncOutput(SIMDFuncInput)> simd_access_func =
      [&](SIMDFuncInput inputs) {
        Assert_eq(inputs.size(), 3);
        SIMDWord address = inputs[0];
        SIMDWord op = inputs[1];
        SIMDWord new_data = inputs[2];
        Word op_word = op.to_word();

        if (addr_width > 0) {
          Word direction = address.slice(0, log_way).to_word();
          address >>= log_way;
          const SIMDFuncOutput& child_result = (*children)[direction].call_simd(
              "simd_access", {address, op, new_data});
          return child_result;
        }
        // set_bit_offset(new_data.bit_offset + new_data.width());
        // 0 for write, 1 for read
        Word new_data_word = new_data.to_word();
        new_data_word = Word::mux(!op_word, data, new_data_word);
        std::swap(data, new_data_word);
        const Word& result_word = new_data_word.slice(word_width);
        const SIMDWord& result =
            SIMDWord(result_word, new_data.bit_offset + new_data.width());
        set_bit_offset(result.bit_offset + word_width);
        return SIMDFuncOutput({result});
      };

  /**
   * @brief Access the memory at the given address, performing either read or
   * write.
   * @param inputs[0] the address
   * @param inputs[1] the operation (0 for write, 1 for read)
   * @param inputs[2] the new data for write or ignored for read
   * @return the data word read from the memory or the old data word for write
   *
   */
  DEFINE_SIMDFUNC(simd_access, std::vector<uint>({word_width}),
                  simd_access_func);

  /**
   * @brief A wrapper of the SIMD function
   *
   */
  DEFINE_FUNC(access, std::vector<uint>({word_width}), [&](FuncInput inputs) {
    SIMDFuncInput simd_inputs =
        SIMDWord::from_words(inputs, caller->get_bit_offset());
    uint64_t sum_input_width = Word::sum_width(inputs);
    caller->inc_bit_offset(sum_input_width);
    SIMDFuncOutput simd_result = simd_access_func(simd_inputs);
    return SIMDWord::to_words(simd_result);
  });

  /**
   * @brief Construct a new AccessRevealRAM object
   *
   * @param caller the caller gadget
   * @param addr_width the width of the address
   * @param word_width the width of the data word
   * @param log_way the log of the number of children at each level (default
   1).
   * The way at the last level may be less than 2^log_way.
   */
  AccessRevealRAM(Gadget* caller, LinkType link_type, uint64_t T,
                  uint addr_width, uint word_width, uint log_way = 1)
      : Gadget(caller, link_type, T),
        addr_width(addr_width),
        word_width(word_width),
        data(self, 1, 0) {
    set_name("Access Reveal SAM addr width: " + std::to_string(addr_width));
    if (addr_width > 0) {
      this->log_way = std::min(log_way, addr_width);
      children = new Group<AccessRevealRAM, uint, uint, uint>(
          self, std::vector<uint64_t>(1UL << this->log_way, T >> this->log_way),
          0, addr_width - this->log_way, word_width, log_way);
    }
  }

  ~AccessRevealRAM() {
    if (children) {
      delete children;
    }
  }
};
}  // namespace PicoGRAM