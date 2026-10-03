#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m quant.live --profile runtime/test/credentials.json --execute-test "$@"
