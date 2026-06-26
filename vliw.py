#!/usr/bin/env python3
"""Tiny VLIW schedule checker for the interview problem."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


SLOTS = ("load", "store", "int0", "int1", "fp")
INT_OPS = {"iadd", "isub", "imul"}
FP_OPS = {"fadd", "fmul"}
ARITH_OPS = INT_OPS | FP_OPS
LATENCY = {
    "load": 3,
    "store": 1,
    "iadd": 1,
    "isub": 1,
    "imul": 2,
    "fadd": 3,
    "fmul": 4,
}


@dataclass(frozen=True)
class Operation:
    id: int
    opcode: str
    dest: str | None
    args: tuple[str, ...]
    line_no: int

    @property
    def slot_kind(self) -> str:
        if self.opcode == "load":
            return "load"
        if self.opcode == "store":
            return "store"
        if self.opcode in INT_OPS:
            return "int"
        if self.opcode in FP_OPS:
            return "fp"
        raise ValueError(f"unknown opcode {self.opcode!r}")

    @property
    def source_registers(self) -> tuple[str, ...]:
        if self.opcode == "load":
            return ()
        if self.opcode == "store":
            return (self.args[1],)
        return self.args


@dataclass(frozen=True)
class ScheduledOp:
    cycle: int
    slot: str
    op_id: int


class CheckError(Exception):
    pass


def strip_comment(line: str) -> str:
    return line.split("#", 1)[0].strip()


def parse_program(text: str) -> dict[int, Operation]:
    operations: dict[int, Operation] = {}

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = strip_comment(raw_line)
        if not line:
            continue

        match = re.fullmatch(r"(\d+)\s*:\s*(.+)", line)
        if not match:
            raise CheckError(f"line {line_no}: expected '<id>: <operation>'")

        op_id = int(match.group(1))
        body = match.group(2)
        if op_id in operations:
            raise CheckError(f"line {line_no}: duplicate operation id {op_id}")

        if body.startswith("store "):
            pieces = split_args(body.removeprefix("store "))
            if len(pieces) != 2:
                raise CheckError(f"line {line_no}: store expects address and value")
            op = Operation(op_id, "store", None, tuple(pieces), line_no)
        else:
            assign = re.fullmatch(r"([a-z][A-Za-z0-9_]*)\s*=\s*(\w+)\s+(.+)", body)
            if not assign:
                raise CheckError(f"line {line_no}: expected assignment or store")
            dest, opcode, arg_text = assign.groups()
            pieces = split_args(arg_text)
            if opcode == "load":
                if len(pieces) != 1:
                    raise CheckError(f"line {line_no}: load expects one address")
            elif opcode in ARITH_OPS:
                if len(pieces) != 2:
                    raise CheckError(f"line {line_no}: {opcode} expects two registers")
            else:
                raise CheckError(f"line {line_no}: unknown opcode {opcode!r}")
            op = Operation(op_id, opcode, dest, tuple(pieces), line_no)

        operations[op_id] = op

    if not operations:
        raise CheckError("program is empty")

    validate_program(operations)
    return operations


def split_args(text: str) -> list[str]:
    return [arg.strip() for arg in text.split(",") if arg.strip()]


def validate_program(operations: dict[int, Operation]) -> None:
    defs: dict[str, int] = {}

    for op_id in sorted(operations):
        op = operations[op_id]

        if op.dest is not None:
            if op.dest in defs:
                raise CheckError(
                    f"line {op.line_no}: register {op.dest!r} is written more than once"
                )

        if op.opcode in ARITH_OPS:
            for reg in op.args:
                if reg not in defs:
                    raise CheckError(
                        f"line {op.line_no}: {op.opcode} operand {reg!r} is not an earlier register"
                    )

        if op.opcode == "store":
            value = op.args[1]
            if value not in defs:
                raise CheckError(
                    f"line {op.line_no}: store value {value!r} is not an earlier register"
                )

        if op.dest is not None:
            defs[op.dest] = op_id


def parse_schedule(text: str) -> list[ScheduledOp]:
    scheduled: list[ScheduledOp] = []
    seen_cycles: set[int] = set()

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = strip_comment(raw_line)
        if not line:
            continue

        match = re.fullmatch(r"cycle\s+(\d+)\s*:\s*(.+)", line)
        if not match:
            raise CheckError(f"line {line_no}: expected 'cycle <n>: ...'")

        cycle = int(match.group(1))
        if cycle in seen_cycles:
            raise CheckError(f"line {line_no}: duplicate cycle {cycle}")
        seen_cycles.add(cycle)

        fields = [field.strip() for field in match.group(2).split("|")]
        slot_values: dict[str, str] = {}
        for field in fields:
            slot_match = re.fullmatch(r"(load|store|int0|int1|fp)\s*:\s*(-|\d+)", field)
            if not slot_match:
                raise CheckError(f"line {line_no}: bad slot field {field!r}")
            slot, value = slot_match.groups()
            if slot in slot_values:
                raise CheckError(f"line {line_no}: duplicate slot {slot!r}")
            slot_values[slot] = value

        missing = set(SLOTS) - set(slot_values)
        if missing:
            raise CheckError(f"line {line_no}: missing slots: {', '.join(sorted(missing))}")

        for slot in SLOTS:
            value = slot_values[slot]
            if value != "-":
                scheduled.append(ScheduledOp(cycle, slot, int(value)))

    return scheduled


def check_schedule(
    operations: dict[int, Operation],
    scheduled: list[ScheduledOp],
    *,
    max_cycles: int | None = None,
    strict_memory_order: bool = False,
) -> int:
    placements: dict[int, ScheduledOp] = {}

    for placed in scheduled:
        if placed.op_id not in operations:
            raise CheckError(
                f"cycle {placed.cycle}, slot {placed.slot}: unknown operation {placed.op_id}"
            )
        if placed.op_id in placements:
            first = placements[placed.op_id]
            raise CheckError(
                f"operation {placed.op_id} appears more than once "
                f"(cycle {first.cycle} and cycle {placed.cycle})"
            )
        placements[placed.op_id] = placed

        op = operations[placed.op_id]
        if not slot_accepts(placed.slot, op):
            raise CheckError(
                f"cycle {placed.cycle}, slot {placed.slot}: "
                f"operation {placed.op_id} ({op.opcode}) cannot use this slot"
            )

    missing = set(operations) - set(placements)
    if missing:
        raise CheckError(f"schedule is missing operations: {format_ids(missing)}")

    extra = set(placements) - set(operations)
    if extra:
        raise CheckError(f"schedule contains unknown operations: {format_ids(extra)}")

    defs = {
        op.dest: op_id
        for op_id, op in operations.items()
        if op.dest is not None
    }

    for op_id, op in operations.items():
        op_cycle = placements[op_id].cycle
        for reg in op.source_registers:
            producer_id = defs[reg]
            producer = operations[producer_id]
            producer_cycle = placements[producer_id].cycle
            ready_cycle = producer_cycle + LATENCY[producer.opcode]
            if op_cycle < ready_cycle:
                raise CheckError(
                    f"operation {op_id} uses register {reg!r} in cycle {op_cycle}, "
                    f"but operation {producer_id} produces it in cycle {ready_cycle}"
                )

    if strict_memory_order:
        memory_ops = [
            op_id
            for op_id in sorted(operations)
            if operations[op_id].opcode in {"load", "store"}
        ]
        for earlier, later in zip(memory_ops, memory_ops[1:]):
            if placements[earlier].cycle > placements[later].cycle:
                raise CheckError(
                    f"memory operation {earlier} is scheduled after later memory operation {later}"
                )

    cycle_count = 0 if not placements else max(p.cycle for p in placements.values()) + 1
    if max_cycles is not None and cycle_count > max_cycles:
        raise CheckError(f"schedule takes {cycle_count} cycles, above limit {max_cycles}")

    return cycle_count


def slot_accepts(slot: str, op: Operation) -> bool:
    if op.slot_kind == "int":
        return slot in {"int0", "int1"}
    return slot == op.slot_kind


def format_ids(ids: set[int]) -> str:
    return ", ".join(str(op_id) for op_id in sorted(ids))


def load_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and score a VLIW schedule.",
    )
    parser.add_argument("program", help="path to a .vliw program")
    parser.add_argument("schedule", help="path to a .sched answer")
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="fail if the schedule takes more than this many cycles",
    )
    parser.add_argument(
        "--strict-memory-order",
        action="store_true",
        help="require all loads/stores to preserve source order",
    )
    args = parser.parse_args(argv)

    try:
        operations = parse_program(load_text(args.program))
        scheduled = parse_schedule(load_text(args.schedule))
        cycles = check_schedule(
            operations,
            scheduled,
            max_cycles=args.max_cycles,
            strict_memory_order=args.strict_memory_order,
        )
    except CheckError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    print(f"OK: valid schedule, cycles={cycles}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
