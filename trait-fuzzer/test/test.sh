#!/usr/bin/env bash
set -euo pipefail

input_file="${1:-bug.rs}"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
cp "$input_file" "$work_dir/bug.rs"

# 先做快速语法检查，避免接受语法错误的候选
set +e
timeout --preserve-status -k 1s 2s rustc +nightly -Z unpretty=ast-tree "$work_dir/bug.rs" >/dev/null 2>&1
parse_status=$?
if [ $parse_status -ne 0 ]; then
  exit 1
fi

# 限制编译时间，确保 reduce 不会卡住
timeout --preserve-status -k 1s 5s rustc +nightly -Z next-solver=globally "$work_dir/bug.rs" >/dev/null 2>&1
# timeout --preserve-status -k 1s 5s rustc +nightly  "$work_dir/bug.rs" >/dev/null 2>&1
status=$?
set -e

# 如果 rustc 卡住（timeout），exit 0；否则 exit 1
if [ $status -eq 124 ] || [ $status -eq 137 ] || [ $status -eq 143 ]; then
  exit 0
else
  exit 1
fi
