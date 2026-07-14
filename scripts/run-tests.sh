#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
python3 -m compileall -q .
python3 -m unittest discover -s tests -p 'test_*.py'

if grep -RInE \
    --exclude-dir=.git --exclude-dir=__pycache__ --exclude='*.png' --exclude='run-tests.sh' \
    '(JoinComplete token:|Attaching .* token [0-9a-fA-F]|using token [0-9a-fA-F])' .
then
    echo "ERROR: source contains a token-printing pattern." >&2
    exit 1
fi

echo "Static token-output scan: OK"
echo "All offline checks passed."
