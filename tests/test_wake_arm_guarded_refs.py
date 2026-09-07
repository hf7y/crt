#!/usr/bin/env python3
# Structural check for bin/crt-stt-solo.py's WAKE_ARM_ENABLED header comment:
# every wake_arm/ARM_STATE reference must live inside an
# `if WAKE_ARM_ENABLED:` guard, or it would run even with the feature off.
# tests/test_stt_gate.py's TestWakeArmDisabledByDefault already witnesses the
# import-time snapshot; this witnesses the structural claim across the whole
# file, not just at module scope.
import ast
import os
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
STT_SOLO_PATH = os.path.join(BIN_DIR, "crt-stt-solo.py")


class _GuardChecker(ast.NodeVisitor):
    """Tracks whether the node currently being visited is nested inside an
    `if WAKE_ARM_ENABLED [and ...]:` -- test AND body both count, since a
    reference inside the test itself (e.g. `... and ARM_STATE.armed`) is
    just as dead when the flag is off, short-circuit."""

    def __init__(self):
        self.depth = 0
        self.offenders = []

    def visit_If(self, node):
        guarded = self._guards(node.test)
        if guarded:
            self.depth += 1
        self.generic_visit(node)
        if guarded:
            self.depth -= 1

    @staticmethod
    def _guards(test):
        if isinstance(test, ast.Name) and test.id == "WAKE_ARM_ENABLED":
            return True
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
            return any(isinstance(v, ast.Name) and v.id == "WAKE_ARM_ENABLED"
                       for v in test.values)
        return False

    def visit_Name(self, node):
        if node.id in ("wake_arm", "ARM_STATE") and self.depth == 0:
            self.offenders.append((node.id, node.lineno))
        self.generic_visit(node)


class TestWakeArmReferencesAllGuarded(unittest.TestCase):
    def test_every_reference_lives_inside_an_if_wake_arm_enabled(self):
        with open(STT_SOLO_PATH) as f:
            tree = ast.parse(f.read(), STT_SOLO_PATH)
        checker = _GuardChecker()
        checker.visit(tree)
        self.assertEqual(checker.offenders, [],
            "wake_arm/ARM_STATE referenced outside an `if WAKE_ARM_ENABLED` "
            "guard -- would run even with the feature off: %r" % (checker.offenders,))


if __name__ == "__main__":
    unittest.main()
