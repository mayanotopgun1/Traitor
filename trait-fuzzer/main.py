import sys
import os
import json
import logging
import argparse
import random
import shutil
import subprocess
import time
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from mutation.mutator_pool import MutatorPool
from utils.compiler import RustCompiler, CompilationStatus
from utils.ttdn_model import TTDNModel
from LLM import LLMConnector, ExtractorAgent, InjectorAgent, RevisionAgent

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def setup_logging(config):
    log_dir = Path(config["paths"]["logs"])
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        filename=log_dir / "fuzzer.log",
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logging.getLogger('').addHandler(console)

def load_config(config_path):
    with open(config_path, 'r') as f:
        return json.load(f)


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob('*'):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except Exception:
        return total
    return total


def _iter_case_dirs_in(status_dir: Path) -> List[Path]:
    if not status_dir.exists() or not status_dir.is_dir():
        return []
    out: List[Path] = []
    for case_dir in status_dir.iterdir():
        if case_dir.is_dir() and case_dir.name.startswith('case_'):
            out.append(case_dir)
    return out


def _case_dirs_by_status(results_dir: Path) -> Dict[str, List[Path]]:
    out: Dict[str, List[Path]] = {}
    if not results_dir.exists():
        return out
    for status_dir in results_dir.iterdir():
        if status_dir.is_dir():
            out[status_dir.name] = _iter_case_dirs_in(status_dir)
    return out


def _sort_oldest_first(paths: List[Path]) -> List[Path]:
    now = time.time()
    return sorted(paths, key=lambda p: p.stat().st_mtime if p.exists() else now)


def _prune_oldest(case_dirs: List[Path], max_keep: int, label: str):
    if max_keep < 0:
        return
    case_dirs[:] = _sort_oldest_first(case_dirs)
    while len(case_dirs) > max_keep:
        victim = case_dirs.pop(0)
        try:
            shutil.rmtree(victim)
            logging.info("Pruned old %s case: %s", label, victim)
        except Exception as e:
            logging.warning("Failed to prune %s: %s", victim, e)
            break


# When pruning triggers, prune down to a lower watermark to avoid prune-on-every-case
# churn. This is intentionally not user-configurable.
_PRUNE_WATERMARK = 0


def enforce_results_limits(
    results_dir: Path,
    max_cases: Optional[int],
    max_results_gb: Optional[float],
    min_free_gb: Optional[float],
    keep_success_cases: int,
    keep_error_cases: int,
) -> bool:
    """Prune only SUCCESS/ERROR cases; never delete HANG/CRASH.

    Returns True if safe to continue. If disk is still below min_free_gb after
    pruning prunable categories, returns False.
    """
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    prune_watermark = _PRUNE_WATERMARK

    # 1) Per-category pruning policy
    by_status = _case_dirs_by_status(results_dir)
    success_dirs = by_status.get("success", [])
    error_dirs = by_status.get("error", [])

    if keep_success_cases >= 0:
        if len(success_dirs) > keep_success_cases:
            target = int(keep_success_cases * prune_watermark)
            target = min(target, keep_success_cases)
            _prune_oldest(success_dirs, target, label="success")
    if keep_error_cases >= 0:
        if len(error_dirs) > keep_error_cases:
            target = int(keep_error_cases * prune_watermark)
            target = min(target, keep_error_cases)
            _prune_oldest(error_dirs, target, label="error")

    # 2) Global caps (apply ONLY to prunable categories: success+error)
    prunable_dirs = _sort_oldest_first(success_dirs + error_dirs)
    if max_cases is not None:
        if len(prunable_dirs) > max_cases:
            target = int(max_cases * prune_watermark)
            target = min(target, max_cases)
        else:
            target = max_cases

        while len(prunable_dirs) > target:
            victim = prunable_dirs.pop(0)
            try:
                shutil.rmtree(victim)
                logging.info("Pruned old prunable case (max-cases): %s", victim)
            except Exception as e:
                logging.warning("Failed to prune %s: %s", victim, e)
                break

    if max_results_gb is not None:
        max_results_bytes = int(max_results_gb * 1024**3)
        # Only measure/prune within success+error folders
        prunable_size = _dir_size_bytes(results_dir / "success") + _dir_size_bytes(results_dir / "error")
        prunable_dirs = _sort_oldest_first(_iter_case_dirs_in(results_dir / "success") + _iter_case_dirs_in(results_dir / "error"))

        if prunable_size > max_results_bytes:
            target_bytes = int(max_results_bytes * prune_watermark)
            target_bytes = min(target_bytes, max_results_bytes)
        else:
            target_bytes = max_results_bytes

        while prunable_dirs and prunable_size > target_bytes:
            victim = prunable_dirs.pop(0)
            try:
                victim_size = _dir_size_bytes(victim)
                shutil.rmtree(victim)
                prunable_size = max(0, prunable_size - victim_size)
                logging.info("Pruned old prunable case (max-results-gb): %s", victim)
            except Exception as e:
                logging.warning("Failed to prune %s: %s", victim, e)
                break

    # 3) Disk free guard (only stop if still low after pruning prunable categories)
    if min_free_gb is not None:
        try:
            usage = shutil.disk_usage(str(results_dir))
        except FileNotFoundError:
            usage = shutil.disk_usage(str(results_dir.parent))
        min_free_bytes = int(min_free_gb * 1024**3)
        if usage.free < min_free_bytes:
            logging.warning(
                "Low disk space after pruning prunable results: free=%.2fGB < min_free=%.2fGB. Stopping.",
                usage.free / 1024**3,
                min_free_gb,
            )
            return False

    return True


def pick_next_new_seed_dir(seeds_dir: Path, prefix: str = "new") -> Path:
    seeds_dir = Path(seeds_dir)
    seeds_dir.mkdir(parents=True, exist_ok=True)
    max_n = 0
    for p in seeds_dir.iterdir():
        if not p.is_dir():
            continue
        name = p.name
        if not name.startswith(prefix):
            continue
        suffix = name[len(prefix):]
        if suffix.isdigit():
            max_n = max(max_n, int(suffix))
    out = seeds_dir / f"{prefix}{max_n + 1}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def enforce_seed_file_cap(seed_dir: Path, max_files: int):
    seed_dir = Path(seed_dir)
    if max_files <= 0 or not seed_dir.exists():
        return
    files = [p for p in seed_dir.glob('*.rs') if p.is_file()]
    files = _sort_oldest_first(files)
    while len(files) > max_files:
        victim = files.pop(0)
        try:
            victim.unlink()
            logging.info("Pruned old promoted seed: %s", victim)
        except Exception as e:
            logging.warning("Failed to prune promoted seed %s: %s", victim, e)
            break


def parse_args_and_config(argv: Optional[List[str]] = None):
    # Stage 1: only parse --config so we can load defaults from the config file.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default="config.json", help="Path to configuration file")
    pre_args, remaining = pre.parse_known_args(argv)

    config = load_config(pre_args.config)
    run_cfg = config.get("run", {})

    # Stage 2: full parser with config-backed defaults. CLI overrides config.
    parser = argparse.ArgumentParser(
        description="Trait-Fuzzer V1.0",
        parents=[pre],
    )

    # Strategy selection
    parser.set_defaults(structural_only=run_cfg.get("structural_only", True))
    parser.add_argument(
        "--structural-only",
        dest="structural_only",
        action="store_true",
        help="Only use AST structural mutators (default from config.run.structural_only)",
    )
    parser.add_argument(
        "--all-strategies",
        dest="structural_only",
        action="store_false",
        help="Enable non-structural + LLM forcing (original behavior)",
    )

    # Safety controls for long runs
    parser.add_argument(
        "--max-cases",
        type=int,
        default=run_cfg.get("max_cases", None),
        help="Max number of saved cases under results/ (oldest pruned).",
    )
    parser.add_argument(
        "--max-results-gb",
        type=float,
        default=run_cfg.get("max_results_gb", None),
        help="Max size of results/ in GB (oldest pruned).",
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=run_cfg.get("min_free_gb", None),
        help="Stop fuzzing if free disk space drops below this GB threshold.",
    )

    # Retention & promotion policy
    parser.add_argument(
        "--keep-success-cases",
        type=int,
        default=int(run_cfg.get("keep_success_cases", 2000)),
        help="How many SUCCESS cases to keep under results/success/ (oldest pruned)",
    )
    parser.add_argument(
        "--keep-error-cases",
        type=int,
        default=int(run_cfg.get("keep_error_cases", 2000)),
        help="How many ERROR cases to keep under results/error/ (oldest pruned)",
    )

    parser.set_defaults(promote_success=bool(run_cfg.get("promote_success", True)))
    parser.add_argument(
        "--promote-success",
        dest="promote_success",
        action="store_true",
        help="Promote SUCCESS mutants into seeds/newN",
    )
    parser.add_argument(
        "--no-promote-success",
        dest="promote_success",
        action="store_false",
        help="Do not promote SUCCESS mutants into seeds/newN",
    )
    parser.add_argument(
        "--new-seeds-max",
        type=int,
        default=int(run_cfg.get("new_seeds_max", 2000)),
        help="Max number of promoted seeds to keep in seeds/newN/ (oldest pruned)",
    )
    parser.add_argument(
        "--new-seeds-prefix",
        type=str,
        default=str(run_cfg.get("new_seeds_prefix", "new")),
        help="Prefix for promoted seed folders under seeds/ (e.g. new1, new2, ...)",
    )

    args = parser.parse_args(remaining, namespace=pre_args)
    return args, config

class SeedSelector:
    def __init__(self, seeds_dir: Path):
        # Allow organizing seeds in subdirectories (e.g. imported official suites).
        all_seeds = list(seeds_dir.rglob("*.rs"))
        self.seeds = [p for p in all_seeds if not self._is_internal_only_seed(p)]
        filtered = len(all_seeds) - len(self.seeds)
        if filtered > 0:
            logging.info(
                "Filtered %d seeds due to internal-only features (rustc_attrs/lang_items/intrinsics/etc.)",
                filtered,
            )
        self.scores = {}
        self._ttdn = TTDNModel()
        self._ttdn_cache = {}  # (path, mtime_ns) -> (depth, cycles)

    @staticmethod
    def _is_internal_only_seed(seed_path: Path) -> bool:
        """Heuristically filter seeds that rely on internal-only rustc features.

        Motivation: ICEs triggered by incorrect usage of internal-only features (e.g.
        rustc_attrs/lang_items/intrinsics) are typically not accepted upstream.

        We only scan a small prefix because these attributes are almost always at the top.
        """
        try:
            text = seed_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return False

        head = text[:8000]

        # Feature gates that strongly suggest "internal-only" testing seeds.
        internal_features = (
            "rustc_attrs",
            "lang_items",
            "intrinsics",
            "core_intrinsics",
            "rustc_private",
        )

        # Quick substring checks (fast path).
        if "#![feature(" in head and any(f in head for f in internal_features):
            return True

        # Attributes often used with rustc-internal plumbing.
        internal_attr_markers = (
            "#[rustc_",
            "#![rustc_",
            "#[lang =",
            "#![no_core]",
            "#![rustc_attrs]",
        )
        if any(m in head for m in internal_attr_markers):
            return True

        # Intrinsics linkage style.
        if "extern \"rust-intrinsic\"" in head:
            return True

        return False
        
    def _calculate_scores(self):
        logging.info("Calculating TTDN scores for all seeds...")
        for seed in self.seeds:
            try:
                mtime_ns = seed.stat().st_mtime_ns
                cache_key = (str(seed), int(mtime_ns))
                cached = self._ttdn_cache.get(cache_key)
                if cached is None:
                    complexity = self._ttdn.calculate_complexity_for_file(seed)
                    cached = (int(complexity.depth), int(complexity.cycles))
                    self._ttdn_cache[cache_key] = cached
                depth, cycles = cached
                # Score = (Depth * 20 + Cycles)^3 for aggressive bias
                base_score = depth * 20 + cycles
                score = base_score ** 3
                self.scores[seed] = max(1, score) # Ensure non-zero
            except Exception as e:
                logging.warning(f"Failed to score {seed.name}: {e}")
                self.scores[seed] = 1

    def select(self, strategy="random"):
        if not self.seeds:
            return None
            
        if strategy == "ttdn_metric":
            if not self.scores:
                self._calculate_scores()
            
            # Weighted choice
            weights = [self.scores[s] for s in self.seeds]
            return random.choices(self.seeds, weights=weights, k=1)[0]
            
        else:
            return random.choice(self.seeds)

    def remove_seed(self, seed: Path):
        try:
            self.seeds.remove(seed)
        except ValueError:
            return
        self.scores.pop(seed, None)

def main():
    try:
        args, config = parse_args_and_config()
        setup_logging(config)
        logging.info("Trait-Fuzzer started with config: %s", args.config)
        
        # Initialize components
        compiler_cfg = config.get("compiler", {})
        compiler = RustCompiler(
            timeout=config["fuzzer"]["max_time_per_case_sec"],
            rustc_cmd=compiler_cfg.get("rustc_cmd"),
        )
        mutator_pool = MutatorPool(config)
        llm_connector = LLMConnector(config)
        
        # LLM Agents
        extractor = ExtractorAgent(llm_connector)
        injector = InjectorAgent(llm_connector)
        revision = RevisionAgent(llm_connector)

        # Unified TTDN model (Rust syn-based extractor via mutation-ast --mode ttdn_metrics)
        ttdn_model = TTDNModel()

        # Option: run only structural AST mutators.
        # This is useful for stabilizing runs and focusing on trait/topology evolution.
        if args.structural_only:
            mutator_pool.strategies = ["ast_structural"]
            mutator_pool.probs = [1.0]

        # Seeds
        seeds_dir = Path(config["paths"]["seeds"])
        results_dir = Path(config["paths"]["results"])
        
        selector = SeedSelector(seeds_dir)
        if not selector.seeds:
            logging.warning("No seeds found in %s", seeds_dir)
            return

        # Seeds that `syn` cannot parse (common in rustc UI tests with newer syntax).
        bad_seeds = set()

        logging.info("Found %d seeds", len(selector.seeds))

        promoted_dir: Optional[Path] = None
        if args.promote_success:
            promoted_dir = pick_next_new_seed_dir(seeds_dir, prefix=args.new_seeds_prefix)
            logging.info("Promoting SUCCESS mutants into %s", promoted_dir)

        # If configured, proactively enforce limits before starting.
        if not enforce_results_limits(
            results_dir,
            max_cases=args.max_cases,
            max_results_gb=args.max_results_gb,
            min_free_gb=args.min_free_gb,
            keep_success_cases=args.keep_success_cases,
            keep_error_cases=args.keep_error_cases,
        ):
            return
        
        # State tracking
        max_complexity = {"depth": 0, "cycles": 0}
        stall_counter = 0
        stall_threshold = config["fuzzer"]["stall_threshold"]

        enable_next_solver = bool(compiler_cfg.get("enable_next_trait_solver", False))
        next_solver_rustc_cmd = compiler_cfg.get("rustc_z_cmd", ["rustc", "+nightly"])
        next_solver_flag = compiler_cfg.get("next_trait_solver_flag", "-Znext-solver=coherence")

        # Config Parameters
        iterations = config["fuzzer"]["iterations"]
        mutations_per_seed = config["fuzzer"].get("mutations_per_seed", 1)
        seed_strategy = config["fuzzer"].get("seed_selection_strategy", "random")

        # Fuzzing Loop
        for i in range(iterations):
            # 1. Select Seed
            seed_path = selector.select(seed_strategy)
            while seed_path is not None and seed_path in bad_seeds and selector.seeds:
                seed_path = selector.select(seed_strategy)
            if seed_path is None:
                logging.warning("No usable seeds available")
                return
            
            # Read seed content once
            with open(seed_path, 'r', encoding='utf-8') as f:
                seed_content = f.read()

            logging.info(f"Iteration {i+1}/{iterations}: Selected seed {seed_path.name}")

            # 2. Variants Loop
            for j in range(mutations_per_seed):
                variant_id = f"iter_{i+1}_var_{j+1}"
                
                # ------------------------------------------------------------------
                # Robust Mutation & Compilation Loop
                # ------------------------------------------------------------------
                max_retries = 10
                mutated_content = None
                current_strategy = None
                
                # A. Mutation Retry Loop
                for attempt in range(max_retries):
                    try:
                        # 1. Adaptive Strategy Selection
                        if stall_counter >= stall_threshold:
                            # When stalled, we normally force LLM injection.
                            # In structural-only mode, keep selecting structural strategies.
                            if args.structural_only:
                                current_strategy = mutator_pool.select_strategy()
                            else:
                                current_strategy = "llm_injection"
                                # Only warn once per stalled variant
                                if attempt == 0:
                                    logging.warning(
                                        f"[{variant_id}] Stagnation detected (Stall: {stall_counter}). Forcing LLM Strategy."
                                    )
                            stall_counter = 0
                        else:
                            current_strategy = mutator_pool.select_strategy()
                        
                        # Log strategy
                        suffix = f" (Retry {attempt})" if attempt > 0 else ""
                        logging.info(f"  -> Variant {j+1}{suffix}: Strategy {current_strategy}")

                        # 2. Perform Mutation
                        if current_strategy == "llm_injection":
                            topology = extractor.extract_topology(seed_content)
                            mutated_content = injector.inject_topology(seed_content, topology)
                            break 
                        
                        elif current_strategy == "ast_non_structural_noop":
                           stall_counter += 1
                           mutated_content = None
                           # Force retry by continuing? No, this strategy specifically means do nothing?
                           # If noop is selected, we skip.
                           continue 

                        else: 
                            # Rust AST Mutation
                            rust_mode = current_strategy
                            bin_dir = Path("mutation/mutation-AST") 
                            with tempfile.TemporaryDirectory(prefix=f"trait_fuzzer_mut_{variant_id}_") as td:
                                output_temp = Path(td) / "mutant.rs"

                                cmd = [
                                    "cargo", "run", "--quiet", "--",
                                    "--input", str(seed_path.absolute()),
                                    "--output", str(output_temp.absolute()),
                                    "--mode", rust_mode,
                                ]

                                proc = subprocess.run(
                                    cmd,
                                    cwd=str(bin_dir.absolute()),
                                    check=True,         # Will raise CalledProcessError on non-zero exit
                                    capture_output=True,
                                    text=True,
                                )

                                # If syn cannot parse this seed, blacklist it and move on.
                                if "Parse failed:" in proc.stderr:
                                    logging.warning(
                                        f"[{variant_id}] Seed not parseable by syn; skipping: {seed_path.name}"
                                    )
                                    bad_seeds.add(seed_path)
                                    selector.remove_seed(seed_path)
                                    mutated_content = None
                                    break

                                # Check for No-Op
                                if "No mutation performed" in proc.stderr:
                                    logging.info(
                                        f"    [No-Op] Strategy {current_strategy} inapplicable. Retrying..."
                                    )
                                    continue  # Retry loop

                                # Success case
                                if output_temp.exists():
                                    with open(output_temp, 'r') as f:
                                        mutated_content = f.read()
                                    break  # Mutated successfully
                                else:
                                    logging.error(f"[{variant_id}] Rust mutation tool produced no output")
                                    continue

                        # If we blacklisted the seed, stop trying more strategies for it.
                        if seed_path in bad_seeds:
                            break

                    except subprocess.CalledProcessError as e:
                        logging.error(f"[{variant_id}] Mutation tool failed: {e.stderr}")
                        continue # Retry
                    except Exception as e:
                        logging.error(f"[{variant_id}] Unexpected error during mutation: {e}")
                        continue

                # B. Compilation & Analysis (Outside Retry Loop)
                if mutated_content is None:
                    logging.warning(f"[{variant_id}] Failed to produce mutation after {max_retries} attempts.")
                    continue

                try: 
                    # 3. Save & Compile
                    temp_src = Path(f"temp_{variant_id}.rs")
                    with open(temp_src, 'w') as f:
                        f.write(mutated_content)

                    # 3.1 Compile (default)
                    result_default = compiler.compile(temp_src)

                    # 3.2 Optional: compile again with the next trait solver (-Z)
                    result_next = None
                    if enable_next_solver:
                        compiler_next = RustCompiler(
                            timeout=config["fuzzer"]["max_time_per_case_sec"],
                            rustc_cmd=next_solver_rustc_cmd,
                        )
                        result_next = compiler_next.compile(temp_src, extra_args=[next_solver_flag])

                    def _rank(status: CompilationStatus) -> int:
                        order = {
                            CompilationStatus.CRASH: 4,
                            CompilationStatus.HANG: 3,
                            CompilationStatus.ERROR: 2,
                            CompilationStatus.SUCCESS: 1,
                            CompilationStatus.UNKNOWN: 0,
                        }
                        return order.get(status, 0)

                    # Overall status: take the worse one (useful for triage/persistence).
                    result = result_default
                    if result_next is not None and _rank(result_next.status) > _rank(result_default.status):
                        result = result_next
                    
                    # 4. Categorize & persist
                    # Always keep HANG/CRASH(ICE) and ERROR. SUCCESS is also kept (capped)
                    # and additionally promoted into seeds/newN.
                    status_name = result.status.value.lower()
                    should_persist = True
                    # Allow explicitly disabling SUCCESS persistence (still can be promoted).
                    if result.status == CompilationStatus.SUCCESS and args.keep_success_cases == 0:
                        should_persist = False

                    dest_case = None
                    if should_persist:
                        # Per-case safety check: prune prunable categories before we write more.
                        if not enforce_results_limits(
                            results_dir,
                            max_cases=args.max_cases,
                            max_results_gb=args.max_results_gb,
                            min_free_gb=args.min_free_gb,
                            keep_success_cases=args.keep_success_cases,
                            keep_error_cases=args.keep_error_cases,
                        ):
                            return

                        dest_dir = results_dir / status_name
                        dest_case = dest_dir / f"case_{variant_id}"
                        dest_case.mkdir(parents=True, exist_ok=True)
                        shutil.copy(seed_path, dest_case / "before.rs")
                        shutil.copy(temp_src, dest_case / "after.rs")

                    # 5. TTDN & Complexity (unified model)
                    complexity = ttdn_model.calculate_complexity_for_file(temp_src)
                    current_depth = int(complexity.depth)
                    current_cycles = int(complexity.cycles)

                    if temp_src.exists():
                        temp_src.unlink()
                    
                    if current_depth > max_complexity["depth"] or current_cycles > max_complexity["cycles"]:
                        logging.info(f"New Complexity Record! Depth: {current_depth}, Cycles: {current_cycles}")
                        max_complexity["depth"] = max(max_complexity["depth"], current_depth)
                        max_complexity["cycles"] = max(max_complexity["cycles"], current_cycles)
                        stall_counter = 0 
                    else:
                        stall_counter += 1
                    
                    if dest_case is not None:
                        with open(dest_case / "detail.log", 'w') as f:
                            f.write(f"Seed: {seed_path.name}\n")
                            f.write(f"Strategy: {current_strategy}\n")
                            f.write(f"Status: {result.status.value}\n")
                            f.write(f"TTDN Depth: {current_depth}\n")
                            f.write(f"TTDN Cycles: {current_cycles}\n")
                            f.write("\n=== rustc (default) ===\n")
                            f.write(f"Status: {result_default.status.value}\n")
                            f.write(f"Duration: {result_default.duration:.4f}s\n")
                            f.write(f"Return code: {result_default.return_code}\n")
                            f.write(f"Stdout:\n{result_default.stdout}\n")
                            f.write(f"Stderr:\n{result_default.stderr}\n")

                            if result_next is not None:
                                f.write("\n=== rustc (-Z next trait-solver) ===\n")
                                f.write(f"Command: {' '.join(map(str, next_solver_rustc_cmd + [next_solver_flag]))}\n")
                                f.write(f"Status: {result_next.status.value}\n")
                                f.write(f"Duration: {result_next.duration:.4f}s\n")
                                f.write(f"Return code: {result_next.return_code}\n")
                                f.write(f"Stdout:\n{result_next.stdout}\n")
                                f.write(f"Stderr:\n{result_next.stderr}\n")

                    logging.info(f"[{variant_id}] Result: {result.status.value} | Depth: {current_depth}")

                    # Promote SUCCESS mutants into seeds/newN (rolling cap)
                    if promoted_dir is not None and result.status == CompilationStatus.SUCCESS:
                        try:
                            out_path = promoted_dir / f"seed_{variant_id}.rs"
                            if out_path.exists():
                                out_path = promoted_dir / f"seed_{variant_id}_{int(time.time())}.rs"
                            out_path.write_text(mutated_content, encoding='utf-8', errors='ignore')
                            enforce_seed_file_cap(promoted_dir, args.new_seeds_max)
                        except Exception as e:
                            logging.warning("Failed to promote seed %s: %s", variant_id, e)

                except Exception as e:
                    logging.error(f"[{variant_id}] Variant compilation/analysis failed: {e}")

            # End of one outer iteration (one selected seed): prune prunable categories.
            if not enforce_results_limits(
                results_dir,
                max_cases=args.max_cases,
                max_results_gb=args.max_results_gb,
                min_free_gb=args.min_free_gb,
                keep_success_cases=args.keep_success_cases,
                keep_error_cases=args.keep_error_cases,
            ):
                return

        logging.info("Trait-Fuzzer finished.")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
