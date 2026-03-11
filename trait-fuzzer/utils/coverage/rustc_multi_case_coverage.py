#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


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

    if rustc_bin:
        rp = Path(rustc_bin).resolve()
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


def infer_sysroot_from_rustc(rustc_bin: str) -> Optional[Path]:
    p = Path(rustc_bin).resolve()
    if p.name != "rustc":
        return None
    parent = p.parent
    if parent.name != "bin":
        return None
    stage_dir = parent.parent
    if stage_dir.name.startswith("stage") and (stage_dir / "lib" / "rustlib").exists():
        return stage_dir
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


def safe_slug(path: Path, idx: int) -> str:
    raw = f"{idx:03d}_{path.stem}"
    return re.sub(r"[^A-Za-z0-9._-]", "_", raw)


def discover_cases(here: Path, cli_cases: Optional[List[str]], cases_dir: Optional[str], pattern: str) -> List[Path]:
    if cli_cases:
        out = [Path(p).resolve() for p in cli_cases]
    elif cases_dir:
        base = Path(cases_dir).resolve()
        out = sorted(base.rglob(pattern))
    else:
        out = [here / "case1.rs"]

    files = [p for p in out if p.exists() and p.is_file() and p.suffix == ".rs"]
    return files


def export_summary_json(
    llvm_cov: str,
    profdata_path: Path,
    cov_objects: List[str],
) -> Dict:
    cmd = [
        llvm_cov,
        "export",
        cov_objects[0],
        "-instr-profile",
        str(profdata_path),
        "-summary-only",
    ]
    for obj in cov_objects[1:]:
        cmd.extend(["-object", obj])
    res = run_cmd(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"llvm-cov export failed: {res.stderr}")
    return json.loads(res.stdout)


def totals_from_export(payload: Dict) -> Dict[str, float]:
    data = payload.get("data", [])
    if not data:
        return {"line_count": 0, "line_covered": 0, "line_percent": 0.0}
    totals = data[0].get("totals", {})
    lines = totals.get("lines", {})
    count = int(lines.get("count", 0) or 0)
    covered = int(lines.get("covered", 0) or 0)
    percent = float(lines.get("percent", 0.0) or 0.0)
    return {
        "line_count": count,
        "line_covered": covered,
        "line_missed": max(0, count - covered),
        "line_percent": percent,
    }


def component_key(filename: str) -> Optional[str]:
    # rustc components live under .../compiler/rustc_*/...
    m = re.search(r"/compiler/(rustc[^/]+)/", filename.replace("\\", "/"))
    if m:
        return m.group(1)
    return None


def component_summary_from_export(payload: Dict) -> List[Dict[str, object]]:
    data = payload.get("data", [])
    if not data:
        return []
    files = data[0].get("files", [])
    agg: Dict[str, Tuple[int, int]] = {}

    for item in files:
        fname = str(item.get("filename", ""))
        comp = component_key(fname)
        if comp is None:
            continue
        lines = item.get("summary", {}).get("lines", {})
        count = int(lines.get("count", 0) or 0)
        covered = int(lines.get("covered", 0) or 0)
        old_count, old_cov = agg.get(comp, (0, 0))
        agg[comp] = (old_count + count, old_cov + covered)

    out: List[Dict[str, object]] = []
    for comp, (count, covered) in agg.items():
        pct = (covered * 100.0 / count) if count > 0 else 0.0
        out.append(
            {
                "component": comp,
                "line_count": count,
                "line_covered": covered,
                "line_missed": max(0, count - covered),
                "line_percent": pct,
            }
        )
    out.sort(key=lambda x: int(x["line_count"]), reverse=True)
    return out


def write_component_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["component", "line_count", "line_covered", "line_missed", "line_percent"])
        for r in rows:
            w.writerow([
                r["component"],
                r["line_count"],
                r["line_covered"],
                r["line_missed"],
                f"{float(r['line_percent']):.4f}",
            ])


def append_timeline_row(path: Path, row: Dict[str, object]) -> None:
    exists = path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow([
                "timestamp",
                "case_index",
                "case_slug",
                "rustc_exit",
                "cumulative_line_count",
                "cumulative_line_covered",
                "cumulative_line_missed",
                "cumulative_line_percent",
            ])
        w.writerow([
            row.get("timestamp", ""),
            row.get("case_index", ""),
            row.get("case_slug", ""),
            row.get("rustc_exit", ""),
            row.get("cumulative_line_count", 0),
            row.get("cumulative_line_covered", 0),
            row.get("cumulative_line_missed", 0),
            f"{float(row.get('cumulative_line_percent', 0.0)):.6f}",
        ])


def load_json_file(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_resume_state(
    state_path: Path,
    *,
    processed_cases: List[str],
    merged_case_count: int,
    last_totals: Dict[str, float],
) -> None:
    state = {
        "processed_cases": processed_cases,
        "merged_case_count": int(merged_case_count),
        "last_totals": {
            "line_count": int(last_totals.get("line_count", 0) or 0),
            "line_covered": int(last_totals.get("line_covered", 0) or 0),
            "line_missed": int(last_totals.get("line_missed", 0) or 0),
            "line_percent": float(last_totals.get("line_percent", 0.0) or 0.0),
        },
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def should_mark_case_processed(row: Dict[str, object]) -> bool:
    # Mark as processed only when the case either failed compilation,
    # or successfully contributed profile data to merged totals.
    try:
        rustc_exit = int(row.get("rustc_exit", 0) or 0)
    except Exception:
        rustc_exit = 0
    try:
        profraw_count = int(row.get("profraw_count", 0) or 0)
    except Exception:
        profraw_count = 0
    return rustc_exit != 0 or profraw_count > 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect rustc coverage for multiple .rs cases: per-case + merged total + per-component"
    )
    here = Path(__file__).resolve().parent
    parser.add_argument("--cases", nargs="*", default=None, help="List of .rs cases")
    parser.add_argument("--cases-dir", default=None, help="Directory to discover .rs cases")
    parser.add_argument("--pattern", default="*.rs", help="Glob pattern under --cases-dir")
    parser.add_argument("--work-dir", default=str(here / "reports_multi"), help="Output directory")
    parser.add_argument("--rustc", default=None, help="rustc binary path")
    parser.add_argument("--sysroot", default=None, help="Optional rustc --sysroot path")
    parser.add_argument("--llvm-profdata", dest="llvm_profdata", default=None, help="llvm-profdata path")
    parser.add_argument("--llvm-cov", dest="llvm_cov", default=None, help="llvm-cov path")
    parser.add_argument("--clean", action="store_true", help="Clean work dir first")
    parser.add_argument(
        "--timeline-csv",
        default=None,
        help="CSV path for cumulative coverage over time. Default: <work-dir>/timeline_total.csv",
    )
    parser.add_argument(
        "--keep-intermediate",
        action="store_true",
        help="Keep per-case intermediate artifacts (profraw/profdata/build). Default is to delete after merge.",
    )
    args = parser.parse_args()

    cases = discover_cases(here, args.cases, args.cases_dir, args.pattern)
    if not cases:
        print("[ERR] no .rs cases found")
        return 2

    try:
        rustc_bin = detect_rustc(args.rustc)
        llvm_profdata = detect_llvm_tool("llvm-profdata", args.llvm_profdata, rustc_bin)
        llvm_cov = detect_llvm_tool("llvm-cov", args.llvm_cov, rustc_bin)
    except RuntimeError as exc:
        print(f"[ERR] {exc}")
        return 2

    sysroot_arg = args.sysroot
    if not sysroot_arg:
        inferred = infer_sysroot_from_rustc(rustc_bin)
        if inferred is not None:
            sysroot_arg = str(inferred)

    cov_objects = collect_cov_objects(rustc_bin, sysroot_arg)

    work_dir = Path(args.work_dir).resolve()
    if args.clean and work_dir.exists():
        shutil.rmtree(work_dir)
    (work_dir / "cases").mkdir(parents=True, exist_ok=True)
    timeline_csv = Path(args.timeline_csv).resolve() if args.timeline_csv else (work_dir / "timeline_total.csv")
    if args.clean and timeline_csv.exists():
        timeline_csv.unlink()

    print(f"[INFO] rustc: {rustc_bin}")
    print(f"[INFO] llvm-profdata: {llvm_profdata}")
    print(f"[INFO] llvm-cov: {llvm_cov}")
    print(f"[INFO] sysroot: {sysroot_arg}")
    print(f"[INFO] llvm-cov objects: {len(cov_objects)}")
    print(f"[INFO] cases: {len(cases)}")

    per_case_rows: List[Dict[str, object]] = []
    total_profdata = work_dir / "total.profdata"
    resume_state_file = work_dir / "resume_state.json"
    if total_profdata.exists() and args.clean:
        total_profdata.unlink()
    if args.clean and resume_state_file.exists():
        resume_state_file.unlink()
    merged_case_count = 0
    total_summary_json = work_dir / "summary_total.json"
    comp_summary_json = work_dir / "summary_components.json"
    comp_summary_csv = work_dir / "summary_components.csv"
    last_totals: Dict[str, float] = {
        "line_count": 0,
        "line_covered": 0,
        "line_missed": 0,
        "line_percent": 0.0,
    }

    per_case_json = work_dir / "summary_per_case.json"
    existing_per_case_rows = load_json_file(per_case_json, [])
    per_case_by_path: Dict[str, Dict[str, object]] = {}
    if isinstance(existing_per_case_rows, list):
        for row in existing_per_case_rows:
            if isinstance(row, dict) and row.get("case"):
                per_case_by_path[str(row["case"])] = row

    processed_cases_order: List[str] = []
    processed_cases_set = set()

    resume_state = load_json_file(resume_state_file, {}) if not args.clean else {}
    if isinstance(resume_state, dict):
        loaded_cases = resume_state.get("processed_cases", [])
        if isinstance(loaded_cases, list):
            for c in loaded_cases:
                if isinstance(c, str) and c not in processed_cases_set:
                    processed_cases_set.add(c)
                    processed_cases_order.append(c)

        loaded_merged = resume_state.get("merged_case_count")
        if isinstance(loaded_merged, int) and loaded_merged >= 0:
            merged_case_count = loaded_merged

        loaded_totals = resume_state.get("last_totals")
        if isinstance(loaded_totals, dict):
            for k in ("line_count", "line_covered", "line_missed", "line_percent"):
                if k in loaded_totals:
                    last_totals[k] = loaded_totals[k]

    if not args.clean and total_summary_json.exists():
        prev_total = load_json_file(total_summary_json, {})
        if isinstance(prev_total, dict):
            prev_merged = prev_total.get("merged_case_count")
            if isinstance(prev_merged, int) and prev_merged > merged_case_count:
                merged_case_count = prev_merged
            for k in ("line_count", "line_covered", "line_missed", "line_percent"):
                if k in prev_total:
                    last_totals[k] = prev_total[k]

    # Guard against stale resume metadata when total.profdata is missing.
    if merged_case_count > 0 and not total_profdata.exists():
        merged_case_count = 0

    # True resume requires existing merged profile baseline.
    # If baseline is absent, do not skip any case from historical summaries/state.
    if not args.clean and not total_profdata.exists():
        processed_cases_order = []
        processed_cases_set = set()

    if not args.clean:
        # Backfill resume set from per-case summary for older runs that don't have resume_state yet.
        if total_profdata.exists():
            for case_path, row in per_case_by_path.items():
                if not should_mark_case_processed(row):
                    continue
                if case_path not in processed_cases_set:
                    processed_cases_set.add(case_path)
                    processed_cases_order.append(case_path)

    def write_periodic_summaries(payload: Dict) -> None:
        totals_now = totals_from_export(payload)
        comps_now = component_summary_from_export(payload)
        totals_now["case_count"] = len(cases)
        totals_now["merged_case_count"] = merged_case_count
        total_summary_json.write_text(json.dumps(totals_now, ensure_ascii=False, indent=2), encoding="utf-8")
        comp_summary_json.write_text(json.dumps(comps_now, ensure_ascii=False, indent=2), encoding="utf-8")
        write_component_csv(comp_summary_csv, comps_now)

    for idx, case in enumerate(cases, start=1):
        case_str = str(case)
        if not args.clean and case_str in processed_cases_set:
            old = per_case_by_path.get(case_str)
            if old is not None:
                per_case_rows.append(old)
            print(f"[SKIP] already processed: {case_str}")
            continue

        case_slug = safe_slug(case, idx)
        case_dir = work_dir / "cases" / case_slug
        profraw_dir = case_dir / "profraw"
        build_dir = case_dir / "build"
        profraw_dir.mkdir(parents=True, exist_ok=True)
        build_dir.mkdir(parents=True, exist_ok=True)

        compile_env = os.environ.copy()
        compile_env["LLVM_PROFILE_FILE"] = str((profraw_dir / f"rustc-{case_slug}-%p-%m.profraw").resolve())

        out_bin = build_dir / f"{case_slug}_bin"
        cmd = [
            rustc_bin,
            str(case),
            "-o",
            str(out_bin),
            "-Copt-level=0",
            "-Cdebuginfo=1",
        ]
        if sysroot_arg:
            cmd.extend(["--sysroot", str(sysroot_arg)])

        comp = run_cmd(cmd, env=compile_env, cwd=case.parent)
        case_profraw = sorted(profraw_dir.glob("*.profraw"))

        case_profdata = case_dir / "case.profdata"
        case_export = case_dir / "case_export_summary.json"

        row: Dict[str, object] = {
            "case": str(case),
            "slug": case_slug,
            "rustc_exit": int(comp.returncode),
            "profraw_count": len(case_profraw),
            "line_count": 0,
            "line_covered": 0,
            "line_missed": 0,
            "line_percent": 0.0,
        }
        merged_into_total = False

        if case_profraw:
            merge_cmd = [llvm_profdata, "merge", "-sparse", *[str(p) for p in case_profraw], "-o", str(case_profdata)]
            merge_res = run_cmd(merge_cmd)
            if merge_res.returncode == 0:
                try:
                    payload = export_summary_json(llvm_cov, case_profdata, cov_objects)
                    if args.keep_intermediate:
                        case_export.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    row.update(totals_from_export(payload))
                except Exception:
                    pass

                # Incremental merge into total.profdata, so we can delete per-case artifacts early.
                try:
                    if merged_case_count == 0:
                        shutil.copy2(case_profdata, total_profdata)
                    else:
                        merged_tmp = work_dir / "total.tmp.profdata"
                        merge_total_cmd = [
                            llvm_profdata,
                            "merge",
                            "-sparse",
                            str(total_profdata),
                            str(case_profdata),
                            "-o",
                            str(merged_tmp),
                        ]
                        merge_total_res = run_cmd(merge_total_cmd)
                        if merge_total_res.returncode == 0:
                            merged_tmp.replace(total_profdata)
                        else:
                            print(f"[WARN] merge total failed for {case_slug}: {merge_total_res.stderr[:200]}")
                            if merged_tmp.exists():
                                merged_tmp.unlink()
                    merged_case_count += 1
                    merged_into_total = True

                    # Record cumulative total coverage trend after each merged case.
                    try:
                        total_payload_now = export_summary_json(llvm_cov, total_profdata, cov_objects)
                        last_totals = totals_from_export(total_payload_now)
                        write_periodic_summaries(total_payload_now)
                        append_timeline_row(
                            timeline_csv,
                            {
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "case_index": idx,
                                "case_slug": case_slug,
                                "rustc_exit": int(comp.returncode),
                                "cumulative_line_count": last_totals.get("line_count", 0),
                                "cumulative_line_covered": last_totals.get("line_covered", 0),
                                "cumulative_line_missed": last_totals.get("line_missed", 0),
                                "cumulative_line_percent": last_totals.get("line_percent", 0.0),
                            },
                        )
                    except Exception as e:
                        print(f"[WARN] failed to write timeline row for {case_slug}: {e}")
                except Exception as e:
                    print(f"[WARN] incremental merge failed for {case_slug}: {e}")

            # Cleanup per-case intermediates to control disk usage.
            if not args.keep_intermediate:
                for p in case_profraw:
                    try:
                        p.unlink()
                    except Exception:
                        pass
                try:
                    if case_profdata.exists():
                        case_profdata.unlink()
                except Exception:
                    pass
                try:
                    if case_export.exists():
                        case_export.unlink()
                except Exception:
                    pass
                try:
                    if out_bin.exists():
                        out_bin.unlink()
                except Exception:
                    pass
                try:
                    if profraw_dir.exists() and not any(profraw_dir.iterdir()):
                        profraw_dir.rmdir()
                except Exception:
                    pass
                try:
                    if build_dir.exists() and not any(build_dir.iterdir()):
                        build_dir.rmdir()
                except Exception:
                    pass

        per_case_rows.append(row)
        per_case_by_path[case_str] = row
        if (merged_into_total or int(row["rustc_exit"]) != 0) and case_str not in processed_cases_set:
            processed_cases_set.add(case_str)
            processed_cases_order.append(case_str)
        write_resume_state(
            resume_state_file,
            processed_cases=processed_cases_order,
            merged_case_count=merged_case_count,
            last_totals=last_totals,
        )
        print(
            f"[CASE] {case_slug}: exit={row['rustc_exit']} profraw={row['profraw_count']} "
            f"lines={row['line_covered']}/{row['line_count']} ({float(row['line_percent']):.2f}%)"
        )

    final_per_case_rows: List[Dict[str, object]] = []
    for case in cases:
        row = per_case_by_path.get(str(case))
        if row is not None:
            final_per_case_rows.append(row)
    per_case_json.write_text(json.dumps(final_per_case_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    if not total_profdata.exists():
        compiled_ok = 0
        for r in final_per_case_rows:
            try:
                if int(r.get("rustc_exit", 1)) == 0:
                    compiled_ok += 1
            except Exception:
                pass
        print("[ERR] no mergeable profraw generated across all cases")
        if compiled_ok > 0:
            print(
                "[HINT] rustc compiled cases but produced no .profraw. "
                "Selected rustc is likely not coverage-instrumented. "
                "Pass --rustc /path/to/instrumented/rustc or build a coverage-enabled rustc first."
            )
        print(f"[INFO] per-case summary: {per_case_json}")
        return 1

    total_export_json = work_dir / "summary_total_export.json"

    payload = export_summary_json(llvm_cov, total_profdata, cov_objects)
    total_export_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    total_summary = totals_from_export(payload)
    last_totals = total_summary
    total_summary["case_count"] = len(cases)
    total_summary["merged_case_count"] = merged_case_count
    total_summary_json.write_text(json.dumps(total_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    comp_rows = component_summary_from_export(payload)
    comp_summary_json.write_text(json.dumps(comp_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_component_csv(comp_summary_csv, comp_rows)

    print("[DONE] multi-case coverage complete")
    print(f"[INFO] per-case summary: {per_case_json}")
    print(f"[INFO] total summary: {total_summary_json}")
    print(f"[INFO] component summary: {comp_summary_csv}")
    print(f"[INFO] timeline csv: {timeline_csv}")
    print(
        "[SUMMARY] TOTAL lines: "
        f"{total_summary['line_covered']}/{total_summary['line_count']} "
        f"({float(total_summary['line_percent']):.2f}%)"
    )

    write_resume_state(
        resume_state_file,
        processed_cases=processed_cases_order,
        merged_case_count=merged_case_count,
        last_totals=last_totals,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
