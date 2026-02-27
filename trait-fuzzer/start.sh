#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/home/laix/Study"
FUZZ_DIR="/home/laix/Study/Traitor/trait-fuzzer"
OLLAMA_CMD="/usr/local/bin/ollama"
OLLAMA_HOST="127.0.0.1:12023"
OLLAMA_MODELS="/home/laix/.ollama/models"

PID_DIR="$BASE_DIR/.pids"
mkdir -p "$PID_DIR"
OLLAMA_PID_FILE="$PID_DIR/ollama.pid"
MAIN_PID_FILE="$PID_DIR/main.pid"

check_and_kill_old_ollama() {
  local pids
  pids=$(pgrep -u laix -f "ollama serve" || true)
  if [ -n "$pids" ]; then
    echo "发现 laix 用户旧的 ollama 进程："
    ps -u laix -f | grep "ollama serve" | grep -v grep || true
    echo -n "是否 kill 这些进程？(y/N): "
    read -r confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
      echo "Killing: $pids"
      kill $pids || true
      sleep 1
    else
      echo "跳过 kill。"
    fi
  fi
}

start_services() {
  check_and_kill_old_ollama

  if ss -ltnp | grep -q ":12023"; then
    echo "Port 12023 is already in use. Stop existing ollama first (use kill)."
    ss -ltnp | grep ":12023" || true
    return 1
  fi

  if [ -f "$OLLAMA_PID_FILE" ]; then
    if kill -0 "$(cat "$OLLAMA_PID_FILE" 2>/dev/null)" 2>/dev/null; then
      echo "Ollama already running with PID $(cat "$OLLAMA_PID_FILE")."
      return 1
    fi
  fi

  if [ -f "$MAIN_PID_FILE" ]; then
    if kill -0 "$(cat "$MAIN_PID_FILE" 2>/dev/null)" 2>/dev/null; then
      echo "main.py already running with PID $(cat "$MAIN_PID_FILE")."
      return 1
    fi
  fi

  echo "Starting ollama..."
  (cd "$FUZZ_DIR" && nohup env OLLAMA_DEBUG=1 OLLAMA_HOST="$OLLAMA_HOST" OLLAMA_MODELS="$OLLAMA_MODELS" OLLAMA_NUM_PARALLEL=1 OMP_NUM_THREADS=32 nice -n 10 taskset -c 0-31 "$OLLAMA_CMD" serve > ollama.log 2>&1 & echo $! > "$OLLAMA_PID_FILE")

  echo "Starting main.py..."
  (cd "$FUZZ_DIR" && nohup nice -n 5 python main.py > my_fuzz.log 2>&1 & echo $! > "$MAIN_PID_FILE")

  echo "Started. PIDs: ollama=$(cat "$OLLAMA_PID_FILE" 2>/dev/null || echo '?'), main=$(cat "$MAIN_PID_FILE" 2>/dev/null || echo '?')"
}

kill_services() {
  if [ -f "$MAIN_PID_FILE" ]; then
    MAIN_PID=$(cat "$MAIN_PID_FILE" || true)
    if [ -n "$MAIN_PID" ]; then
      echo "Killing main.py PID $MAIN_PID and its children..."
      pkill -P "$MAIN_PID" || true
      kill "$MAIN_PID" || true
    fi
    rm -f "$MAIN_PID_FILE" || true
  else
    echo "No main PID file found."
  fi

  if [ -f "$OLLAMA_PID_FILE" ]; then
    OLLAMA_PID=$(cat "$OLLAMA_PID_FILE" || true)
    if [ -n "$OLLAMA_PID" ]; then
      echo "Killing ollama PID $OLLAMA_PID and its children..."
      pkill -P "$OLLAMA_PID" || true
      kill "$OLLAMA_PID" || true
    fi
    rm -f "$OLLAMA_PID_FILE" || true
  else
    echo "No ollama PID file found."
  fi

  echo "是否清理？输入 1 清理，其他跳过："
  read -r do_clean
  if [ "$do_clean" = "1" ]; then
    (cd "$FUZZ_DIR" && python clean.py --all)
  else
    echo "跳过清理。"
  fi
}

watch_logs() {
  echo "Choose log to watch:"
  echo "1) my_fuzz.log"
  echo "2) ollama.log"
  read -r choice
  case "$choice" in
    1) (cd "$FUZZ_DIR" && tail -f my_fuzz.log) ;;
    2) (cd "$FUZZ_DIR" && tail -f ollama.log) ;;
    *) echo "Unknown choice" ;;
  esac
}

occupy() {
  ps -u laix -o %cpu,%mem --no-headers | awk '{cpu += $1; mem += $2} END {printf "\n\033[1;32m[ laix7 资源汇总报告 ]\033[0m\nCPU 总占用: %.1f%%\n内存总占用: %.1f%%\n(当前机器核心数: 96 | 总内存: 251G)\n", cpu, mem}'

  total_procs=$(ps -u laix --no-headers | wc -l | tr -d ' ')
  echo "进程总数（laix）: ${total_procs}"

  if [ -f "$MAIN_PID_FILE" ]; then
    MAIN_PID=$(cat "$MAIN_PID_FILE" 2>/dev/null || true)
    if [ -n "$MAIN_PID" ] && kill -0 "$MAIN_PID" 2>/dev/null; then
      child_count=$(pgrep -P "$MAIN_PID" | wc -l | tr -d ' ')
      echo "main.py 进程树数量（含主进程）: $((child_count + 1))"
    fi
  fi
}

main_menu() {
  echo "输入 1：start  输入 2：kill  输入 3：watch  输入 5：occupy"
  read -r action
  case "$action" in
    1|start) start_services ;;
    2|kill) kill_services ;;
    3|watch) watch_logs ;;
    5|occupy) occupy ;;
    *) echo "Unknown action" ;;
  esac
}

main_menu