from __future__ import annotations

import unittest
from pathlib import Path

import compiler
import machine


PROGRAM_DIR = Path(__file__).parents[1] / "programs"


class PublicProgramTests(unittest.TestCase):
    def test_compiler_on_all_public_programs(self):
        paths = sorted(PROGRAM_DIR.glob("*.json"))
        self.assertEqual(len(paths), 8)
        for path in paths:
            with self.subTest(program=path.name):
                program = machine.load_program(path)
                compilation = compiler.compile_program(program)
                machine.check_compilation(program, compilation)
                for case in program["cases"]:
                    machine.check_case(program, compilation, case)


if __name__ == "__main__":
    unittest.main()
