#!/bin/sh
cd "$(dirname "$0")" || exit 1
if [ -x .runtime/bin/python3 ]; then
  NF_PYTHON="$PWD/.runtime/bin/python3"
else
  NF_PYTHON=$(command -v python3 || true)
fi
if [ -z "$NF_PYTHON" ] || ! "$NF_PYTHON" -c 'import sys; sys.exit(sys.version_info < (3,9))' 2>/dev/null; then
  echo 'Python 3.9 이상이 필요합니다. python.org에서 Python 3을 설치한 뒤 다시 열어 주세요.'
  read -r NF_CLOSE
  exit 1
fi
PYTHONDONTWRITEBYTECODE=1 "$NF_PYTHON" app/nfbridge.py
NF_STATUS=$?
if [ "$NF_STATUS" -ne 0 ]; then
  echo 'Enter를 누르면 닫습니다.'
  read -r NF_CLOSE
fi
exit "$NF_STATUS"
