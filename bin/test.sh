#!/bin/sh

# Runs the unit tests.
#
# Usage examples:
#   bin/test.sh
#   bin/test.sh tests/00_sanity_test.py

set -e

dir=$(dirname "$0")
cd "$dir/.."

echo
echo "----------------------"
echo "| Running unit tests |"
echo "----------------------"

if [ $# -gt 0 ]
then
  uv run python -m pytest -v -p no:faulthandler "$@"
else
  uv run python -m pytest -v -p no:faulthandler tests/
fi
