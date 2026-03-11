#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

TARGET="${1:-}"
MODE="${2:-}"
PATTERN="${3:-}"
RUN_STYLE="${4:---bg}"

prompt_target() {
  echo "选择覆盖来源："
  echo "  1) seeds"
  echo "  2) cases (utils/coverage/case)"
  echo "  3) show (查看当前 run_cov 进程)"
  read -r -p "请输入 1/2/3 [默认 1]: " choice
  case "${choice:-1}" in
    1) TARGET="seeds" ;;
    2) TARGET="cases" ;;
    3) TARGET="show" ;;
    *)
      echo "输入无效，使用默认 seeds"
      TARGET="seeds"
      ;;
  esac
}

show_status() {
  local log_file="utils/coverage/live_reports/run_cov.log"
  local pid_file="utils/coverage/live_reports/run_cov.pid"
  local pids=""

  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      pids="$pid"
    fi
  fi

  if [[ -z "$pids" ]]; then
    pids="$(pgrep -f "python utils/coverage/rustc_multi_case_coverage.py" || true)"
  fi

  if [[ -z "$pids" ]]; then
    echo "当前没有运行中的 run_cov 覆盖任务。"
    exit 0
  fi

  echo "当前运行中的 run_cov 任务 PID: $pids"
  ps -fp $pids || true
  echo "日志文件: $log_file"
  echo "查看日志: tail -f $log_file"
  echo "停止任务: kill $pids"
  exit 0
}

prompt_mode() {
  echo "选择运行模式："
  echo "  1) clean (清空后重跑)"
  echo "  2) resume (续跑，不清空)"
  read -r -p "请输入 1 或 2 [默认 1]: " choice
  case "${choice:-1}" in
    1) MODE="--clean" ;;
    2) MODE="--resume" ;;
    *)
      echo "输入无效，使用默认 clean"
      MODE="--clean"
      ;;
  esac
}

prompt_pattern() {
  read -r -p "文件匹配 pattern [默认 *.rs]: " input_pattern
  PATTERN="${input_pattern:-*.rs}"
}



if [[ -z "$TARGET" ]]; then
  prompt_target
fi

if [[ "$TARGET" == "show" ]]; then
  show_status
fi

if [[ -z "$MODE" ]]; then
  prompt_mode
fi
if [[ -z "$PATTERN" ]]; then
  prompt_pattern
fi

case "$TARGET" in
  seeds)
    CASES_DIR="Traitor_Agent/trait_dense_seeds"
    ;;
  cases)
    CASES_DIR="utils/coverage/case"
    ;;
  show)
    show_status
    ;;
  *)
    echo "错误: TARGET 只能是 seeds / cases / show"
    exit 1
    ;;
esac

CLEAN_FLAG=""
case "$MODE" in
  1)
    CLEAN_FLAG="--clean"
    MODE="--clean"
    ;;
  2)
    CLEAN_FLAG=""
    MODE="--resume"
    ;;
  --clean)
    CLEAN_FLAG="--clean"
    ;;
  --resume)
    CLEAN_FLAG=""
    ;;
  *)
    echo "错误: 第二个参数只能是 --clean 或 --resume"
    exit 1
    ;;
esac



EXISTING_PIDS="$(pgrep -f "python utils/coverage/rustc_multi_case_coverage.py" || true)"
if [[ -n "$EXISTING_PIDS" ]]; then
  echo "检测到已有覆盖任务在运行: $EXISTING_PIDS"
  echo -n "是否先停止旧任务再继续？(y/N): "
  read -r confirm_kill
  if [[ "$confirm_kill" == "y" || "$confirm_kill" == "Y" ]]; then
    kill $EXISTING_PIDS || true
    sleep 1
  else
    echo "已取消，避免多个任务同时写同一个 timeline。"
    exit 1
  fi
fi

CMD=(
  python utils/coverage/rustc_multi_case_coverage.py
  --cases-dir "$CASES_DIR"
  --pattern "$PATTERN"
  --work-dir utils/coverage/live_reports
  --timeline-csv utils/coverage/live_reports/timeline_total.csv
)

if [[ -n "$CLEAN_FLAG" ]]; then
  CMD+=("$CLEAN_FLAG")
fi

case "$RUN_STYLE" in
  --bg|bg|"")
    RUN_STYLE="--bg"
    ;;
  --fg|fg)
    RUN_STYLE="--fg"
    ;;
  *)
    echo "错误: 第四个参数只能是 --bg 或 --fg"
    exit 1
    ;;
esac

LOG_FILE="utils/coverage/live_reports/run_cov.log"
PID_FILE="utils/coverage/live_reports/run_cov.pid"

echo
echo "目标目录: $CASES_DIR"
echo "模式: $MODE"
echo "pattern: $PATTERN"
echo "运行方式: $RUN_STYLE"

echo "执行命令: ${CMD[*]}"
if [[ "$RUN_STYLE" == "--bg" ]]; then
  nohup "${CMD[@]}" > "$LOG_FILE" 2>&1 &
  RUN_PID=$!
  echo "$RUN_PID" > "$PID_FILE"
  echo "已后台启动，PID: $RUN_PID"
  echo "日志: $LOG_FILE"
  echo "看进度: tail -f $LOG_FILE"
  echo "停任务: kill $RUN_PID"
else
  "${CMD[@]}"
fi
