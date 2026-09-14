#!/usr/bin/env bash
# macOS: double-click this file in Finder to start the platform.
# (If macOS blocks it the first time: right-click -> Open -> Open.)
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  python3 run.py
else
  echo "Python 3 was not found."
  echo "Install it from https://www.python.org/downloads/ and try again."
  read -r -p "Press Return to close."
  exit 1
fi
echo
read -r -p "Stopped. Press Return to close this window."
