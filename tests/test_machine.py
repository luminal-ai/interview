"""Luminal Compiler Take Home — Machine contract tests for compiler engineering."""

from __future__ import annotations

import unittest

import machine


def micro_program() -> dict:
    return {
        "name": "micro",
        "buffers": {"out": 1},
        "operations": [
            {"id": 0, "op": "const", "dest": "a", "value": 6},
            {"id": 1, "op": "const", "dest": "b", "value": 7},
            {"id": 2, "op": "mul", "dest": "product", "args": ["a", "b"]},
            {
                "id": 3,
                "op": "store",
                "args": ["product"],
                "buffer": "out",
                "offset": 0,
            },
        ],
        "cases": [{"out": [0]}],
    }


class MachineTests(unittest.TestCase):
    def test_serial_compiler_executes_correctly(self):
        program = micro_program()
        compilation = machine.serial_compile(program)
        machine.check_case(program, compilation, program["cases"][0])
        self.assertEqual(
            machine.run_compilation(program, compilation, program["cases"][0])["out"],
            [42],
        )

    def test_rejects_consumer_before_result_latency(self):
        program = micro_program()
        compilation = {
            "scratch": {"a": 0, "b": 1, "product": 2},
            "bundles": [
                {"load": [0, 1], "scalar": [2]},
                {},
                {"store": [3]},
            ],
        }
        with self.assertRaisesRegex(machine.CompileError, "produces it in cycle"):
            machine.check_compilation(program, compilation)

    def test_rejects_engine_capacity_overflow(self):
        program = micro_program()
        compilation = machine.serial_compile(program)
        compilation["bundles"] = [
            {"load": [0, 1]},
            {"scalar": [2, 2, 2]},
            {},
            {"store": [3]},
        ]
        with self.assertRaisesRegex(machine.CompileError, "limit is 2"):
            machine.check_compilation(program, compilation)

    def test_rejects_overlapping_scratch_allocations(self):
        program = micro_program()
        compilation = machine.serial_compile(program)
        compilation["scratch"]["b"] = compilation["scratch"]["a"]
        with self.assertRaisesRegex(machine.CompileError, "overlap"):
            machine.check_compilation(program, compilation)

    def test_memory_predecessor_only_for_overlapping_range(self):
        program = {
            "name": "memory",
            "buffers": {"data": 16},
            "operations": [
                {"id": 0, "op": "vload", "dest": "first", "buffer": "data", "offset": 0},
                {"id": 1, "op": "vstore", "args": ["first"], "buffer": "data", "offset": 8},
                {"id": 2, "op": "vload", "dest": "second", "buffer": "data", "offset": 8},
            ],
            "cases": [{"data": list(range(16))}],
        }
        machine.validate_program(program)
        self.assertEqual(machine.memory_predecessors(program, 1), [])
        self.assertEqual(machine.memory_predecessors(program, 2), [1])

    def test_vector_allocation_requires_alignment(self):
        program = {
            "name": "vector",
            "buffers": {"data": 8},
            "operations": [
                {"id": 0, "op": "vload", "dest": "value", "buffer": "data", "offset": 0}
            ],
            "cases": [{"data": list(range(8))}],
        }
        compilation = {"scratch": {"value": 1}, "bundles": [{"load": [0]}]}
        with self.assertRaisesRegex(machine.CompileError, "aligned"):
            machine.check_compilation(program, compilation)


class ScratchReuseTests(unittest.TestCase):
    def test_in_place_result_after_final_read(self):
        program = micro_program()
        compilation = machine.serial_compile(program)
        compilation['scratch']['product'] = compilation['scratch']['a']
        machine.check_case(program, compilation, program['cases'][0])
        self.assertEqual(machine.scratch_footprint(program, compilation), 2)

    def test_write_on_final_read_cycle_is_rejected(self):
        program = micro_program()
        program['operations'].insert(2, {'id': 2, 'op': 'const', 'dest': 'unused', 'value': 9})
        for i, op in enumerate(program['operations']):
            op['id'] = i
        compilation = {
            'scratch': {'a': 0, 'b': 1, 'unused': 0, 'product': 2},
            'bundles': [{'load': [0, 1]}, {'load': [2]}, {'scalar': [3]}, {}, {'store': [4]}],
        }
        with self.assertRaisesRegex(machine.CompileError, 'overlap while live'):
            machine.check_compilation(program, compilation)

    def test_pending_unused_write_clobbers_live_value(self):
        program = {
            'name': 'pending', 'buffers': {'data': 1, 'out': 1},
            'operations': [
                {'id': 0, 'op': 'load', 'dest': 'unused', 'buffer': 'data', 'offset': 0},
                {'id': 1, 'op': 'const', 'dest': 'a', 'value': 7},
                {'id': 2, 'op': 'store', 'args': ['a'], 'buffer': 'out', 'offset': 0},
            ], 'cases': [{'data': [9], 'out': [0]}],
        }
        compilation = {'scratch': {'unused': 0, 'a': 0},
                       'bundles': [{'load': [0]}, {'load': [1]}, {}, {}, {'store': [2]}]}
        with self.assertRaisesRegex(machine.CompileError, 'overlap while live'):
            machine.check_compilation(program, compilation)

    def test_partial_scalar_vector_reuse(self):
        program = {
            'name': 'partial', 'buffers': {'data': 8, 'out': 8},
            'operations': [
                {'id': 0, 'op': 'vload', 'dest': 'v', 'buffer': 'data', 'offset': 0},
                {'id': 1, 'op': 'vstore', 'args': ['v'], 'buffer': 'out', 'offset': 0},
                {'id': 2, 'op': 'const', 'dest': 's', 'value': 3},
                {'id': 3, 'op': 'store', 'args': ['s'], 'buffer': 'out', 'offset': 0},
            ], 'cases': [{'data': list(range(8)), 'out': [0] * 8}],
        }
        compilation = machine.serial_compile(program)
        compilation['scratch']['s'] = 3
        machine.check_case(program, compilation, program['cases'][0])
        self.assertEqual(machine.scratch_footprint(program, compilation), 8)
        compilation['bundles'] = [{'load': [0]}, {}, {}, {'load': [2]}, {'store': [1]}, {'store': [3]}]
        with self.assertRaisesRegex(machine.CompileError, 'overlap while live'):
            machine.check_compilation(program, compilation)


if __name__ == "__main__":
    unittest.main()
