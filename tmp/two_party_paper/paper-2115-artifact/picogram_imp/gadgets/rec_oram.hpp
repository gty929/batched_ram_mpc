#pragma once

#include "circuit_oram.hpp"
#include "vec.hpp"

namespace PicoGRAM {
/**
 * @brief Circuit ORAM with recursive position maps.
 *
 */
struct RecursiveORAM : DataType {
  // when the address space is small, use a linear position map
  Vec* linear_pos_map = NULL;
  // otherwise, use a recursive ORAM for the position map
  RecursiveORAM* pos_map = NULL;
  uint positions_per_word;  // number of positions stored in each word of the
                            // position map
  uint log_positions_per_word;  // log2 of positions_per_word
  uint64_t memory_space;  // the size of the memory space (must be a power of 2)
  CircuitORAM oram;       // the ORAM for the data
  // a permutation of the initial and evicting positions
  std::vector<uint64_t> position_perm;
  // a counter tracking the current position in the permutation
  uint64_t position_perm_counter = 0;
  uint64_t T = 0;  // the number of provisioned accesses
  using UpdateFuncType = std::function<Word(const Word&)>;

  /**
   * @brief Access the ORAM with a custom update function.
   *
   * @param addr the address of the data
   * @param update_func the update function to apply to the data
   */
  void access(const Word& addr, const UpdateFuncType& update_func) {
    uint64_t new_position_val = 0;
    if (get_mode() == GARBLE || get_mode() == DEBUG) {
      Assert_less(position_perm_counter, position_perm.size());
      new_position_val = position_perm[position_perm_counter++];
    }
    const Word& new_position =
        Word::input_g(get_owner(), oram.position_width, new_position_val);
    Word old_position;
    if (linear_pos_map) {
      old_position = linear_pos_map->write(addr, new_position);
    } else {
      Word pos_map_addr = addr >> log_positions_per_word;
      Word pos_map_block_offset = addr.slice(log_positions_per_word);
      CircuitORAM::UpdateFuncType pos_map_update_func = [&](const Word& block) {
        // convert the block to a vector of words
        Vec block_vec(get_owner(), positions_per_word);
        for (uint i = 0; i < positions_per_word; ++i) {
          block_vec.set_word(i, block.slice(i * oram.position_width,
                                            (i + 1) * oram.position_width));
        }
        // update the block with the new address
        old_position = block_vec.write(pos_map_block_offset, new_position);
        // convert the updated block back to a word
        Word new_block(get_owner(), positions_per_word * oram.position_width);
        for (uint i = 0; i < positions_per_word; ++i) {
          for (uint j = 0; j < oram.position_width; ++j) {
            new_block.set_bit(i * oram.position_width + j, block_vec[i][j]);
          }
        }
        return new_block;
      };
      pos_map->access(pos_map_addr, pos_map_update_func);
    }
    Assert_eq(old_position.width(), oram.position_width);
    oram.access(old_position, addr, new_position, update_func);
  }

  /**
   * @brief Read or write a word from the ORAM.
   *
   * @param addr the address of the data
   * @param is_write whether the operation is a write
   * @param new_data the new data to write
   * @return Word the old data read from the ORAM
   */
  Word read_or_write(const Word& addr, const Bit& is_write,
                     const Word& new_data) {
    Word old_data_copy;
    UpdateFuncType update_func = [&](const Word& old_data) {
      old_data_copy = old_data;
      return Word::mux(is_write, old_data, new_data);
    };
    access(addr, update_func);
    return old_data_copy;
  }

  /**
   * @brief Initialize the ORAM with the given data.
   *
   * @param data the data to initialize the ORAM
   */
  void init_ram_g(const std::vector<std::vector<bool>>& data) {
    Assert_eq(data.size(), memory_space);
    init_empty_ram();
    // todo: incorporate the code below into init_ram_g
    std::vector<PlaintextBlocksInPos> blocks_in_pos(memory_space);
    if (get_mode() == GARBLE || get_mode() == DEBUG) {
      Assert(T);
      Assert_eq(position_perm.size(), T + memory_space);
      for (uint64_t i = 0; i < memory_space; ++i) {
        // the random position assigned to the data
        // (the first T positions are for eviction)
        uint64_t position = position_perm[i + T];
        uint64_t rev_position = reverse_bits(position, oram.position_width);
        blocks_in_pos[rev_position].emplace_back(position, i, data[i]);
      }
      position_perm.resize(T);
      position_perm.shrink_to_fit();
    }
    oram.init_ram_g(blocks_in_pos.begin(), blocks_in_pos.end());
  }

  /**
   * @brief Initialize the position map.
   */
  void init_empty_ram() {
    oram.init_evict_counter(T % memory_space);
    if (get_mode() == GARBLE || get_mode() == DEBUG) {
      Assert(T);
      position_perm.resize(T + memory_space);
      for (uint64_t i = 0; i < T + memory_space; ++i) {
        position_perm[i] = i;
      }
      secure_permute(position_perm.begin(), position_perm.end());
      // we permute the initial positions of the data and the newly assigned
      // positions of data together to ensure obliviousness and a balanced
      // number of accesses across the sub-trees
      // the last memory_space elements are the initial positions of the data
    }
    if (linear_pos_map) {
      std::vector<std::vector<bool>> linear_pos_map_data(memory_space);
      if (get_mode() == GARBLE || get_mode() == DEBUG) {
        for (uint64_t i = 0; i < memory_space; ++i) {
          linear_pos_map_data[i].resize(oram.position_width);
          uint64_t addr = position_perm[i + T];
          for (uint j = 0; j < oram.position_width; ++j) {
            linear_pos_map_data[i][j] = (addr >> j) & 1;
          }
        }
      }
      linear_pos_map->init_ram_g(linear_pos_map_data, oram.position_width);
    } else {
      Assert(pos_map);
      uint64_t pos_map_memory_space = memory_space / positions_per_word;
      std::vector<std::vector<bool>> pos_map_data(pos_map_memory_space);
      if (get_mode() == GARBLE || get_mode() == DEBUG) {
        for (uint64_t i = 0; i < pos_map_memory_space; ++i) {
          pos_map_data[i].resize(oram.position_width * positions_per_word);
          for (uint j = 0; j < positions_per_word; ++j) {
            uint64_t pos = i * positions_per_word + j;
            uint64_t addr = position_perm[pos + T];
            for (uint k = 0; k < oram.position_width; ++k) {
              pos_map_data[i][j * oram.position_width + k] = (addr >> k) & 1;
            }
          }
        }
      }
      pos_map->init_ram_g(pos_map_data);
    }
  }

  void init_ram(const std::vector<Word>& data) {
    Assert_eq(data.size(), memory_space);
    init_empty_ram();
    std::vector<uint64_t> init_positions;
    if (get_mode() == GARBLE || get_mode() == MEASURE) {
      // set the initial positions of the data
      // to be (position_perm.begin() + T, position_perm.end())
      init_positions.resize(memory_space);
      for (uint64_t i = 0; i < memory_space; ++i) {
        init_positions[i] = position_perm[i + T];
      }
      position_perm.resize(T);
      position_perm.shrink_to_fit();
    }
    oram.init_ram(data, init_positions);
  }

  /**
   * @brief Construct a new Recursive ORAM
   *
   * @param owner
   * @param memory_space the number of blocks in the ORAM, must be a power of 2
   * @param word_width the width of the data word
   * @param T the number of provisioned accesses
   * @param linear_oram_threshold the threshold memory space for using a linear
   * position map
   */
  RecursiveORAM(Gadget* owner, uint64_t memory_space, uint word_width,
                uint64_t T, uint64_t simd_link_threshold = 8,
                uint64_t linear_oram_threshold = 512)
      : DataType(owner),
        memory_space(memory_space),
        oram(owner, memory_space, word_width, T,
             ORAMConstParams::recommended_params(log2ceil(memory_space),
                                                 simd_link_threshold)),
        T(T) {
    Assert(memory_space > 0 && (memory_space & (memory_space - 1)) == 0);
    positions_per_word = 4;
    log_positions_per_word = log2ceil(positions_per_word);
    uint64_t pos_map_memory_space = memory_space / positions_per_word;
    if (pos_map_memory_space < linear_oram_threshold) {
      linear_pos_map = new Vec(owner, memory_space);
    } else {
      pos_map = new RecursiveORAM(owner, pos_map_memory_space,
                                  oram.position_width * positions_per_word, T,
                                  simd_link_threshold, linear_oram_threshold);
    }
  }

  ~RecursiveORAM() {
    if (linear_pos_map) {
      delete linear_pos_map;
    }
    if (pos_map) {
      delete pos_map;
    }
  }
};
}  // namespace PicoGRAM