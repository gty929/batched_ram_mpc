# Garbled Merge and Non-Oblivious Stack Artifact

This repository is the CCS 2026 artifact for the paper **Improved Garbled RAM
via Garbled Merge**. It contains:

- the accepted paper PDF: `ccs2026a-paper2115.pdf`
- the garbled-merge benchmark implementation: `src/`, `header/`
- the baseline PicoGRAM code: `picogram/`
- the modified PicoGRAM code with the garbled stack: `picogram_imp/`
- artifact helper scripts: `artifact/scripts/`

The artifact is designed for the CCS artifact-evaluation procedure.

## Claims Covered

The scripts below reproduce the main experimental claims from Section 6 of the
paper:

1. Garbled merge has substantially lower communication than the Boolean
   compaction baseline and PicoGRAM-style SIMD compaction.
2. Replacing PicoGRAM's stack subroutine with our garbled stack reduces
   end-to-end GRAM communication per access across tested RAM sizes.

Exact wall-clock timings depend on CPU, and memory bandwidth.
The communication sizes and the relative ordering are the primary reproducible
outputs.

## Tested Platform

The paper used an AWS `c5ad.8xlarge` instance with 64 GB RAM and
`lambda = 128`. The artifact has also been tested on Ubuntu 24.04 with:

- GCC 13.3
- CMake 3.28
- Python 3.12
- OpenSSL 3
- EMP toolkit installed under `~/libs`

An x86-64 CPU with AES-NI is expected because the benchmarks are compiled with
AES instructions.

## Setup

Install system packages and EMP toolkit:

```bash
./setup.sh
```

`setup.sh` installs EMP into `${EMP_TOOL_ROOT:-$HOME/libs}`. If EMP is already
installed elsewhere, set `EMP_TOOL_ROOT` and `CMAKE_PREFIX_PATH` before building:

```bash
export EMP_TOOL_ROOT=/path/to/emp/prefix
export CMAKE_PREFIX_PATH="$EMP_TOOL_ROOT"
```

The PicoGRAM variants use the vendored GoogleTest tree in
`picogram_imp/googletest`. `picogram/googletest` may be a symlink to that copy;
the build and benchmark scripts recreate the symlink if needed.

## Quick Artifact Check

This is the recommended first command for evaluators. It builds all components,
runs a short garbled-merge benchmark, and runs one small end-to-end PicoGRAM
comparison point.

```bash
./artifact/scripts/quick_check.sh
```

Expected time on a modern Ubuntu machine: minutes. Expected output includes:

- focused GoogleTest passes for shared primitives and `picogram_imp` switch-stack tests
- `check=OK` in evaluator logs for merge correctness
- `REC_ORAM_BENCH_RESULT ...` lines for both `picogram` and `picogram_imp`
- parsed result files under `artifact_results/quick_picogram/`

## Build Only

```bash
./artifact/scripts/build_all.sh
```

This creates:

- `build/garbler` and `build/evaluator`
- `picogram/build/test_basic`
- `picogram_imp/build/test_basic`

## Reproduce Garbled-Merge Communication

Short run:

```bash
./artifact/scripts/run_merge_benchmark.sh --rounds 4 --outdir artifact_results/merge_short
```

Full paper-scale local run for merge sizes `N=2^1` through `N=2^12`:

```bash
./artifact/scripts/run_merge_benchmark.sh --rounds 12 --outdir artifact_results/merge_full
```

The script runs the two-party garbler/evaluator programs on localhost.

#### **NOTE**, the longer run might take 10 or more hours to complete on the testing machine, and might blow up memory if SWAP was not properly setup. 

It writes garbler/evaluator logs plus a parsed CSV:

```text
artifact_results/merge_full/
  ours_garbler.log
  ours_evaluator.log
  baseline_garbler.log
  baseline_evaluator.log
  merge_communication.csv
```

The CSV columns are `type, wordwidth, 2^k...` and contain communication in bits
for the requested word width for `bool`, `switch` (ours), and `simd` baselines.
Larger `--rounds` values take longer because the merge size doubles each round.

## Reproduce End-to-End GRAM Comparison

Short comparison:

```bash
python3 run_picogram_compare.py \
  --projects picogram picogram_imp \
  --min-exp 5 --max-exp 8 \
  --outdir artifact_results/picogram_short
```

Longer comparison:

```bash
python3 run_picogram_compare.py \
  --projects picogram picogram_imp \
  --min-exp 10 --max-exp 16 \
  --outdir artifact_results/picogram_long
```

Full paper-scale runs up to `N=2^24` may require substantial RAM and many hours;
AEC evaluators can stop early once the trend is established. The script writes:

```text
artifact_results/picogram_long/
  picogram_bandwidthbench_raw.txt
  picogram_imp_bandwidthbench_raw.txt
  picogram_time_per_access.txt
  picogram_imp_time_per_access.txt
  combined_time_per_access.txt
```

`gc_size_bytes / T` is the communication per RAM access. The expected result is
that `picogram_imp` has lower communication per access than `picogram` for the
same `N`, while timings may vary.

## Plotting and CSV Helpers

- `export.py` parses garbled-merge logs into a communication CSV.
- `plot.py` reproduces the merge communication/computation figures from parsed
  logs. It expects log names matching the historical `build/*.txt` layout.
- `picogram_imp/scripts/bench_bandwidth_rec_oram.py` simulates end-to-end
  runtime under bandwidth choices after running one `RecORAM.BandwidthBench`.


## Cleanup

To return to a source-only artifact tree:

```bash
./artifact/scripts/clean_generated.sh
```

## Troubleshooting

- If CMake cannot find EMP, export `EMP_TOOL_ROOT` and `CMAKE_PREFIX_PATH`.
- If `picogram/googletest` is missing or broken, rerun
  `python3 run_picogram_compare.py ...`; it recreates the symlink.
- If a large run exhausts memory or takes too long, reduce `--max-exp`.
- Install only for plotting:
  `python3 -m pip install matplotlib numpy`.


## Claims

- **Functional.** The artifact builds and runs, implementing the garbled merge of Theorem 2 and the end-to-end Garbled RAM of Section 5.3 using **only symmetric-key primitives** (a CCR hash via fixed-key AES). No public-key (DDH) assumption is used.
#### Garbled merge
 
- **C1.** Communication of our merge is **linear in both `n` and `w`**, matching the `(w+1)·n·λ`-bit bound of Theorem 2. *(Fig. 9b)*
- **C2.** Our merge cuts communication by **≈3×** versus PicoGRAM's DDH-based merge: at `n = 2^11`, `w = 128`, ours is ≈4.1 MB vs ≈14.8 MB. *(Fig. 9b)*
- **C3.** Our merge cuts communication by **≈10×** versus the Goodrich-style Boolean compaction network: at `n = 2^11`, `w = 32`, ours is ≈1 MB vs ≈24 MB. *(Fig. 9b)*
- **C4.** Our merge cuts communication by **≈21×** versus the Boolean-circuit baseline: at `n = 2^10`, `w = 128`, ours is ≈2.1 MB vs >44 MB. *(Sec. 6.1)*
- **C5.** These savings trade off **higher local computation** — `Θ(w·n²)` hash calls — roughly two orders of magnitude more than the Boolean compaction network at `n = 2^12`. *(Fig. 9a)*
#### End-to-end Garbled RAM
 
- **C6.** Replacing **only** PicoGRAM's stack subroutine with our garbled merge lowers amortized communication **per RAM access across all sizes** `N = 2^10` to `2^24`, with our curve lying uniformly below PicoGRAM's. *(Fig. 10a)*
- **C7.** Our construction keeps the stack's share of total communication at **≈20%**, versus **≈25–34%** for PicoGRAM. *(Fig. 10b)*