import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "sanlight_mesh" / "bluez_runtime.py"


class MaxBrightnessRuntimeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(RUNTIME.read_text(encoding="utf-8"), filename=str(RUNTIME))
        cls.methods = {
            node.name: node
            for node in ast.walk(cls.tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    @staticmethod
    def called_methods(node):
        names = set()
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            if isinstance(child.func, ast.Attribute):
                names.add(child.func.attr)
            elif isinstance(child.func, ast.Name):
                names.add(child.func.id)
        return names

    def test_set_max_ack_and_timeout_both_start_readback(self):
        self.assertIn(
            "start_get_max_readback",
            self.called_methods(self.methods["on_set_max_status"]),
        )
        self.assertIn(
            "start_get_max_readback",
            self.called_methods(self.methods["finish_or_retry_set_max"]),
        )

    def test_readback_methods_never_trigger_another_write(self):
        readback_methods = (
            "start_get_max_readback",
            "send_get_max_brightness",
            "on_get_max_status",
            "finish_or_retry_get_max",
            "schedule_get_max_retry",
            "retry_get_max",
        )
        for name in readback_methods:
            with self.subTest(method=name):
                self.assertNotIn(
                    "send_max_brightness",
                    self.called_methods(self.methods[name]),
                )

    def test_get_max_response_is_strictly_decoded(self):
        calls = self.called_methods(self.methods["MessageReceived"])
        self.assertIn("get_max_brightness_status_value", calls)
        self.assertIn("unicast_status_rejection_reason", calls)

    def test_transition_to_write_invalidates_stale_get_max_timers(self):
        self.assertIn(
            "_cancel_get_max_transaction",
            self.called_methods(self.methods["_reset_brightness_write_transaction"]),
        )
        self.assertIn(
            "_cancel_get_max_transaction",
            self.called_methods(self.methods["on_get_max_status"]),
        )

    def test_successful_restore_marks_snapshot_completed(self):
        self.assertIn(
            "_mark_restore_snapshot_completed",
            self.called_methods(self.methods["_start_next_restore_preflight_query"]),
        )
        self.assertIn(
            "_mark_restore_snapshot_completed",
            self.called_methods(self.methods["start_next_batch_brightness_write"]),
        )

    def test_already_off_blackout_does_not_create_an_empty_snapshot(self):
        method = self.methods["_start_next_blackout_preflight_query"]
        source = ast.get_source_segment(RUNTIME.read_text(encoding="utf-8"), method)
        self.assertIn("if not changing_targets", source)
        self.assertIn("no write and no restore snapshot were created", source)


if __name__ == "__main__":
    unittest.main()
