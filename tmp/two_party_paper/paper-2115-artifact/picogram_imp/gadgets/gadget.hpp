#pragma once
#include <unordered_map>

#include "func.hpp"
#include "gc_ptr.hpp"
#include "util.hpp"

namespace PicoGRAM {
/**
 * @brief The base class of all gadgets (components that consume gc)
 *
 */
struct BaseGadget {
 protected:
  uint64_t T = 0;
  // the current time step of the gadget
  uint64_t t = -1;
  // the caller gadget, or NULL if this is the main gadget
  Gadget* caller = NULL;
  Mode mode = DEFAULT;
  bool garbled = false;
  GCPtr init_gc;
  GCPtr gc;
  // the name of the gadget (for debugging)
  std::string name;

 public:
  explicit BaseGadget(uint64_t T) : T(T), init_gc(-1), gc(-1) {}

  BaseGadget(Mode mode, uint64_t T) : T(T), mode(mode), init_gc(-1), gc(-1) {}

  BaseGadget(Mode mode, Gadget* caller, uint64_t T)
      : T(T), caller(caller), mode(mode), init_gc(-1), gc(-1) {}

  /**
   * @brief Garble the gadget for T timesteps. For each timestep, garble every
   * function in funcs_to_garble in order.
   *
   * @param gc_begin the starting GCPtr
   * @param T the number of timesteps
   * @return GCPtr the ending GCPtr
   */
  virtual GCPtr garble(const GCPtr& begin) {
    Assert(!(mode == GARBLE || mode == EVAL) || begin.is_valid());
    Assert(T > 0);
    garbled = true;
    return begin;
  };

  virtual void inc_time() { ++t; }

  Gadget* get_caller() const { return caller; }

  inline const GCPtr& get_gc() const { return gc; }

  inline const GCPtr& get_init_gc() const { return init_gc; }

  inline GCPtr& get_gc() { return gc; }

  inline Mode get_mode() const { return mode; }

  void init_gc_ptr(const GCPtr& gc) {
    this->init_gc = gc;
    this->gc = gc;
  }

  uint64_t get_time() const { return t; }

  void set_name(const std::string& name) { this->name = name; }

  const std::string& get_name() const { return name; }

  bool is_garbled() const { return garbled; }

  friend std::ostream& operator<<(std::ostream& os, const BaseGadget& gadget) {
    os << gadget.get_name();
    return os;
  }

  virtual ~BaseGadget() {}
};

struct BaseLink;
struct DirectLink;
struct BaseConditionalLink;
struct SIMDLink;
struct Link;

/**
 * @brief Base class for all non-link gadgets
 *
 */
struct Gadget : BaseGadget {
 private:
  // the initial bit offset of the gadget
  uint64_t init_bit_offset = 0;

  // the current bit offset of the gadget
  uint64_t bit_offset = 0;

  // the link to the caller gadget, or NULL if there is no link
  BaseLink* caller_link = NULL;

  // a vtable mapping function names to function pointers
  std::unordered_map<std::string, FuncType*> func_registry;

  // a list of functions in this gadget to be garbled in order, the same
  // function may appear multiple times
  std::vector<FuncType*> funcs_to_garble;

  // the SIMD label of the gadget at the current time step
  BigInt simd_label;

  std::vector<Gadget*> callee_registry;

#ifdef FAST_MEASURE
  uint64_t measure_multiplier = 1;
#endif

 protected:
  // if the gadget has the same T as the caller, then it is treated as part of
  // the caller gadget and self is set to be the caller
  Gadget* self = this;

  explicit Gadget(uint64_t T) : BaseGadget(T) {}

 public:
  /**
   * @brief Construct the main gadget
   *
   * @param mode the mode of the gadget
   */
  Gadget(Mode mode, uint64_t T);

  /**
   * @brief Construct a child gadget of a parent gadget. The constructor
   * automatically creates a link between the parent and the child.
   *
   * @param caller the parent gadget
   * @param link_type the type of the link
   * @param T the number of timestamps the gadget is called
   */
  Gadget(Gadget* caller, LinkType link_type, uint64_t T
#ifdef FAST_MEASURE
         ,
         uint64_t measure_multiplier = 1
#endif
  );

  /**
   * @brief Copy constructor
   *
   */
  Gadget(const Gadget& other) = delete;

  /**
   * @brief Move constructor
   *
   */
  Gadget(Gadget&& other) = default;

  /**
   * @brief Copy assignment
   *
   */
  Gadget& operator=(const Gadget& other) = delete;

  /**
   * @brief Garble the gadget for T timesteps. For each timestep, garble
   * every function in funcs_to_garble in order.
   *
   * @param begin the starting GCPtr
   * @return GCPtr the ending GCPtr
   *
   */
  GCPtr garble(const GCPtr& begin) override;

  /**
   * @brief Garble the callees of the gadget for T timesteps, starting from the
   * current offset of the gadget. For each timestep, garble every function in
   * funcs_to_garble in order.
   *
   * @return GCPtr the ending GCPtr
   */
  GCPtr garble_callees();

  /**
   * @brief Add a callee gadget to the callee registry
   *
   * @param callee the callee gadget
   */
  void add_callee_gadget(Gadget* callee) {
    callee_registry.emplace_back(callee);
  }

  /**
   * @brief Get the bit offset of the gadget for initializing SIMD words.
   *
   * @return uint64_t the bit offset
   */
  uint64_t get_bit_offset() const { return bit_offset; }

  /**
   * @brief Increment the bit offset of the gadget by one.
   * Only works in GARBLE mode.
   *
   */
  void inc_bit_offset() {
    if (mode == GARBLE) {
      ++bit_offset;
    }
  }

  /**
   * @brief Increment the bit offset of the gadget by count.
   * Only works in GARBLE mode.
   *
   * @param count the number of bits to increment
   */
  void inc_bit_offset(uint64_t count) {
    if (mode == GARBLE) {
      bit_offset += count;
    }
  }

  /**
   * @brief Set the bit offset of the gadget to offset.
   * Only works in GARBLE mode.
   *
   * @param offset the new bit offset
   */
  void set_bit_offset(uint64_t offset) {
    if (mode == GARBLE) {
      bit_offset = offset;
    }
  }

  /**
   * @brief Get the type of the link to the caller gadget
   *
   * @return LinkType the link type
   */
  LinkType get_link_type() const;

  BaseLink* get_base_link() const { return caller_link; }

  BaseConditionalLink* get_base_conditional_link();

  const BaseConditionalLink* get_base_conditional_link() const;

  /**
   * @brief Cast the caller link to a DirectLink
   *
   * @return DirectLink*
   */
  DirectLink* get_direct_link();

  /**
   * @brief Cast the caller link to a DirectLink
   *
   * @return const DirectLink*
   */
  const DirectLink* get_direct_link() const;

  /**
   * @brief Cast the caller link to a Link
   *
   * @return Link*
   */
  Link* get_link();

  /**
   * @brief Cast the caller link to a Link
   *
   * @return const Link*
   */
  const Link* get_link() const;

  /**
   * @brief Cast the caller link to a SIMDLink
   *
   * @return SIMDLink*
   */
  SIMDLink* get_simd_link();

  /**
   * @brief Cast the caller link to a SIMDLink
   *
   * @return const SIMDLink*
   */
  const SIMDLink* get_simd_link() const;

  /**
   * @brief Get the SIMD label of the gadget at the current time step
   *
   * @return const BigInt& the SIMD label
   */
  const BigInt& get_simd_label() const { return simd_label; }

  void set_simd_label(const BigInt& label) { simd_label = label; }

  /**
   * @brief Add a function to a list of functions to be garbled in order
   * during each timestep. The same function may appear multiple times.
   *
   * @param func the function to add
   */
  void add_func_to_garble(FuncType* func) {
    funcs_to_garble.emplace_back(func);
  }

  uint64_t get_T() const { return T; }

  /**
   * @brief Increment the time step of the gadget by one.
   * For the garbler, also update the random simd label and reset the bit
   * offset.
   *
   */
  void inc_time() override;

  /**
   * @brief Get the func object by its name
   *
   * @param name
   * @return FuncType*
   */
  FuncType* get_func_by_name(const std::string& name) const {
    auto it = func_registry.find(name);
    if (it == func_registry.end()) {
      std::cerr << "Function " << name << " not found in gadget " << get_name()
                << std::endl;
      return NULL;
    }
    return it->second;
  }

  /**
   * @brief Register a function to the gadget so that it can be queried by name
   *
   * @param func the function to register
   */
  void register_func(FuncType* func) {
    Assert(func);
    func_registry[func->get_name()] = func;
  }

  using GCPtrConstIter = std::vector<GCPtr>::const_iterator;

 private:
  void get_init_gc_ptrs_helper(std::vector<GCPtr>& init_gc_ptrs) const;

  GCPtrConstIter set_init_gc_ptrs_helper(GCPtrConstIter begin,
                                         GCPtrConstIter end);

 public:
  /**
   * @brief Get the initial GCPtrs of the gadget and its callees in a DFS order
   *
   * @return std::vector<GCPtr>
   */
  std::vector<GCPtr> get_init_gc_ptrs() const {
    std::vector<GCPtr> init_gc_ptrs;
    get_init_gc_ptrs_helper(init_gc_ptrs);
    return init_gc_ptrs;
  }

  /**
   * @brief Set the initial GCPtrs of the gadget and its callees in a DFS order
   *
   * @param gc_offsets the initial GCPtrs
   */
  void set_init_gc_ptrs(const std::vector<GCPtr>& gc_offsets) {
    Assert(gc_offsets.size() > 0);
    set_init_gc_ptrs_helper(gc_offsets.begin(), gc_offsets.end());
  }

  void dbg_check_gc_sync() {
    uint64_t offset = gc.get_offset();
    if (mode == GARBLE) {
      // std::cout << "check sync: garbler offset " << offset << std::endl;
      gc.write_default(offset);
    } else if (mode == EVAL) {
      // std::cout << "check sync: evaluator offset " << offset << std::endl;
      uint64_t garbler_offset = 0;
      gc.read_default(garbler_offset);
      Assert_eq(offset, garbler_offset);
    } else if (mode == MEASURE) {
      gc.skip_default<uint64_t>();
    }
  }

#ifdef FAST_MEASURE
  uint64_t get_measure_multiplier() const { return measure_multiplier; }
  void set_measure_multiplier(uint64_t factor) { measure_multiplier = factor; }
#endif

  ~Gadget();
};
}  // namespace PicoGRAM