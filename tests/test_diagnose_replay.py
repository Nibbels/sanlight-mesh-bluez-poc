import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "diagnose-replay.sh"


class DiagnoseReplayScriptTest(unittest.TestCase):
    def run_bash(self, source: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", source],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_success_marker_matches_only_received_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            success = Path(tmp) / "success.txt"
            timeout = Path(tmp) / "timeout.txt"
            success.write_text(
                "GET-NET-TX COMPLETE. Node 0x0002: transmissions=1.\n",
                encoding="utf-8",
            )
            timeout.write_text(
                "GET-NET-TX COMPLETE. No Config Network Transmit Status was observed.\n",
                encoding="utf-8",
            )

            command = f"""
source {shlex.quote(str(SCRIPT))}
probe_output_has_status {shlex.quote(str(success))}
! probe_output_has_status {shlex.quote(str(timeout))}
"""
            result = self.run_bash(command)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_retry_accepts_second_successful_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "combined.txt"
            command = f"""
source {shlex.quote(str(SCRIPT))}
MAX_ATTEMPTS=2
RETRY_DELAY_SECONDS=0
NODE=0002
calls=0
run_probe_once() {{
    calls=$((calls + 1))
    if [[ $calls -eq 1 ]]; then
        printf '%s\n' 'GET-NET-TX COMPLETE. No Config Network Transmit Status was observed.' >"$2"
    else
        printf '%s\n' 'GET-NET-TX COMPLETE. Node 0x0002: transmissions=1.' >"$2"
    fi
}}
run_probe_with_retries get-net-tx-sender canonical-sender {shlex.quote(str(output))} >/dev/null
printf '%s' "$PROBE_ATTEMPTS"
"""
            result = self.run_bash(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "2")

    def test_script_does_not_classify_after_one_attempt(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("MAX_ATTEMPTS=2", source)
        self.assertIn("run_probe_with_retries", source)
        self.assertIn("A single missing Mesh status reply is not enough", source)
        self.assertIn("This remains a diagnosis, not mathematical proof", source)


if __name__ == "__main__":
    unittest.main()
