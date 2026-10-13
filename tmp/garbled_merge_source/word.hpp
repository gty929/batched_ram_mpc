#pragma once
#include <algorithm>
#include <vector>

#include "bit.hpp"

namespace PicoGRAM {
/**
 * @brief A data type that represents a word, which is a sequence of bits. A
 * word < 64 bits can also represent an unsigned integer.
 *
 */
struct Word : DataType {
 private:
  std::vector<Bit> bits;  // the bits of the word, bits[0] is the least
                          // significant bit

  // the maximum value of the word when treated as an unsigned integer
  // it helps determine the width of the output word for operations like
  // addition. If max_value is UINT64_MAX, the value is not limited. Notice that
  // the max value has to be agreed by both the garbler and the evaluator
  uint64_t max_value = 0;

  /**
   * @brief A helper function to get the maximum value of a word with a given
   * width
   *
   * @param width the width of the word
   * @param max_value (optional) an upper bound of the value
   * @return constexpr uint64_t
   */
  static constexpr uint64_t default_max_value(uint width,
                                              uint64_t max_value = UINT64_MAX) {
    return width <= 64 ? std::min(max_value, (1UL << width) - 1) : max_value;
  }

 public:
  Word() {}

  /**
   * @brief Construct a new Word object
   *
   * @param owner owner gadget
   * @param len the width of the word
   * @param max_value (optional) the maximum value of the word
   */
  Word(Gadget* owner, uint len, uint64_t max_value = UINT64_MAX)
      : DataType(owner),
        bits(len, Bit::constant(owner, 0)),
        max_value(default_max_value(len, max_value)) {}

  explicit Word(const Bit& bit) : DataType(bit.get_owner()), bits({bit}) {
    max_value = 1;
  }

  /**
   * @brief Construct a Word representing a constant value
   *
   * @param owner owner gadget
   * @param len the width of the word
   * @param value the constant value in integer
   * @return Word
   */
  static Word constant(Gadget* owner, uint len, uint64_t value) {
    Word word(owner, len);
    for (uint i = 0; i < len; ++i) {
      word.bits[i] = Bit::constant(owner, (value >> i) & 1);
    }
    word.max_value = value;

    return word;
  }

  /**
   * @brief Construct a Word representing a constant value
   *
   * @param owner owner gadget
   * @param len the width of the word
   * @param data the constant value in bytes, note that each byte of data is
   * converted to one bit in Word.
   * @return Word
   */
  static Word constant(Gadget* owner, uint len, const uint8_t* data) {
    Word word(owner, len);
    for (uint i = 0; i < len; ++i) {
      word.bits[i] = Bit::constant(owner, data[i]);
    }
    if (len <= 64) {
      for (uint i = 0; i < len; ++i) {
        word.max_value <<= 1;
        word.max_value |= data[i];
      }
    } else {
      word.max_value = UINT64_MAX;
    }

    return word;
  }

  /**
   * @brief Construct a Word representing a constant value
   *
   * @param owner owner gadget
   * @param len the width of the word
   * @param data the constant value
   * @return Word
   */
  static Word constant(Gadget* owner, uint len, const std::vector<bool>& data) {
    Word word(owner, len);
    for (uint i = 0; i < len; ++i) {
      word.bits[i] = Bit::constant(owner, data[i]);
    }
    word.max_value = UINT64_MAX;
    return word;
  }

  /**
   * @brief Construct a Word carrying a value known to the garbler
   *
   * @param owner owner gadget
   * @param len the width of the word
   * @param data the value in integer
   * @return Word
   */
  static Word input_g(Gadget* owner, uint len, uint64_t data) {
    Word word(owner, len);
    for (uint i = 0; i < len; ++i) {
      word.bits[i] = Bit::input_g(owner, (data >> i) & 1);
    }
    word.max_value = data;
    return word;
  }

  /**
   * @brief Construct a Word carrying a value known to the garbler
   *
   * @param owner owner gadget
   * @param len the width of the word
   * @param data the value in bytes, note that each byte of data is converted
   * to one bit in Word.
   * @return Word
   */
  static Word input_g(Gadget* owner, uint len, const uint8_t* data) {
    Word word(owner, len);
    for (uint i = 0; i < len; ++i) {
      word.bits[i] = Bit::input_g(owner, data[i]);
    }
    word.max_value = UINT64_MAX;
    return word;
  }

  /**
   * @brief Construct a Word carrying a value known to the garbler
   *
   * @param owner owner gadget
   * @param len the width of the word
   * @param data the value
   * @return Word
   */
  static Word input_g(Gadget* owner, uint len, const std::vector<bool>& data) {
    Word word(owner, len);
    for (uint i = 0; i < len; ++i) {
      uint8_t val = i < data.size() ? data[i] : 0;
      word.bits[i] = Bit::input_g(owner, val);
    }
    word.max_value = UINT64_MAX;
    return word;
  }

  /**
   * @brief Construct a Word carrying a value provided by the evaluator for
   * debugging
   *
   * @param owner owner gadget
   * @param len the width of the word
   * @param data the value in integer
   * @return Word
   */
  static Word input_dbg(Gadget* owner, uint len, uint64_t data) {
    Word word(owner, len);
    for (uint i = 0; i < len; ++i) {
      word.bits[i] = Bit::input_dbg(owner, (data >> i) & 1);
    }
    word.max_value = default_max_value(len);
    return word;
  }

  bool is_pub_g() const {
    return std::all_of(bits.begin(), bits.end(),
                       [](const Bit& bit) { return bit.is_pub_g(); });
  }

  bool is_pub_e() const {
    return std::all_of(bits.begin(), bits.end(),
                       [](const Bit& bit) { return bit.is_pub_e(); });
  }

  void set_pub_g(bool pub_g) {
    for (Bit& bit : bits) {
      bit.set_pub_g(pub_g);
    }
  }

  void set_pub_e(bool pub_e) {
    for (Bit& bit : bits) {
      bit.set_pub_e(pub_e);
    }
  }

  void skip() {
    for (Bit& bit : bits) {
      bit.skip();
    }
  }

  bool is_skip() const {
    return std::all_of(bits.begin(), bits.end(),
                       [](const Bit& bit) { return bit.is_skip(); });
  }

  /**
   * @brief Construct a Word carrying a value provided by the evaluator for
   * debugging
   *
   * @param owner owner gadget
   * @param len the width of the word
   * @param data the value in bytes, note that each byte of data is converted
   * to one bit in Word.
   * @return Word
   */
  static Word input_dbg(Gadget* owner, uint len, const uint8_t* data) {
    Word word(owner, len);
    for (uint i = 0; i < len; ++i) {
      word.bits[i] = Bit::input_dbg(owner, data[i]);
    }
    word.max_value = default_max_value(len);
    return word;
  }

  /**
   * @brief Create a word with random labels.
   *
   * @param owner the owner gadget
   * @param len the length of the word
   * @return Word
   */
  static Word rand_label_word(Gadget* owner, uint len) {
    Word word(owner, len);
    for (uint i = 0; i < len; ++i) {
      word.bits[i] = Bit::rand_label_bit(owner);
    }
    return word;
  }

  /**
   * @brief Translate a word src to a word dst. In garble mode, both the src and
   * dst label need to be set. In eval mode, the src bit is converted to the dst
   * bit. A usecase is to break down a circuit into multiple sub-circuits to
   * garble, and use join between sub-circuits to connect them.
   * Incurs lambda bits of communication per bit.
   *
   * @param src the word to be translated from
   * @param dst the word to be translated to
   */
  static void join(const Word& src, Word& dst) {
    Assert_eq(src.get_owner(), dst.get_owner());
    Assert_eq(src.width(), dst.width());
    for (uint i = 0; i < src.width(); ++i) {
      Bit::join(src.bits[i], dst.bits[i]);
    }
  }

  /**
   * @brief convert the word to a hexidecimal string
   *
   * @return std::string
   */
  std::string to_hex_str() const {
    // output hexidecimal
    std::stringstream hexStream;
    int bitCount = 0;
    unsigned char byte = 0;

    for (const Bit& bit : bits) {
      // Set the bit in reverse order within the byte (LSB at offset 0)
      if (bit.to_int()) {
        byte |= (1 << (bitCount % 8));
      }

      ++bitCount;

      // When we've accumulated 8 bits, convert to hex
      if (bitCount % 8 == 0) {
        hexStream << std::hex << std::setw(2) << std::setfill('0')
                  << static_cast<int>(byte);
        byte = 0;  // Reset byte for the next 8 bits
      }
    }

    // Handle the remaining bits (if not a multiple of 8)
    if (bitCount % 8 != 0) {
      hexStream << std::hex << std::setw(2) << std::setfill('0')
                << static_cast<int>(byte);
    }

    return hexStream.str();
  }

  /**
   * @brief convert the word to an integer
   *
   * @return uint64_t
   */
  uint64_t to_int() const {
    Assert(width() <= 64);
    uint64_t result = 0;
    uint64_t mask = 1;
    for (const Bit& bit : bits) {
      if (bit.to_int()) {
        result |= mask;
      }
      mask <<= 1;
    }
    return result;
  }

  /**
   * @brief The width (number of binary bits) of the word
   *
   * @return uint
   */
  uint width() const { return bits.size(); }

  /**
   * @brief Set a bit in the word
   *
   * @param index the index of the bit
   * @param bit the new bit value
   */
  void set_bit(uint index, const Bit& bit) {
    Assert(index < width());
    Assert(get_owner() == bit.get_owner());
    bits[index] = bit;
    if (bit.is_pub_e() && bit.is_pub_g()) {
      max_value |= (uint64_t)bit.to_int() << index;
    } else {
      max_value |= 1UL << index;
    }
  }

  /**
   * @brief Get a bit in the word or a constant bit 0 if the index is out of
   * the range
   *
   * @param index the index of the bit
   * @return Bit
   */
  Bit get_bit(uint index) const {
    return index < width() ? bits[index] : Bit::constant(get_owner(), 0);
  }

  // below are overloaded operators for Word, with the same syntax and
  // semantics as in C++

  const Bit& operator[](uint index) const {
    Assert(index < width());
    return bits[index];
  }

  Bit& operator[](uint index) {
    Assert(index < width());
    return bits[index];
  }

  Word operator^(const Word& other) const {
    Assert(get_owner() == other.get_owner());
    if (width() < other.width()) {
      return other ^ *this;
    }
    Word result = *this;
    for (uint i = 0; i < other.width(); ++i) {
      result.bits[i] ^= other.bits[i];
    }
    result.max_value = max_value | ((1UL << other.width()) - 1);
    return result;
  }

  Word operator&(const Word& other) const {
    Assert(get_owner() == other.get_owner());
    if (width() > other.width()) {
      return other & *this;
    }
    Word result = *this;
    for (uint i = 0; i < width(); ++i) {
      result.bits[i] &= other.bits[i];
    }
    result.max_value = std::min(max_value, other.max_value);
    return result;
  }

  Word operator|(const Word& other) const {
    Assert(get_owner() == other.get_owner());
    if (width() < other.width()) {
      return other | *this;
    }
    Word result = *this;
    for (uint i = 0; i < other.width(); ++i) {
      result.bits[i] |= other.bits[i];
    }
    result.max_value = max_value | ((1UL << other.width()) - 1);
    return result;
  }

  Word operator~() const {
    Word result(get_owner(), width());
    for (uint i = 0; i < width(); ++i) {
      result.bits[i] = ~bits[i];
    }
    return result;
  }

  Bit operator!() const {
    return !std::accumulate(bits.begin(), bits.end(),
                            Bit::constant(get_owner(), 0),
                            [](const Bit& a, const Bit& b) { return a | b; });
  }

  Word operator+(const Word& other) const {
    Assert(get_owner() == other.get_owner());
    uint64_t result_max_value = max_value + other.max_value;
    uint result_width;
    if (result_max_value < max_value) {
      // overflow
      result_max_value = UINT64_MAX;
      result_width = std::max(width(), other.width()) + 1;
    } else {
      result_width = bit_width(result_max_value);
    }

    Word result(get_owner(), result_width);
    result.max_value = result_max_value;
    Bit carry = Bit::constant(get_owner(), 0);
    for (uint i = 0; i < result_width; ++i) {
      // full adder
      Bit this_bit = get_bit(i);
      Bit other_bit = other.get_bit(i);
      result.bits[i] = this_bit ^ other_bit ^ carry;
      if (i != result_width - 1) {
        carry = ((carry ^ this_bit) & (carry ^ other_bit)) ^ carry;
      }
    }
    return result;
  }

  Word operator+(const Bit& bit) const {
    Assert(get_owner() == bit.get_owner());
    uint64_t result_max_value = max_value + 1UL;
    uint result_width;
    if (max_value == UINT64_MAX) {
      // overflow
      std::cerr << "Warning: overflow in Word::operator+()" << std::endl;
      result_max_value = UINT64_MAX;
      result_width = width() + 1;
    } else {
      result_width = bit_width(result_max_value);
    }
    Word result(get_owner(), result_width);
    result.max_value = result_max_value;
    Bit carry = bits[0] & bit;
    result.bits[0] = bits[0] ^ bit;
    for (uint i = 1; i < result_width; ++i) {
      // half adder
      Bit this_bit = get_bit(i);
      result.bits[i] = this_bit ^ carry;
      if (i != result_width - 1) {
        carry &= this_bit;
      }
    }
    return result;
  }

  Word operator*(const Bit& other) const {
    Assert(get_owner() == other.get_owner());
    Word result(get_owner(), width());
    result.max_value = max_value;
    for (uint i = 0; i < width(); ++i) {
      result.bits[i] = bits[i] & other;
    }
    return result;
  }

  Word operator<<(uint shift) const {
    Word result(get_owner(), width() + shift);
    for (uint i = 0; i < width(); ++i) {
      result.bits[i + shift] = bits[i];
    }
    if (max_value << shift >> shift != max_value) {
      result.max_value = UINT64_MAX;  // overflow
    } else {
      result.max_value = max_value << shift;
    }
    return result;
  }

  Word operator>>(uint shift) const {
    if (width() < shift) {
      return constant(get_owner(), 1, (uint64_t)0);
    }
    Word result(get_owner(), width() - shift);
    for (uint i = 0; i < result.width(); ++i) {
      result.bits[i] = bits[i + shift];
    }
    if (max_value == UINT64_MAX) {
      result.max_value = default_max_value(result.width());
    } else {
      result.max_value = max_value >> shift;
    }
    return result;
  }

  void operator+=(const Word& other) { *this = *this + other; }

  void operator+=(const Bit& bit) { *this = *this + bit; }

  void operator*=(const Bit& bit) { *this = *this * bit; }

  void operator<<=(uint shift) { *this = *this << shift; }

  void operator>>=(uint shift) { *this = *this >> shift; }

  void operator^=(const Word& other) { *this = *this ^ other; }

  void operator&=(const Word& other) { *this = *this & other; }

  void operator|=(const Word& other) { *this = *this | other; }

  Bit operator!=(const Word& other) const {
    Assert(get_owner() == other.get_owner());
    if (width() < other.width()) {
      return other != *this;
    }
    Bit result = Bit::constant(get_owner(), 0);
    for (uint i = 0; i < other.width(); ++i) {
      result |= (bits[i] != other.bits[i]);
    }
    for (uint i = other.width(); i < width(); ++i) {
      result |= bits[i];
    }
    return result;
  }

  Bit operator==(const Word& other) const { return !(*this != other); }

  Bit operator!=(uint64_t other_val) const {
    if (other_val > default_max_value(width(), max_value)) {
      return Bit::constant(get_owner(), 1);
    }
    Bit result = Bit::constant(get_owner(), 0);
    for (uint i = 0; i < width(); ++i) {
      result |= bits[i] != ((other_val >> i) & 1);
    }
    return result;
  }

  Bit operator==(uint64_t other_val) const { return !(*this != other_val); }

  Bit operator<(const Word& other) const {
    Assert(get_owner() == other.get_owner());
    // treat as signed integers
    uint signed_width = std::max(this->width(), other.width()) + 1;
    Word neg_this(get_owner(), signed_width);
    for (uint i = 0; i < this->width(); ++i) {
      neg_this.set_bit(i, !this->bits[i]);
    }
    for (uint i = this->width(); i < signed_width; ++i) {
      neg_this.set_bit(i, Bit::constant(get_owner(), 1));
    }
    Word diff = neg_this + other;
    return !diff.get_bit(signed_width - 1);
  }

  Bit operator<=(const Word& other) const { return !(other < *this); }

  Bit operator>(const Word& other) const { return other < *this; }

  Bit operator>=(const Word& other) const { return !(*this < other); }

  /**
   * @brief Return a slice of the word. If out of range, the result is padded
   * with constant 0s
   *
   * @param start the start index of the slice (inclusive)
   * @param end the end index of the slice (exclusive)
   * @return Word
   */
  Word slice(uint start, uint end) const {
    Assert(start <= end);
    Assert(end - start <= (1UL << 24));
    Word result(get_owner(), end - start);
    for (uint i = start; i < std::min(end, width()); ++i) {
      result.bits[i - start] = (*this)[i];
    }
    for (uint i = width(); i < end; ++i) {
      result.bits[i - start] = Bit::constant(get_owner(), 0);
    }
    if (max_value == UINT64_MAX) {
      result.max_value = default_max_value(std::min(end, width()) - start);
    } else {
      result.max_value = (max_value >> start) & ((1UL << (end - start)) - 1);
    }
    return result;
  }

  /**
   * @brief Return a slice of the word starting from the beginning. If out of
   * range, the result is padded with constant 0s
   *
   * @param end the end index of the slice (exclusive)
   * @return Word
   */
  Word slice(uint end) const { return slice(0, end); }

  static Word mux(const Bit& control, const Word& word0, const Word& word1) {
    Bit not_control = !control;
    if (word0.width() < word1.width()) {
      return mux(not_control, word1, word0);
    }
    Word result = word0;
    for (uint i = 0; i < word1.width(); ++i) {
      result.bits[i] ^= control & (word0.bits[i] ^ word1.bits[i]);
    }
    for (uint i = word1.width(); i < word0.width(); ++i) {
      result.bits[i] &= not_control;
    }
    result.max_value = std::max(word0.max_value, word1.max_value);
    return result;
  }

  static void cond_mov(const Bit& control, Word& word0, const Word& word1) {
    uint max_width = std::max(word0.width(), word1.width());
    if (word0.width() < max_width) {
      Bit zero = Bit::constant(word1.get_owner(), 0);
      word0.bits.resize(max_width, zero);
    }
    for (uint i = 0; i < max_width; ++i) {
      Bit::cond_mov(control, word0.bits[i], word1.bits[i]);
    }
    word0.max_value = std::max(word0.max_value, word1.max_value);
  }

  static void cond_swap(const Bit& control, Word& word0, Word& word1) {
    uint max_width = std::max(word0.width(), word1.width());
    if (word0.width() < max_width) {
      Bit zero = Bit::constant(word1.get_owner(), 0);
      word0.bits.resize(max_width, zero);
    } else if (word1.width() < max_width) {
      Bit zero = Bit::constant(word0.get_owner(), 0);
      word1.bits.resize(max_width, zero);
    }
    for (uint i = 0; i < max_width; ++i) {
      Bit::cond_swap(control, word0.bits[i], word1.bits[i]);
    }
    uint64_t max_value = std::max(word0.max_value, word1.max_value);
    word0.max_value = max_value;
    word1.max_value = max_value;
  }

  /**
   * @brief Count the number of 1s in the word. Circuit size linear in the
   * word width.
   *
   * Number of AND gates: f(n) = f((n+2)/3) + f((n+1)/3) + (n+1)/3 + (n+2)/3-1
   * => f(n) ~ 2n
   *
   *
   * @return Word
   */
  Word count_ones() {
    if (width() == 1) {
      return *this;
    }
    Word lsbs = Word::constant(get_owner(), (width() + 2) / 3, (uint64_t)0);
    for (uint i = 0; i < width(); i += 3) {
      if (i + 1 == width()) {
        lsbs.set_bit(i / 3, bits[i]);
      } else if (i + 2 == width()) {
        lsbs.set_bit(i / 3, bits[i] ^ bits[i + 1]);
      } else {
        lsbs.set_bit(i / 3, bits[i] ^ bits[i + 1] ^ bits[i + 2]);
      }
    }
    Word carries = Word::constant(get_owner(), (width() + 1) / 3, (uint64_t)0);
    for (uint i = 0; i < width() - 1; i += 3) {
      if (i + 2 == width()) {
        carries.set_bit(i / 3, bits[i] & bits[i + 1]);
      } else {
        carries.set_bit(
            i / 3,
            ((bits[i] ^ bits[i + 1]) & (bits[i] ^ bits[i + 2])) ^ bits[i]);
      }
    }
    Word result = (carries.count_ones() << 1) + lsbs.count_ones();
    result.max_value = width();
    if (max_value != UINT64_MAX) {
      result.max_value =
          std::min(result.max_value, (uint64_t)bit_width(max_value));
      Assert_eq(result.width(), bit_width(result.max_value));
      return result;
    }
    return result.slice(bit_width(result.max_value));
  }

  /**
   * @brief Count the number of 0s in the word. Circuit size linear in the
   * word width. Number of AND gates: f(n) ~ 2n
   *
   * @return Word
   */
  Word count_zeros() { return (~(*this)).count_ones(); }

  /**
   * @brief Count the number of trailing 0s in the word. Circuit size linear
   * in the word width. Number of AND gates: f(n) ~ n + 2n / log_base
   * @param log_base the base of the logarithm used in the trailing_zeros
   * @return Word
   */
  Word trailing_zeros(uint log_base = 1) const {
    // base should be a power of 2
    Assert(log_base > 0);
    uint mask_width = (width() + log_base - 1) / log_base;
    Word trailing_zero_mask =
        Word::constant(get_owner(), mask_width, (uint64_t)0);
    Bit is_continuous_zero = Bit::constant(get_owner(), (uint8_t)1);
    for (uint i = 0; i < mask_width; ++i) {
      for (uint j = 0; j < log_base; ++j) {
        uint index = i * log_base + j;
        if (index >= width()) {
          break;
        }
        is_continuous_zero &= !bits[index];
      }
      trailing_zero_mask.set_bit(i, is_continuous_zero);
    }
    return trailing_zero_mask.count_ones();
  }

  /**
   * @brief Get a mask that only keeps the most significant one bit, or all
   * zeros if *this is 0.
   *
   * @return Word
   */
  Word ms_one() const {
    Bit clear_mask = Bit::constant(get_owner(), 1);
    Word result = *this;
    for (uint i = width() - 1; i + 1; --i) {
      result.set_bit(i, result[i] & clear_mask);
      if (i > 0) {
        clear_mask &= !result[i];
      }
    }
    return result;
  }

  /**
   * @brief Get a mask that only keeps the least significant one bit, or all
   * zeros if *this is 0.
   *
   * @return Word
   */
  Word ls_one() const {
    Bit clear_mask = Bit::constant(get_owner(), 1);
    Word result = *this;
    for (uint i = 0; i < width(); ++i) {
      result.set_bit(i, result[i] & clear_mask);
      if (i < width() - 1) {
        clear_mask &= !result[i];
      }
    }
    return result;
  }

  friend std::ostream& operator<<(std::ostream& os, const Word& word) {
    os << word.to_hex_str();
    return os;
  }

  void set_owner(Gadget* owner) override {
    DataType::set_owner(owner);
    for (Bit& bit : bits) {
      bit.set_owner(owner);
    }
  }

  uint64_t get_max_value() const { return max_value; }

  void set_max_value(uint64_t max_value) {
    this->max_value = default_max_value(width(), max_value);
  }

  static uint64_t sum_width(const std::vector<Word>& words) {
    return std::accumulate(
        words.begin(), words.end(), 0UL,
        [](uint64_t sum, const Word& word) { return sum + word.width(); });
  }

  void print_encodings() const {
    for (const Bit& bit : bits) {
      bit.print_label();
    }
    std::cout << std::endl;
  }

  void dbg_check_labels() const {
    for (const Bit& bit : bits) {
      bit.dbg_check_label();
    }
  }
};

struct WordMetaData : DataType {
  std::vector<bool> pub_es;
  std::vector<bool> pub_gs;
  std::vector<bool> values;
  uint64_t max_value;

  static WordMetaData from_word(const Word& word) {
    WordMetaData meta_data;
    uint len = word.width();
    meta_data.pub_es.resize(len);
    meta_data.pub_gs.resize(len);
    meta_data.values.resize(len);
    for (uint i = 0; i < len; ++i) {
      const Bit& bit = word.get_bit(i);
      meta_data.pub_es[i] = bit.is_pub_e();
      meta_data.pub_gs[i] = bit.is_pub_g();
      meta_data.values[i] = bit.get_value();
    }
    meta_data.max_value = word.get_max_value();
    meta_data.owner = word.get_owner();
    return meta_data;
  }

  static Word to_word(const WordMetaData& meta_data) {
    uint len = meta_data.pub_es.size();
    Word word(meta_data.owner, len, meta_data.max_value);
    for (uint i = 0; i < len; ++i) {
      Bit bit = Bit::constant(meta_data.owner, meta_data.values[i]);
      bit.set_pub_e(meta_data.pub_es[i]);
      bit.set_pub_g(meta_data.pub_gs[i]);
      word.set_bit(i, bit);
    }
    return word;
  }

  Word to_word() const { return to_word(*this); }
};

}  // namespace PicoGRAM