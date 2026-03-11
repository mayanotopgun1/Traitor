#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List


def run(cmd, cwd: Path | None = None, check: bool = True):
    print("[CMD]", " ".join(map(str, cmd)))
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if check and p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(map(str, cmd))}")
    return p.returncode


def try_clone(repo_dir: Path, urls: List[str], timeout_sec: int = 300) -> bool:
    for url in urls:
        print(f"[INFO] trying clone url: {url}")
        if repo_dir.exists():
            shutil.rmtree(repo_dir, ignore_errors=True)
        cmd = [
            "timeout",
            str(timeout_sec),
            "git",
            "clone",
            "--depth",
            "1",
            "--filter=blob:none",
            url,
            str(repo_dir),
        ]
        rc = run(cmd, check=False)
        if rc == 0 and (repo_dir / ".git").exists():
            print(f"[OK] cloned from: {url}")
            return True
        print(f"[WARN] clone failed from: {url} (exit={rc})")
    return False


def detect_host_triple() -> str:
    p = subprocess.run(["rustc", "-vV"], text=True, capture_output=True)
    if p.returncode == 0:
        for line in p.stdout.splitlines():
            if line.startswith("host: "):
                return line.split(":", 1)[1].strip()
    return "x86_64-unknown-linux-gnu"


def ensure_repo(repo_dir: Path, clone_urls: List[str], clone_timeout: int):
    if (repo_dir / ".git").exists():
        print(f"[INFO] rust repo exists: {repo_dir}")
        return
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    ok = try_clone(repo_dir, clone_urls, timeout_sec=clone_timeout)
    if not ok:
        raise RuntimeError("clone rust-lang/rust failed from all candidate URLs")


def write_bootstrap(repo_dir: Path, host: str):
    content = f'''profile = "compiler"
change-id = "ignore"

[build]
build = "{host}"
host = ["{host}"]
target = ["{host}"]
extended = false
profiler = true

[rust]
download-rustc = false
debuginfo-level = 1
debuginfo-level-rustc = 1
incremental = false
llvm-tools = true
rustflags = ["-Cinstrument-coverage", "-Ccodegen-units=1", "-Clink-dead-code"]

[target.{host}]
profiler = true
'''
    path = repo_dir / "bootstrap.toml"
    path.write_text(content, encoding="utf-8")
    print(f"[INFO] wrote {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a coverage-instrumented stage1 rustc")
    parser.add_argument("--repo", default="/home/laix/Study/rust-lang-rust", help="rust-lang/rust checkout path")
    parser.add_argument("--run-build", action="store_true", help="actually run x build after generating bootstrap.toml")
    parser.add_argument("--clone-timeout", type=int, default=300, help="timeout seconds per clone attempt")
    parser.add_argument(
        "--repo-url",
        action="append",
        default=[],
        help="candidate clone URL (can repeat). If omitted, use built-in fallbacks",
    )
    args = parser.parse_args()

    if shutil.which("git") is None:
        print("[ERR] git not found")
        return 2

    host = detect_host_triple()
    repo_dir = Path(args.repo).resolve()
    default_urls = [
        "https://github.com/rust-lang/rust.git",
        "https://ghproxy.com/https://github.com/rust-lang/rust.git",
        "https://mirror.ghproxy.com/https://github.com/rust-lang/rust.git",
    ]
    clone_urls = args.repo_url if args.repo_url else default_urls

    try:
        ensure_repo(repo_dir, clone_urls=clone_urls, clone_timeout=int(args.clone_timeout))
        write_bootstrap(repo_dir, host)
    except Exception as e:
        print(f"[ERR] prepare failed: {e}")
        return 1

    build_cmd = ["python", "x.py", "build", "--stage", "1", "compiler/rustc"]
    print("[NEXT] Build command:")
    print("       ", " ".join(build_cmd), f"(cwd={repo_dir})")

    stage1_rustc = repo_dir / "build" / host / "stage1" / "bin" / "rustc"
    print(f"[NEXT] expected rustc: {stage1_rustc}")
    print("[NEXT] after build, run:")
    print(
        "       python /home/laix/Study/Traitor/trait-fuzzer/utils/coverage/rustc_case1_line_coverage.py "
        f"--rustc {stage1_rustc} --clean"
    )

    if not args.run_build:
        return 0

    try:
        run(build_cmd, cwd=repo_dir)
    except Exception as e:
        print(f"[ERR] build failed: {e}")
        return 1

    if stage1_rustc.exists():
        print(f"[OK] built instrumented rustc: {stage1_rustc}")
        return 0

    print("[WARN] build finished but stage1 rustc path not found, check build logs")
    return 1


if __name__ == "__main__":
    sys.exit(main())
