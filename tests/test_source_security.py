import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_NAMES = {
    "token",
    "net_key",
    "app_key",
    "device_key",
}


class SourceSecurityTest(unittest.TestCase):
    def test_print_calls_do_not_reference_secret_variables(self):
        violations = []
        for path in sorted((ROOT / "sanlight_mesh").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Name) or node.func.id != "print":
                    continue
                names = {
                    child.id for child in ast.walk(node) if isinstance(child, ast.Name)
                }
                leaked = sorted(names & SENSITIVE_NAMES)
                if leaked:
                    violations.append(f"{path.name}:{node.lineno}: {', '.join(leaked)}")
        self.assertEqual(
            violations,
            [],
            "secret variable referenced by print(): " + "; ".join(violations),
        )

class SetupSafetyTest(unittest.TestCase):
    def test_setup_contains_no_lamp_write_command(self):
        setup = (ROOT / "scripts" / "setup-all.sh").read_text(encoding="utf-8")
        for command in ("set-max", "set-time", "set-uptime", "sync-now"):
            self.assertNotIn(command, setup)

    def test_service_does_not_hardcode_wrong_rfkill_path(self):
        files = [
            ROOT / "scripts" / "start-meshd-generic.sh",
            ROOT / "systemd" / "sanlight-meshd-generic.service.example",
        ]
        for path in files:
            self.assertNotIn("/usr/bin/rfkill", path.read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()
