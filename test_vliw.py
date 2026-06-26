import unittest

import vliw


PROBLEM = """
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
"""

VALID_SCHEDULE = """
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
"""


class VliwTests(unittest.TestCase):
    def test_valid_schedule_scores_cycle_count(self):
        operations = vliw.parse_program(PROBLEM)
        schedule = vliw.parse_schedule(VALID_SCHEDULE)

        cycles = vliw.check_schedule(operations, schedule)

        self.assertEqual(cycles, 13)

    def test_rejects_direct_arithmetic_operand_that_was_not_loaded(self):
        with self.assertRaisesRegex(vliw.CheckError, "not an earlier register"):
            vliw.parse_program(
                """
                0: a = load A
                1: b = iadd a, K
                """
            )

    def test_rejects_wrong_slot(self):
        operations = vliw.parse_program(PROBLEM)
        bad_schedule = VALID_SCHEDULE.replace(
            "cycle 7: load:- | store:- | int0:7 | int1:- | fp:-",
            "cycle 7: load:- | store:- | int0:- | int1:- | fp:7",
        )

        with self.assertRaisesRegex(vliw.CheckError, "cannot use this slot"):
            vliw.check_schedule(operations, vliw.parse_schedule(bad_schedule))

    def test_rejects_too_early_use(self):
        operations = vliw.parse_program(PROBLEM)
        bad_schedule = VALID_SCHEDULE.replace(
            "cycle 7: load:- | store:- | int0:7 | int1:- | fp:-",
            "cycle 6: load:6 | store:- | int0:7 | int1:- | fp:-",
        ).replace(
            "cycle 6: load:6 | store:- | int0:- | int1:- | fp:-",
            "cycle 7: load:- | store:- | int0:- | int1:- | fp:-",
        )

        with self.assertRaisesRegex(vliw.CheckError, "produces it in cycle"):
            vliw.check_schedule(operations, vliw.parse_schedule(bad_schedule))

    def test_rejects_missing_operation(self):
        operations = vliw.parse_program(PROBLEM)
        bad_schedule = VALID_SCHEDULE.replace("store:13", "store:-")

        with self.assertRaisesRegex(vliw.CheckError, "missing operations: 13"):
            vliw.check_schedule(operations, vliw.parse_schedule(bad_schedule))

    def test_rejects_cycle_limit_miss(self):
        operations = vliw.parse_program(PROBLEM)
        schedule = vliw.parse_schedule(VALID_SCHEDULE)

        with self.assertRaisesRegex(vliw.CheckError, "above limit 12"):
            vliw.check_schedule(operations, schedule, max_cycles=12)


if __name__ == "__main__":
    unittest.main()

