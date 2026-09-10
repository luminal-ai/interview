# VLIW Backend Compiler Take-Home

Build a general backend compiler for a small, deterministic VLIW machine. The
input is a typed, straight-line SSA program. Your compiler must assign every
virtual value to the machine's scratchpad and schedule every operation into
VLIW bundles. Correctness is required; shorter schedules and smaller scratch footprints score better.

The starter compiler is deliberately simple and serial. It is correct for all
supported programs, so you can improve it incrementally and measure every
change.

## Candidate task

Implement scheduling and scratch allocation in `compile_program()` in `compiler.py`.
You may add helpers and standard-library imports to that file. Do not modify `machine.py`, the
public programs, or the tests when preparing a submission.

Your compiler receives a parsed program dictionary and returns:

```python
{
    "scratch": {"virtual_value": 0, "another_value": 8},
    "bundles": [
        {"load": [0, 1]},
        {},
        {"vector": [2], "store": [3]},
    ],
}
```

The `scratch` mapping assigns each SSA result to a word address in scratch.
The lists in each bundle contain operation IDs from the input program. Missing
engines and empty bundles are allowed. Every operation must appear exactly
once.

Run the public suite and benchmark with:

```sh
python3 -m unittest -v
python3 score.py
```

Compile one program to a JSON schedule with:

```sh
python3 compiler.py programs/03_vector_axpy.json > axpy.schedule.json
python3 machine.py programs/03_vector_axpy.json axpy.schedule.json
```

Eight public programs are in `programs/`. Submission grading uses another
eight programs that are not included in the candidate repository. Hidden
programs use only the documented operations and limits below. Solutions that
special-case public filenames, operation IDs, or constants will not generalize.

## Machine model

The machine has a 256-word scratchpad. Each word is an unsigned 32-bit integer.
There is no implicit register file or cache. Every SSA result must be assigned
scratch space before it can be consumed.

SIMD vectors contain eight words and occupy eight consecutive scratch words.
Vector allocations must begin at an address divisible by eight. Scalar values
occupy one word. Values may share all or part of their scratch ranges when their
live intervals do not overlap. All supplied programs fit without spilling even
with the starter's allocation; reducing scratch use is part of the challenge.

A value's live interval starts when its result writes scratch, at issue cycle
plus latency, and ends at its last consumer's issue cycle, inclusive. An unused
result still occupies scratch for its write cycle. Writes happen before reads in
a cycle, so a new result must write strictly after an old value's final read to
reuse its words. Two writes to overlapping words in the same cycle are invalid.
An operation may read its input and later write its output to the same address.
Account for in-flight results when choosing addresses and schedules.

Scratch footprint is the highest allocated end address, including alignment
holes. For example, a vector at address 8 uses a footprint of at least 16 words.
There are no moves or spills to insert: every original operation must issue
exactly once, and the input program must not be changed.

Each cycle issues one VLIW bundle with these engine limits:

| Engine | Slots per cycle |
| --- | ---: |
| `load` | 2 |
| `scalar` | 2 |
| `vector` | 2 |
| `store` | 1 |
| `flow` | 1 |

An operation issued in cycle `c` may be consumed in cycle `c + latency`.
Results are not forwarded within the same bundle. Independent operations can
issue in any order if dependencies, engine capacity, and memory ordering are
preserved.

## Instruction set

| Operation | Engine | Latency | Result | Arguments |
| --- | --- | ---: | --- | --- |
| `const` | load | 1 | scalar | immediate `value` field |
| `load` | load | 3 | scalar | memory `buffer` and `offset` |
| `vload` | load | 4 | vector | eight words at `buffer` and `offset` |
| `store` | store | 1 | none | scalar value, memory `buffer` and `offset` |
| `vstore` | store | 1 | none | vector value, memory `buffer` and `offset` |
| `add`, `sub`, `xor`, `and`, `or`, `shl`, `shr`, `eq`, `lt` | scalar | 1 | scalar | two scalars |
| `mul` | scalar | 2 | scalar | two scalars |
| `vadd`, `vsub`, `vxor`, `vand`, `vor`, `vshl`, `vshr` | vector | 1 | vector | two vectors, lane-wise |
| `vmul` | vector | 3 | vector | two vectors, lane-wise |
| `splat` | vector | 1 | vector | one scalar copied to every lane |
| `select` | flow | 1 | scalar | condition, true value, false value |
| `vselect` | flow | 2 | vector | vector condition, true vector, false vector |

Arithmetic wraps modulo `2**32`. Shift counts use their low five bits. `eq`
and `lt` produce `0` or `1`; comparisons are unsigned. `select` chooses its
second argument when the condition is nonzero.

Programs use the following JSON shape:

```json
{
  "name": "example",
  "buffers": {"x": 8, "out": 8},
  "operations": [
    {"id": 0, "op": "vload", "dest": "vx", "buffer": "x", "offset": 0},
    {"id": 1, "op": "vstore", "args": ["vx"], "buffer": "out", "offset": 0}
  ],
  "cases": [
    {"x": [1, 2, 3, 4, 5, 6, 7, 8], "out": [0, 0, 0, 0, 0, 0, 0, 0]}
  ]
}
```

Operations are listed in SSA dependency order. IDs are consecutive starting at
zero. Every argument names a result defined by an earlier operation.

## Memory ordering

Memory ranges are known statically. Loads may reorder freely unless they overlap
an earlier store. A store must remain after every earlier overlapping load or
store, and every later overlapping load or store must remain after it. Two
ordered memory operations must issue in different cycles. Operations accessing
provably disjoint ranges may reorder.

## Evaluation

Every public and hidden case is interpreted directly from the input IR to
produce its reference memory image. The frozen grader then validates scratch
allocations, dependencies, engine limits, latencies, memory ordering, and final
memory. Modifying or bypassing the public simulator cannot change hidden results.

Correctness on all programs is the first requirement. Among correct compilers,
we report geometric-mean cycle speedup and geometric-mean scratch reduction
relative to the frozen serial baseline across all sixteen programs. For each
program these ratios are `baseline_cycles / cycles` and
`baseline_scratch_words / scratch_words`. The combined score is
`sqrt(cycle_speedup_geomean * scratch_reduction_geomean)`, giving equal weight
to both objectives. The starter scores 1.000x on each metric. Public scoring
uses the same formula on the eight visible programs; the private grader reports
the final combined result on all sixteen. We also review compiler structure, clarity, and the
tradeoffs in your scheduling heuristic.

Useful directions include critical-path priorities, latency-aware ready queues,
scarce-engine prioritization, and filling bundles without blocking newly ready
work. Optimal scheduling is not expected.


## Logistics and submission

Use Python 3.10 or later; no third-party packages are required. Run commands
from the repository root. Spend up to four hours, including reading and testing;
submit what you have at that point and note unfinished work. We value a clear,
correct incremental improvement over an unfinished complicated design.

Documentation, internet research, and AI coding tools are allowed. Disclose the
tools used and how you checked their output. You should be able to explain and
modify your submission in a follow-up discussion. Do not share the exercise or
solution publicly or collaborate with another person.

Email `compiler.py` and a short `SUBMISSION.md` to
[submissions@luminal.com](mailto:submissions@luminal.com). Include time spent,
your scheduling and allocation approach, measured public scores, tradeoffs, unfinished work, and
any tool assistance. You may include additional tests separately; do not alter
the supplied tests or machine. The compiler must emit only schedule JSON on
stdout when invoked through the documented CLI; send diagnostics to stderr.
The grader allows 20 seconds per program. Hidden inputs follow the same machine
contract, and grading uses trusted copies of all public and hidden programs.
