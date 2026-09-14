#!/bin/sh
set -eu
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
shasum -a 256 -c MANIFEST.sha256
python3 - <<'PYCODE'
from pathlib import Path
for p in Path('.').rglob('*.py'):
    compile(p.read_bytes(), str(p), 'exec')
PYCODE
python3 -m unittest discover -s mac-client -p 'test_*.py'
python3 -m unittest discover -s mac-connection -p 'test_*.py'
python3 -m unittest discover -s tests -p 'test_*.py'
for name in empty_roll simple_one_roll detailed_two_rolls; do
 python3 mac-client/f100_readonly.py compare --reference "mac-client/fixtures/golden/$name.reference.json" --capture "mac-client/fixtures/golden/$name.hex" >/dev/null
done
echo 'PASS: integrity, compilation, offline tests and synthetic comparisons'
