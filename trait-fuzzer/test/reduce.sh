#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SOURCE_FILE="${1:-$SCRIPT_DIR/bug.rs}"
TEST_SCRIPT="$SCRIPT_DIR/test.sh"
OUTPUT_FILE="$SCRIPT_DIR/treereduce.out"

rm -f "$OUTPUT_FILE"
exec treereduce-rust -s "$SOURCE_FILE" "$TEST_SCRIPT" @@ --timeout 6 -j 1 --passes 1 --on-parse-error error -o "$OUTPUT_FILE"
