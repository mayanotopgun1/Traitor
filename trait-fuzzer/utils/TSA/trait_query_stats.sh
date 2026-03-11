#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./utils/TSA/trait_query_stats.sh --file <path/to/file.rs> [options]

Options:
  --compiler <0|1|2>   0=stable, 1=nightly (default), 2=next-solver (nightly)
  --out-dir <path>     Output directory (default: ./trait_query_stats_<timestamp>)
  --top <N>            Top N trait modules to print (default: 15)
  --help               Show this help

Outputs:
  - trait.log          rustc_trait_selection logs
  - build.log          rustc stdout/stderr (except trait log)
  - trait_top.txt      frequency table of trait submodules
  - rustc_profile-*    self-profile artifacts (if emitted)
EOF
}

SOURCE_FILE=""
COMPILER_MODE="1"
OUT_DIR=""
TOP_N="15"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --file)
      SOURCE_FILE="$2"
      shift 2
      ;;
    --compiler)
      COMPILER_MODE="$2"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --top)
      TOP_N="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$SOURCE_FILE" ]]; then
  echo "Missing required --file" >&2
  usage
  exit 1
fi

if [[ ! -f "$SOURCE_FILE" ]]; then
  echo "Source file not found: $SOURCE_FILE" >&2
  exit 1
fi

if ! [[ "$TOP_N" =~ ^[0-9]+$ ]] || [[ "$TOP_N" -le 0 ]]; then
  echo "--top must be a positive integer" >&2
  exit 1
fi

if [[ -z "$OUT_DIR" ]]; then
  OUT_DIR="$(pwd)/trait_query_stats_$(date +%Y%m%d_%H%M%S)"
fi
mkdir -p "$OUT_DIR"

PROFILE_PREFIX="$OUT_DIR/rustc_profile"
TRAIT_LOG="$OUT_DIR/trait.log"
BUILD_LOG="$OUT_DIR/build.log"
TOP_LOG="$OUT_DIR/trait_top.txt"

RUSTC_CMD=("rustc")
EXTRA_ARGS=()
ENABLE_SELF_PROFILE=0
case "$COMPILER_MODE" in
  0)
    RUSTC_CMD=("rustc")
    ENABLE_SELF_PROFILE=0
    ;;
  1)
    RUSTC_CMD=("rustc" "+nightly")
    ENABLE_SELF_PROFILE=1
    ;;
  2)
    RUSTC_CMD=("rustc" "+nightly")
    EXTRA_ARGS=("-Z" "next-solver=globally")
    ENABLE_SELF_PROFILE=1
    ;;
  *)
    echo "Invalid --compiler value: $COMPILER_MODE (expected 0, 1, or 2)" >&2
    exit 1
    ;;
esac

set +e
if [[ "$ENABLE_SELF_PROFILE" -eq 1 ]]; then
  RUSTC_LOG=rustc_trait_selection=info \
    "${RUSTC_CMD[@]}" \
    "${EXTRA_ARGS[@]}" \
    -Z self-profile="$PROFILE_PREFIX" \
    -Z self-profile-events=query-provider,query-cache-hit,query-keys \
    --out-dir "$OUT_DIR" \
    "$SOURCE_FILE" \
    >"$BUILD_LOG" 2>"$TRAIT_LOG"
else
  RUSTC_LOG=rustc_trait_selection=info \
    "${RUSTC_CMD[@]}" \
    "${EXTRA_ARGS[@]}" \
    --out-dir "$OUT_DIR" \
    "$SOURCE_FILE" \
    >"$BUILD_LOG" 2>"$TRAIT_LOG"
fi
compile_status=$?
set -e

trait_total=$(grep -c "rustc_trait_selection" "$TRAIT_LOG" || true)

grep -Eo "rustc_trait_selection::[a-zA-Z0-9_:]+" "$TRAIT_LOG" \
  | sort | uniq -c | sort -nr | head -n "$TOP_N" > "$TOP_LOG" || true

{
  echo "=== trait query stats ==="
  echo "source: $SOURCE_FILE"
  echo "compiler_mode: $COMPILER_MODE (0=stable,1=nightly,2=next-solver)"
  echo "compile_exit_code: $compile_status"
  echo "trait_log_lines: $trait_total"
  echo "out_dir: $OUT_DIR"
  echo
  echo "--- top trait modules ---"
  if [[ -s "$TOP_LOG" ]]; then
    cat "$TOP_LOG"
  else
    echo "(no rustc_trait_selection entries captured)"
  fi
  echo
  echo "--- self-profile artifacts ---"
  profile_list=$(find "$OUT_DIR" -maxdepth 1 -type f \( -name 'rustc_profile*' -o -name '*.mm_profdata' -o -name '*.mm_profevents' -o -name '*.mm_string_data' \) | sort)
  if [[ -n "$profile_list" ]]; then
    echo "$profile_list"
  else
    echo "(no self-profile artifacts found)"
  fi
  echo
  echo "logs:"
  echo "  trait log: $TRAIT_LOG"
  echo "  build log: $BUILD_LOG"
} | tee "$OUT_DIR/summary.txt"
