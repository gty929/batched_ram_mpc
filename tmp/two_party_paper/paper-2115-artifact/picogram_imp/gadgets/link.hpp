#pragma once
#include <queue>

#include "ec.hpp"
#include "gadget.hpp"
#include "simd_word.hpp"
#include "switch_stack.hpp"

namespace PicoGRAM {
/**
 * @brief Base-type of links, which connects two gadgets: a parent gadget and a
 * child gadget. The parent gadget may call the child gadget at each timestep
 * using the link.
 *
 */
struct BaseLink {
 protected:
  Gadget* callee;
  LinkType type;

 public:
  LinkType get_type() const { return type; }

  BaseLink(Gadget* callee, LinkType type) : callee(callee), type(type) {}

  /**
   * @brief For the evaluator to translate words in child's timezone to parent's
   * timezone, or in reverse. Intended to be overriden.
   *
   * @param input
   * @return std::vector<Word>
   */
  virtual std::vector<Word> translate(const std::vector<Word>& input) {
    // must be overriden to call
    Assert(false);
    return input;
  }

  /**
   * @brief For the evaluator to translate SIMD words in child's timezone to
   * parent's timezone, or in reverse. Intended to be overriden.
   *
   * @param input
   * @return std::vector<SIMDWord>
   */
  virtual std::vector<SIMDWord> translate(const std::vector<SIMDWord>& input) {
    // must be overriden to call
    Assert(false);
    return input;
  }

  virtual ~BaseLink() {}
};

/**
 * @brief A direct link is used when the call is always real (active).
 * The direct link allows the two gadgets with synchronous timesteps to be
 * garbled separately.
 *
 */
struct DirectLink : BaseLink {
 public:
  /**
   * @brief Translate between Words from the caller timezone and the callee
   * timezone
   *
   * @param input
   * @return std::vector<Word>
   */
  std::vector<Word> translate(const std::vector<Word>& inputs) override {
    std::vector<Word> outputs = inputs;
    if (!inputs.empty()) {
      Gadget* output_owner =
          inputs[0].get_owner() == callee ? callee->get_caller() : callee;
      for (Word& output : outputs) {
        output.set_owner(output_owner);
      }
    }
    return outputs;
  }

  explicit DirectLink(Gadget* callee) : BaseLink(callee, DIRECT) {}

  ~DirectLink() {}
};

/**
 * @brief Base class of Link and SIMDLink, which implement stacks for
 * conditional function calls.
 * The pub_g flags of words / SIMD words will always be set to false after the
 * conversion, since the garbler cannot predict the calling schedule.
 * The pub_e flags will be kept in the input words of the calls (conversion from
 * caller to callee), but will be set to false by default in the returned words
 * (callee to caller) because the caller is garbled before the callee.
 *
 */
struct BaseConditionalLink : BaseLink, BaseGadget {
 protected:
  std::vector<Bit> controls;  // used by the garbler to store the controls

  // the prefix sum of the controls, used by both the garbler and evaluator as
  // inputs to the SIMD buffer gates in the compaction (stack) circuit
  std::vector<Word> prefix_sum;

  bool is_active = false;  // whether the link is active, i.e., the latest
                           // control is real, used by the evaluator

  // the last timestamp when the caller updated the link, used to prevent the
  // caller from updating the link multiple times in the same timestamp
  uint64_t last_caller_time = -2;

  /**
   * @brief Treat the join gates in the compaction network as a 2D array,
   * used by the evaluator to calculate the index of the join gate at row and
   * col. Below is an example for T = 16, the numbers stand for the index.
   * By arranging the indices in this format, we get good cache locality for
   * both the garbler and evaluator.
   *
   * 0   1   3   5   8  11  14  17  21  25  29  33  37  41  45
   *     2   4   6   9  12  15  18  22  26  30  34  38  42  46
   *             7  10  13  16  19  23  27  31  35  39  43  47
   *                            20  24  28  32  36  40  44  48
   *
   * @param row the row index
   * @param col the column index
   * @return uint64_t the index of the join gate in GC
   */
  static uint64_t index_calculator(uint row, uint64_t col);

 public:
  BaseConditionalLink(Gadget* callee, LinkType type)
      : BaseLink(callee, type),
        BaseGadget(callee->get_caller()->get_mode(), callee->get_caller(),
                   callee->get_caller()->get_T()) {
    Assert(caller);
    Assert(callee);
    prefix_sum.emplace_back(caller, 1, 0);  // initially 0 (1-bit)
  }
};

/**
 * @brief Implements a stack based on compaction circuit in tri-state circuit
 * model.
 *
 */
struct Link : BaseConditionalLink {
 private:
  // used by the garbler
  // before garble the link, records the words of the parents
  // after garble the link, records the words of the children
  std::vector<std::vector<Word>> port_words;
  uint64_t curr_retrieved_t = 0;
  uint64_t curr_retrieved_word_idx = 0;
  uint64_t curr_bit_offset = 0;

  uint64_t word_width_sum = -1;
  SwitchStackState switch_state;

 public:
  explicit Link(Gadget* callee);
  /**
   * @brief Conditionally activate the link between the caller and the callee
   *
   * @param control control = 0 indicates that the link should become active
   * @return true if the link is active
   * @return false if the link is inactive
   */
  bool update_link(const Bit& control);

  /**
   * @brief Called by the garbler to specify the input/output words on the
   * caller side
   *
   * @param parent_words
   */
  void add_caller_words(const std::vector<Word>& parent_words);

  /**
   * @brief Called by the garbler to retrieve the next num input/output words on
   * the callee side after the link is garbled
   *
   * @param num
   * @return std::vector<Word>
   */
  std::vector<Word> retrieve_callee_words(uint64_t num);

  /**
   * Should be called after all the callee words are retrieved to save memory
   */
  void clear_callee_words();

  /**
   * @brief Called by the evaluator to translate words between the caller and
   * callee gadgets. Should be called only when the link is active.
   *
   * @param input
   * @return std::vector<Word>
   */
  std::vector<Word> translate(const std::vector<Word>& input) override;

  /**
   * @brief Garble the link for T timesteps, and compute the SIMD labels for
   * each timestamp of the callee gadget
   *
   * @param gc_begin the starting GCPtr
   * @return GCPtr the ending GCPtr
   */
  GCPtr garble(const GCPtr& gc_begin) override;
};

/**
 * @brief A SIMD link is used when the call may be real or fake (inactive).
 * The SIMD link leverages the optimized stack in PicoGRAM.
 *
 */
struct SIMDLink : BaseConditionalLink {
 private:
  BigInt relative_label;  // used by the evaluator to cache the relative label
  // between the parent and child at the current timestamp
  BigInt inv_relative_label;  // the inverse of relative label, used to
                              // translate SIMD words from callee to caller
                              // timezone more efficiently
  // used by the garbler to store random labels for each timestamp.
  // before the link is garbled, the labels are for the caller;
  // after the link is garbled, the labels are for the callee
  std::vector<BigInt> simd_labels;

 public:
  /**
   * @brief Construct a new SIMDLink object
   *
   * @param callee the callee gadget
   * @param T the number of timestamps
   */
  explicit SIMDLink(Gadget* callee);

  /**
   * @brief For the garbler, either set a new caller label and update the prefix
   * sum, or do nothing if caller has updated the link at the same timestamp.
   * For the evaluator, update the prefix sum. If the control bit is 0, update
   * the relative label for translation.
   *
   * @param control the control bit, 0 for real call, 1 for fake call
   * @param caller_label the label of the caller at the current timestamp (only
   * used in GARBLE mode)
   * @return true if control is 0 or in GARBLE mode
   * @return false otherwise
   */
  bool update_link(const Bit& control, const BigInt& caller_label = BigInt());

  /**
   * @brief Garble the link for T timesteps, and compute the SIMD labels for
   * each timestamp of the callee gadget
   *
   * @param gc_begin the starting GCPtr
   * @return GCPtr the ending GCPtr
   */
  GCPtr garble(const GCPtr& gc_begin) override;

  /**
   * @brief Translate a SIMDWord from the caller timezone to the callee
   * timezone, or in reverse.
   *
   * @param input the SIMDWord of the input timezone (either caller or callee)
   * @return SIMDWord the SIMDWord in the output timezone
   */
  std::vector<SIMDWord> translate(const std::vector<SIMDWord>& inputs) override;

  const BigInt& get_simd_label(uint64_t t) {
    Assert(t < simd_labels.size());
    return simd_labels[t];
  }

  // release the heap resources
  void release() { clear_and_release(simd_labels); }

  ~SIMDLink() {}
};
}  // namespace PicoGRAM
