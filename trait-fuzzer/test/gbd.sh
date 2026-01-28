#!/bin/bash

# --- 配置 ---
INPUT_FILE="bug.rs"
# 强制使用当前目录的绝对路径
OUTPUT_LOG="$(pwd)/n.txt"
WAIT_TIME=10
TARGET_THREAD=99

echo "目标文件: $INPUT_FILE"
echo "输出路径: $OUTPUT_LOG"

# --- 1. 准备 GDB 指令文件 ---
cat <<EOF > cmd.gdb
set pagination off
# 设置日志输出到文件
set logging file $OUTPUT_LOG
set logging enabled on
# 开始运行
run
# 注意：收到 Ctrl+C 后会停在这里，然后继续执行下面的指令
thread $TARGET_THREAD
bt 30
# 强制刷新缓冲区并关闭日志
set logging enabled off
quit
EOF

# --- 2. 运行 GDB ---
# 使用 -batch 可能会导致中断后直接退出，所以我们不用 -batch
# 我们在后台启动它
gdb -q -x cmd.gdb --args rustc +nightly -Z next-solver=globally "$INPUT_FILE" &
GDB_PID=$!

# --- 3. 等待并中断 ---
echo "正在等待编译器 Hang 住 ($WAIT_TIME 秒)..."
sleep $WAIT_TIME

echo "发送中断信号提取堆栈..."
# 发送 INT 信号（相当于按下 Ctrl+C）
kill -INT $GDB_PID

# 给 GDB 一点时间执行 thread 99 和 bt 20
sleep 3

# 如果 GDB 还没退出，强行补刀，但通常它执行完指令会自己 quit
if ps -p $GDB_PID > /dev/null; then
    kill -9 $GDB_PID 2>/dev/null
fi

# --- 4. 检查结果 ---
if [ -f "$OUTPUT_LOG" ]; then
    echo "--------------------------------------"
    echo "成功！指纹已保存至: $OUTPUT_LOG"
    echo "文件内容预览 (前5行):"
    head -n 5 "$OUTPUT_LOG"
    echo "--------------------------------------"
else
    echo "错误: 未能生成 $OUTPUT_LOG。"
    echo "请检查当前目录下是否有权限写入文件，或者尝试手动运行一次以确认线程 99 是否存在。"
fi

# 清理
rm -f cmd.gdb