from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-gateway.sh"
PASSWORD_HELPER = ROOT / "scripts" / "mosquitto-password.py"


class LocalBrokerInstallerTest(unittest.TestCase):
    def test_public_installer_owns_local_broker_setup(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")

        self.assertIn("mosquitto mosquitto-clients", text)
        self.assertIn('mqtt_host="127.0.0.1"', text)
        self.assertIn("/etc/mosquitto/conf.d/sanlight-mesh-mqtt-gateway.conf", text)
        self.assertIn("allow_anonymous false", text)
        self.assertIn("password_file ${MOSQUITTO_PASSWORD_DB}", text)
        self.assertIn("acl_file ${MOSQUITTO_ACL}", text)
        self.assertNotIn('prompt "MQTT broker host', text)
        self.assertNotIn('prompt "MQTT username', text)
        self.assertNotIn("LOCAL_BROKER", text)
        self.assertIn("Migrating the existing gateway configuration", text)
        self.assertIn('mqtt_host="127.0.0.1"', text)
        self.assertIn("MIGRATED_EXTERNAL_BROKER=1", text)
        self.assertNotIn("--reset-mesh-state", text)

    def test_acl_is_scoped_to_one_gateway(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        root = "sanlightmesh/v1/${gateway_id}"

        self.assertIn(f"topic read {root}/command", text)
        self.assertIn(f"topic write {root}/command", text)
        self.assertIn(f"topic read {root}/availability", text)
        self.assertIn(f"topic read {root}/gateway/#", text)
        self.assertIn(f"topic read {root}/nodes/#", text)
        self.assertIn(f"topic read {root}/result/#", text)
        self.assertNotIn(f"topic read {root}/#", text)
        self.assertNotIn("sanlightmesh/v1/+/", text)

    def test_broker_files_are_staged_and_restored_on_failure(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")

        self.assertIn("BROKER_STAGE=", text)
        self.assertIn("restore_previous_broker_files", text)
        self.assertIn("fail_and_restore_broker", text)
        self.assertIn('mv -f -- "$STAGED_PASSWORD_DB" "$MOSQUITTO_PASSWORD_DB"', text)
        self.assertNotIn('rm -f -- "$MOSQUITTO_PASSWORD_DB"', text)

    def test_docs_define_one_installer_and_one_adapter_per_gateway(self) -> None:
        setup = (ROOT / "SETUP.md").read_text(encoding="utf-8")
        integration = (ROOT / "docs" / "IOBROKER_INTEGRATION.md").read_text(
            encoding="utf-8"
        )
        combined = setup + "\n" + integration

        self.assertIn("sudo bash scripts/install-gateway.sh", setup)
        self.assertIn("https://github.com/Nibbels/ioBroker.sanlightmesh", combined)
        self.assertIn("one sanlightmesh instance per gateway Pi", integration)
        self.assertIn("one exact gateway ID", integration)
        self.assertIn("another adapter instance", integration)
        self.assertNotIn("install-mosquitto-broker.sh", combined)
        self.assertIn("generic ioBroker MQTT adapter is not required", setup)

    def test_gateway_service_requires_local_broker(self) -> None:
        unit = (ROOT / "systemd" / "sanlight-mqtt-gateway.service.example").read_text(
            encoding="utf-8"
        )
        self.assertIn("Requires=mosquitto.service sanlight-meshd-generic.service", unit)

    def test_password_helper_does_not_put_secret_in_argv(self) -> None:
        helper = PASSWORD_HELPER.read_text(encoding="utf-8")
        self.assertIn("pty.fork()", helper)
        self.assertIn("secret_file", helper)
        self.assertNotIn('argv.extend([str(args.password_db), args.username,', helper)

    def test_password_helper_drives_interactive_program(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake-passwd.py"
            fake.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import getpass
                    import json
                    import sys

                    args = sys.argv[1:]
                    create = bool(args and args[0] == "-c")
                    if create:
                        args = args[1:]
                    output, username = args
                    first = getpass.getpass("Password:")
                    second = getpass.getpass("Reenter password:")
                    if first != second:
                        raise SystemExit(2)
                    mode = "w" if create else "a"
                    with open(output, mode, encoding="utf-8") as handle:
                        handle.write(json.dumps({"username": username, "password": first}) + "\\n")
                    """
                ),
                encoding="utf-8",
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

            secret = root / "secret.txt"
            secret.write_text("not-in-argv\n", encoding="utf-8")
            os.chmod(secret, 0o600)
            database = root / "passwords"

            subprocess.run(
                [
                    sys.executable,
                    str(PASSWORD_HELPER),
                    "--password-db",
                    str(database),
                    "--username",
                    "gateway-a",
                    "--secret-file",
                    str(secret),
                    "--create",
                    "--executable",
                    str(fake),
                ],
                check=True,
                timeout=10,
            )

            record = json.loads(database.read_text(encoding="utf-8"))
            self.assertEqual(record["username"], "gateway-a")
            self.assertEqual(record["password"], "not-in-argv")


if __name__ == "__main__":
    unittest.main()
