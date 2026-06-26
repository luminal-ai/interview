# VLIW Packing Interview Question

## Goal

Given a straight-line program, pack its operations into as few VLIW instructions as possible.

The machine is simulated. There are no branches, no speculation, no cache misses, and no register allocation. The challenge is instruction scheduling under dependency and resource constraints.

## Machine Model

Each VLIW instruction has 5 slots:

```text
| load | store | int0 | int1 | fp |
```

At most one operation may be placed in each slot per cycle.

Supported operations:

| Op type | Slot | Latency | Form |
| --- | --- | ---: | --- |
| `load` | load | 3 | `x = load addr` |
| `store` | store | 1 | `store addr, x` |
| `iadd` | int | 1 | `x = iadd r1, r2` |
| `isub` | int | 1 | `x = isub r1, r2` |
| `imul` | int | 2 | `x = imul r1, r2` |
| `fadd` | fp | 3 | `x = fadd r1, r2` |
| `fmul` | fp | 4 | `x = fmul r1, r2` |

Latency means: if an operation is issued in cycle `c`, its result may be consumed by an operation issued in cycle `c + latency`.

Examples:

- An `iadd` issued in cycle 0 can feed another op in cycle 1.
- A `load` issued in cycle 0 can feed another op in cycle 3.
- A `store` consumes its value operand and produces no result.

Integer and floating-point operations may only consume register operands. External values, memory values, and constants must first be loaded into registers with a `load` operation.

## Input Program

The input is a list of numbered operations in dependency order.

```text
0: a = load A
1: b = load B
2: k = load K
3: x = load X
4: y = load Y
5: z = load Z
6: c = iadd a, b
7: d = imul c, k
8: e = fmul x, y
9: f = fadd e, z
10: store C, d
11: store D, f
```

Operands written in uppercase, such as `A`, `B`, `K`, `X`, `Y`, `Z`, are load/store addresses. They may appear as the address operand of a `load` or `store`, but they may not be passed directly to an integer or floating-point operation.

Operands written by earlier operations are available only after the producing operation's latency has elapsed.

Memory ordering is simplified:

- Loads may be freely reordered with other loads.
- Stores may not move before operations that compute their address or value.
- Stores may be freely reordered with each other unless the interviewer enables the optional aliasing rule.

Optional aliasing rule for a harder version:

- Preserve the original order of all memory operations whose addresses are not statically different.

## Output Schedule

The candidate returns a list of VLIW instructions.

```text
cycle 0: load:3 | store:- | int0:- | int1:- | fp:-
cycle 1: load:4 | store:- | int0:- | int1:- | fp:-
cycle 2: load:5 | store:- | int0:- | int1:- | fp:-
cycle 3: load:0 | store:- | int0:- | int1:- | fp:-
cycle 4: load:1 | store:- | int0:- | int1:- | fp:8
cycle 5: load:2 | store:- | int0:- | int1:- | fp:-
cycle 6: load:- | store:- | int0:- | int1:- | fp:-
cycle 7: load:- | store:- | int0:6 | int1:- | fp:-
cycle 8: load:- | store:- | int0:7 | int1:- | fp:9
cycle 9: load:- | store:- | int0:- | int1:- | fp:-
cycle 10: load:- | store:10 | int0:- | int1:- | fp:-
cycle 11: load:- | store:11 | int0:- | int1:- | fp:-
```

Empty slots are written as `-`.

## Validity Rules

A schedule is valid if:

1. Every input operation appears exactly once.
2. Every operation appears in a compatible slot.
3. No slot contains more than one operation in the same cycle.
4. Every operation is issued only after all of its operands are available.
5. Every source operand of an integer or floating-point operation is a register written by an earlier operation.
6. Stores obey the configured memory-ordering rule.

The score is the number of cycles in the schedule. Lower is better.

For interviews, accept any valid schedule, then ask the candidate how they would improve it. For take-home grading, compare against a known optimal or near-optimal answer.

## Worked Example

Input:

```text
0: a = load A
1: b = load B
2: c = load C
3: x = load X
4: y = load Y
5: z = load Z
6: n = load N
7: d = iadd a, b
8: e = imul d, c
9: f = fmul x, y
10: g = fadd f, z
11: h = iadd e, n
12: store OUT1, h
13: store OUT2, g
```

One good schedule:

```text
cycle 0: load:3 | store:- | int0:- | int1:- | fp:-
cycle 1: load:4 | store:- | int0:- | int1:- | fp:-
cycle 2: load:5 | store:- | int0:- | int1:- | fp:-
cycle 3: load:0 | store:- | int0:- | int1:- | fp:-
cycle 4: load:1 | store:- | int0:- | int1:- | fp:9
cycle 5: load:2 | store:- | int0:- | int1:- | fp:-
cycle 6: load:6 | store:- | int0:- | int1:- | fp:-
cycle 7: load:- | store:- | int0:7 | int1:- | fp:-
cycle 8: load:- | store:- | int0:8 | int1:- | fp:10
cycle 9: load:- | store:- | int0:- | int1:- | fp:-
cycle 10: load:- | store:- | int0:11 | int1:- | fp:-
cycle 11: load:- | store:12 | int0:- | int1:- | fp:-
cycle 12: load:- | store:13 | int0:- | int1:- | fp:-
```

This schedule takes 13 cycles.

Key observations:

- The `x`, `y`, and `z` values are loaded first so the independent floating-point chain can start early.
- All operands to `iadd`, `imul`, `fadd`, and `fmul` are registers produced by earlier loads or arithmetic operations.
- Loads are issued in consecutive cycles because there is only one load slot.
- The two integer slots do not help much here because the integer dependency chain is serial.
- Stores can be packed as soon as their value operands are ready, but only one store may issue per cycle.

## Interview Variants

Easy version:

- The candidate only needs to validate and improve schedules manually.
- Programs contain 10-20 operations.
- All memory addresses are known distinct.

Medium version:

- The candidate writes a scheduler.
- A greedy list scheduler is enough for solid performance.
- Programs contain 50-200 operations.

Hard version:

- Add memory alias constraints.
- Add multiple basic blocks.
- Ask for either optimal scheduling with branch-and-bound for small inputs or near-optimal scheduling for large inputs.

## Expected Candidate Approach

A reasonable implementation usually has these pieces:

1. Parse operations and build a dependency graph.
2. Track each operation's unscheduled predecessor count.
3. Maintain a ready set of operations whose dependencies are satisfied.
4. For each cycle, fill slots using a priority heuristic.
5. Advance time, mark completed results, and add newly ready operations.

Useful priority heuristics:

- Prefer operations on the critical path.
- Prefer longer-latency operations when otherwise tied.
- Prefer scarce slots when many ready operations compete for them.
- Schedule stores late if they are not on the critical path.

The minimal correct solution can be a straightforward greedy scheduler. The best candidates will notice that "ready" is not the same as "all predecessors scheduled"; an operand is usable only after the producer's latency has elapsed.

## Follow-Up Questions

- How would you compute a critical-path priority?
- How would you prove a schedule is valid?
- When can a greedy scheduler be suboptimal?
- How would you find the optimal answer for programs under 20 operations?
- What changes if loads and stores may alias?
- What changes if the machine supports forwarding from an operation in the same cycle?

## Checker

This folder includes a small Python checker:

```sh
python3 vliw.py examples/problem1.vliw examples/answer1.sched --max-cycles 13
```

Expected output:

```text
OK: valid schedule, cycles=13
```

A bad schedule fails with a concrete reason:

```sh
python3 vliw.py examples/problem1.vliw examples/bad_too_early.sched
```

Expected output:

```text
INVALID: operation 7 uses register 'b' in cycle 6, but operation 1 produces it in cycle 7
```

Run the checker tests with:

```sh
python3 -m unittest -v
```
