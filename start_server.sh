#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export PC06_HOST="${PC06_HOST:-127.0.0.1}"
export PC06_PORT="${PC06_PORT:-5000}"

exec python3 app.py
