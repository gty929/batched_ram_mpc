#pragma once
#include "func.hpp"
#include "gadget.hpp"

namespace PicoGRAM {

template <typename GadgetType, typename... Args>
struct Group;

/**
 * @brief A reference to a callee gadget in a group. The group entry can be
 * reused for multiple calls to the same gadget at each timestep. A typical use
 * case is to call functions of the sub-tree corresponding to the path in a
 * circuit ORAM tree. Note that the counters of all the gadgets in the group are
 * updated at each timestep, while only the function of the selected gadget is
 * called.
 *
 * @tparam GadgetType
 * @tparam Args
 */
template <typename GadgetType, typename... Args>
struct GroupEntry {
 private:
  Word selector;  // the index of the gadget to call
  Group<GadgetType, Args...>* gadget_group_ptr = NULL;

  /**
   * @brief Helper function for calling a gadget in the group
   *
   * @tparam WordType_ could be Word or SIMDWord
   * @tparam FuncType_ could be Func or SIMDFunc
   * @param aggregated_outputs for the garbler, the output languages are the
   * same for all the gadgets, so the aggregated_outputs are set by gadget with
   * index 0. for the evaluator, the aggregated_outputs are set by the gadget
   * that actually gets selected.
   * @param i the index of the selected gadget
   * @param func the function to be called in the gadget
   * @param inputs the input words or simd-words to the function
   * @param predefined_outputs in garble mode, when the link the non-simd, the
   * predefined outputs should be specified so that all gadgets in the group can
   * share the same output language
   */
  template <typename WordType_, typename FuncType_>
  void call_internal(std::vector<WordType_>& aggregated_outputs, uint i,
                     FuncType_& func, const std::vector<WordType_>& inputs,
                     const std::vector<WordType_>& predefined_outputs = {}) {
    Word index = Word::constant(selector.get_owner(), selector.width(),
                                reverse_bits(i, selector.width()));
    Assert_eq(index.width(), selector.width());
    Bit is_selected = (selector == index);
    Bit is_selected_revealed = is_selected.reveal();
    uint8_t is_selected_val = is_selected_revealed.to_int();
    std::vector<WordType_> outputs = predefined_outputs;
    func.exec(!is_selected_revealed, inputs, outputs);
    Mode mode = selector.get_mode();
    // for garble mode, the output labels of all the gadgets are the same,
    // so we simply use the first one (i = 0)
    bool to_aggregate =
        (mode == EVAL || mode == DEBUG) ? is_selected_val : i == 0;
    if (to_aggregate) {
      // update the aggregated outputs
      std::swap(aggregated_outputs, outputs);
    }
  }

  /**
   * @brief Call a non-simd function
   *
   * @param func_name name of the function
   * @param inputs input words
   * @return std::vector<Word> output words
   */
  std::vector<Word> call_non_simd(const std::string& func_name,
                                  FuncInput inputs) {
    std::vector<Word> aggregated_outputs;
    std::vector<Word> predefined_outputs;
    Mode mode = selector.get_mode();
    for (uint64_t i = 0; i < gadget_group_ptr->num_children(); ++i) {
      FuncType* sub_func_base_ptr =
          gadget_group_ptr->get_child(i)->get_func_by_name(func_name);
      Assert(sub_func_base_ptr);
      Func* sub_func = dynamic_cast<Func*>(sub_func_base_ptr);
      Assert(sub_func);
      if (i == 0 && (mode == GARBLE || mode == MEASURE)) {
        const std::vector<uint>& out_widths = sub_func->get_out_widths();
        for (uint width : out_widths) {
          predefined_outputs.emplace_back(
              Word::rand_label_word(selector.get_owner(), width));
        }
      }
      call_internal(aggregated_outputs, i, *sub_func, inputs,
                    predefined_outputs);
    }
    return aggregated_outputs;
  }

 public:
  GroupEntry() {}
  GroupEntry(const Word& selector, Group<GadgetType, Args...>& gadget_group)
      : selector(selector), gadget_group_ptr(&gadget_group) {}

  /**
   * @brief Call a simd function
   *
   * @param func_name the name of the function
   * @param simd_inputs the input SIMD words
   * @return std::vector<SIMDWord> the output SIMD words
   */
  std::vector<SIMDWord> call_simd(const std::string& func_name,
                                  SIMDFuncInput simd_inputs) {
    std::vector<SIMDWord> aggregated_simd_outputs;

    Gadget* caller = selector.get_owner();
    uint64_t curr_bit_offset = caller->get_bit_offset();
    for (uint64_t i = 0; i < gadget_group_ptr->num_children(); ++i) {
      Assert_eq(caller->get_bit_offset(), curr_bit_offset);
      caller->set_bit_offset(curr_bit_offset);
      FuncType* sub_func_base_ptr =
          gadget_group_ptr->get_child(i)->get_func_by_name(func_name);
      Assert(sub_func_base_ptr);
      SIMDFunc* sub_func = dynamic_cast<SIMDFunc*>(sub_func_base_ptr);
      Assert(sub_func);
      call_internal(aggregated_simd_outputs, i, *sub_func, simd_inputs);
    }
    return aggregated_simd_outputs;
  }

  /**
   * @brief Call a function of the selected gadget in the group. The function
   * must be registered to the gadget. If the link is SIMD, the words are
   * converted to SIMD words and the call_simd function is invoked.
   *
   * @param func_name the name of the function
   * @param inputs the inputs to the function (owned by the caller)
   * @return std::vector<Word> the outputs of the function (owned by the caller)
   */
  std::vector<Word> call(const std::string& func_name, FuncInput inputs) {
    if (gadget_group_ptr->get_link_type() == SIMD_COND) {
      Gadget* caller = selector.get_owner();
      SIMDFuncInput simd_inputs =
          SIMDWord::from_words(inputs, caller->get_bit_offset());
      uint64_t sum_output_width = Word::sum_width(inputs);
      caller->inc_bit_offset(sum_output_width);
      const std::vector<SIMDWord>& aggregated_simd_outputs =
          call_simd(func_name, simd_inputs);
      return SIMDWord::to_words(aggregated_simd_outputs);
    } else {
      return call_non_simd(func_name, inputs);
    }
  }
};

/**
 * @brief A data structure that groups a number of gadgets together, with one
 * of the gadgets being called at every timestep. A typical use case is to group
 * the sub-trees of a circuit ORAM tree.
 *
 * @tparam GadgetType
 * @tparam Args
 */
template <typename GadgetType, typename... Args>
struct Group {
 private:
  std::vector<GadgetType*> gadgets;  // the gadgets in the group
  uint64_t simd_threshold_T;
  LinkType link_type = NONE;

 public:
  /**
   * @brief Construct a new Group object
   *
   * @param caller the caller gadget
   * @param num_gadgets the number of gadgets in the group
   * @param child_T_calculator a function that calculates the maximum number of
   * timestamps the child gadget can run, assuming the parent gadget runs for
   * T_parent timesteps. This allows the garbler to provision the correct number
   * of GC circuitry for the child gadgets. If the output of the function is
   * greater than the number of timesteps the parent gadget runs, the child
   * gadget will run for the maximum number of timesteps the parent gadget runs.
   * @param args Additional arguments to pass to the constructor of the child
   */
  Group(Gadget* caller, const std::vector<uint64_t>& T_children, Args... args)
      : Group(caller, T_children, 0, args...) {}

  Group(Gadget* caller, const std::vector<uint64_t>& T_children,
        uint64_t simd_threshold_T, Args... args)
      : simd_threshold_T(simd_threshold_T) {
    uint64_t num_gadgets = T_children.size();
    gadgets.reserve(num_gadgets);
    link_type = COND;
#ifdef FAST_MEASURE
    if (caller->get_measure_multiplier() == 0) {
      Assert_eq(caller->get_mode(), MEASURE);
      return;
    }
    if (caller->get_mode() == MEASURE) {
      // check if T_children are all the same
      uint64_t T0 = T_children[0];
      bool fast_measure_flag =
          std::all_of(T_children.begin(), T_children.end(),
                      [T0](uint64_t T) { return T == T0; });
      if (fast_measure_flag) {
        for (uint64_t i = 0; i < num_gadgets; ++i) {
          gadgets.push_back(new GadgetType(caller, link_type, T_children[i],
                                           i == 0 ? num_gadgets : 0, args...));
        }
        return;
      }
    }
    for (uint64_t i = 0; i < num_gadgets; ++i) {
      gadgets.push_back(
          new GadgetType(caller, link_type, T_children[i], 1, args...));
    }
#else
    for (uint64_t i = 0; i < num_gadgets; ++i) {
      gadgets.push_back(
          new GadgetType(caller, link_type, T_children[i], args...));
    }
#endif
  }

  /**
   * @brief Get a GroupEntry object that references the gadget at the given
   * index
   *
   * @param index
   * @return GroupEntry<GadgetType, Args...>
   */
  GroupEntry<GadgetType, Args...> operator[](const Word& index) {
    return GroupEntry<GadgetType, Args...>(index, *this);
  }

  /**
   * @brief Number of children (callee) gadgets in the group
   *
   * @return uint64_t
   */
  uint64_t num_children() const { return gadgets.size(); }

  /**
   * @brief Get the i-th child (callee) gadget in the group
   *
   * @param i
   * @return GadgetType*
   */
  GadgetType* get_child(uint64_t i) const { return gadgets[i]; }

  LinkType get_link_type() const { return link_type; }

  ~Group() {
    for (GadgetType* gadget : gadgets) {
      if (gadget) {
        delete gadget;
      }
    }
  }
};
}  // namespace PicoGRAM
