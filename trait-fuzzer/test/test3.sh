#!/usr/bin/env bash
set -euo pipefail

input_file="${1:-bug.rs}"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
cp "$input_file" "$work_dir/bug.rs"

# 关闭 -e，我们需要手动处理返回码
set +e

# ---------------------------------------------------------
# 1. 基准检查 (Standard)
# 预期：必须报错 (FAIL)
# 如果旧版都能编译通过，说明不是我们要找的差异，丢弃。
# ---------------------------------------------------------
rustc +nightly --crate-type lib "$work_dir/bug.rs" >/dev/null 2>&1
if [ $? -eq 0 ]; then
  exit 1 
fi

# ---------------------------------------------------------
# 2. 差异检查 (Next Solver)
# 预期：必须通过 (SUCCESS)
# 如果新版能编译过，而上面旧版没过，就是我们要找的 case。
# ---------------------------------------------------------
rustc +nightly -Z next-solver=globally --crate-type lib "$work_dir/bug.rs" >/dev/null 2>&1
if [ $? -eq 0 ]; then
  exit 0 # 找到了 (Interesting)
else
  exit 1 # 新版也报错，丢弃
fi