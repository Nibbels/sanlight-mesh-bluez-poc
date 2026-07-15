#!/usr/bin/env bash
set -euo pipefail
umask 077

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Compile the actual project sources in memory. Do not traverse private/.state
# and do not create __pycache__ files, even when this script is run via sudo.
python3 - <<'PY'
from pathlib import Path

root = Path.cwd()
paths = [
    root / "sanlight_canonical_sender_poc.py",
    root / "sanlight_protocol.py",
    root / "sanlight_mqtt_gateway.py",
]
for directory in (root / "sanlight_mesh", root / "tests"):
    paths.extend(sorted(directory.rglob("*.py")))

for path in paths:
    compile(path.read_bytes(), str(path), "exec")

print(f"Python syntax check: OK ({len(paths)} files)")
PY

# Unit-test imports must not leave root-owned bytecode behind in the repository.
PYTHONDONTWRITEBYTECODE=1 \
    python3 -m unittest discover -s tests -p 'test_*.py'

# Search source and documentation only. Private CDB/state directories are
# deliberately excluded both for secrecy and because they may be root-only.
if grep -RInE \
    --exclude-dir=.git \
    --exclude-dir=.state \
    --exclude-dir=private \
    --exclude-dir=__pycache__ \
    --exclude='*.png' \
    --exclude='run-tests.sh' \
    '(JoinComplete token:|Attaching .* token [0-9a-fA-F]|using token [0-9a-fA-F])' \
    README.md SETUP.md INSTRUCTIONS.md AI_CONTEXT.md \
    sanlight_canonical_sender_poc.py sanlight_protocol.py \
    sanlight_mesh scripts systemd tests
then
    echo "ERROR: source contains a token-printing pattern." >&2
    exit 1
fi

echo "Static token-output scan: OK"
echo "All offline checks passed."
