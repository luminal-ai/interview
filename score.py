#!/usr/bin/env python3
"""Luminal Compiler Take Home — compiler engineering public benchmark."""

from __future__ import annotations

import math
from pathlib import Path

import compiler
import machine


PROGRAM_DIR = Path(__file__).parent / "programs"


def main() -> int:
    print("Luminal Compiler Take Home — compiler engineering public benchmark")
    speedups = []
    reductions = []
    print(f"{'program':30} {'cycles':>8} {'baseline':>9} {'speedup':>9} {'scratch':>8} {'reduction':>10}")
    print("-" * 60)
    for path in sorted(PROGRAM_DIR.glob("*.json")):
        program = machine.load_program(path)
        compilation = compiler.compile_program(program)
        cycles = machine.check_compilation(program, compilation)
        for case in program["cases"]:
            machine.check_case(program, compilation, case)
        baseline = machine.check_compilation(program, machine.serial_compile(program))
        speedup = baseline / cycles
        speedups.append(speedup)
        words = machine.scratch_footprint(program, compilation)
        baseline_words = machine.scratch_footprint(program, machine.serial_compile(program))
        reduction = baseline_words / words
        reductions.append(reduction)
        print(f"{program['name']:30} {cycles:8d} {baseline:9d} {speedup:8.3f}x {words:8d} {reduction:9.3f}x")

    geometric_mean = math.prod(speedups) ** (1 / len(speedups))
    print("-" * 60)
    print(f"public geometric-mean speedup: {geometric_mean:.3f}x")
    scratch_mean = math.prod(reductions) ** (1 / len(reductions))
    print(f"public geometric-mean scratch reduction: {scratch_mean:.3f}x")
    print(f"public combined score: {math.sqrt(geometric_mean * scratch_mean):.3f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
