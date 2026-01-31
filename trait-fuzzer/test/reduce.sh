#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODE="0"
SOURCE_FILE="$SCRIPT_DIR/bug.rs"

while [[ $# -gt 0 ]]; do
  case $1 in
    --mode) MODE="$2"; shift 2 ;;
    *) SOURCE_FILE="$1"; shift ;;
  esac
done

# 导出变量供 test.sh 使用
export FUZZ_MODE="$MODE"
chmod +x "$SCRIPT_DIR/test.sh"

rm -f "$SCRIPT_DIR/treereduce.out"
# 直接传脚本路径，@@ 会被替换为临时文件名
exec treereduce-rust -s "$SOURCE_FILE" "$SCRIPT_DIR/test.sh" @@ --timeout 6 -j 1 -o "$SCRIPT_DIR/treereduce.out"