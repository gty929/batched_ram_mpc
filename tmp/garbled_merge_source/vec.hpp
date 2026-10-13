#pragma once
#include <vector>

#include "word.hpp"

namespace PicoGRAM {
struct Vec : DataType {
 private:
  std::vector<Word> data;
  Word read_internal(const Word& index, uint64_t begin_offset,
                     uint64_t end_offset) const {
    if (end_offset - begin_offset == 1) {
      return data[begin_offset];
    }
    uint width = log2ceil(end_offset - begin_offset);
    uint64_t mid_offset = begin_offset + (1UL << (width - 1));
    const Word& left = read_internal(index, begin_offset, mid_offset);
    const Word& right = read_internal(index, mid_offset, end_offset);
    return Word::mux(index[width - 1], left, right);
  }

  void write_internal(const Word& index, uint64_t begin_offset,
                      uint64_t end_offset, Word& new_data,
                      const Bit& real_flag) {
    if (end_offset - begin_offset == 1) {
      Word::cond_swap(real_flag, data[begin_offset], new_data);
      return;
    }
    uint width = log2ceil(end_offset - begin_offset);
    uint64_t mid_offset = begin_offset + (1UL << (width - 1));
    write_internal(index, begin_offset, mid_offset, new_data,
                   real_flag & !index[width - 1]);
    write_internal(index, mid_offset, end_offset, new_data,
                   real_flag & index[width - 1]);
  }

#ifdef FAST_MEASURE
  void mock_write_internal_controls(const Word& index, uint64_t begin_offset,
                                    uint64_t end_offset, const Bit& real_flag) {
    if (end_offset - begin_offset == 1) {
      return;
    }
    uint width = log2ceil(end_offset - begin_offset);
    uint64_t mid_offset = begin_offset + (1UL << (width - 1));
    mock_write_internal_controls(index, begin_offset, mid_offset,
                                 real_flag & !index[width - 1]);
    mock_write_internal_controls(index, mid_offset, end_offset,
                                 real_flag & index[width - 1]);
  }
#endif

 public:
  Vec(Gadget* owner, uint len)
      : DataType(owner), data(len, Word::constant(owner, 0, (uint64_t)0)) {}

  void set_word(uint index, const Word& word) {
    Assert(index < data.size());
    data[index] = word;
  }

  void init_ram_g(const std::vector<std::vector<bool>>& data, uint word_width) {
    Assert_eq(data.size(), this->data.size());
    for (uint i = 0; i < data.size(); ++i) {
      this->data[i] = Word::input_g(get_owner(), word_width, data[i]);
    }
  }

  const Word& get_word(uint index) const {
    Assert(index < data.size());
    return data[index];
  }

  const Word& operator[](uint index) const { return get_word(index); }

  Word read(const Word& index) const {
    return read_internal(index, 0, data.size());
  }

  Word write(const Word& index, const Word& new_data, const Bit& real_flag) {
    Word new_data_copy = new_data;
#ifdef FAST_MEASURE
    if (get_mode() == MEASURE && get_owner()->get_time() > 1) {
      if (data.size() > 1) {
        uint64_t begin_gc_offset = get_owner()->get_gc().get_offset();
        write_internal(index, 0, 1, new_data_copy, index[0]);

        uint64_t end_gc_offset = get_owner()->get_gc().get_offset();
        uint64_t gc_cost_per_index = end_gc_offset - begin_gc_offset;
        get_owner()->get_gc().skip_data(gc_cost_per_index * (data.size() - 1));
        mock_write_internal_controls(index, 0, data.size(), real_flag);
        return new_data_copy;
      }
    }
#endif

    write_internal(index, 0, data.size(), new_data_copy, real_flag);
    return new_data_copy;
  }

  Word write(const Word& index, const Word& new_data) {
    return write(index, new_data, Bit::constant(get_owner(), 1));
  }

  uint size() const { return data.size(); }
};
}  // namespace PicoGRAM