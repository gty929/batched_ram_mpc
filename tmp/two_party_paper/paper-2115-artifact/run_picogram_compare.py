#!/usr/bin/env python3

import argparse
import csv
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_PROJECTS = ("picogram", "picogram_imp")
RESULT_PATTERN = re.compile(r"([A-Za-z_]+)=([0-9]+)")
REQUIRED_KEYS = {
    "N",
    "T",
    "W",
    "gc_size_bytes",
    "garble_time_ms",
    "eval_time_ms",
}


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    if env is None:
        env = os.environ.copy()
    emp_root = env.get("EMP_TOOL_ROOT")
    if emp_root:
        lib = str(Path(emp_root) / "lib")
        env["LD_LIBRARY_PATH"] = f"{lib}:{env.get('LD_LIBRARY_PATH', '')}"
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
    )


def ensure_local_googletest(project_dir: Path) -> None:
    vendored = project_dir / "googletest"
    cmake_file = vendored / "CMakeLists.txt"
    if cmake_file.exists():
        return

    sibling = ROOT / "picogram_imp" / "googletest" / "CMakeLists.txt"
    if not sibling.exists():
        raise RuntimeError(
            f"Missing googletest in {project_dir / 'googletest'} and no reusable "
            f"sibling copy found at {sibling}"
        )

    if vendored.is_symlink():
        vendored.unlink()

    if vendored.exists() and any(vendored.iterdir()):
        raise RuntimeError(
            f"{vendored} exists but is incomplete; refusing to overwrite it automatically"
        )

    if vendored.exists():
        vendored.rmdir()
    vendored.symlink_to(Path("..") / "picogram_imp" / "googletest")


def ensure_built(project_dir: Path, build_type: str, rebuild: bool) -> Path:
    build_dir = project_dir / "build"
    binary = build_dir / "test_basic"

    ensure_local_googletest(project_dir)

    if rebuild and build_dir.exists():
        proc = run(
            ["cmake", "--build", "build", "--target", "clean"],
            cwd=project_dir,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Failed to clean {project_dir.name} build:\n{proc.stdout}\n{proc.stderr}"
            )

    if not binary.exists():
        configure = run(
            [
                "cmake",
                "-S",
                ".",
                "-B",
                "build",
                f"-DCMAKE_BUILD_TYPE={build_type}",
            ],
            cwd=project_dir,
        )
        if configure.returncode != 0:
            raise RuntimeError(
                f"Failed to configure {project_dir.name}:\n{configure.stdout}\n{configure.stderr}"
            )

        build = run(
            ["cmake", "--build", "build", "-j"],
            cwd=project_dir,
        )
        if build.returncode != 0:
            raise RuntimeError(
                f"Failed to build {project_dir.name}:\n{build.stdout}\n{build.stderr}"
            )

    return binary


def parse_result(output: str) -> dict[str, int]:
    for line in output.splitlines():
        if not line.startswith("REC_ORAM_BENCH_RESULT"):
            continue
        values = {key: int(value) for key, value in RESULT_PATTERN.findall(line)}
        missing = REQUIRED_KEYS - values.keys()
        if missing:
            raise RuntimeError(f"Missing keys in benchmark output: {sorted(missing)}")
        return values
    raise RuntimeError("Did not find REC_ORAM_BENCH_RESULT in benchmark output")


def benchmark_project(
    project: str,
    binary: Path,
    outdir: Path,
    min_exp: int,
    max_exp: int,
    word_width: int,
    simd_threshold: int,
    linear_threshold: int,
    workers: int,
    seed: int,
) -> list[dict[str, float]]:
    project_dir = binary.parent.parent
    raw_path = outdir / f"{project}_bandwidthbench_raw.txt"
    table_path = outdir / f"{project}_time_per_access.txt"

    results: list[dict[str, float]] = []

    with (
        raw_path.open("w", encoding="ascii", buffering=1) as raw_file,
        table_path.open("w", encoding="ascii", newline="", buffering=1) as table_file,
    ):
        writer = csv.writer(table_file, delimiter="\t")
        writer.writerow(
            [
                "project",
                "N",
                "T",
                "W",
                "gc_size_bytes",
                "garble_time_ms",
                "eval_time_ms",
                "garble_ms_per_access",
                "eval_ms_per_access",
                "total_compute_ms_per_access",
            ]
        )
        table_file.flush()
        raw_file.write(
            f"# project={project} workers={workers} word_width={word_width} "
            f"simd_threshold={simd_threshold} linear_threshold={linear_threshold}\n"
        )
        raw_file.flush()
        for exp in range(min_exp, max_exp + 1):
            n = 1 << exp
            print(f"[{project}] benchmarking N={n}", flush=True)
            env = os.environ.copy()
            env["PICOGRAM_RUN_BANDWIDTH_BENCH"] = "1"
            env["PICOGRAM_BENCH_N"] = str(n)
            env["PICOGRAM_BENCH_W"] = str(word_width)
            env["PICOGRAM_BENCH_WORKERS"] = str(workers)
            env["PICOGRAM_BENCH_SIMD_THRESHOLD"] = str(simd_threshold)
            env["PICOGRAM_BENCH_LINEAR_THRESHOLD"] = str(linear_threshold)
            if seed:
                env["PICOGRAM_BENCH_SEED"] = str(seed)

            cmd = [
                str(binary),
                "--gtest_filter=RecORAM.BandwidthBench",
                "--gtest_color=no",
            ]
            proc = run(cmd, cwd=project_dir, env=env)

            raw_file.write(f"\n## N={n}\n")
            raw_file.write(proc.stdout)
            if proc.stderr:
                raw_file.write("\n[stderr]\n")
                raw_file.write(proc.stderr)
                raw_file.write("\n")
            raw_file.flush()

            if proc.returncode != 0:
                raise RuntimeError(
                    f"{project} benchmark failed for N={n}. "
                    f"See {raw_path} for captured output."
                )

            parsed = parse_result(proc.stdout)
            t = parsed["T"]
            garble_time_ms = parsed["garble_time_ms"]
            eval_time_ms = parsed["eval_time_ms"]
            row: dict[str, float] = {
                "project": project,
                "N": parsed["N"],
                "T": t,
                "W": parsed["W"],
                "gc_size_bytes": parsed["gc_size_bytes"],
                "garble_time_ms": garble_time_ms,
                "eval_time_ms": eval_time_ms,
                "garble_ms_per_access": garble_time_ms / t,
                "eval_ms_per_access": eval_time_ms / t,
                "total_compute_ms_per_access": (garble_time_ms + eval_time_ms) / t,
            }
            results.append(row)
            writer.writerow(
                [
                    row["project"],
                    int(row["N"]),
                    int(row["T"]),
                    int(row["W"]),
                    int(row["gc_size_bytes"]),
                    int(row["garble_time_ms"]),
                    int(row["eval_time_ms"]),
                    f"{row['garble_ms_per_access']:.6f}",
                    f"{row['eval_ms_per_access']:.6f}",
                    f"{row['total_compute_ms_per_access']:.6f}",
                ]
            )
            table_file.flush()

    return results


def write_combined(rows: list[dict[str, float]], outdir: Path) -> None:
    combined_path = outdir / "combined_time_per_access.txt"
    with combined_path.open("w", encoding="ascii", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(
            [
                "project",
                "N",
                "garble_ms_per_access",
                "eval_ms_per_access",
                "total_compute_ms_per_access",
            ]
        )
        for row in sorted(rows, key=lambda item: (int(item["N"]), str(item["project"]))):
            writer.writerow(
                [
                    row["project"],
                    int(row["N"]),
                    f"{row['garble_ms_per_access']:.6f}",
                    f"{row['eval_ms_per_access']:.6f}",
                    f"{row['total_compute_ms_per_access']:.6f}",
                ]
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run single-thread RecORAM.BandwidthBench for picogram and picogram_imp, "
            "then store raw logs and per-access timing tables."
        )
    )
    parser.add_argument(
        "--projects",
        nargs="+",
        default=list(DEFAULT_PROJECTS),
        help="Projects to benchmark. Default: picogram picogram_imp",
    )
    parser.add_argument("--min-exp", type=int, default=5, help="Min exponent for N=2^exp")
    parser.add_argument("--max-exp", type=int, default=16, help="Max exponent for N=2^exp")
    parser.add_argument("--word-width", type=int, default=64, help="RecORAM word width")
    parser.add_argument(
        "--simd-threshold",
        type=int,
        default=32,
        help="SIMD link threshold for the communication-optimized configuration",
    )
    parser.add_argument(
        "--linear-threshold",
        type=int,
        default=512,
        help="Linear ORAM threshold",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="SIMD worker threads. Use 0 for the no-multithread run.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help="PRNG seed for RecORAM.BandwidthBench. Use 0 for time-based randomness.",
    )
    parser.add_argument(
        "--build-type",
        default="Release",
        choices=["Release", "Debug", "RelWithDebInfo", "MinSizeRel"],
        help="CMake build type if a project must be built",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Require an existing build/test_basic instead of configuring/building",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Clean and rebuild when build/test_basic is missing or stale",
    )
    parser.add_argument(
        "--outdir",
        default="benchmark_results",
        help="Directory for raw logs and parsed timing tables",
    )
    args = parser.parse_args()

    outdir = (ROOT / args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, float]] = []

    for project in args.projects:
        project_dir = ROOT / project
        if not project_dir.is_dir():
            raise RuntimeError(f"Missing project directory: {project_dir}")

        binary = project_dir / "build" / "test_basic"
        if args.skip_build:
            if not binary.exists():
                raise RuntimeError(f"Missing benchmark binary: {binary}")
        else:
            binary = ensure_built(project_dir, args.build_type, args.rebuild)

        rows = benchmark_project(
            project=project,
            binary=binary,
            outdir=outdir,
            min_exp=args.min_exp,
            max_exp=args.max_exp,
            word_width=args.word_width,
            simd_threshold=args.simd_threshold,
            linear_threshold=args.linear_threshold,
            workers=args.workers,
            seed=args.seed,
        )
        all_rows.extend(rows)

    write_combined(all_rows, outdir)

    print(f"Wrote benchmark outputs to {outdir}")
    for project in args.projects:
        print(f"  - {outdir / f'{project}_bandwidthbench_raw.txt'}")
        print(f"  - {outdir / f'{project}_time_per_access.txt'}")
    print(f"  - {outdir / 'combined_time_per_access.txt'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
