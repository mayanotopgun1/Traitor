import subprocess
import time
import logging
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
    def __init__(self, timeout: int = 5):
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    def compile(self, source_path: Path, output_path: Optional[Path] = None) -> CompilationResult:
        """
        Compiles the given Rust source file.
        """
        cmd = ["rustc", str(source_path)]
        if output_path:
             cmd.extend(["-o", str(output_path)])
        
        # Add basic flags to speed up check-only builds if we don't need binaries
        # For fuzzing we might want to just check: cmd.extend(["--emit", "metadata"])
        # But to catch code generation bugs we might need full compilation.
        # Let's stick to default for now, maybe add -Z mir-opt-level=0 if needed.
        
        start_time = time.time()
        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            duration = time.time() - start_time
            
            status = CompilationStatus.SUCCESS if process.returncode == 0 else CompilationStatus.ERROR
            
            # Check for Internal Compiler Error (ICE)
            if "internal compiler error" in process.stderr.lower() or "thread 'rustc' panicked" in process.stderr.lower():
                status = CompilationStatus.CRASH

            # Cleanup generated artifacts
            try:
                # determine artifact basename
                if output_path:
                    stem = output_path.stem
                    parent = output_path.parent
                else:
                    stem = source_path.stem
                    parent = source_path.parent
                
                # Cleanup .exe, .pdb, .rlib (Windows/Rust specific)
                for ext in [".exe", ".pdb", ".rlib"]:
                    artifact = parent / (stem + ext)
                    if artifact.exists():
                        artifact.unlink()
            except Exception as e:
                self.logger.warning(f"Failed to cleanup artifacts for {source_path}: {e}")

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
