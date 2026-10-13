#pragma once

#include "data_type.hpp"
#include "hash.hpp"
#include "key_manager.hpp"
#include "util.hpp"

namespace PicoGRAM {

struct GCPtr;
/**
 * @brief Most basic data type that carries the garbling of a wire.
 * The garbler and the evaluator may hold different labels for the same wire.
 *
 */
struct Bit : DataType {
 private:
  Label label;        // the label (as a bit string)
  uint8_t value = 0;  // the value of the wire, or any value if the wire is not
                      // pub to the party

  bool pub_g = true;  // whether the wire value is public to the garbler (G)
  bool pub_e = true;  // whether the wire value is public to the evaluator (E)
  // whether future computation should be skipped by E
  bool skip_e = false;

 public:
  Bit() {}

  explicit Bit(Gadget* owner) : DataType(owner) {}

  Bit(Gadget* owner, const Label& label, uint8_t value, bool pub_g, bool pub_e,
      bool skip_e = false)
      : DataType(owner),
        label(label),
        value(value),
        pub_g(pub_g),
        pub_e(pub_e),
        skip_e(skip_e) {}

  /**
   * @brief Returns a bit carrying constant value, which is public to both G
   * and
   * E
   *
   * @param owner the owner gadget of the bit
   * @param value the constant value of the bit
   * @return Bit
   */
  static Bit constant(Gadget* owner, uint8_t value);

  /**
   * @brief Returns a bit that carries value provided by G but unknown to E
   *
   * @param owner the owner gadget of the bit
   * @param value the value provided by the garbler. Ignored if get_mode() ==
   * EVAL.
   * @return Bit
   */
  static Bit input_g(Gadget* owner, uint8_t value);

  /**
   * @brief Input a bit for debugging purposes. The value is provided by the
   * evaluator.
   *
   * @param owner the owner gadget of the bit
   * @param value the value provided by the evaluator. Ignored if get_mode() ==
   * GARBLE.
   * @return Bit
   */
  static Bit input_dbg(Gadget* owner, uint8_t value);

  /**
   * @brief Construct a bit with random label
   *
   * @param owner the owner gadget of the bit
   * @return Bit
   */
  static Bit rand_label_bit(Gadget* owner);

  /**
   * @brief Convert a src bit to a dst bit. In garble mode, both the src and dst
   * label need to be set. In eval mode, the src bit is converted to the dst
   * bit. A usecase is to break down a circuit into multiple sub-circuits to
   * garble, and use join between sub-circuits to connect them.
   *
   * @param src the source bit
   * @param dst the destination bit
   */
  static void join(const Bit& src, Bit& dst);

  /**
   * @brief Clone *this but make the value public to the evaluator
   *
   * @return Bit
   */
  Bit reveal() const;

  /**
   * @brief Set the skip_e flag set to true
   *
   */
  void skip() { skip_e = true; }

  /**
   * @brief A debug helper function to check if the label of the bit is
   * correctly shared between the parties, should only be called in debug
   * mode.
   *
   */
  void dbg_check_label() const;

  /**
   * @brief Output the value of the bit as an integer
   *
   * @return uint8_t
   */
  uint8_t to_int() const;

  bool is_pub_g() const { return pub_g; }
  bool is_pub_e() const { return pub_e; }
  void set_pub_e(bool pub_e) { this->pub_e = pub_e; }
  void set_pub_g(bool pub_g) { this->pub_g = pub_g; }
  bool is_skip() const { return skip_e; }
  const Label& get_label() const { return label; }
  Label& get_label() { return label; }
  uint8_t get_value() const { return value; }

  // Below we define operations on bits with the same syntax and symmantics as
  // in C++.

  Bit operator^(const Bit& other) const {
    Bit result = *this;
    result ^= other;
    return result;
  }

 private:
  void HALF_AND_pub_e_inner(const Bit& other, Mode mode, GCPtr& gc,
                            Bit& result) const;

  void HALF_AND_pub_g_inner(const Bit& other, Mode mode, GCPtr& gc,
                            Bit& result) const;

  Bit AND_inner(const Bit& other, Mode mode) const;

 public:
  Bit operator&(const Bit& other) const;

  Bit operator!() const;

  Bit operator~() const { return !*this; }

  Bit operator|(const Bit& other) const { return ~((~*this) & (~other)); }

  Bit operator!=(const Bit& other) const { return *this ^ other; }

  Bit operator==(const Bit& other) const { return !(*this != other); }

  Bit operator!=(uint8_t const_val) const {
    if (const_val) {
      return !*this;
    }
    return *this;
  }

  Bit operator==(uint8_t const_val) const { return *this != !const_val; }

  Bit operator<(const Bit& other) const { return (~*this) & other; }

  Bit operator<=(const Bit& other) const { return (~*this) | other; }

  Bit operator>(const Bit& other) const { return other < *this; }

  Bit operator>=(const Bit& other) const { return other <= *this; }

  void operator^=(const Bit& other);

  void operator&=(const Bit& other) { *this = *this & other; }

  void operator|=(const Bit& other) { *this = *this | other; }

  static void cond_swap(const Bit& control, Bit& bit0, Bit& bit1);

  static Bit mux(const Bit& control, const Bit& bit0, const Bit& bit1) {
    Bit xor_bit = bit0 ^ bit1;
    Bit masked_xor_bit = xor_bit & control;
    return bit0 ^ masked_xor_bit;
  }

  static void cond_mov(const Bit& control, Bit& bit0, const Bit& bit1) {
    bit0 ^= (bit0 ^ bit1) & control;
  }

  void print_label() const { std::cout << label << std::endl; }
};
}  // namespace PicoGRAM