#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def run_cmd(cmd: List[str], *, env: Optional[dict] = None, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        env=env,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )


def detect_rustc(user_rustc: Optional[str]) -> str:
    if user_rustc:
        return user_rustc

    # Prefer locally built rustc (stage1) if available.
    stage1_candidates = []
    for root in (Path("/home/laix/Study"), Path("/home/laix/Study/Traitor")):
        if not root.exists():
            continue
        stage1_candidates.extend(root.glob("**/build/*/stage1/bin/rustc"))

    for p in stage1_candidates:
        if p.is_file():
            return str(p.resolve())

    probe = run_cmd(["rustup", "which", "--toolchain", "nightly", "rustc"])
    if probe.returncode == 0 and probe.stdout.strip():
        return probe.stdout.strip()

    fallback = shutil.which("rustc")
    if fallback:
        return fallback

    raise RuntimeError("Cannot find rustc. Please pass --rustc /path/to/rustc")


def detect_llvm_tool(name: str, user_path: Optional[str], rustc_bin: Optional[str] = None) -> str:
    if user_path:
        return user_path

    # Prefer tool versions that match a locally built rustc from rust-lang/rust.
    if rustc_bin:
        rp = Path(rustc_bin).resolve()
        # Expected: .../build/<host>/stage1/bin/rustc
        try:
            host_dir = rp.parents[2]  # .../build/<host>
            ci_tool = host_dir / "ci-llvm" / "bin" / name
            if ci_tool.exists() and ci_tool.is_file():
                return str(ci_tool)
        except Exception:
            pass

    from_path = shutil.which(name)
    if from_path:
        return from_path

    raise RuntimeError(f"Cannot find {name}. Please pass --{name} /path/to/{name}")


def parse_total_line_coverage(report_text: str) -> Optional[str]:
    for line in report_text.splitlines():
        if line.strip().startswith("TOTAL"):
            parts = re.split(r"\s+", line.strip())
            if parts:
                return line.strip()
    return None


def collect_cov_objects(rustc_bin: str, sysroot_arg: Optional[str]) -> List[str]:
    objs: List[str] = [str(Path(rustc_bin).resolve())]
    if not sysroot_arg:
        return objs

    sysroot = Path(sysroot_arg)
    lib_dir = sysroot / "lib"
    if not lib_dir.exists():
        return objs

    patterns = [
        "librustc_driver-*.so",
        "librustc_driver-*.dylib",
        "rustc_driver-*.dll",
        "librustc_*.so",
        "librustc_*.dylib",
        "rustc_*.dll",
    ]
    seen = {objs[0]}
    for pat in patterns:
        for p in sorted(lib_dir.glob(pat)):
            rp = str(p.resolve())
            if rp not in seen:
                objs.append(rp)
                seen.add(rp)
    return objs


def infer_sysroot_from_rustc(rustc_bin: str) -> Optional[Path]:
    p = Path(rustc_bin).resolve()
    # Typical stage path: .../build/<host>/stage1/bin/rustc
    if p.name != "rustc":
        return None
    parent = p.parent
    if parent.name != "bin":
        return None
    stage_dir = parent.parent
    if stage_dir.name.startswith("stage") and (stage_dir / "lib" / "rustlib").exists():
        return stage_dir
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect rustc line coverage for case1.rs without using config.json")
    here = Path(__file__).resolve().parent
    parser.add_argument("--case", default=str(here / "case1.rs"), help="Path to case rust file")
    parser.add_argument("--work-dir", default=str(here / "reports_case1"), help="Output work directory")
    parser.add_argument("--rustc", default=None, help="rustc binary path (default: rustup nightly rustc if available)")
    parser.add_argument("--sysroot", default=None, help="Optional rustc --sysroot path. If omitted, infer for stage rustc.")
    parser.add_argument("--llvm-profdata", dest="llvm_profdata", default=None, help="llvm-profdata path")
    parser.add_argument("--llvm-cov", dest="llvm_cov", default=None, help="llvm-cov path")
    parser.add_argument("--clean", action="store_true", help="Clean work-dir before running")
    args = parser.parse_args()

    case_path = Path(args.case).resolve()
    if not case_path.exists():
        print(f"[ERR] case file not found: {case_path}")
        return 2

    work_dir = Path(args.work_dir).resolve()
    profraw_dir = work_dir / "profraw"
    build_dir = work_dir / "build"
    profdata_path = work_dir / "rustc_case1.profdata"
    report_path = work_dir / "rustc_line_report.txt"

    if args.clean and work_dir.exists():
        shutil.rmtree(work_dir)

    profraw_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)

    try:
        rustc_bin = detect_rustc(args.rustc)
        llvm_profdata = detect_llvm_tool("llvm-profdata", args.llvm_profdata, rustc_bin)
        llvm_cov = detect_llvm_tool("llvm-cov", args.llvm_cov, rustc_bin)
    except RuntimeError as exc:
        print(f"[ERR] {exc}")
        return 2

    print(f"[INFO] case: {case_path}")
    print(f"[INFO] rustc: {rustc_bin}")
    print(f"[INFO] llvm-profdata: {llvm_profdata}")
    print(f"[INFO] llvm-cov: {llvm_cov}")

    # This profile is for rustc itself while compiling case1.rs.
    profile_pattern = str((profraw_dir / "rustc-case1-%p-%m.profraw").resolve())
    compile_env = os.environ.copy()
    compile_env["LLVM_PROFILE_FILE"] = profile_pattern

    out_bin = build_dir / "case1_bin"

    sysroot_arg = args.sysroot
    if not sysroot_arg:
        inferred = infer_sysroot_from_rustc(rustc_bin)
        if inferred is not None:
            sysroot_arg = str(inferred)
            print(f"[INFO] inferred sysroot: {sysroot_arg}")

    compile_cmd = [
        rustc_bin,
        str(case_path),
        "-o",
        str(out_bin),
        "-Copt-level=0",
        "-Cdebuginfo=1",
    ]
    if sysroot_arg:
        compile_cmd.extend(["--sysroot", str(sysroot_arg)])

    compile_result = run_cmd(compile_cmd, env=compile_env, cwd=case_path.parent)
    print(f"[INFO] rustc exit code: {compile_result.returncode}")
    if compile_result.stderr.strip():
        print("[INFO] rustc stderr (tail):")
        print("\n".join(compile_result.stderr.splitlines()[-20:]))

    profraw_files = sorted(profraw_dir.glob("*.profraw"))
    if not profraw_files:
        print("[ERR] No .profraw generated.")
        print("[HINT] rustc is likely not coverage-instrumented.")
        print("[HINT] Run: python utils/coverage/prepare_instrumented_rustc.py")
        return 1

    merge_cmd = [llvm_profdata, "merge", "-sparse", *[str(p) for p in profraw_files], "-o", str(profdata_path)]
    merge_result = run_cmd(merge_cmd)
    if merge_result.returncode != 0:
        print("[ERR] llvm-profdata merge failed:")
        print(merge_result.stderr)
        return 1

    cov_objects = collect_cov_objects(rustc_bin, sysroot_arg)
    cov_cmd = [
        llvm_cov,
        "report",
        cov_objects[0],
        "-instr-profile",
        str(profdata_path),
    ]
    for obj in cov_objects[1:]:
        cov_cmd.extend(["-object", obj])

    print(f"[INFO] llvm-cov objects: {len(cov_objects)}")
    cov_result = run_cmd(cov_cmd)
    if cov_result.returncode != 0:
        print("[ERR] llvm-cov report failed:")
        print(cov_result.stderr)
        return 1

    report_text = cov_result.stdout
    report_path.write_text(report_text, encoding="utf-8")

    total_line = parse_total_line_coverage(report_text)
    print(f"[INFO] profraw count: {len(profraw_files)}")
    print(f"[INFO] profdata: {profdata_path}")
    print(f"[INFO] report: {report_path}")
    if total_line:
        print(f"[SUMMARY] rustc line coverage (TOTAL): {total_line}")
    else:
        print("[WARN] TOTAL line not found in report output")

    # Keep exit code from rustc compile visible, but coverage already generated.
    return 0


if __name__ == "__main__":
    sys.exit(main())
