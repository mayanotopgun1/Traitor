import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from .compiler_utils import compile_code


class TSAMeter:
    def __init__(
        self,
        rustc_cmd: List[str],
        project_root: Optional[Path] = None,
        use_script: bool = True,
        compiler_mode: int = 1,
        extra_args: Optional[List[str]] = None,
        timeout_sec: int = 20,
    ):
        self.rustc_cmd = list(rustc_cmd)
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
        self.use_script = bool(use_script)
        self.compiler_mode = int(compiler_mode)
        self.extra_args = list(extra_args or [])
        self.timeout_sec = int(timeout_sec)
        self.script_path = self.project_root / "utils" / "TSA" / "trait_query_stats.sh"
        self._pattern = re.compile(
            r"(trait|obligation|projection|coherence|impl|associated type|overflow evaluating)",
            re.IGNORECASE,
        )

    def _measure_via_script(self, code: str) -> Optional[dict]:
        if not self.script_path.exists():
            return None

        with tempfile.TemporaryDirectory(prefix="tsa_") as td:
            td_path = Path(td)
            src = td_path / "input.rs"
            src.write_text(code, encoding="utf-8")
            out_dir = td_path / "out"

            cmd = [
                "bash",
                str(self.script_path),
                "--file",
                str(src),
                "--compiler",
                str(self.compiler_mode),
                "--out-dir",
                str(out_dir),
                "--top",
                "15",
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_sec)
            except Exception:
                return None

            summary_path = out_dir / "summary.txt"
            trait_lines = None
            if summary_path.exists():
                text = summary_path.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"trait_log_lines:\s*(\d+)", text)
                if m:
                    trait_lines = int(m.group(1))

            if trait_lines is None:
                # fallback parse from stdout in case summary was not produced
                m2 = re.search(r"trait_log_lines:\s*(\d+)", f"{proc.stdout}\n{proc.stderr}")
                if m2:
                    trait_lines = int(m2.group(1))

            if trait_lines is None:
                return None
            return {
                "score": trait_lines,
                "method": "utils_tsa_script",
                "compiler_mode": self.compiler_mode,
                "script_exit_code": proc.returncode,
            }

    def _measure_via_fallback(self, code: str) -> dict:
        outcome = compile_code(
            code=code,
            rustc_cmd=self.rustc_cmd,
            extra_args=self.extra_args,
            timeout_sec=self.timeout_sec,
        )
        text = f"{outcome.stdout}\n{outcome.stderr}"
        lines = [ln for ln in text.splitlines() if self._pattern.search(ln)]
        return {
            "score": len(lines),
            "method": "stderr_regex_fallback",
            "compile_status": outcome.status,
        }

    def measure_with_details(self, code: str) -> dict:
        if self.use_script:
            via_script = self._measure_via_script(code)
            if via_script is not None:
                return via_script
        return self._measure_via_fallback(code)

    def measure(self, code: str) -> int:
        return int(self.measure_with_details(code).get("score", 0))
