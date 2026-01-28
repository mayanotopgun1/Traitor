#!/usr/bin/env bash
set -euo pipefail

input_file="${1:-bug.rs}"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
cp "$input_file" "$work_dir/bug.rs"

# 关闭 -e，我们需要手动处理返回码
set +e

# ---------------------------------------------------------
# 1. 基准检查 (Baseline Check)
# 标准 nightly 必须编译成功。
# 如果这一步失败，说明代码本身有语法错误，或者 reduce 到了非法的状态，
# 这不是我们要找的 "行为差异" case。
# ---------------------------------------------------------
# 注意：这里隐式包含了语法检查，所以不需要额外的 ast-tree 检查步骤。
rustc +nightly --crate-type lib "$work_dir/bug.rs" >/dev/null 2>&1
status_std=$?

if [ $status_std -ne 0 ]; then
  exit 1 # 标准编译失败，丢弃
fi

# ---------------------------------------------------------
# 2. 差异检查 (Divergence Check)
# 加上 -Z next-solver=globally 后，必须编译失败 (Error)。
# ---------------------------------------------------------
rustc +nightly -Z next-solver=globally --crate-type lib "$work_dir/bug.rs" >/dev/null 2>&1
status_new=$?

if [ $status_new -ne 0 ]; then
  exit 0 # 找到了！标准版成功，但新 Solver 失败 (Interesting)
else
  exit 1 # 新 Solver 也成功了，没有表现出差异 (Boring)
fi