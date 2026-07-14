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

    def test_sequence_recovery_never_prints_node_json_content(self):
        source = (ROOT / "sanlight_mesh" / "sequence_recovery.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        print_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ]
        self.assertEqual(print_calls, [])


class SetupSafetyTest(unittest.TestCase):
    def test_setup_contains_no_lamp_write_command(self):
        setup = (ROOT / "scripts" / "setup-all.sh").read_text(encoding="utf-8")
        for command in (
            "set-max", "blackout", "restore-blackout",
            "set-time", "set-uptime", "sync-now"
        ):
            self.assertNotIn(command, setup)

    def test_service_does_not_hardcode_wrong_rfkill_path(self):
        files = [
            ROOT / "scripts" / "start-meshd-generic.sh",
            ROOT / "systemd" / "sanlight-meshd-generic.service.example",
        ]
        for path in files:
            self.assertNotIn("/usr/bin/rfkill", path.read_text(encoding="utf-8"))

    def test_service_readiness_checks_network_interface(self):
        installer = (ROOT / "scripts" / "install-service.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("busctl introspect", installer)
        self.assertIn("org.bluez.mesh.Network1", installer)
        self.assertNotIn(
            "busctl tree org.bluez.mesh /org/bluez/mesh",
            installer,
        )

    def test_test_runner_does_not_write_into_private_or_state_paths(self):
        runner = (ROOT / "scripts" / "run-tests.sh").read_text(encoding="utf-8")
        self.assertNotIn("python3 -m compileall -q .", runner)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", runner)
        self.assertIn("--exclude-dir=.state", runner)
        self.assertIn("--exclude-dir=private", runner)

    def test_replay_diagnostic_contains_only_read_only_mesh_commands(self):
        script = (ROOT / "scripts" / "diagnose-replay.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("get-net-tx", script)
        self.assertIn("get-net-tx-sender", script)
        for command in ("set-max", "set-time", "set-uptime", "sync-now"):
            self.assertNotIn(command, script)


if __name__ == "__main__":
    unittest.main()
