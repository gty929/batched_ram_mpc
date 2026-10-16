#include "func.hpp"

#include "gadget_group.hpp"
#include "link.hpp"
#include "simd_word.hpp"
namespace PicoGRAM {
LinkType FuncType::get_link_type() const {
  Assert(owner);
  return owner->get_link_type();
}

SIMDFunc::SIMDFunc(
    Gadget* owner,
    const std::function<std::vector<SIMDWord>(const std::vector<SIMDWord>&)>&
        func,
    const std::vector<uint>& out_widths, const std::string& name)
    : FuncType(owner, out_widths, name), func(func) {
  Assert(owner);
  owner->register_func(this);
}

SIMDLink* SIMDFunc::get_simd_link() const {
  return get_owner()->get_simd_link();
}

Gadget* FuncType::get_caller() const {
  return owner->get_caller() ? owner->get_caller() : owner;
}

void SIMDFunc::exec(const Bit& control, SIMDFuncInput inputs,
                    SIMDFuncOutput& outputs) {
  // we require at least one input to the function to determine the output
  // bitoffset
  Assert(!inputs.empty() || out_widths.empty());

  Assert(get_caller()->get_mode() == get_mode());
  Gadget* caller = get_caller();

  Assert(caller == control.get_owner());
  for (const SIMDWord& input : inputs) {
    Assert_eq(caller->get_name(), input.get_owner()->get_name());
    Assert(caller == input.get_owner());
  }

  Assert(!inputs.empty());
  Assert(get_simd_link());

  if (get_mode() == GARBLE || get_mode() == MEASURE) {
    uint64_t caller_time = get_caller()->get_time();
    if (caller_time != caller_last_time) {
      caller_last_time = caller_time;
      called_count = 0;
    }
    if (caller_time == 0) {
      // first time step, add the function to the garble list
      owner->add_func_to_garble(this);
      Assert_eq(in_widths.size(), called_count);
      // record the input info
      in_widths.push_back({});
      in_pub_es.push_back({});
      in_bit_offsets.push_back({});
      in_shifts.push_back({});
      for (const auto& input : inputs) {
        in_widths[called_count].push_back(input.width());
        in_pub_es[called_count].push_back(input.pub_es);
        in_bit_offsets[called_count].push_back(input.bit_offset);
        in_shifts[called_count].push_back(input.shift);
      }
    } else {
      // check the input info matches the previous calls
      Assert_eq(inputs.size(), in_widths[called_count].size());
      Assert_eq(inputs.size(), in_pub_es[called_count].size());
      for (uint i = 0; i < inputs.size(); ++i) {
        if (inputs[i].width() != in_widths[called_count][i]) {
          std::cerr << "Input width mismatch for function " << get_name()
                    << " input offset " << i << std::endl;
        }
        Assert_eq(inputs[i].width(), in_widths[called_count][i]);
        Assert_eq(inputs[i].shift, in_shifts[called_count][i]);
        if (get_mode() == GARBLE) {
          Assert_eq(inputs[i].bit_offset, in_bit_offsets[called_count][i]);
        }
        for (uint j = 0; j < inputs[i].width(); ++j) {
          if (inputs[i].pub_es[j] != in_pub_es[called_count][i][j]) {
            std::cerr << "Input pub_e mismatch for function " << get_name()
                      << " input offset " << i << " bit offset " << j
                      << std::endl;
          }
          Assert_eq(inputs[i].pub_es[j], in_pub_es[called_count][i][j]);
        }
      }
    }
    ++called_count;

    const BigInt& in_simd_label = inputs[0].label;

    // check the input labels match each other
    if (get_mode() == GARBLE) {
      Assert(in_simd_label.is_set());
      for (const SIMDWord& input : inputs) {
        Assert_eq(input.label, in_simd_label);
      }
    }
    Assert(get_simd_link());

    // update the SIMD link
    get_simd_link()->update_link(control, in_simd_label);
    uint output_begin_offset =
        inputs.empty() ? 0 : inputs.back().bit_offset + inputs.back().width();
    uint output_offset = output_begin_offset;
    // mock the output
    outputs.reserve(out_widths.size());
    for (uint out_width : out_widths) {
      outputs.emplace_back(caller, out_width, output_offset, in_simd_label);
      output_offset += out_width;
    }

  } else if (get_mode() == EVAL || get_mode() == DEBUG) {
    bool active = get_simd_link()->update_link(control);
    if (active) {
      const std::vector<SIMDWord>& child_inputs =
          get_simd_link()->translate(inputs);
      // make the function call
      const std::vector<SIMDWord>& child_outputs = func(child_inputs);
      Assert_eq(child_outputs.size(), out_widths.size());

      // translate the outputs back
      for (uint i = 0; i < out_widths.size(); ++i) {
        Assert_eq(child_outputs[i].width(), out_widths[i]);
      }

      outputs = get_simd_link()->translate(child_outputs);

    } else {
      // call is fake, return dummy outputs
      outputs.reserve(out_widths.size());
      std::transform(out_widths.begin(), out_widths.end(),
                     std::back_inserter(outputs),
                     [&](uint out_width) -> SIMDWord {
                       return SIMDWord(caller, out_width, 0, BigInt());
                     });
    }
  }
}

std::vector<SIMDWord> SIMDFunc::operator()(
    const Bit& control, const std::vector<SIMDWord>& inputs) {
  SIMDFuncOutput outputs;
  exec(control, inputs, outputs);
  return outputs;
}

void SIMDFunc::garble() {
  if (get_owner()->get_time() != callee_last_time) {
    // new time step, reset the called count
    callee_last_time = get_owner()->get_time();
    called_count = 0;
  }
  std::vector<SIMDWord> callee_inputs;
  if (!in_widths.empty()) {
    callee_inputs.reserve(in_widths[called_count].size());
    for (uint i = 0; i < in_widths[called_count].size(); ++i) {
      callee_inputs.emplace_back(get_owner(), in_widths[called_count][i],
                                 in_bit_offsets[called_count][i],
                                 owner->get_simd_label(),
                                 in_pub_es[called_count][i]);
      callee_inputs.back() >>= in_shifts[called_count][i];
    }
  }
  ++called_count;
  func(callee_inputs);  // we can safely ignore the output since it has been
                        // mocked
}

Func::Func(Gadget* owner, const std::function<FuncOutput(FuncInput)>& func,
           const std::vector<uint>& out_widths, const std::string& name)
    : FuncType(owner, out_widths, name), original_func(func) {
  LinkType link_type = get_link_type();
  if (name == "main") {
    // add main function to the registry
    // other functions are added while garbling
    owner->add_func_to_garble(this);
  }
  if (link_type == SIMD_COND) {
    simd_func = new SIMDFunc(  // create a SIMDFunc that wraps the func
        owner,
        [=](const std::vector<SIMDWord>& simd_inputs) {
          std::vector<Word> inputs = SIMDWord::to_words(simd_inputs);

          std::vector<Word> outputs = func(inputs);
          Assert(outputs.size() == out_widths.size());
          uint64_t output_begin_offset =
              simd_inputs.empty()
                  ? 0
                  : simd_inputs.back().bit_offset + simd_inputs.back().width();
          // temporarily rewind the bit offset to output to the parent
          std::vector<SIMDWord> simd_outputs =
              SIMDWord::from_words(outputs, output_begin_offset);
          // restore the bit offset
          return simd_outputs;
        },
        out_widths, name);
  } else {
    owner->register_func(this);
  }
}

void Func::operator()() {
  Assert_eq(get_name(), "main");
  get_owner()->inc_time();
  original_func({});
}

FuncOutput Func::operator()(const Bit& control, FuncInput inputs) {
  FuncOutput outputs;
  LinkType link_type = get_link_type();
  if (link_type == DIRECT || link_type == COND) {
    if (get_mode() == GARBLE || get_mode() == MEASURE) {
      outputs.resize(out_widths.size());
      for (uint i = 0; i < out_widths.size(); ++i) {
        outputs[i] = Word::rand_label_word(get_caller(), out_widths[i]);
      }
    }
  }
  exec(control, inputs, outputs);
  return outputs;
}

void Func::exec(const Bit& control, FuncInput inputs, FuncOutput& outputs) {
  LinkType link_type = get_link_type();
  if (link_type == NONE) {
    Assert(outputs.empty());
    outputs = original_func(inputs);
    return;
  }

  if (link_type == DIRECT || link_type == COND) {
    BaseLink* base_link = get_owner()->get_base_link();
    bool is_active = true;
    if (link_type == COND) {
      is_active = dynamic_cast<Link*>(base_link)->update_link(control);
    }

    if (get_mode() == GARBLE || get_mode() == MEASURE) {
      bool add_to_garble_flag =
          link_type == DIRECT ? !owner->get_time() : !get_caller()->get_time();
      if (add_to_garble_flag) {
        // first time step, add the function to the garble list
        owner->add_func_to_garble(this);
      }
      Assert_eq(outputs.size(), out_widths.size());
      for (uint64_t i = 0; i < out_widths.size(); ++i) {
        Assert_eq(outputs[i].width(), out_widths[i]);
      }

      if (link_type == DIRECT) {
        if (get_mode() == GARBLE) {
          in_words.push_back(inputs);
          out_words.push_back(outputs);
        } else {
          Assert_eq(get_mode(), MEASURE);
          // measure mode, record the meta data
          std::vector<WordMetaData> in_meta_data;
          std::vector<WordMetaData> out_meta_data;
          in_meta_data.reserve(inputs.size());
          out_meta_data.reserve(outputs.size());
          for (const Word& input : inputs) {
            in_meta_data.emplace_back(WordMetaData::from_word(input));
          }
          for (const Word& output : outputs) {
            out_meta_data.emplace_back(WordMetaData::from_word(output));
          }
          in_words_meta_data.push_back(in_meta_data);
          out_words_meta_data.push_back(out_meta_data);
        }
      } else {
        input_sizes.push_back(inputs.size());
        Link* link = dynamic_cast<Link*>(base_link);
        link->add_caller_words(inputs);
        link->add_caller_words(outputs);
      }
    } else if (get_mode() == EVAL || get_mode() == DEBUG) {
      if (!is_active) {
        Assert(outputs.empty());
        // the call is fake, return dummy outputs
        outputs.reserve(out_widths.size());
        for (uint out_width : out_widths) {
          outputs.emplace_back(get_caller(), out_width);
          outputs.back().set_pub_e(false);
          outputs.back().set_pub_g(false);
        }
        return;
      }
      const std::vector<Word>& child_inputs = base_link->translate(inputs);
      FuncOutput child_output = original_func(child_inputs);
      for (Word& output_word : child_output) {
        output_word.set_pub_e(false);
        output_word.set_pub_g(false);
      }
      Assert_eq(child_output.size(), out_widths.size());
      FuncOutput output_after_join;
      output_after_join.reserve(out_widths.size());
      for (uint i = 0; i < out_widths.size(); ++i) {
        Word output_word(owner, out_widths[i]);
        Assert(child_output[i].width() <= out_widths[i]);
        if (child_output[i].width() == out_widths[i]) {
          Word::join(child_output[i], output_word);
        } else {
          Word::join(child_output[i].slice(out_widths[i]), output_word);
        }
        output_after_join.emplace_back(output_word);
      }
      Assert(outputs.empty());
      outputs = base_link->translate(output_after_join);
    }
  } else {
    Assert_eq(link_type, SIMD_COND);
    std::vector<SIMDWord> simd_inputs =
        SIMDWord::from_words(inputs, get_caller()->get_bit_offset());
    uint64_t sum_input_width = Word::sum_width(inputs);
    get_caller()->inc_bit_offset(sum_input_width);
    Assert(simd_func);
    std::vector<SIMDWord> simd_outputs = (*simd_func)(control, simd_inputs);
    Assert(outputs.empty());
    outputs = SIMDWord::to_words(simd_outputs);
  }
}

FuncOutput Func::operator()(FuncInput inputs) {
  Assert(get_link_type() == NONE || get_link_type() == DIRECT);
  return operator()(Bit::constant(get_caller(), 0), inputs);
}

void Func::garble() {
  if (get_link_type() == NONE) {
    Assert_eq(get_name(), "main");
    original_func({});
    return;
  }
  if (get_link_type() == SIMD_COND) {
    Assert(simd_func);
    simd_func->garble();
    return;
  }
  FuncOutput original_outputs;
  FuncOutput mocked_child_outputs;
  if (get_link_type() == COND) {
    Link* link = get_owner()->get_link();
    Assert(link);
    Assert(link->is_garbled());
    FuncInput inputs = link->retrieve_callee_words(input_sizes[garble_counter]);
    original_outputs = original_func(inputs);
    mocked_child_outputs = link->retrieve_callee_words(out_widths.size());
    for (uint i = 0; i < out_widths.size(); ++i) {
      Assert_eq(out_widths[i], mocked_child_outputs[i].width());
    }
  } else if (get_link_type() == DIRECT) {
    DirectLink* link = get_owner()->get_direct_link();
    if (get_mode() == GARBLE) {
      Assert(garble_counter < in_words.size());
      FuncInput inputs = link->translate(in_words[garble_counter]);
      original_outputs = original_func(inputs);
      mocked_child_outputs = link->translate(out_words[garble_counter]);
    } else {
      Assert_eq(get_mode(), MEASURE);
      Assert_less(garble_counter, in_words_meta_data.size());
      in_words.resize(1);
      in_words[0].clear();
      in_words[0].reserve(in_words_meta_data[garble_counter].size());
      for (const WordMetaData& meta_data : in_words_meta_data[garble_counter]) {
        in_words[0].emplace_back(meta_data.to_word());
      }
      FuncInput inputs = link->translate(in_words[0]);
      original_outputs = original_func(inputs);

      out_words.resize(1);
      out_words[0].clear();
      out_words[0].reserve(out_words_meta_data[garble_counter].size());
      for (const WordMetaData& meta_data :
           out_words_meta_data[garble_counter]) {
        out_words[0].emplace_back(meta_data.to_word());
      }
      mocked_child_outputs = link->translate(out_words[0]);
    }
  }
  Assert_eq(original_outputs.size(), mocked_child_outputs.size());
  for (uint i = 0; i < original_outputs.size(); ++i) {
    Assert_eq(original_outputs[i].get_owner(), get_owner());
    Word& mocked_child_output = mocked_child_outputs[i];
    Assert(original_outputs[i].width() <= mocked_child_output.width());
    if (original_outputs[i].width() == mocked_child_output.width()) {
      Word::join(original_outputs[i], mocked_child_output);
    } else {
      Word::join(original_outputs[i].slice(mocked_child_output.width()),
                 mocked_child_output);
    }
  }
  ++garble_counter;
  uint64_t max_garble_counter =
      get_link_type() == COND
          ? input_sizes.size()
          : std::max(in_words.size(), in_words_meta_data.size());
  if (garble_counter == max_garble_counter) {
    clear_and_release(in_words);
    clear_and_release(out_words);
    clear_and_release(input_sizes);
    clear_and_release(in_words_meta_data);
    clear_and_release(out_words_meta_data);
    if (get_link_type() == COND) {
      get_owner()->get_link()->clear_callee_words();
    }
  }
  return;
}
}  // namespace PicoGRAM