#!/bin/bash
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
if [ ! -f .env ]; then
  echo "Copy .env.example to .env and configure it first."
  exit 1
fi
exec uv run --locked --env-file .env python my_ocr.py
