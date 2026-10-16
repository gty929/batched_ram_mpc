#include "header/args.hpp"
#include "header/merge_switch.hpp"
#include "header/merge_boolean.hpp"
#include "header/merge_simd.hpp"
#include <math.h>
int main(int argc, char** argv) {
  Args a = parse_args(argc, argv);
  int counter = a.rounds;
  if (a.base){
    while (counter --){
    std::cout << "================= Base Case (Boolean)=================\n";
    nog::run_evaluator_compaction_boolean_gc(a);
    std::cout << "================= Base Case (SIMD)=================\n";
    nog::run_evaluator_compaction_simd(a);
    a.n *= 2; 
    a.m *= 2;
    // a.w += 1; //log n
    // a.w += 1 + 2 * (int)sqrt(a.w); // log^2 n
    }
    
  }
  else {
    while (counter --){
        std::cout << "================= Our Approach =================\n";
        nog::run_evaluator(a);
        std::cout << "================= Our Approach (Randomized)=================\n";
        nog::run_evaluator_randomized(a);
        a.n *= 2; 
        a.m *= 2;
    // a.w += 1; //log n
    // a.w += 1 + 2 * (int)sqrt(a.w); // log^2 n
      }
  }
  
  return 0;
}
