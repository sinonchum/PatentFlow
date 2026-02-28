#!/bin/bash

set -e

OA_FILE=${1:-"data/raw/sample_oa.txt"}
SPEC_FILE=${2:-""}

source venv/bin/activate

echo "--- Step 1: Parsing Office Action & Retrieving Templates ---"

if [ -n "$SPEC_FILE" ] && [ -f "$SPEC_FILE" ]; then
  python -m src.pipeline --oa_path "$OA_FILE" --spec_path "$SPEC_FILE"
else
  python -m src.pipeline --oa_path "$OA_FILE"
fi

echo "--- Step 2: Generation Complete ---"
echo "Check data/output/ for the generated draft."
