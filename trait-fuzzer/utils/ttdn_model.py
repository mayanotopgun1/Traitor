import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass(frozen=True)
class TTDNComplexity:
    extra: Dict[str, int]


class TTDNModel:
    """Unified TTDN interface for the Python driver.

    Source of truth is the Rust `syn`-based extractor in mutation-AST (crate::ttdn).
    We call it via `cargo run` in `--mode ttdn_metrics` and parse the JSON output.
    """

    def __init__(self, mutation_ast_dir: Optional[Path] = None):
        self.mutation_ast_dir = Path(mutation_ast_dir) if mutation_ast_dir is not None else Path("mutation/mutation-AST")

    def calculate_complexity_for_file(self, rust_file: Path, timeout_sec: int = 20) -> TTDNComplexity:
        rust_file = Path(rust_file)
        # Write to a temp output path (content is irrelevant for metrics mode).
        out_path = rust_file.with_suffix(rust_file.suffix + ".ttdn_out")

        bin_path = self.mutation_ast_dir / "target" / "debug" / "mutation-ast"
        if bin_path.exists():
            cmd = [
                str(bin_path.absolute()),
                "--input",
                str(rust_file.absolute()),
                "--output",
                str(out_path.absolute()),
                "--mode",
                "ttdn_metrics",
            ]
        else:
            cmd = [
                "cargo",
                "run",
                "--quiet",
                "--",
                "--input",
                str(rust_file.absolute()),
                "--output",
                str(out_path.absolute()),
                "--mode",
                "ttdn_metrics",
            ]

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.mutation_ast_dir.absolute()),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=True,
            )

            payload = json.loads(proc.stdout.strip() or "{}")
            extra = {k: int(v) for k, v in payload.items() if isinstance(v, int)}
            return TTDNComplexity(extra=extra)
        except Exception:
            # Minimal fallback: if metrics extraction fails, return a neutral score.
            return TTDNComplexity(extra={})
        finally:
            try:
                if out_path.exists():
                    out_path.unlink()
            except Exception:
                pass
