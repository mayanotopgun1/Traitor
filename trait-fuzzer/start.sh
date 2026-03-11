#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/home/laix/Study"
FUZZ_DIR="/home/laix/Study/Traitor/trait-fuzzer"
OLLAMA_CMD="/usr/local/bin/ollama"
OLLAMA_HOST="127.0.0.1:12023"
OLLAMA_MODELS="/home/laix/.ollama/models"
TARGET_USER="laix"

PID_DIR="$BASE_DIR/.pids"
mkdir -p "$PID_DIR"
OLLAMA_PID_FILE="$PID_DIR/ollama.pid"
MAIN_PID_FILE="$PID_DIR/main.pid"
COVERAGE_CONSUMER_PID_FILE="$FUZZ_DIR/utils/coverage/live_reports/consumer.pid"

pid_cmdline() {
  local pid="$1"
  ps -p "$pid" -o args= 2>/dev/null || true
}

pid_owner() {
  local pid="$1"
  ps -o user= -p "$pid" 2>/dev/null | awk '{print $1}' || true
}

is_target_user_pid() {
  local pid="$1"
  local owner
  owner=$(pid_owner "$pid")
  [ "$owner" = "$TARGET_USER" ]
}

kill_pid_tree() {
  local pid="$1"
  if [ -z "$pid" ]; then
    return 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  if ! is_target_user_pid "$pid"; then
    echo "Skip killing pid=$pid: owner is not $TARGET_USER"
    return 0
  fi

  # Kill children only if they are also owned by TARGET_USER
  local child
  for child in $(pgrep -P "$pid" || true); do
    if is_target_user_pid "$child"; then
      kill "$child" || true
    else
      echo "Skip killing child pid=$child: owner is not $TARGET_USER"
    fi
  done

  kill "$pid" || true
}

safe_kill_pidfile() {
  local pid_file="$1"
  local expected_pat="$2"
  local label="$3"

  if [ ! -f "$pid_file" ]; then
    echo "No ${label} PID file found."
    return 0
  fi

  local pid
  pid=$(cat "$pid_file" 2>/dev/null || true)
  if [ -z "$pid" ]; then
    echo "${label} PID file is empty or unreadable: $pid_file"
    rm -f "$pid_file" || true
    return 0
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    echo "${label} pid from file is not running: $pid (stale pid file)"
    rm -f "$pid_file" || true
    return 0
  fi

  local cmd
  cmd=$(pid_cmdline "$pid")
  if echo "$cmd" | grep -Eq "$expected_pat"; then
    echo "Killing ${label} PID: $pid (and children)..."
    kill_pid_tree "$pid"
  else
    echo "Skip killing ${label}: pid=$pid does not match expected pattern."
    echo "  expected: $expected_pat"
    echo "  actual:   $cmd"
  fi

  rm -f "$pid_file" || true
}

ollama_pids() {
  pgrep -u "$TARGET_USER" -f "[o]llama serve" || true
}

ollama_listener_pid() {
  ss -ltnp 2>/dev/null | awk '/127\.0\.0\.1:12023/ { if (match($0, /pid=[0-9]+/)) { print substr($0, RSTART+4, RLENGTH-4); exit } }'
}

wait_port_free() {
  local port="$1"
  local tries="${2:-20}"
  local i
  for i in $(seq 1 "$tries"); do
    if ! ss -ltnp | grep -q ":${port}"; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

wait_port_listen() {
  local port="$1"
  local tries="${2:-30}"
  local i
  for i in $(seq 1 "$tries"); do
    if ss -ltnp | grep -q ":${port}"; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

kill_ollama_all() {
  local pids listener_pid
  listener_pid=$(ollama_listener_pid)

  # Only target the listener bound to our configured port to avoid killing unrelated ollama serves.
  pids="$listener_pid"

  # If pid file exists, include it too (dedup later).
  if [ -f "$OLLAMA_PID_FILE" ]; then
    local pid_file_pid
    pid_file_pid=$(cat "$OLLAMA_PID_FILE" 2>/dev/null || true)
    if [ -n "$pid_file_pid" ]; then
      pids="$pids $pid_file_pid"
    fi
  fi

  pids=$(echo "$pids" | tr ' ' '\n' | awk 'NF' | sort -u | xargs)
  if [ -z "$pids" ]; then
    return 0
  fi

  echo "Killing (TERM): $pids"
  kill $pids || true
  sleep 1

  local remain
  remain=""
  for pid in $pids; do
    if ! is_target_user_pid "$pid"; then
      echo "Skip non-$TARGET_USER ollama pid: $pid"
      continue
    fi
    if kill -0 "$pid" 2>/dev/null; then
      remain="$remain $pid"
    fi
  done
  remain=$(echo "$remain" | xargs || true)
  if [ -n "$remain" ]; then
    echo "Force killing (KILL): $remain"
    kill -9 $remain || true
  fi

  if ! wait_port_free 12023 20; then
    echo "Port 12023 still busy after kill attempts:"
    ss -ltnp | grep ":12023" || true
    return 1
  fi
  return 0
}

check_and_kill_old_ollama() {
  local pids
  pids=$(ollama_listener_pid)
  if [ -n "$pids" ]; then
    echo "发现占用 12023 的 ollama 进程："
    ps -fp $pids || true
    echo -n "是否 kill 这些进程？(y/N): "
    read -r confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
      kill_ollama_all || return 1
    else
      echo "跳过 kill。"
    fi
  fi
}

kill_other_user_processes() {
  local candidates=""
  local pats=(
    "python(3)?[[:space:]]+main\.py"
    "python(3)?[[:space:]]+utils/coverage/live_case_consumer\.py"
    "[o]llama serve"
    "mutation-AST/target/.*/mutation-ast"
    "(^|[[:space:]/])(gccrs|crab1|rust1)([[:space:]]|$)"
  )

  for pat in "${pats[@]}"; do
    local p
    p=$(pgrep -u "$TARGET_USER" -f "$pat" || true)
    if [ -n "$p" ]; then
      candidates+=" $p"
    fi
  done

  # unique + drop empty
  local pids
  pids=$(echo "$candidates" | tr ' ' '\n' | awk 'NF' | sort -u | xargs)

  if [ -z "$pids" ]; then
    echo "未发现可清理的任务相关进程（main.py/ollama/mutation-ast/gccrs/crab1/rust1）。"
    return 0
  fi

  echo "将清理以下任务相关进程："
  ps -fp $pids || true
  echo -n "确认执行上述清理？(y/N): "
  read -r confirm
  if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "已取消其他进程清理。"
    return 0
  fi
  echo "执行 TERM..."
  local safe_pids=""
  for pid in $pids; do
    if is_target_user_pid "$pid"; then
      safe_pids+=" $pid"
    else
      echo "Skip non-$TARGET_USER pid: $pid"
    fi
  done
  safe_pids=$(echo "$safe_pids" | xargs || true)
  if [ -z "$safe_pids" ]; then
    echo "没有可安全清理的 $TARGET_USER 进程。"
    return 0
  fi

  kill $safe_pids || true
  sleep 1

  local remain=""
  for pid in $safe_pids; do
    if kill -0 "$pid" 2>/dev/null; then
      remain+=" $pid"
    fi
  done
  remain=$(echo "$remain" | xargs || true)
  if [ -n "$remain" ]; then
    echo "以下进程仍存活，尝试 KILL: $remain"
    kill -9 $remain || true
  fi
}

run_clean() {
  (cd "$FUZZ_DIR" && python clean.py --all)
}

cleanup_locks() {
  echo "Cleaning lock dirs..."
  rm -rf \
    "$FUZZ_DIR"/llm_global_lock*.dir \
    "$FUZZ_DIR"/utils/coverage/live_reports/stats_lock.dir \
    "$FUZZ_DIR"/utils/coverage/live_reports/profraw \
    "$FUZZ_DIR"/utils/coverage/live_reports/tmp
}

show_occupy() {
  echo "===== ${TARGET_USER} 资源占用 ====="
  echo "[CPU/内存 Top 15 进程]"
  ps -u "$TARGET_USER" -o pid,ppid,%cpu,%mem,rss,etime,cmd --sort=-%cpu | head -n 16 || true
  echo
  echo "[用户进程总占比]"
  ps -u "$TARGET_USER" -o %cpu=,%mem= | awk '{cpu+=$1; mem+=$2} END {printf("CPU合计: %.2f%%\nMEM合计: %.2f%%\n", cpu, mem)}'
  echo
  echo "[磁盘占用]"
  du -sh "/home/${TARGET_USER}" 2>/dev/null || true
  df -h "/home/${TARGET_USER}" 2>/dev/null || true
}

start_services() {
  check_and_kill_old_ollama

  if ss -ltnp | grep -q "127.0.0.1:12023"; then
    echo "Port 12023 is already in use. Stop existing ollama first (use kill)."
    ss -ltnp | grep "127.0.0.1:12023" || true
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

  if ! wait_port_listen 12023 30; then
    echo "Ollama did not bind 12023 in time. Check ollama.log"
    return 1
  fi

  # Prefer the actual listener pid, fallback to background pid.
  local listen_pid
  listen_pid=$(ss -ltnp | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | head -n 1)
  if [ -n "$listen_pid" ]; then
    echo "$listen_pid" > "$OLLAMA_PID_FILE"
  fi

  echo "Starting main.py..."
  (cd "$FUZZ_DIR" && nohup nice -n 5 python main.py > my_fuzz.log 2>&1 & echo $! > "$MAIN_PID_FILE")

  echo "Started. PIDs: ollama=$(cat "$OLLAMA_PID_FILE" 2>/dev/null || echo '?'), main=$(cat "$MAIN_PID_FILE" 2>/dev/null || echo '?')"
}

kill_services() {
  safe_kill_pidfile "$MAIN_PID_FILE" "python(3)?[[:space:]]+main\\.py.*trait-fuzzer" "main.py"

  # Fallback: kill trait-fuzzer main.py processes even if PID file is stale.
  pkill -u "$TARGET_USER" -f "python(3)?[[:space:]]+main\.py.*trait-fuzzer" || true

  safe_kill_pidfile "$OLLAMA_PID_FILE" "ollama[[:space:]]+serve|/usr/local/bin/ollama" "ollama"

  safe_kill_pidfile "$COVERAGE_CONSUMER_PID_FILE" "python(3)?[[:space:]]+utils/coverage/live_case_consumer\\.py" "coverage-consumer"

  # Fallback: kill coverage consumer even if pid file is stale/missing.
  pkill -u "$TARGET_USER" -f "python(3)?[[:space:]]+utils/coverage/live_case_consumer\.py" || true

  cleanup_locks

  echo "是否继续检查 ${TARGET_USER} 的其他进程并清理？输入 1 清理，输入 0 跳过："
  read -r kill_other
  if [ "$kill_other" = "1" ]; then
    kill_other_user_processes
  else
    echo "跳过其他进程清理。"
  fi

  echo "是否清理？输入 1 清理，其他跳过："
  read -r do_clean
  if [ "$do_clean" = "1" ]; then
    run_clean
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

main_menu() {
  echo "输入 1：start  输入 2：kill  输入 3：watch  输入 4：occupy  输入 5：clean"
  read -r action
  case "$action" in
    1|start) start_services ;;
    2|kill) kill_services ;;
    3|watch) watch_logs ;;
    4|occupy) show_occupy ;;
    5|clean) run_clean ;;
    *) echo "Unknown action" ;;
  esac
}

main_menu