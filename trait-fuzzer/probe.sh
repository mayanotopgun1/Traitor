#!/usr/bin/env bash

set -euo pipefail

# Ensure cargo-installed tools are visible.
export PATH="$HOME/.cargo/bin:$PATH"

FILE_PATH="${1:-}"
if [[ -z "${FILE_PATH}" ]]; then
    echo "Usage: bash ./probe.sh <path/to/file.rs>" >&2
    exit 2
fi
if [[ ! -f "${FILE_PATH}" ]]; then
    echo "Error: file not found: ${FILE_PATH}" >&2
    exit 2
fi

# Convert to absolute path because we run rustc inside a temp workdir.
FILE_PATH="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "${FILE_PATH}")"

if ! command -v rustc >/dev/null 2>&1; then
    echo "Error: rustc not found in PATH" >&2
    exit 1
fi
if ! command -v summarize >/dev/null 2>&1; then
    echo "Error: summarize not found in PATH." >&2
    echo "Hint: install it via cargo (measureme tools), e.g. 'cargo install summarize' (exact crate may vary)." >&2
    exit 1
fi

# Run profiling in an isolated temp dir so we can reliably collect *.mm_profdata.
WORKDIR="$(mktemp -d -t trait_probe_XXXXXX)"
if [[ "${KEEP_PROBE:-0}" == "1" ]]; then
        echo "[probe] KEEP_PROBE=1 set; will not delete workdir on exit." >&2
else
        cleanup() { rm -rf "${WORKDIR}"; }
        trap cleanup EXIT
fi

echo "[probe] workdir: ${WORKDIR}"

set +e
pushd "${WORKDIR}" >/dev/null

# Ensure rustc uses a writable temp directory. Some environments have /dev unwritable.
export TMPDIR="${WORKDIR}"

OUTDIR="${WORKDIR}/out"
mkdir -p "${OUTDIR}"

# Note: the correct spelling is '-Zself-profile' (no space after -Z).
# We don't require successful compilation; we only need the profile output.
# Added 'timeout' to prevent infinite hangs.
RUSTC_BIN="${RUSTC_BIN:-rustc}"
RUSTC_TOOLCHAIN="${RUSTC_TOOLCHAIN:-+nightly}"
SELF_PROFILE_EVENTS="${SELF_PROFILE_EVENTS:-default,args}"
CRATE_NAME="${CRATE_NAME:-trait_probe}"

if ! command -v "${RUSTC_BIN}" >/dev/null 2>&1; then
        echo "Error: rustc binary not found: ${RUSTC_BIN}" >&2
        exit 1
fi

TIMEOUT_ARGS=()
if command -v timeout >/dev/null 2>&1; then
        # Default timeout is conservative; override via env if needed.
        PROBE_TIMEOUT="${PROBE_TIMEOUT:-10s}"
        PROBE_TIMEOUT_KILL_AFTER="${PROBE_TIMEOUT_KILL_AFTER:-5}"
        TIMEOUT_ARGS=(timeout -k "${PROBE_TIMEOUT_KILL_AFTER}" "${PROBE_TIMEOUT}")
fi

RUSTC_CMD=("${RUSTC_BIN}")
if [[ -n "${RUSTC_TOOLCHAIN}" ]]; then
        RUSTC_CMD+=("${RUSTC_TOOLCHAIN}")
fi

"${TIMEOUT_ARGS[@]}" "${RUSTC_CMD[@]}" \
    -Zself-profile \
        -Zself-profile-events="${SELF_PROFILE_EVENTS}" \
                --crate-name "${CRATE_NAME}" \
        --crate-type=lib \
        --out-dir "${OUTDIR}" \
    "${FILE_PATH}" \
    2>"rustc.stderr"
RUSTC_RC=$?

popd >/dev/null
set -e

if [[ ${RUSTC_RC} -ne 0 ]]; then
    echo "[probe] rustc exited non-zero (${RUSTC_RC}); continuing (profile may still exist)." >&2
fi

export RUSTC_RC
export RUSTC_STDERR="${WORKDIR}/rustc.stderr"
export WORKDIR

PROF_FILE="$(ls -t "${WORKDIR}"/*.mm_profdata 2>/dev/null | head -n 1 || true)"
# [FIX] Do not exit if no profdata found, allow Python to handle the missing file (using RC=124 to detect timeout)
if [[ -z "${PROF_FILE}" ]]; then
    echo "Warning: no .mm_profdata produced (likely early crash/timeout)." >&2
    export SUMMARY_JSON=""
        export PROF_FILE=""
        export FILE_PREFIX=""
else
    echo "[probe] profdata: ${PROF_FILE}"
    FILE_PREFIX="${PROF_FILE%.mm_profdata}"
    echo "[probe] summarize prefix: ${FILE_PREFIX}"
        export PROF_FILE
        export FILE_PREFIX

    # summarize --json writes a json file next to <FILE_PREFIX> (not stdout).
    set +e
    summarize summarize --json "${FILE_PREFIX}" 2>"${WORKDIR}/summarize.stderr"
    SUM_RC=$?
    set -e

    SUMMARY_JSON="${FILE_PREFIX}.json"
    
    # [FIX] If summarize fails (e.g. corrupt file due to timeout), do NOT exit.
    # Instead, treat valid JSON as empty, let Python use RUSTC_RC to give fallback score.
    if [[ ${SUM_RC} -ne 0 || ! -s "${SUMMARY_JSON}" ]]; then
            echo "Warning: summarize failed (RC=${SUM_RC}). Profile likely corrupt due to timeout." >&2
            echo "--- summarize stderr (tail) ---" >&2
            tail -n 10 "${WORKDIR}/summarize.stderr" >&2 || true
            export SUMMARY_JSON=""
    else
            export SUMMARY_JSON
    fi
fi

export FILE_PATH

python3 - <<'PY'
import json
import re
import os
import math
from pathlib import Path

# [FIX] Handle empty/missing env var safely
summary_path_str = os.environ.get("SUMMARY_JSON", "")
input_path = Path(os.environ["FILE_PATH"])
r_rc = int(os.environ.get("RUSTC_RC", "0"))
stderr_path = Path(os.environ.get("RUSTC_STDERR", ""))
workdir = os.environ.get("WORKDIR", "")
prof_file = os.environ.get("PROF_FILE", "")
file_prefix = os.environ.get("FILE_PREFIX", "")
size_norm_mode = os.environ.get("SIZE_NORM", "loc_log")  # loc_log|none

try:
        rustc_stderr = stderr_path.read_text(encoding="utf-8", errors="ignore") if str(stderr_path) else ""
except Exception:
        rustc_stderr = ""

def classify_status(rc: int, stderr: str) -> tuple[str, str]:
        s = stderr
        sl = s.lower()
        if rc == 0:
                return "ok", ""
        # Common external terminations.
        if rc in (124, 137, 143):
                return "timeout_or_killed", f"rustc_rc={rc}"
        # ICEs / panics.
        if "internal compiler error" in sl or "compiler unexpectedly panicked" in sl or "thread 'rustc' panicked" in sl:
                return "ice", "rustc ICE/panic"
        # Trait overflow
        if "error[e0275]" in sl and "overflow evaluating" in sl:
                return "trait_overflow", "E0275 overflow evaluating"
        if "overflow evaluating the requirement" in sl:
                return "trait_overflow", "overflow evaluating the requirement"
        return "compile_error", "rustc exited non-zero"

status, status_detail = classify_status(r_rc, rustc_stderr)

# [FIX] Robust JSON loading. If file doesn't exist or is invalid, rows = []
rows = []
if summary_path_str and os.path.exists(summary_path_str):
    try:
        data = json.loads(Path(summary_path_str).read_text(encoding="utf-8", errors="ignore"))
        rows = data.get("results") or data.get("query_data") or []
    except Exception:
        rows = []

try:
        text = input_path.read_text(encoding="utf-8", errors="ignore")
        loc = max(1, text.count("\n") + 1)
        nbytes = len(text.encode("utf-8", errors="ignore"))
except Exception:
        loc = 1
        nbytes = 0

def as_ns_time(v):
        if isinstance(v, dict) and "secs" in v and "nanos" in v:
                return int(v.get("secs", 0)) * 1_000_000_000 + int(v.get("nanos", 0))
        try:
                return int(v)
        except Exception:
                return 0

def num(x, k, default=0):
        try:
                return int(x.get(k, default))
        except Exception:
                return default

def calls_of(r):
        if "number_of_calls" in r:
                return num(r, "number_of_calls")
        if "invocation_count" in r:
                return num(r, "invocation_count")
        return 0

def self_ns_of(r):
        return as_ns_time(r.get("self_time", 0))

total_self = sum(self_ns_of(r) for r in rows)
total_calls = sum(calls_of(r) for r in rows)

# A broad, *exploratory* matcher for trait-solving-ish work.
trait_re = re.compile(r"trait|obligation|select|fulfill|evaluate|solve|coherence|infer", re.I)
trait_core_re = trait_re
trait_like_re = re.compile(r"trait|obligation|select|fulfill|evaluate|solve|coherence|infer|normalize|projection", re.I)

trait_core_self = sum(self_ns_of(r) for r in rows if trait_core_re.search(str(r.get("label", ""))))
trait_like_self = sum(self_ns_of(r) for r in rows if trait_like_re.search(str(r.get("label", ""))))

proj_re = re.compile(r"normalize|projection", re.I)
proj_self = sum(self_ns_of(r) for r in rows if proj_re.search(str(r.get("label", ""))))

# [NEW] Add Monomorphization monitoring
mono_re = re.compile(r"monomorphization|codegen|llvm", re.I)
mono_self = sum(self_ns_of(r) for r in rows if mono_re.search(str(r.get("label", ""))))

def find_exact(label: str):
        return next((r for r in rows if str(r.get("label", "")) == label), None)

def pick_eval_event(rows_in):
        # Prefer exact known labels, but fall back to fuzzy matches.
        exact_priority = [
                "evaluate_obligation",
                "evaluate_obligation_recursively",
                "trait_select",
        ]
        for lab in exact_priority:
                hit = next((r for r in rows_in if str(r.get("label", "")) == lab), None)
                if hit:
                        return lab, hit

        # Fuzzy fallback: pick the best trait-solver-ish match by call volume (then by self time).
        patterns = [
                re.compile(r"evaluate_obligation", re.I),
                re.compile(r"trait_select", re.I),
                re.compile(r"fulfill|obligation", re.I),
        ]
        for pat in patterns:
                candidates = []
                for r in rows_in:
                        label = str(r.get("label", ""))
                        if pat.search(label):
                                candidates.append(r)
                if not candidates:
                        continue
                candidates.sort(key=lambda r: (calls_of(r), self_ns_of(r)), reverse=True)
                chosen = candidates[0]
                return str(chosen.get("label", "")), chosen

        return "", None

eval_ob = find_exact("evaluate_obligation")
eval_time_ns = self_ns_of(eval_ob) if eval_ob else 0
eval_calls = calls_of(eval_ob) if eval_ob else 0

eval_ms = eval_time_ns / 1e6
eval_avg_us = (eval_time_ns / max(eval_calls, 1)) / 1e3 

eval_label_used, eval_row_used = pick_eval_event(rows)
eval_used_time_ns = self_ns_of(eval_row_used) if eval_row_used else 0
eval_used_calls = calls_of(eval_row_used) if eval_row_used else 0
eval_used_ms = eval_used_time_ns / 1e6
eval_used_avg_us = (eval_used_time_ns / max(eval_used_calls, 1)) / 1e3

def topn(filter_re=None, n=12):
        rows_out = []
        for r in rows_in:
                label = str(r.get("label", ""))
                if filter_re and not filter_re.search(label):
                        continue
                rows_out.append((self_ns_of(r), calls_of(r), label))
        rows_out.sort(reverse=True)
        return rows_out[:n]

rows_in = rows

print("\n================ probe results ================")
print(f"Status: {status} (rustc_rc={r_rc})" + (f" [{status_detail}]" if status_detail else ""))
print(f"Total self time: {total_self/1e9:.6f} s")
print(f"Total calls:     {total_calls}")
if total_self:
        print(f"Trait-like self: {trait_like_self/1e9:.6f} s ({trait_like_self/total_self*100:.2f}%)")
        print(f"Trait-core self: {trait_core_self/1e9:.6f} s ({trait_core_self/total_self*100:.2f}%)")
else:
        print("Trait-like self: 0")
        print("Trait-core self: 0")

if total_self:
        print(f"Proj/Norm self:  {proj_self/1e9:.6f} s ({proj_self/total_self*100:.2f}%)")
else:
        print("Proj/Norm self:  0")

if total_self:
        print(f"Mono/Gen self:   {mono_self/1e9:.6f} s ({mono_self/total_self*100:.2f}%)")
else:
        print("Mono/Gen self:   0")

print("\nTop by self_time (overall):")
for self_ns, calls, label in topn(None, n=10):
        avg_us = (self_ns / calls / 1e3) if calls else 0.0
        print(f"  {self_ns/1e6:10.3f} ms | calls={calls:8d} | avg={avg_us:9.3f} us | {label}")

print("\nTop by self_time (trait-like):")
for self_ns, calls, label in topn(trait_re, n=12):
        avg_us = (self_ns / calls / 1e3) if calls else 0.0
        print(f"  {self_ns/1e6:10.3f} ms | calls={calls:8d} | avg={avg_us:9.3f} us | {label}")

for key in ("trait_select", "evaluate_obligation", "evaluate_obligation_recursively"):
        hit = next((r for r in rows if r.get("label") == key), None)
        if hit:
                calls = calls_of(hit)
                self_ns = self_ns_of(hit)
                avg_us = (self_ns / calls / 1e3) if calls else 0.0
                print(f"\nKey event '{key}': self={self_ns/1e6:.3f} ms calls={calls} avg={avg_us:.3f} us")

if eval_row_used is not None:
        print(
                "\nEval event used for scoring: "
                + f"label='{eval_label_used}' self={eval_used_ms:.3f} ms calls={eval_used_calls} avg={eval_used_avg_us:.3f} us"
        )

# A simple score for fuzzing: higher means "harder trait solving".
trait_like_pct = (trait_like_self / total_self) if total_self else 0.0
proj_ms = proj_self / 1e6
mono_ms = mono_self / 1e6 
trait_ms = trait_core_self / 1e6

# [IMPROVED LOGIC]
pressure_ms = trait_ms + proj_ms + mono_ms
complexity_mult = 1.0 + (eval_used_avg_us / 50.0)

base = pressure_ms * complexity_mult
gating = 0.1 if trait_like_pct < 0.01 else 1.0
if size_norm_mode == "none":
        size_norm = 1.0
else:
        # Keep it mild: downweight huge files without flattening small ones.
        size_norm = math.log1p(loc)

fallback_base = 0.0
# [IMPROVED] Dynamic fallback scores
if status == "trait_overflow":
        fallback_base = 5000.0 * complexity_mult 
elif status == "ice":
        fallback_base = 10000.0 
elif status == "timeout_or_killed":
        fallback_base = 20000.0 

base_eff = max(base, fallback_base)
score = (base_eff * gating) / size_norm

print("\n================ score (with variable meanings) ================")
print("1) Formula")
print("   [IMPROVED] Linear Scoring w/ Complexity Multiplier (Log removed)")
print("   pressure_ms = trait_ms + proj_ms + mono_ms")
print("   complexity  = 1.0 + (eval_avg_us / 50.0)")
print("   base        = pressure_ms * complexity")
print("   score       = (max(base, fallback) * gating) / size_norm")
print("   size_norm   = ln(1 + loc) by default (set SIZE_NORM=none to disable)")

print("\n   Variable meanings")
print("   eval_avg_us    = average self time per 'evaluate_obligation' call (microseconds/call).")
print("   eval_calls     = number of calls for 'evaluate_obligation'.")
print("   proj_ms        = sum of self time for labels matching /normalize|projection/i.")
print("   mono_ms        = sum of self time for labels matching /monomorphization|codegen|llvm/i (NEW).")
print("   trait_like_pct = trait_like_self / total_self (ratio).")
print("   loc            = lines of code (ignored for scoring now).")
print("   base           = score before gating.")

print("\n2) Values substituted")
print(f"   status         = {status}")
print(f"   rustc_rc       = {r_rc}")
print(f"   eval_label_used= {eval_label_used or '<none>'}")
print(f"   eval_used_avg_us = {eval_used_avg_us:.6f} us/call")
print(f"   eval_used_calls  = {eval_used_calls}")
print(f"   (exact evaluate_obligation avg_us={eval_avg_us:.6f}, calls={eval_calls})")
print(f"   proj_ms        = {proj_ms:.6f} ms")
print(f"   mono_ms        = {mono_ms:.6f} ms")
print(f"   trait_like_pct = {trait_like_pct:.6f}")
print(f"   loc            = {loc}")
print(f"   size_norm      = {size_norm:.6f}")
print(f"   gating         = {gating:.1f}")
print(f"   base           = {base:.6f}")
print(f"   fallback_base  = {fallback_base:.6f}")
print(f"   base_eff       = {base_eff:.6f}")

print("\n3) Final score")
print("   score = {:.6f}".format(score))
print("================================================\n")

payload = {
        "input_loc": loc,
        "input_bytes": nbytes,
        "workdir": workdir,
        "profdata": prof_file,
        "profile_prefix": file_prefix,
        "summary_json": summary_path_str,
        "status": status,
        "status_detail": status_detail,
        "rustc_rc": r_rc,
        "total_self_ms": total_self / 1e6,
        "total_calls": total_calls,
        "trait_like_ms": trait_like_self / 1e6,
        "trait_core_ms": trait_core_self / 1e6,
        "trait_like_pct": trait_like_pct,
        "proj_norm_ms": proj_ms,
        "mono_ms": mono_ms,
        "evaluate_obligation_ms": eval_ms,
        "evaluate_obligation_calls": eval_calls,
        "evaluate_obligation_avg_us": eval_avg_us,
        "eval_label_used": eval_label_used,
        "eval_used_ms": eval_used_ms,
        "eval_used_calls": eval_used_calls,
        "eval_used_avg_us": eval_used_avg_us,
        "score_base": base,
        "score_fallback_base": fallback_base,
        "score_base_eff": base_eff,
        "score_gating": gating,
        "score_size_norm": size_norm,
        "score": score,
}
print("PROBE_JSON " + json.dumps(payload, sort_keys=True))

print("==============================================\n")
PY