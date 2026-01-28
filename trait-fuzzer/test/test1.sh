#!/usr/bin/env bash
set -euo pipefail

input_file="${1:-bug.rs}"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
cp "$input_file" "$work_dir/bug.rs"

# 1. 语法检查 (Sanity Check)
# 依然保留这一步，防止 reduce 出连 AST 都无法生成的无效代码
# (这里保留 timeout 只是为了防一手 parsing 阶段的极端死循环，如果不想要也可以去掉)
set +e
timeout --preserve-status -k 1s 10s rustc +nightly -Z unpretty=ast-tree "$work_dir/bug.rs" >/dev/null 2>&1
parse_status=$?
if [ $parse_status -ne 0 ]; then
  exit 1
fi

# 2. 运行编译器 (无 timeout)
# 直接运行，重定向所有输出到文件，以便检索报错信息
output_log="$work_dir/output.log"

# 注意：这里去掉了 timeout 命令
# rustc +nightly -Z next-solver=globally "$work_dir/bug.rs" >"$output_log" 2>&1
rustc  +nightly "$work_dir/bug.rs" >"$output_log" 2>&1
status=$?

# 3. 判定逻辑
# ICE 的特征是 stderr 中包含 "internal compiler error"
if grep -Fq "internal" "$output_log"; then
  exit 0 # 找到了 ICE，这是我们要的
else
  exit 1 # 普通报错或编译成功，丢弃
fi