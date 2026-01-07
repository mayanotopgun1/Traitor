import subprocess
import time
import logging
import tempfile
from enum import Enum
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple

class CompilationStatus(Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    HANG = "HANG"
    CRASH = "CRASH" # ICE
    UNKNOWN = "UNKNOWN"

@dataclass
class CompilationResult:
    status: CompilationStatus
    return_code: Optional[int]
    stdout: str
    stderr: str
    duration: float

class RustCompiler:
    def __init__(self, timeout: int = 5, rustc_cmd=None):
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)
        self.rustc_cmd = list(rustc_cmd) if rustc_cmd else ["rustc"]

    def compile(
        self,
        source_path: Path,
        output_path: Optional[Path] = None,
        extra_args: Optional[list] = None,
    ) -> CompilationResult:
        """
        Compiles the given Rust source file.
        """
        source_path = Path(source_path).resolve()
        output_path = Path(output_path).resolve() if output_path is not None else None

        extra_args = list(extra_args) if extra_args else []

        cmd = [*self.rustc_cmd, str(source_path), *extra_args]
        if output_path:
            cmd.extend(["-o", str(output_path)])
        
        # Add basic flags to speed up check-only builds if we don't need binaries
        # For fuzzing we might want to just check: cmd.extend(["--emit", "metadata"])
        # But to catch code generation bugs we might need full compilation.
        # Let's stick to default for now, maybe add -Z mir-opt-level=0 if needed.
        
        start_time = time.time()
        try:
            # Compile into a temporary directory to avoid polluting the working tree with
            # artifacts like `temp_iter_*`, `libtemp_iter_*.rlib`, `.d`, etc.
            # Using both `cwd` and `--out-dir` keeps most outputs contained.
            with tempfile.TemporaryDirectory(prefix="trait_fuzzer_rustc_") as tmp:
                tmp_dir = Path(tmp)
                # Only redirect artifacts when the caller doesn't request a specific output path.
                # If `-o` is used, rustc will write that file where requested.
                if output_path is None:
                    cmd_with_outdir = cmd + ["--out-dir", str(tmp_dir)]
                else:
                    cmd_with_outdir = cmd

                process = subprocess.run(
                    cmd_with_outdir,
                    cwd=str(tmp_dir),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
            duration = time.time() - start_time
            
            status = CompilationStatus.SUCCESS if process.returncode == 0 else CompilationStatus.ERROR
            
            # Check for Internal Compiler Error (ICE)
            if "internal compiler error" in process.stderr.lower() or "thread 'rustc' panicked" in process.stderr.lower():
                status = CompilationStatus.CRASH

            # Best-effort cleanup for the explicit output_path.
            # Most artifacts are already confined to the temporary directory above.
            if output_path is not None:
                try:
                    output_path = Path(output_path)
                    if output_path.exists():
                        output_path.unlink()
                except Exception as e:
                    self.logger.warning(f"Failed to cleanup output artifact for {source_path}: {e}")

            return CompilationResult(
                status=status,
                return_code=process.returncode,
                stdout=process.stdout,
                stderr=process.stderr,
                duration=duration
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            self.logger.warning(f"Compilation timed out for {source_path}")
            return CompilationResult(
                status=CompilationStatus.HANG,
                return_code=None,
                stdout="",
                stderr="TimeoutExpired",
                duration=duration
            )
        except Exception as e:
            duration = time.time() - start_time
            self.logger.error(f"Execution failed: {e}")
            return CompilationResult(
                status=CompilationStatus.UNKNOWN,
                return_code=-1,
                stdout="",
                stderr=str(e),
                duration=duration
            )
