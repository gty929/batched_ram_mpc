#include "gadget.hpp"

#include "func.hpp"
#include "link.hpp"

namespace PicoGRAM {
Gadget::Gadget(Mode mode, uint64_t T) : BaseGadget(mode, T) {
  Assert(mode != DEFAULT);
}

Gadget::Gadget(Gadget* caller, LinkType link_type, uint64_t T
#ifdef FAST_MEASURE
               ,
               uint64_t measure_multiplier
#endif
               )
    : BaseGadget(caller->get_mode(), caller, T) {
#ifdef FAST_MEASURE
  this->measure_multiplier = measure_multiplier;
#endif
  Assert(caller);
  Assert(caller->get_mode() != DEFAULT);
  switch (link_type) {
    case NONE:
      self = caller;
      return;
    case DIRECT:
      caller_link = new DirectLink(this);
      break;
    case COND:
      caller_link = new Link(this);
      break;
    case SIMD_COND:

      caller_link = new SIMDLink(this);
      break;
    default:
      break;
  }
  caller->add_callee_gadget(this);
}

void Gadget::inc_time() {
  ++t;
  Assert_less(t, T);
  if (mode == GARBLE) {
    if (get_link_type() == SIMD_COND) {
      simd_label = get_simd_link()->get_simd_label(t);
      simd_label.to_montgomery();
    } else {
      // TODO: optimize this
      simd_label.unset();
    }
    bit_offset = init_bit_offset;
  }
}

GCPtr Gadget::garble(const GCPtr& begin) {
#ifdef FAST_MEASURE
  if (measure_multiplier == 0) {
    Assert_eq(get_mode(), MEASURE);
    return begin;
  }
#ifdef MEASURE_STACK_COST
  uint64_t start_stack_cost = global_stack_cost;
#endif
#ifdef MEASURE_TSC_STACK
  uint64_t start_tsc_stack_cost = global_tsc_stack_cost;
#endif
#endif
  // std::cout << "garbling gadget " << get_name() << " for " << T << "
  // timesteps"
  //           << std::endl;
  // If T_self is calculated greater than T_parent, then T_self_actual is set to
  // T_parent
  BaseGadget::garble(begin);

  GCPtr gc_ptr = begin;

  if (get_link_type() == SIMD_COND || get_link_type() == COND) {
    BaseConditionalLink* base_cond_link = get_base_conditional_link();
    gc_ptr = base_cond_link->garble(gc_ptr);
  }

  init_gc_ptr(gc_ptr);
  init_bit_offset = caller ? caller->get_bit_offset() : 0;
  t = -1;
  inc_time();
  for (; t < T;) {
    // garble the functions
    for (FuncType* func : funcs_to_garble) {
      func->garble();
    }
    if (t < T - 1) {
      inc_time();
    } else {
      ++t;  // TODO: remove this line
    }
  }

  if (get_simd_link()) {
    get_simd_link()->release();  // release the SIMD labels
  }

  gc_ptr = garble_callees();

#ifdef FAST_MEASURE
  if (measure_multiplier > 1) {
    Assert_eq(get_mode(), MEASURE);
    uint64_t gc_size = gc_ptr.get_offset() - begin.get_offset();
    gc_ptr.skip_default<uint8_t>(gc_size * (measure_multiplier - 1));
#ifdef MEASURE_STACK_COST
    uint64_t stack_cost = global_stack_cost - start_stack_cost;
    global_stack_cost += stack_cost * (measure_multiplier - 1);
#endif
#ifdef MEASURE_TSC_STACK
    uint64_t tsc_stack_cost = global_tsc_stack_cost - start_tsc_stack_cost;
    global_tsc_stack_cost += tsc_stack_cost * (measure_multiplier - 1);
#endif
  }
#endif

  return gc_ptr;
}

GCPtr Gadget::garble_callees() {
  // garble each callee gadget
  return std::accumulate(
      callee_registry.begin(), callee_registry.end(), get_gc(),
      [](const GCPtr& gc, Gadget* callee) { return callee->garble(gc); });
}

LinkType Gadget::get_link_type() const {
  if (caller_link) {
    return caller_link->get_type();
  }
  return NONE;
}

DirectLink* Gadget::get_direct_link() {
  return dynamic_cast<DirectLink*>(caller_link);
}

const DirectLink* Gadget::get_direct_link() const {
  return dynamic_cast<const DirectLink*>(caller_link);
}

BaseConditionalLink* Gadget::get_base_conditional_link() {
  return dynamic_cast<BaseConditionalLink*>(caller_link);
}

const BaseConditionalLink* Gadget::get_base_conditional_link() const {
  return dynamic_cast<const BaseConditionalLink*>(caller_link);
}

SIMDLink* Gadget::get_simd_link() {
  return dynamic_cast<SIMDLink*>(caller_link);
}

const SIMDLink* Gadget::get_simd_link() const {
  return dynamic_cast<const SIMDLink*>(caller_link);
}

Link* Gadget::get_link() { return dynamic_cast<Link*>(caller_link); }

const Link* Gadget::get_link() const {
  return dynamic_cast<const Link*>(caller_link);
}

void Gadget::get_init_gc_ptrs_helper(std::vector<GCPtr>& init_gc_ptrs) const {
  if (get_link_type() == SIMD_COND || get_link_type() == COND) {
    init_gc_ptrs.push_back(get_base_conditional_link()->get_init_gc());
  }
  init_gc_ptrs.push_back(init_gc);
  for (Gadget* callee : callee_registry) {
    callee->get_init_gc_ptrs_helper(init_gc_ptrs);
  }
}

Gadget::GCPtrConstIter Gadget::set_init_gc_ptrs_helper(
    Gadget::GCPtrConstIter begin, Gadget::GCPtrConstIter end) {
  Assert(begin < end);
  if (get_link_type() == SIMD_COND || get_link_type() == COND) {
    get_base_conditional_link()->init_gc_ptr(*begin);
    ++begin;
  }
  init_gc_ptr(*begin);
  return std::accumulate(callee_registry.begin(), callee_registry.end(),
                         begin + 1, [=](GCPtrConstIter it, Gadget* callee) {
                           return callee->set_init_gc_ptrs_helper(it, end);
                         });
}

Gadget::~Gadget() {
  if (caller_link) {
    delete caller_link;
    caller_link = NULL;
  }
}

}  // namespace PicoGRAM