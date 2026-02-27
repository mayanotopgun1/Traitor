#!/usr/bin/env bash
# 注意：treereduce 会把待测文件名作为第一个参数传进来 ($1)
INPUT_FILE="${1:-bug.rs}"
MODE="${FUZZ_MODE:-0}"

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
cp "$INPUT_FILE" "$work_dir/bug.rs"

case $MODE in
  0) # Hang check
    set +e
    timeout --preserve-status 2s rustc +nightly -Z unpretty=ast-tree "$work_dir/bug.rs" >/dev/null 2>&1
    [ $? -ne 0 ] && exit 1
    timeout --preserve-status 8s rustc +nightly  -Z next-solver=globally "$work_dir/bug.rs" >/dev/null 2>&1
    status=$?
    # 124, 137, 143 是 timeout 杀掉进程的状态码
    [[ $status -eq 124 || $status -eq 137 || $status -eq 143 ]] && exit 0 || exit 1
    ;;
  1) # ICE check
    set +e
    timeout --preserve-status 5s rustc +nightly -Z unpretty=ast-tree "$work_dir/bug.rs" >/dev/null 2>&1
    [ $? -ne 0 ] && exit 1
    output_log="$work_dir/output.log"
    rustc +nightly -Z next-solver=globally "$work_dir/bug.rs" >"$output_log" 2>&1
    grep -Fq "panicked" "$output_log" && exit 0 || exit 1
    ;;
  2) # Standard success, new fail
    rustc +nightly --crate-type lib "$work_dir/bug.rs" >/dev/null 2>&1 || exit 1
    rustc +nightly -Z next-solver=globally --crate-type lib "$work_dir/bug.rs" >/dev/null 2>&1
    [ $? -ne 0 ] && exit 0 || exit 1
    ;;
  3) # Standard fail, new success
    rustc +nightly --crate-type lib "$work_dir/bug.rs" >/dev/null 2>&1 && exit 1
    rustc +nightly -Z next-solver=globally --crate-type lib "$work_dir/bug.rs" >/dev/null 2>&1
    [ $? -eq 0 ] && exit 0 || exit 1
    ;;
esac