"""Pure policy and dependency direction: no runtime construction required."""
import ast
import itertools
import unittest
from pathlib import Path

from radioflix.timefree.admission import require_capture_start
from radioflix.timefree.contracts import CaptureAdmission, CaptureNotReady


class AdmissionTests(unittest.TestCase):
    def test_all_start_conditions_are_required(self):
        for enabled, writes, ready, approved in itertools.product((False, True), repeat=4):
            state = CaptureAdmission('enabled' if enabled else 'disabled', writes, ready, approved)
            with self.subTest(state=state):
                if enabled and writes and ready and approved:
                    self.assertIsNone(require_capture_start(state))
                else:
                    with self.assertRaises(CaptureNotReady):
                        require_capture_start(state)

    def test_truthy_non_boolean_flags_are_rejected(self):
        for field in ('timefree_writes', 'ready', 'bridge_approved'):
            for value in ('1', 1, object()):
                args = dict(boot_mode='enabled', timefree_writes=True, ready=True, bridge_approved=True)
                args[field] = value
                with self.subTest(field=field, value=type(value).__name__):
                    with self.assertRaises(CaptureNotReady):
                        require_capture_start(CaptureAdmission(**args))

    def test_policy_dependency_layer_is_shallow(self):
        root = Path(__file__).parents[1] / 'radioflix/timefree'
        allowed = {'dataclasses', 'radioflix.timefree.contracts'}
        for name in ('contracts.py', 'admission.py'):
            tree = ast.parse((root / name).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertTrue(all(alias.name in allowed for alias in node.names))
                elif isinstance(node, ast.ImportFrom):
                    self.assertIn(node.module, allowed)

    def test_old_capture_exceptions_keep_identity(self):
        from radioflix.timefree.capture.errors import CaptureNotReady as old
        self.assertIs(old, CaptureNotReady)
