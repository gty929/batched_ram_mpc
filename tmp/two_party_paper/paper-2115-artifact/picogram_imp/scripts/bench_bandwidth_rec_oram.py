#!/usr/bin/env python3

import argparse
import csv
import math
import os
import re
import subprocess
import sys
from pathlib import Path


def logspace(start: float, stop: float, num: int) -> list[float]:
    if num <= 1:
        return [float(start)]
    a = math.log10(start)
    b = math.log10(stop)
    return [10 ** (a + (b - a) * i / (num - 1)) for i in range(num)]


def parse_bench_result(output: str) -> dict[str, int]:
    for line in output.splitlines():
        if not line.startswith("REC_ORAM_BENCH_RESULT"):
            continue
        pairs = dict(re.findall(r"([A-Za-z_]+)=([0-9]+)", line))
        required = {
            "N",
            "T",
            "W",
            "gc_size_bytes",
            "garble_time_ms",
            "eval_time_ms",
        }
        missing = required - set(pairs.keys())
        if missing:
            raise ValueError(f"Missing keys in bench output: {sorted(missing)}")
        return {k: int(v) for k, v in pairs.items()}
    raise ValueError("Did not find REC_ORAM_BENCH_RESULT line in output")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run RecORAM.BandwidthBench once and simulate end-to-end runtime under "
            "varying bandwidths. Bandwidth is Mbps; times are milliseconds."
        )
    )
    parser.add_argument("--build-dir", default="build", help="CMake build dir")
    parser.add_argument("--out", default="scripts/rec_oram_bandwidth.csv", help="CSV output path")

    parser.add_argument("--N", type=int, default=1024, help="RAM size and #accesses (T)")
    parser.add_argument("--W", type=int, default=64, help="Word width in bits")
    parser.add_argument("--workers", type=int, default=0, help="SIMD worker threads")
    parser.add_argument("--simd-threshold", type=int, default=32, help="SIMD link threshold")
    parser.add_argument(
        "--linear-threshold", type=int, default=512, help="Linear ORAM threshold"
    )
    parser.add_argument("--seed", type=int, default=0, help="PRNG seed (0 = time-based)")

    parser.add_argument(
        "--bandwidths",
        default="",
        help="Comma-separated Mbps values (overrides --bw-min/max/points)",
    )
    parser.add_argument("--bw-min", type=float, default=10.0, help="Min bandwidth (Mbps)")
    parser.add_argument(
        "--bw-max", type=float, default=10 ** 3.6, help="Max bandwidth (Mbps)"
    )
    parser.add_argument("--bw-points", type=int, default=100, help="#bandwidth points")

    args = parser.parse_args()

    test_binary = Path(args.build_dir) / "test_basic"
    if not test_binary.exists():
        print(f"Missing test binary: {test_binary}", file=sys.stderr)
        print(
            "Build first, e.g.: rm -rf build && cmake -S . -B build -G 'Unix Makefiles' "
            "-DCMAKE_BUILD_TYPE=Release && cmake --build build -j",
            file=sys.stderr,
        )
        return 2

    env = os.environ.copy()
    env["PICOGRAM_RUN_BANDWIDTH_BENCH"] = "1"
    env["PICOGRAM_BENCH_N"] = str(args.N)
    env["PICOGRAM_BENCH_W"] = str(args.W)
    env["PICOGRAM_BENCH_WORKERS"] = str(args.workers)
    env["PICOGRAM_BENCH_SIMD_THRESHOLD"] = str(args.simd_threshold)
    env["PICOGRAM_BENCH_LINEAR_THRESHOLD"] = str(args.linear_threshold)
    if args.seed:
        env["PICOGRAM_BENCH_SEED"] = str(args.seed)

    cmd = [
        str(test_binary),
        "--gtest_filter=RecORAM.BandwidthBench",
        "--gtest_color=no",
    ]
    proc = subprocess.run(cmd, env=env, text=True, capture_output=True)
    if proc.returncode != 0:
        print(proc.stdout, end="")
        print(proc.stderr, end="", file=sys.stderr)
        return proc.returncode

    result = parse_bench_result(proc.stdout)
    gc_size_bytes = result["gc_size_bytes"]
    T = result["T"]
    garble_time_ms = result["garble_time_ms"]
    eval_time_ms = result["eval_time_ms"]

    if args.bandwidths.strip():
        bws = [float(x) for x in args.bandwidths.split(",") if x.strip()]
    else:
        bws = logspace(args.bw_min, args.bw_max, args.bw_points)
    bws = sorted(bws)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["bandwidth", "e2etime", "garbler_time", "eval_time", "time_per_access"]
        )
        for bw in bws:
            comm_ms_total = gc_size_bytes * 8.0 / (bw * 1e6)
            e2e_ms_total = comm_ms_total+ float(garble_time_ms) + float(eval_time_ms)
            time_per_access_ms = e2e_ms_total / float(T)
            writer.writerow(
                [
                    f"{bw:.6g}",
                    f"{e2e_ms_total:.6f}",
                    f"{float(garble_time_ms):.6f}",
                    f"{float(eval_time_ms):.6f}",
                    f"{time_per_access_ms:.6f}",
                ]
            )

    print(
        f"Wrote {out_path} (N={result['N']} T={T} W={result['W']} gc={gc_size_bytes}B "
        f"garble={garble_time_ms}ms eval={eval_time_ms}ms)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

