"""Pure policy and dependency direction: no runtime construction required."""
import ast
import itertools
import subprocess
import sys
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
        for name in ('contracts.py', 'admission.py'):
            allowed = {'dataclasses', 'radioflix.timefree.contracts'}
            if name == 'admission.py':
                allowed |= {'argparse', 'json', 'os', 'stat', 'datetime', 'pathlib'}
            tree = ast.parse((root / name).read_text())
            # Only the explicitly invoked job-admission CLI may load API/services.
            tree.body = [node for node in tree.body
                         if not (isinstance(node, ast.FunctionDef) and node.name == 'main')]
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertTrue(all(alias.name in allowed for alias in node.names))
                elif isinstance(node, ast.ImportFrom):
                    self.assertIn(node.module, allowed)

    def test_old_capture_exceptions_keep_identity(self):
        from radioflix.timefree.capture.errors import CaptureNotReady as old
        self.assertIs(old, CaptureNotReady)

    def test_capture_import_paths_in_fresh_processes(self):
        root = Path(__file__).parents[1]
        for module in ('admission', 'runtime_policy', 'capture.production',
                       'acceptance_profile', 'acceptance'):
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, '-B', '-c',
                     'import importlib, sys; '
                     f'importlib.import_module("radioflix.timefree.{module}"); '
                     'from radioflix.timefree.admission import require_capture_start; '
                     'assert callable(require_capture_start); '
                     'assert "radioflix.api.timefree" not in sys.modules; '
                     'assert "app" not in sys.modules'],
                    cwd=root, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_capture_state_is_rejected(self):
        for state in (None, True, {}, object()):
            with self.subTest(state=type(state).__name__):
                with self.assertRaises(CaptureNotReady):
                    require_capture_start(state)
