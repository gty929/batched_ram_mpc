#include "bit.hpp"

#include "gadget.hpp"
#include "three_halves.hpp"

namespace PicoGRAM {
Bit Bit::constant(Gadget* owner, uint8_t value) {
  Bit bit(owner);
  bit.pub_g = true;
  bit.pub_e = true;
  bit.value = value;
  bit.label = value && owner->get_mode() == GARBLE
                  ? key_manager.get_neg_rand_encoding()
                  : key_manager.get_rand_encoding();

  return bit;
}

Bit Bit::input_g(Gadget* owner, uint8_t value) {
  Bit bit(owner);
  bit.pub_g = true;
  bit.pub_e = false;
  bit.value = value;
  bit.label = owner->get_mode() == GARBLE && value
                  ? key_manager.get_neg_rand_encoding()
                  : key_manager.get_rand_encoding();

  return bit;
}

Bit Bit::input_dbg(Gadget* owner, uint8_t value) {
  Bit bit(owner);
  bit.pub_g = false;
  bit.pub_e = false;
  bit.label = Hash(key_manager.get_rand_encoding());
  if (owner->get_mode() == EVAL && value) {
    // in debug mode, assume evaluator knows Delta
    bit.label ^= key_manager.get_Delta();
  }
  bit.value = value;

  // bit.label = 0;  // TODO, oblivious transfer
  return bit;
}

Bit Bit::rand_label_bit(Gadget* owner) {
  Label label;
  if (owner->get_mode() == GARBLE) {
    label = Label::random();
  }
  return Bit(owner, label, 0, false, false, false);
}

void Bit::join(const Bit& src, Bit& dst) {
  Mode mode = src.get_mode();
  Gadget* owner = src.get_owner();
  if (mode == GARBLE) {
    Assert_eq(GARBLE, dst.get_mode());
    Assert_eq(owner, dst.get_owner());
    owner->get_gc().write_label(src.label ^ dst.label);
  } else if (mode == EVAL) {
    Label diff_label;
    owner->get_gc().read_label(diff_label);
    Label dst_label = src.label ^ diff_label;
    dst = Bit(owner, dst_label, src.value, false, false, src.skip_e);
  } else if (mode == MEASURE) {
    owner->get_gc().skip_label();
  } else if (mode == DEBUG) {
    dst = Bit(owner, Label(), src.value, false, false, src.skip_e);
  }
}

Bit Bit::reveal() const {
  Assert(owner);
  Bit result = *this;
  result.pub_e = true;
  if (!pub_e) {
    if (get_mode() == GARBLE) {
      owner->get_gc().write_bit(label.LSB());
    } else if (get_mode() == EVAL) {
      uint8_t lsb;
      owner->get_gc().read_bit(lsb);
      result.value = lsb ^ label.LSB();
    } else if (get_mode() == MEASURE) {
      owner->get_gc().skip_bit();
    }
  }
  return result;
}

void Bit::dbg_check_label() const {
#ifdef NDEBUG
  std::cerr << "Warning: dbg_check_label should not be called in release mode"
            << std::endl;
#endif
  if (get_mode() == GARBLE) {
    owner->get_gc().write_label(label);
    owner->get_gc().write_label(label ^ key_manager.get_Delta());
  } else if (get_mode() == EVAL) {
    Label label0, label1;
    owner->get_gc().read_label(label0);
    owner->get_gc().read_label(label1);
    if (label != label0 && label != label1) {
      std::cerr << "Evaluator gets label \n"
                << label << "\n but valid labels are \n"
                << label0 << "\n"
                << label1 << std::endl;
    }
    Assert(label == label0 || label == label1);
  } else if (get_mode() == MEASURE) {
    owner->get_gc().skip_label(2);
  }
}

uint8_t Bit::to_int() const {
  Bit revealed = reveal();
  return revealed.value;
}

void Bit::operator^=(const Bit& other) {
  Assert(owner && owner == other.owner);
  Assert(!get_mode() || !other.get_mode() || get_mode() == other.get_mode());
  pub_e &= other.pub_e;
  pub_g &= other.pub_g;
  value ^= other.value;
  label ^= other.label;
  skip_e |= other.skip_e;
}

void Bit::HALF_AND_pub_e_inner(const Bit& other, Mode mode, GCPtr& gc,
                               Bit& result) const {
  // evaluator half-and
  if (mode == GARBLE) {
    Label h0 = Hash(label, gc.get_offset());
    Label h1 = Hash(label ^ key_manager.get_Delta(), gc.get_offset());
    Label gc_material = h0 ^ h1 ^ other.label;
    gc.write_label(gc_material);
    result.label = h0;
  } else if (mode == EVAL) {
    if (result.skip_e) {
      gc.skip_label();
    } else {
      Label h = Hash(label, gc.get_offset());
      if (value == 0) {
        gc.skip_label();
        result.label = h;
      } else {
        gc.read_label(result.label);
        result.label ^= h ^ other.label;
      }
    }
  } else if (mode == MEASURE) {
    gc.skip_label();
  }
  result.pub_e = other.pub_e;
  result.pub_g = false;  // because self is not pub_g, otherwise it is a free
                         // and we should not be here
}

void Bit::HALF_AND_pub_g_inner(const Bit& other, Mode mode, GCPtr& gc,
                               Bit& result) const {
  // garbler half-and
  bool select_bit = other.label.LSB();
  if (mode == GARBLE) {
    Label h0 = Hash(other.label, gc.get_offset());
    Label h1 = Hash(other.label ^ key_manager.get_Delta(), gc.get_offset());
    Label gc_material = h0 ^ h1;
    if (value) {
      gc_material ^= key_manager.get_Delta();
    }
    gc.write_label(gc_material);
    result.label = h0;
    if (select_bit) {
      result.label ^= gc_material;
    }
  } else if (mode == EVAL) {
    if (result.skip_e) {
      gc.skip_label();
    } else {
      Label h = Hash(other.label, gc.get_offset());
      if (select_bit == 0) {
        gc.skip_label();
        result.label = h;
      } else {
        gc.read_label(result.label);
        result.label = h ^ result.label;
      }
    }
  } else if (mode == MEASURE) {
    gc.skip_label();
  }
  result.pub_e = false;
  result.pub_g = other.pub_g;
}

Bit Bit::AND_inner(const Bit& other, Mode mode) const {
  if (pub_g && pub_e) {
    // free and
    return !value ? *this : other;
  }
  Bit result(owner);
  result.skip_e = skip_e || other.skip_e;
  Assert(owner && owner == other.owner);
  GCPtr& gc = owner->get_gc();
  if (pub_e) {
    HALF_AND_pub_e_inner(other, mode, gc, result);
  } else if (pub_g) {
    if (other.pub_g) {
      return input_g(owner, value & other.value);
    }
    HALF_AND_pub_g_inner(other, mode, gc, result);
  } else {
#ifdef USE_THREE_HALVES
    if (mode == GARBLE) {
      uint8_t material[25];
      result.label =
          ThreeHalves::Garble(label, other.label, gc.get_offset(), material);
      gc.write_data(material, 25);
    } else if (mode == EVAL) {
      uint8_t material[25];
      uint64_t offset = gc.get_offset();
      gc.read_data(material, 25);
      Assert(material[24] < 32);
      result.label = ThreeHalves::Eval(label, other.label, offset, material);
    } else if (mode == MEASURE) {
      gc.skip_data(25);
    }
#else
    Bit r(result.owner);
    uint8_t r_val = other.label.LSB();
    if (mode == GARBLE) {
      r.value = r_val;
      r.label = !r_val ? key_manager.get_rand_encoding()
                       : key_manager.get_neg_rand_encoding();
    } else if (mode == EVAL) {
      r.label = key_manager.get_rand_encoding();
    }
    Bit bit_left(result.owner), bit_right(result.owner),
        r_xor_other(result.owner);
    bit_left.skip_e = bit_right.skip_e = result.skip_e;
    r.HALF_AND_pub_g_inner(*this, mode, gc, bit_left);
    r_xor_other.label = r.label ^ other.label;
    r_xor_other.value = r_val;
    r_xor_other.HALF_AND_pub_e_inner(*this, mode, gc, bit_right);
    result.label = bit_left.label ^ bit_right.label;
#endif
    result.pub_g = result.pub_e = false;
  }
  result.value = value & other.value;
  return result;
}

Bit Bit::operator&(const Bit& other) const {
  Assert(!owner || !other.owner || owner == other.owner);
  Assert(owner || other.owner || get_mode() == DEBUG ||
         other.get_mode() == DEBUG || (!get_mode() && !other.get_mode()));
  Assert(!get_mode() || !other.get_mode() || get_mode() == other.get_mode());
  Assert(get_mode() || other.get_mode() || (pub_g && pub_e) ||
         (other.pub_g && other.pub_e));
  Mode mode = get_mode();
  if (mode == DEFAULT) {
    mode = other.get_mode();
  }
  uint8_t pub_score = ((uint8_t)pub_e << 1) | pub_g;
  uint8_t other_pub_score = ((uint8_t)other.pub_e << 1) | other.pub_g;
  if (pub_score < other_pub_score) {
    return other.AND_inner(*this, mode);
  }
  return AND_inner(other, mode);
}

Bit Bit::operator!() const {
  Bit result = *this;
  result.value = !value;
  Mode mode = get_mode();
  if (mode == GARBLE) {
    result.label ^= key_manager.get_neg_rand_encoding();
  } else if (mode == EVAL) {
    result.label ^= key_manager.get_rand_encoding();
  }
  return result;
}

void Bit::cond_swap(const Bit& control, Bit& bit0, Bit& bit1) {
  Bit bit_xor = bit0 ^ bit1;
  Bit bit_xor_or_zero = control & bit_xor;
  bit0 ^= bit_xor_or_zero;
  bit1 ^= bit_xor_or_zero;
}
}  // namespace PicoGRAM