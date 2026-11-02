#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
printf 'Open http://127.0.0.1:8000 in your browser.\n'
.venv/bin/python server.py
