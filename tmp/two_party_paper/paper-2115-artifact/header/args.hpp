#pragma once
#include <string>
#include <cstdlib>
#include <cstring>
struct Args {
  std::string ip = "127.0.0.1";
  int port = 12345;
  int n = 1;
  int m = 1;
  int w = 32;
  int lambda_bits = 128;
  int rounds = 12;
  bool base = false;
};
inline bool eq(const char* a, const char* b){ return std::strcmp(a,b)==0; }
inline Args parse_args(int argc, char** argv) {
  Args a;
  for (int i=1;i<argc;i++) {
    if (eq(argv[i],"-i") && i+1<argc) a.ip = argv[++i];
    else if (eq(argv[i],"-p") && i+1<argc) a.port = std::atoi(argv[++i]);
    else if (eq(argv[i],"-n") && i+1<argc) a.n = std::atoi(argv[++i]);
    else if (eq(argv[i],"-m") && i+1<argc) a.m = std::atoi(argv[++i]);
    else if (eq(argv[i],"-w") && i+1<argc) a.w = std::atoi(argv[++i]);
    else if (eq(argv[i],"-l") && i+1<argc) a.lambda_bits = std::atoi(argv[++i]);
    else if (eq(argv[i],"-rounds") && i+1<argc) a.rounds = std::atoi(argv[++i]);
    else if (eq(argv[i],"-base")) a.base = true;
  }
  if (a.rounds < 1) a.rounds = 1;
  return a;
}
