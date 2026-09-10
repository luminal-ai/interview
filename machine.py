#!/usr/bin/env python3
"""Luminal Compiler Take Home — compiler engineering machine and validator."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path


VLEN = 8
SCRATCH_WORDS = 256
WORD_MASK = (1 << 32) - 1

ENGINE_LIMITS = {
    "load": 2,
    "scalar": 2,
    "vector": 2,
    "store": 1,
    "flow": 1,
}


def _spec(engine: str, latency: int, result: str | None, args: tuple[str, ...]):
    return {"engine": engine, "latency": latency, "result": result, "args": args}


OP_SPECS = {
    "const": _spec("load", 1, "scalar", ()),
    "load": _spec("load", 3, "scalar", ()),
    "vload": _spec("load", 4, "vector", ()),
    "store": _spec("store", 1, None, ("scalar",)),
    "vstore": _spec("store", 1, None, ("vector",)),
    "add": _spec("scalar", 1, "scalar", ("scalar", "scalar")),
    "sub": _spec("scalar", 1, "scalar", ("scalar", "scalar")),
    "mul": _spec("scalar", 2, "scalar", ("scalar", "scalar")),
    "xor": _spec("scalar", 1, "scalar", ("scalar", "scalar")),
    "and": _spec("scalar", 1, "scalar", ("scalar", "scalar")),
    "or": _spec("scalar", 1, "scalar", ("scalar", "scalar")),
    "shl": _spec("scalar", 1, "scalar", ("scalar", "scalar")),
    "shr": _spec("scalar", 1, "scalar", ("scalar", "scalar")),
    "eq": _spec("scalar", 1, "scalar", ("scalar", "scalar")),
    "lt": _spec("scalar", 1, "scalar", ("scalar", "scalar")),
    "vadd": _spec("vector", 1, "vector", ("vector", "vector")),
    "vsub": _spec("vector", 1, "vector", ("vector", "vector")),
    "vmul": _spec("vector", 3, "vector", ("vector", "vector")),
    "vxor": _spec("vector", 1, "vector", ("vector", "vector")),
    "vand": _spec("vector", 1, "vector", ("vector", "vector")),
    "vor": _spec("vector", 1, "vector", ("vector", "vector")),
    "vshl": _spec("vector", 1, "vector", ("vector", "vector")),
    "vshr": _spec("vector", 1, "vector", ("vector", "vector")),
    "splat": _spec("vector", 1, "vector", ("scalar",)),
    "select": _spec("flow", 1, "scalar", ("scalar", "scalar", "scalar")),
    "vselect": _spec("flow", 2, "vector", ("vector", "vector", "vector")),
}

MEMORY_OPS = {"load", "vload", "store", "vstore"}
LOAD_OPS = {"load", "vload"}
STORE_OPS = {"store", "vstore"}


class ProgramError(ValueError):
    pass


class CompileError(ValueError):
    pass


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def u32(value: int) -> int:
    return value & WORD_MASK


def load_program(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        program = json.load(handle)
    validate_program(program)
    return program


def validate_program(program: dict) -> None:
    if not isinstance(program, dict):
        raise ProgramError("program must be a JSON object")
    if not isinstance(program.get("name"), str) or not program["name"]:
        raise ProgramError("program requires a non-empty name")

    buffers = program.get("buffers")
    if not isinstance(buffers, dict) or not buffers:
        raise ProgramError("program requires at least one memory buffer")
    for name, length in buffers.items():
        if not isinstance(name, str) or not name:
            raise ProgramError("buffer names must be non-empty strings")
        if not _plain_int(length) or length <= 0:
            raise ProgramError(f"buffer {name!r} must have a positive integer length")

    operations = program.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ProgramError("program requires a non-empty operations list")

    definitions: dict[str, str] = {}
    for expected_id, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ProgramError(f"operation {expected_id} must be an object")
        if operation.get("id") != expected_id:
            raise ProgramError(
                f"operation IDs must be consecutive: expected {expected_id}, "
                f"found {operation.get('id')!r}"
            )

        opcode = operation.get("op")
        if opcode not in OP_SPECS:
            raise ProgramError(f"operation {expected_id} has unknown op {opcode!r}")
        spec = OP_SPECS[opcode]

        args = operation.get("args", [])
        if not isinstance(args, list) or len(args) != len(spec["args"]):
            raise ProgramError(
                f"operation {expected_id} ({opcode}) expects "
                f"{len(spec['args'])} arguments"
            )
        for index, (arg, expected_kind) in enumerate(zip(args, spec["args"])):
            if arg not in definitions:
                raise ProgramError(
                    f"operation {expected_id} argument {arg!r} is not an earlier value"
                )
            actual_kind = definitions[arg]
            if actual_kind != expected_kind:
                raise ProgramError(
                    f"operation {expected_id} argument {index} expects {expected_kind}, "
                    f"got {actual_kind} value {arg!r}"
                )

        result_kind = spec["result"]
        if result_kind is None:
            if "dest" in operation:
                raise ProgramError(f"operation {expected_id} ({opcode}) cannot have a dest")
        else:
            dest = operation.get("dest")
            if not isinstance(dest, str) or not dest:
                raise ProgramError(f"operation {expected_id} ({opcode}) requires a dest")
            if dest in definitions:
                raise ProgramError(f"SSA value {dest!r} is defined more than once")
            definitions[dest] = result_kind

        if opcode == "const":
            if not _plain_int(operation.get("value")):
                raise ProgramError(f"operation {expected_id} const requires integer value")
        elif opcode in MEMORY_OPS:
            _validate_memory_operation(program, operation)

    cases = program.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ProgramError("program requires at least one test case")
    for case_index, case in enumerate(cases):
        validate_case(program, case, case_index)


def _plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_memory_operation(program: dict, operation: dict) -> None:
    op_id = operation["id"]
    buffer = operation.get("buffer")
    if buffer not in program["buffers"]:
        raise ProgramError(f"operation {op_id} references unknown buffer {buffer!r}")
    offset = operation.get("offset")
    if not _plain_int(offset) or offset < 0:
        raise ProgramError(f"operation {op_id} requires a non-negative integer offset")
    width = memory_width(operation)
    if offset + width > program["buffers"][buffer]:
        raise ProgramError(
            f"operation {op_id} accesses {buffer}[{offset}:{offset + width}] "
            f"past length {program['buffers'][buffer]}"
        )


def validate_case(program: dict, case: dict, case_index: int | None = None) -> None:
    label = "case" if case_index is None else f"case {case_index}"
    if not isinstance(case, dict):
        raise ProgramError(f"{label} must be an object")
    expected_buffers = set(program["buffers"])
    actual_buffers = set(case)
    if actual_buffers != expected_buffers:
        missing = sorted(expected_buffers - actual_buffers)
        extra = sorted(actual_buffers - expected_buffers)
        raise ProgramError(f"{label} buffer mismatch: missing={missing}, extra={extra}")
    for name, length in program["buffers"].items():
        values = case[name]
        if not isinstance(values, list) or len(values) != length:
            raise ProgramError(f"{label} buffer {name!r} must contain {length} words")
        if any(not _plain_int(value) for value in values):
            raise ProgramError(f"{label} buffer {name!r} contains a non-integer word")


def producer_map(program: dict) -> dict[str, int]:
    return {
        operation["dest"]: operation["id"]
        for operation in program["operations"]
        if OP_SPECS[operation["op"]]["result"] is not None
    }


def result_kinds(program: dict) -> dict[str, str]:
    return {
        operation["dest"]: OP_SPECS[operation["op"]]["result"]
        for operation in program["operations"]
        if OP_SPECS[operation["op"]]["result"] is not None
    }


def memory_width(operation: dict) -> int:
    return VLEN if operation["op"] in {"vload", "vstore"} else 1


def memory_predecessors(program: dict, op_id: int) -> list[int]:
    """Return earlier memory operations that must issue before op_id."""

    operation = program["operations"][op_id]
    if operation["op"] not in MEMORY_OPS:
        return []

    predecessors = []
    for earlier in program["operations"][:op_id]:
        if earlier["op"] not in MEMORY_OPS:
            continue
        if earlier["buffer"] != operation["buffer"]:
            continue
        if not _memory_ranges_overlap(earlier, operation):
            continue
        if earlier["op"] in LOAD_OPS and operation["op"] in LOAD_OPS:
            continue
        predecessors.append(earlier["id"])
    return predecessors


def _memory_ranges_overlap(first: dict, second: dict) -> bool:
    first_start = first["offset"]
    second_start = second["offset"]
    return (
        first_start < second_start + memory_width(second)
        and second_start < first_start + memory_width(first)
    )


def serial_compile(program: dict) -> dict:
    """Frozen serial baseline used to calculate speedup."""

    scratch: dict[str, int] = {}
    cursor = 0
    for kind in ("vector", "scalar"):
        for operation in program["operations"]:
            if OP_SPECS[operation["op"]]["result"] != kind:
                continue
            if kind == "vector":
                cursor = align_up(cursor, VLEN)
                scratch[operation["dest"]] = cursor
                cursor += VLEN
            else:
                scratch[operation["dest"]] = cursor
                cursor += 1
    if cursor > SCRATCH_WORDS:
        raise CompileError("serial allocation exceeds scratch capacity")

    bundles: list[dict[str, list[int]]] = []
    issue_cycle: dict[int, int] = {}
    producers = producer_map(program)
    for operation in program["operations"]:
        earliest = len(bundles)
        for arg in operation.get("args", []):
            pred_id = producers[arg]
            pred = program["operations"][pred_id]
            earliest = max(
                earliest, issue_cycle[pred_id] + OP_SPECS[pred["op"]]["latency"]
            )
        for pred_id in memory_predecessors(program, operation["id"]):
            earliest = max(earliest, issue_cycle[pred_id] + 1)
        while len(bundles) < earliest:
            bundles.append({})
        engine = OP_SPECS[operation["op"]]["engine"]
        bundles.append({engine: [operation["id"]]})
        issue_cycle[operation["id"]] = earliest
    return {"scratch": scratch, "bundles": bundles}


def check_compilation(program: dict, compilation: dict) -> int:
    validate_program(program)
    if not isinstance(compilation, dict):
        raise CompileError("compiler result must be an object")
    scratch = compilation.get("scratch")
    bundles = compilation.get("bundles")
    if not isinstance(scratch, dict):
        raise CompileError("compiler result requires a scratch mapping")
    if not isinstance(bundles, list) or not bundles:
        raise CompileError("compiler result requires a non-empty bundles list")

    issue_cycle = _collect_issue_cycles(program, bundles)
    _check_scratch_allocations(program, scratch, issue_cycle)
    operations = program["operations"]
    producers = producer_map(program)

    for operation in operations:
        cycle = issue_cycle[operation["id"]]
        for arg in operation.get("args", []):
            pred_id = producers[arg]
            pred = operations[pred_id]
            ready = issue_cycle[pred_id] + OP_SPECS[pred["op"]]["latency"]
            if cycle < ready:
                raise CompileError(
                    f"operation {operation['id']} uses {arg!r} in cycle {cycle}, "
                    f"but operation {pred_id} produces it in cycle {ready}"
                )
        for pred_id in memory_predecessors(program, operation["id"]):
            if cycle <= issue_cycle[pred_id]:
                raise CompileError(
                    f"memory operation {operation['id']} must issue after overlapping "
                    f"operation {pred_id}"
                )
    return len(bundles)


def scratch_footprint(program: dict, compilation: dict) -> int:
    """Highest allocated scratch end address, in words (including holes)."""
    return max(
        (compilation["scratch"][name] + (VLEN if kind == "vector" else 1)
         for name, kind in result_kinds(program).items()), default=0
    )


def _check_scratch_allocations(program: dict, scratch: dict,
                               issue_cycle: dict[int, int]) -> None:
    kinds = result_kinds(program)
    if set(scratch) != set(kinds):
        missing = sorted(set(kinds) - set(scratch))
        extra = sorted(set(scratch) - set(kinds))
        raise CompileError(f"scratch mapping mismatch: missing={missing}, extra={extra}")

    # Writes commit at the beginning of a cycle, before all operand reads.
    # Even an unused result writes scratch and can clobber another live value.
    lifetimes = {}
    for operation in program["operations"]:
        if "dest" in operation:
            ready = issue_cycle[operation["id"]] + OP_SPECS[operation["op"]]["latency"]
            lifetimes[operation["dest"]] = [ready, ready]
    for operation in program["operations"]:
        for arg in operation.get("args", []):
            lifetimes[arg][1] = max(lifetimes[arg][1], issue_cycle[operation["id"]])

    occupied: list[tuple[int, int, str]] = []
    for name, kind in kinds.items():
        base = scratch[name]
        if not _plain_int(base) or base < 0:
            raise CompileError(f"scratch address for {name!r} must be non-negative integer")
        width = VLEN if kind == "vector" else 1
        if kind == "vector" and base % VLEN != 0:
            raise CompileError(f"vector {name!r} must be aligned to {VLEN} words")
        if base + width > SCRATCH_WORDS:
            raise CompileError(
                f"scratch allocation {name!r} ends at {base + width}, "
                f"past limit {SCRATCH_WORDS}"
            )
        for other_start, other_end, other_name in occupied:
            start, end = lifetimes[name]
            other_live_start, other_live_end = lifetimes[other_name]
            if (base < other_end and other_start < base + width
                    and start <= other_live_end and other_live_start <= end):
                raise CompileError(
                    f"scratch allocations {name!r} and {other_name!r} overlap while live"
                )
        occupied.append((base, base + width, name))


def _collect_issue_cycles(program: dict, bundles: list) -> dict[int, int]:
    issue_cycle: dict[int, int] = {}
    operations = program["operations"]
    for cycle, bundle in enumerate(bundles):
        if not isinstance(bundle, dict):
            raise CompileError(f"bundle {cycle} must be an object")
        for engine, op_ids in bundle.items():
            if engine not in ENGINE_LIMITS:
                raise CompileError(f"bundle {cycle} uses unknown engine {engine!r}")
            if not isinstance(op_ids, list):
                raise CompileError(f"bundle {cycle} engine {engine} must contain a list")
            if len(op_ids) > ENGINE_LIMITS[engine]:
                raise CompileError(
                    f"bundle {cycle} has {len(op_ids)} {engine} operations, "
                    f"limit is {ENGINE_LIMITS[engine]}"
                )
            for op_id in op_ids:
                if not _plain_int(op_id) or not 0 <= op_id < len(operations):
                    raise CompileError(f"bundle {cycle} contains unknown operation {op_id!r}")
                if op_id in issue_cycle:
                    raise CompileError(
                        f"operation {op_id} appears in cycles {issue_cycle[op_id]} and {cycle}"
                    )
                expected_engine = OP_SPECS[operations[op_id]["op"]]["engine"]
                if engine != expected_engine:
                    raise CompileError(
                        f"operation {op_id} ({operations[op_id]['op']}) requires "
                        f"engine {expected_engine}, not {engine}"
                    )
                issue_cycle[op_id] = cycle

    missing = sorted(set(range(len(operations))) - set(issue_cycle))
    if missing:
        raise CompileError(f"schedule is missing operations {missing}")
    return issue_cycle


def run_reference(program: dict, case: dict) -> dict[str, list[int]]:
    validate_program(program)
    validate_case(program, case)
    memory = _copy_case(case)
    values: dict[str, int | list[int]] = {}

    for operation in program["operations"]:
        opcode = operation["op"]
        args = [values[name] for name in operation.get("args", [])]
        result = _evaluate(opcode, args, operation, memory)
        if OP_SPECS[opcode]["result"] is not None:
            values[operation["dest"]] = result
    return memory


def run_compilation(program: dict, compilation: dict, case: dict) -> dict[str, list[int]]:
    check_compilation(program, compilation)
    validate_case(program, case)
    memory = _copy_case(case)
    scratch = [0] * SCRATCH_WORDS
    allocations = compilation["scratch"]
    operations = program["operations"]
    pending: dict[int, list[tuple[int, list[int]]]] = {}

    for cycle, bundle in enumerate(compilation["bundles"]):
        for base, words in pending.pop(cycle, []):
            scratch[base : base + len(words)] = words

        memory_writes: list[tuple[str, int, list[int]]] = []
        for op_ids in bundle.values():
            for op_id in op_ids:
                operation = operations[op_id]
                opcode = operation["op"]
                arg_values = []
                for name, kind in zip(
                    operation.get("args", []), OP_SPECS[opcode]["args"]
                ):
                    base = allocations[name]
                    width = VLEN if kind == "vector" else 1
                    words = scratch[base : base + width]
                    arg_values.append(words if kind == "vector" else words[0])

                if opcode in STORE_OPS:
                    words = arg_values[0] if opcode == "vstore" else [arg_values[0]]
                    memory_writes.append(
                        (operation["buffer"], operation["offset"], list(words))
                    )
                    continue

                result = _evaluate(opcode, arg_values, operation, memory)
                words = result if isinstance(result, list) else [result]
                ready = cycle + OP_SPECS[opcode]["latency"]
                pending.setdefault(ready, []).append(
                    (allocations[operation["dest"]], list(words))
                )

        for buffer, offset, words in memory_writes:
            memory[buffer][offset : offset + len(words)] = words

    return memory


def check_case(program: dict, compilation: dict, case: dict) -> None:
    expected = run_reference(program, case)
    actual = run_compilation(program, compilation, case)
    if actual != expected:
        mismatches = []
        for buffer in program["buffers"]:
            if actual[buffer] != expected[buffer]:
                mismatches.append(buffer)
        raise CompileError(f"incorrect final memory in buffers {mismatches}")


def _copy_case(case: dict) -> dict[str, list[int]]:
    return {name: [u32(value) for value in words] for name, words in deepcopy(case).items()}


def _evaluate(opcode: str, args: list, operation: dict, memory: dict):
    if opcode == "const":
        return u32(operation["value"])
    if opcode == "load":
        return memory[operation["buffer"]][operation["offset"]]
    if opcode == "vload":
        offset = operation["offset"]
        return list(memory[operation["buffer"]][offset : offset + VLEN])
    if opcode == "store":
        memory[operation["buffer"]][operation["offset"]] = u32(args[0])
        return None
    if opcode == "vstore":
        offset = operation["offset"]
        memory[operation["buffer"]][offset : offset + VLEN] = [u32(v) for v in args[0]]
        return None
    if opcode in {"add", "sub", "mul", "xor", "and", "or", "shl", "shr", "eq", "lt"}:
        return _scalar_binary(opcode, args[0], args[1])
    if opcode in {"vadd", "vsub", "vmul", "vxor", "vand", "vor", "vshl", "vshr"}:
        scalar_opcode = opcode[1:]
        return [_scalar_binary(scalar_opcode, a, b) for a, b in zip(args[0], args[1])]
    if opcode == "splat":
        return [u32(args[0])] * VLEN
    if opcode == "select":
        return u32(args[1] if args[0] != 0 else args[2])
    if opcode == "vselect":
        return [u32(a if cond != 0 else b) for cond, a, b in zip(*args)]
    raise AssertionError(f"unhandled operation {opcode}")


def _scalar_binary(opcode: str, first: int, second: int) -> int:
    first = u32(first)
    second = u32(second)
    if opcode == "add":
        return u32(first + second)
    if opcode == "sub":
        return u32(first - second)
    if opcode == "mul":
        return u32(first * second)
    if opcode == "xor":
        return first ^ second
    if opcode == "and":
        return first & second
    if opcode == "or":
        return first | second
    if opcode == "shl":
        return u32(first << (second & 31))
    if opcode == "shr":
        return first >> (second & 31)
    if opcode == "eq":
        return int(first == second)
    if opcode == "lt":
        return int(first < second)
    raise AssertionError(f"unhandled binary operation {opcode}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 machine.py <program.json> <schedule.json>", file=sys.stderr)
        return 2
    try:
        program = load_program(argv[0])
        with Path(argv[1]).open(encoding="utf-8") as handle:
            compilation = json.load(handle)
        cycles = check_compilation(program, compilation)
        for case in program["cases"]:
            check_case(program, compilation, case)
    except (OSError, json.JSONDecodeError, ProgramError, CompileError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {program['name']}, cases={len(program['cases'])}, cycles={cycles}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
