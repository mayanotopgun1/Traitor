#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from rustc_multi_case_coverage import (
    collect_cov_objects,
    component_summary_from_export,
    detect_llvm_tool,
    detect_rustc,
    export_summary_json,
    infer_sysroot_from_rustc,
    totals_from_export,
)


class DirLock:
    def __init__(self, lock_dir: Path, timeout: float = 120.0):
        self.lock_dir = Path(lock_dir)
        self.timeout = float(timeout)

    def __enter__(self):
        start = time.time()
        while True:
            try:
                self.lock_dir.mkdir(parents=True, exist_ok=False)
                return self
            except FileExistsError:
                if (time.time() - start) > self.timeout:
                    raise TimeoutError(f"Could not acquire lock {self.lock_dir} in {self.timeout}s")
                time.sleep(0.2)

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.lock_dir.rmdir()
        except Exception:
            pass


def append_timeline_row(path: Path, row: Dict[str, object]) -> None:
    exists = path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(
                [
                    "timestamp",
                    "worker",
                    "variant_id",
                    "rustc_exit",
                    "cumulative_line_count",
                    "cumulative_line_covered",
                    "cumulative_line_missed",
                    "cumulative_line_percent",
                ]
            )
        w.writerow(
            [
                row.get("timestamp", ""),
                row.get("worker", ""),
                row.get("variant_id", ""),
                row.get("rustc_exit", ""),
                row.get("cumulative_line_count", 0),
                row.get("cumulative_line_covered", 0),
                row.get("cumulative_line_missed", 0),
                f"{float(row.get('cumulative_line_percent', 0.0)):.6f}",
            ]
        )


def write_component_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["component", "line_count", "line_covered", "line_missed", "line_percent"])
        for r in rows:
            w.writerow(
                [
                    r.get("component", ""),
                    r.get("line_count", 0),
                    r.get("line_covered", 0),
                    r.get("line_missed", 0),
                    f"{float(r.get('line_percent', 0.0)):.4f}",
                ]
            )


def parse_case_meta(case_path: Path):
    stem = case_path.stem
    worker = 0
    variant = stem
    try:
        if stem.startswith("case_w"):
            rem = stem[len("case_w"):]
            worker_str, rem2 = rem.split("_", 1)
            worker = int(worker_str)
            parts = rem2.rsplit("_", 1)
            variant = parts[0] if parts else rem2
    except Exception:
        pass
    return worker, variant


def iter_key_from_variant(variant: str) -> str:
    m = re.match(r"^(w\d+_iter_\d+)", str(variant or ""))
    return m.group(1) if m else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Consume queued coverage cases and update live coverage reports")
    parser.add_argument("--case-dir", default="utils/coverage/case", help="Directory containing queued .rs cases")
    parser.add_argument("--work-dir", default="utils/coverage/live_reports", help="Directory for live coverage reports")
    parser.add_argument("--rustc", default=None, help="rustc binary path")
    parser.add_argument("--sysroot", default=None, help="optional rustc --sysroot")
    parser.add_argument("--llvm-profdata", dest="llvm_profdata", default=None, help="llvm-profdata path")
    parser.add_argument("--llvm-cov", dest="llvm_cov", default=None, help="llvm-cov path")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="poll interval seconds")
    parser.add_argument("--compile-timeout", type=float, default=20.0, help="timeout seconds for each case compile")
    parser.add_argument(
        "--summary-every",
        type=int,
        default=20,
        help="Run expensive llvm-cov summary export every N merged cases",
    )
    args = parser.parse_args()

    case_dir = Path(args.case_dir).resolve()
    work_dir = Path(args.work_dir).resolve()
    profraw_dir = work_dir / "profraw"
    tmp_dir = work_dir / "tmp"
    total_profdata = work_dir / "total.profdata"
    timeline_csv = work_dir / "timeline_total.csv"
    summary_total_json = work_dir / "summary_total.json"
    summary_components_json = work_dir / "summary_components.json"
    summary_components_csv = work_dir / "summary_components.csv"
    lock_dir = work_dir / "stats_lock.dir"
    failed_dir = work_dir / "failed_cases"
    claimed_keys_file = work_dir / "claimed_iter_keys.txt"
    consumer_pid_file = work_dir / "consumer.pid"

    case_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    profraw_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    # Clear stale lock directory if there is no alive consumer process recorded.
    # This avoids startup deadlocks after abrupt termination.
    consumer_alive = False
    if consumer_pid_file.exists():
        try:
            pid_text = consumer_pid_file.read_text(encoding="utf-8").strip()
            pid = int(pid_text)
            os.kill(pid, 0)
            consumer_alive = True
        except Exception:
            consumer_alive = False

    if lock_dir.exists() and not consumer_alive:
        try:
            shutil.rmtree(lock_dir)
        except Exception:
            pass

    # Stale raw profiles from previous interrupted runs can grow very large.
    # We keep incremental state in total.profdata, so it's safe to drop leftovers here.
    for stale in profraw_dir.glob("*.profraw"):
        try:
            stale.unlink()
        except Exception:
            pass

    claimed_iter_keys = set()
    if claimed_keys_file.exists():
        try:
            with open(claimed_keys_file, "r", encoding="utf-8") as f:
                for line in f:
                    key = line.strip()
                    if key:
                        claimed_iter_keys.add(key)
        except Exception:
            pass

    def claim_iter_key(key: str) -> None:
        if not key or key in claimed_iter_keys:
            return
        claimed_iter_keys.add(key)
        try:
            with open(claimed_keys_file, "a", encoding="utf-8") as f:
                f.write(key + "\n")
        except Exception:
            pass

    merged_counter = 0
    summary_every = max(1, int(args.summary_every))

    def load_last_totals() -> Dict[str, float]:
        if summary_total_json.exists():
            try:
                payload = json.loads(summary_total_json.read_text(encoding="utf-8"))
                return {
                    "line_count": int(payload.get("line_count", 0) or 0),
                    "line_covered": int(payload.get("line_covered", 0) or 0),
                    "line_missed": int(payload.get("line_missed", 0) or 0),
                    "line_percent": float(payload.get("line_percent", 0.0) or 0.0),
                }
            except Exception:
                pass
        return {
            "line_count": 0,
            "line_covered": 0,
            "line_missed": 0,
            "line_percent": 0.0,
        }

    last_totals: Dict[str, float] = load_last_totals()

    rustc_bin = detect_rustc(args.rustc)
    llvm_profdata = detect_llvm_tool("llvm-profdata", args.llvm_profdata, rustc_bin)
    llvm_cov = detect_llvm_tool("llvm-cov", args.llvm_cov, rustc_bin)

    sysroot_arg = args.sysroot
    if not sysroot_arg:
        inferred = infer_sysroot_from_rustc(rustc_bin)
        if inferred is not None:
            sysroot_arg = str(inferred)

    cov_objects = collect_cov_objects(rustc_bin, sysroot_arg)

    print(f"[consumer] case_dir={case_dir}")
    print(f"[consumer] work_dir={work_dir}")
    print(f"[consumer] rustc={rustc_bin}")

    while True:
        try:
            queued = list(case_dir.glob("*.rs"))
        except Exception:
            queued = []

        # Queue-level one-pass rule:
        # 1) if key already claimed: delete all queued files for that key;
        # 2) otherwise random keep 1 and delete the rest.
        grouped: Dict[str, List[Path]] = {}
        passthrough: List[Path] = []
        for p in queued:
            _w, _v = parse_case_meta(p)
            k = iter_key_from_variant(_v)
            if not k:
                passthrough.append(p)
                continue
            grouped.setdefault(k, []).append(p)

        cases: List[Path] = list(passthrough)
        for k, arr in grouped.items():
            if k in claimed_iter_keys:
                for drop in arr:
                    try:
                        drop.unlink()
                    except Exception:
                        pass
                continue

            random.shuffle(arr)
            keep = arr[0]
            for drop in arr[1:]:
                try:
                    drop.unlink()
                except Exception:
                    pass
            cases.append(keep)

        random.shuffle(cases)

        if not cases:
            time.sleep(max(0.2, float(args.poll_interval)))
            continue

        for case in cases:
            worker, variant = parse_case_meta(case)
            iter_key = iter_key_from_variant(variant)

            # Coverage rule: for each (worker, iter), only test one case.
            # Any subsequent same-key cases are deleted directly.
            if iter_key and iter_key in claimed_iter_keys:
                try:
                    case.unlink()
                except Exception:
                    pass
                continue
            if iter_key:
                claim_iter_key(iter_key)

            slug = case.stem
            ts = int(time.time() * 1000)
            profraw_pattern = str((profraw_dir / f"rustc-{slug}-{ts}-%p-%m.profraw").resolve())
            out_bin = tmp_dir / f"build_{slug}_{ts}"
            case_profdata = tmp_dir / f"case_{slug}_{ts}.profdata"
            profraw_files: List[Path] = []

            env = os.environ.copy()
            env["LLVM_PROFILE_FILE"] = profraw_pattern

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

            try:
                comp = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=max(1.0, float(args.compile_timeout)),
                )
            except subprocess.TimeoutExpired:
                try:
                    case.rename(failed_dir / case.name)
                except Exception:
                    pass
                continue
            except Exception:
                try:
                    case.rename(failed_dir / case.name)
                except Exception:
                    pass
                continue
            merged_ok = False
            snapshot_profdata = tmp_dir / f"snapshot_{slug}_{ts}.profdata"
            try:
                profraw_files = sorted(profraw_dir.glob(f"rustc-{slug}-{ts}-*.profraw"))
                if not profraw_files:
                    try:
                        case.rename(failed_dir / case.name)
                    except Exception:
                        pass
                    continue

                merge_cmd = [llvm_profdata, "merge", "-sparse", *[str(p) for p in profraw_files], "-o", str(case_profdata)]
                merge_res = subprocess.run(merge_cmd, capture_output=True, text=True)
                if merge_res.returncode != 0:
                    try:
                        case.rename(failed_dir / case.name)
                    except Exception:
                        pass
                    continue

                try:
                    with DirLock(lock_dir, timeout=180.0):
                        if total_profdata.exists():
                            merged_tmp = tmp_dir / f"total_{ts}.profdata"
                            merge_total_cmd = [
                                llvm_profdata,
                                "merge",
                                "-sparse",
                                str(total_profdata),
                                str(case_profdata),
                                "-o",
                                str(merged_tmp),
                            ]
                            merge_total_res = subprocess.run(merge_total_cmd, capture_output=True, text=True)
                            if merge_total_res.returncode != 0:
                                try:
                                    case.rename(failed_dir / case.name)
                                except Exception:
                                    pass
                                continue
                            merged_tmp.replace(total_profdata)
                        else:
                            shutil.copy2(case_profdata, total_profdata)

                        shutil.copy2(total_profdata, snapshot_profdata)

                    merged_counter += 1
                    should_export = (
                        (merged_counter % summary_every == 0)
                        or (not summary_total_json.exists())
                        or (not summary_components_json.exists())
                        or (not summary_components_csv.exists())
                    )

                    current_totals = last_totals
                    if should_export:
                        payload = export_summary_json(llvm_cov, snapshot_profdata, cov_objects)
                        totals = totals_from_export(payload)
                        comps = component_summary_from_export(payload)

                        summary_total_json.write_text(json.dumps(totals, ensure_ascii=False, indent=2), encoding="utf-8")
                        summary_components_json.write_text(json.dumps(comps, ensure_ascii=False, indent=2), encoding="utf-8")
                        write_component_csv(summary_components_csv, comps)
                        last_totals = totals
                        current_totals = totals

                    append_timeline_row(
                        timeline_csv,
                        {
                            "timestamp": datetime.now().isoformat(timespec="seconds"),
                            "worker": worker,
                            "variant_id": variant,
                            "rustc_exit": int(comp.returncode),
                            "cumulative_line_count": current_totals.get("line_count", 0),
                            "cumulative_line_covered": current_totals.get("line_covered", 0),
                            "cumulative_line_missed": current_totals.get("line_missed", 0),
                            "cumulative_line_percent": current_totals.get("line_percent", 0.0),
                        },
                    )

                    merged_ok = True
                except TimeoutError:
                    # Skip this case and continue loop; do not crash consumer.
                    continue
            finally:
                if merged_ok:
                    try:
                        case.unlink()
                    except Exception:
                        pass

                for p in profraw_files:
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
                    if out_bin.exists():
                        out_bin.unlink()
                except Exception:
                    pass
                try:
                    if snapshot_profdata.exists():
                        snapshot_profdata.unlink()
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
