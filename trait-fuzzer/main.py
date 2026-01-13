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
import math
import collections
import hashlib
import re
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
_PRUNE_WATERMARK = 0.90


def enforce_results_limits(
    results_dir: Path,
    max_cases: Optional[int],
    max_results_gb: Optional[float],
    min_free_gb: Optional[float],
    keep_success_cases: int,
    keep_error_cases: int,
) -> bool:
    """Prune only SUCCESS/ERROR cases; never delete HANG/CRASH/FATE.

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


def maybe_roll_promoted_dir(current_dir: Path, seeds_dir: Path, prefix: str, max_files: int) -> Path:
    """If current promoted dir already contains >= max_files seeds, roll to the next newN dir.

    This matches the expected behavior: new1 fills up, then new2 is created, etc.
    """
    current_dir = Path(current_dir)
    if max_files <= 0:
        return current_dir
    try:
        files = [p for p in current_dir.glob('*.rs') if p.is_file()]
        if len(files) >= int(max_files):
            nxt = pick_next_new_seed_dir(Path(seeds_dir), prefix=str(prefix or "new"))
            logging.info(
                "Promoted dir full (%d/%d): rolling to %s",
                len(files),
                int(max_files),
                nxt,
            )
            return nxt
    except Exception:
        # Be conservative: if we can't inspect, keep writing to the current dir.
        return current_dir
    return current_dir


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
        help="Max number of promoted seeds per seeds/<newN>/; when full, roll to <new(N+1)>",
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
    def __init__(self, seeds_dir: Path, fuzzer_cfg: Optional[dict] = None, promoted_prefix: str = "new"):
        # Allow organizing seeds in subdirectories (e.g. imported official suites).
        self._seeds_dir = Path(seeds_dir)
        self._promoted_prefix = str(promoted_prefix or "new")

        # Probability of sampling from the promoted pool first.
        # Default is aggressive base:promoted = 9:1.
        fuzzer_cfg = dict(fuzzer_cfg or {})
        self._promoted_pool_prob = float(fuzzer_cfg.get("seed_promoted_pool_prob", 0.10))
        if self._promoted_pool_prob < 0.0:
            self._promoted_pool_prob = 0.0
        if self._promoted_pool_prob > 1.0:
            self._promoted_pool_prob = 1.0

        self._promoted_seeds: set = set()

        all_seeds = list(seeds_dir.rglob("*.rs"))
        self.seeds = [p for p in all_seeds if not self._is_internal_only_seed(p)]
        for p in self.seeds:
            if self._is_promoted_seed(p):
                self._promoted_seeds.add(p)
        filtered = len(all_seeds) - len(self.seeds)
        if filtered > 0:
            logging.info(
                "Filtered %d seeds due to internal-only features (rustc_attrs/lang_items/intrinsics/etc.)",
                filtered,
            )
        self.scores: Dict[Path, int] = {}
        self._ttdn = TTDNModel()
        self._ttdn_cache = {}  # (path, mtime_ns) -> score(int)
        self._scores_initialized = False

        # Seed selection smoothing to avoid getting stuck on one high-score seed.
        # These are optional knobs (read from config.fuzzer.*) with safe defaults.
        self._weight_temperature = float(fuzzer_cfg.get("seed_weight_temperature", 2.0))
        self._pick_decay_beta = float(fuzzer_cfg.get("seed_pick_decay_beta", 1.0))
        self._min_weight = float(fuzzer_cfg.get("seed_min_weight", 1.0))
        self._repeat_window = int(fuzzer_cfg.get("seed_repeat_window", 32))
        self._max_picks_per_seed = fuzzer_cfg.get("seed_max_picks_per_seed", 1)

        if self._repeat_window < 0:
            self._repeat_window = 0
        if self._weight_temperature <= 0:
            self._weight_temperature = 1.0
        if self._pick_decay_beta < 0:
            self._pick_decay_beta = 0.0
        if self._min_weight <= 0:
            self._min_weight = 1.0

        self._pick_counts: Dict[Path, int] = {}
        self._recent: "collections.deque[Path]" = collections.deque(maxlen=self._repeat_window)

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

    def _is_promoted_seed(self, seed_path: Path) -> bool:
        """Return True if the seed lives under seeds/<prefix><digits>/..."""
        try:
            rel = Path(seed_path).resolve().relative_to(self._seeds_dir.resolve())
        except Exception:
            return False
        if not rel.parts:
            return False
        top = rel.parts[0]
        if not top.startswith(self._promoted_prefix):
            return False
        suffix = top[len(self._promoted_prefix):]
        return bool(suffix) and suffix.isdigit()
        
    def _calculate_scores(self):
        logging.info("Calculating seed scores (constraint-choice metric) for all seeds...")
        for seed in self.seeds:
            try:
                self.scores[seed] = self._score_one(seed)
            except Exception as e:
                logging.warning(f"Failed to score {seed.name}: {e}")
                self.scores[seed] = 1

        self._scores_initialized = True

    def _score_one(self, seed: Path) -> int:
        mtime_ns = seed.stat().st_mtime_ns
        cache_key = (str(seed), int(mtime_ns))
        cached = self._ttdn_cache.get(cache_key)
        if cached is None:
            complexity = self._ttdn.calculate_complexity_for_file(seed)

            # New definition (source of truth):
            # score = sum over all constraint injection sites of (# selectable constraints).
            # Exposed by mutation-ast --mode ttdn_metrics as `constraint_choice_sum`.
            score = int(complexity.extra.get("constraint_choice_sum", 0))

            # Backwards-compatible fallback if the Rust tool is older.
            if score <= 0:
                depth = int(complexity.extra.get("depth", 0))
                cycles = int(complexity.extra.get("cycles", 0))
                score = max(1, depth * 20 + cycles)

            cached = int(score)
            self._ttdn_cache[cache_key] = cached

        return max(1, int(cached))

    def add_seed(self, seed: Path):
        seed = Path(seed)
        if not seed.exists() or not seed.is_file() or seed.suffix != ".rs":
            return
        if seed in self.seeds:
            return
        if self._is_internal_only_seed(seed):
            return
        self.seeds.append(seed)
        if self._is_promoted_seed(seed):
            self._promoted_seeds.add(seed)
        # If we've already initialized scoring, score this seed now (incremental, cheap).
        if self._scores_initialized or self.scores:
            try:
                self.scores[seed] = self._score_one(seed)
            except Exception:
                self.scores[seed] = 1

    def _choose_pool_candidates(self, eligible: List[Path]) -> List[Path]:
        if not eligible:
            return eligible

        promoted = [s for s in eligible if s in self._promoted_seeds]
        base = [s for s in eligible if s not in self._promoted_seeds]

        # Prefer base pool by default (aggressive 9:1), but fall back if empty.
        want_promoted = random.random() < self._promoted_pool_prob
        if want_promoted and promoted:
            return promoted
        if base:
            return base
        return promoted

    def _eligible_seeds(self) -> List[Path]:
        if not self.seeds:
            return []

        # Enforce a simple budget per seed if configured.
        if self._max_picks_per_seed is not None:
            try:
                max_picks = int(self._max_picks_per_seed)
            except Exception:
                max_picks = -1
            if max_picks >= 0:
                return [s for s in self.seeds if self._pick_counts.get(s, 0) < max_picks]

        return list(self.seeds)

    def _weight_for_seed(self, seed: Path) -> float:
        base = float(self.scores.get(seed, 1))

        # Temperature > 1 flattens distribution; < 1 makes it greedier.
        shaped = math.pow(max(1.0, base), 1.0 / self._weight_temperature)

        # Penalize repeatedly selected seeds to avoid being stuck.
        picked = float(self._pick_counts.get(seed, 0))
        decayed = shaped / math.pow(1.0 + picked, self._pick_decay_beta)

        return max(self._min_weight, decayed)

    def _weighted_choice(self, candidates: List[Path]) -> Optional[Path]:
        if not candidates:
            return None
        weights = [self._weight_for_seed(s) for s in candidates]
        return random.choices(candidates, weights=weights, k=1)[0]

    def _record_pick(self, seed: Path):
        self._pick_counts[seed] = self._pick_counts.get(seed, 0) + 1
        if self._repeat_window > 0:
            self._recent.append(seed)

    def _candidates_within_window(self, eligible: List[Path]) -> List[Path]:
        if self._repeat_window <= 0 or len(eligible) <= 1:
            return eligible
        recent_set = set(self._recent)
        candidates = [s for s in eligible if s not in recent_set]
        # If all seeds are "recent", relax the constraint.
        return candidates if candidates else eligible

    def select(self, strategy="random"):
        if not self.seeds:
            return None

        def _pick_with_retry(pick_fn):
            # Seeds under promoted pool can be pruned on disk (new_seeds_max). If we
            # still have stale paths in memory, drop them lazily and retry.
            for _ in range(16):
                picked = pick_fn()
                if picked is None:
                    return None
                if Path(picked).exists():
                    return picked
                self.remove_seed(Path(picked))
            return None
            
        if strategy == "ttdn_metric":
            if not self.scores:
                self._calculate_scores()

            # Prefer not repeating seeds within a short window.
            eligible = self._eligible_seeds()
            if not eligible:
                return None

            pool = self._choose_pool_candidates(eligible)
            candidates = self._candidates_within_window(pool)

            def _do_pick():
                return self._weighted_choice(candidates)

            picked = _pick_with_retry(_do_pick)
            if picked is not None:
                self._record_pick(picked)
            return picked
            
        else:
            eligible = self._eligible_seeds()
            if not eligible:
                return None
            pool = self._choose_pool_candidates(eligible)
            candidates = self._candidates_within_window(pool)
            def _do_pick():
                if not candidates:
                    return None
                return random.choice(candidates)

            picked = _pick_with_retry(_do_pick)
            if picked is not None:
                self._record_pick(picked)
            return picked

    def remove_seed(self, seed: Path):
        try:
            self.seeds.remove(seed)
        except ValueError:
            return
        self.scores.pop(seed, None)
        self._promoted_seeds.discard(seed)
        self._pick_counts.pop(seed, None)
        if self._repeat_window > 0:
            try:
                self._recent = collections.deque([s for s in self._recent if s != seed], maxlen=self._repeat_window)
            except Exception:
                pass

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
        
        selector = SeedSelector(seeds_dir, fuzzer_cfg=config.get("fuzzer", {}), promoted_prefix=args.new_seeds_prefix)
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
        max_choice = {"constraint_choice_sum": 0}
        stall_counter = 0
        stall_threshold = config["fuzzer"]["stall_threshold"]

        # Promotion rate limit: each parent seed can contribute at most N SUCCESS mutants
        # into seeds/<newN>/ across the whole run.
        max_promotions_per_seed = int(config.get("fuzzer", {}).get("max_promotions_per_seed", 2))
        promotions_by_seed: Dict[Path, int] = {}

        enable_next_solver = bool(compiler_cfg.get("enable_next_trait_solver", False))
        # If we enable next-solver, we almost always also want a plain nightly compile for comparison.
        enable_nightly_compile = bool(compiler_cfg.get("enable_nightly_compile", enable_next_solver))
        nightly_rustc_cmd = compiler_cfg.get("rustc_z_cmd", ["rustc", "+nightly"])
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

            parent_key = seed_path.resolve()

            # Baseline compilation for the original seed (lazy).
            # Used only to decide whether CRASH/HANG variants should be classified as "fate"
            # (i.e., the seed already CRASH/HANGs before mutation).
            seed_baseline_results = None
            seed_is_fate: Optional[bool] = None

            def _compile_seed_baseline() -> Dict[str, object]:
                nonlocal seed_baseline_results
                if seed_baseline_results is not None:
                    return seed_baseline_results

                baseline_src = Path(f"temp_seed_baseline_iter_{i+1}.rs")
                with open(baseline_src, "w") as f:
                    f.write(seed_content)

                try:
                    base_stable = compiler.compile(baseline_src)
                    out: Dict[str, object] = {"stable": base_stable}

                    if enable_nightly_compile:
                        compiler_nightly = RustCompiler(
                            timeout=config["fuzzer"]["max_time_per_case_sec"],
                            rustc_cmd=nightly_rustc_cmd,
                        )
                        out["nightly"] = compiler_nightly.compile(baseline_src)

                    if enable_next_solver:
                        compiler_next = RustCompiler(
                            timeout=config["fuzzer"]["max_time_per_case_sec"],
                            rustc_cmd=nightly_rustc_cmd,
                        )
                        out["next"] = compiler_next.compile(baseline_src, extra_args=[next_solver_flag])

                    seed_baseline_results = out
                    return out
                finally:
                    try:
                        if baseline_src.exists():
                            baseline_src.unlink()
                    except Exception:
                        pass

            def _is_seed_fate() -> bool:
                """A seed is 'fate' if its baseline already CRASH/HANGs in any enabled mode."""
                nonlocal seed_is_fate
                if seed_is_fate is not None:
                    return seed_is_fate

                try:
                    base = _compile_seed_baseline()
                    order = {
                        CompilationStatus.CRASH: 4,
                        CompilationStatus.HANG: 3,
                        CompilationStatus.ERROR: 2,
                        CompilationStatus.SUCCESS: 1,
                        CompilationStatus.UNKNOWN: 0,
                    }
                    worst_status = None
                    for r in base.values():
                        st = r.status  # type: ignore[attr-defined]
                        if worst_status is None or order.get(st, 0) > order.get(worst_status, 0):
                            worst_status = st
                    seed_is_fate = worst_status in (CompilationStatus.CRASH, CompilationStatus.HANG)
                    return bool(seed_is_fate)
                except Exception:
                    # If baseline check fails unexpectedly, do NOT classify as fate.
                    seed_is_fate = False
                    return False

            try:
                rel = seed_path.relative_to(seeds_dir)
                rel_s = str(rel)
            except Exception:
                rel_s = str(seed_path)
            logging.info(f"Iteration {i+1}/{iterations}: Selected seed {rel_s}")

            # Deduplicate identical mutations produced from the same seed.
            # Keyed by mutator strategy name; values are sha256 hashes of mutated content.
            # This is per selected seed (per outer iteration) to keep memory bounded.
            seen_mutations_by_strategy: Dict[str, set] = {}

            # Avoid repeatedly sampling the same mutation *point* inside the AST mutators.
            # Keyed by mutator strategy name; values are 0-based candidate indices already tried.
            used_indices_by_strategy: Dict[str, set] = {}
            # Keyed by strategy name; values are total candidate count reported by mutation-AST.
            known_candidate_counts: Dict[str, int] = {}
            # Leaf strategies that have no remaining mutation points for this seed.
            exhausted_strategies: set = set()

            def _enabled_leaf_strategies() -> List[str]:
                # Determine which leaf strategies may be selected (given current mutator_pool settings).
                top_enabled = {
                    s for (s, p) in zip(getattr(mutator_pool, "strategies", []), getattr(mutator_pool, "probs", []))
                    if float(p) > 0.0
                }
                leaf: List[str] = []

                if "ast_structural" in top_enabled:
                    ops = list(getattr(mutator_pool, "structural_ops", []))
                    subw = getattr(mutator_pool, "structural_subweights", {}) or {}
                    # Match MutatorPool semantics: if all zeros/missing, fall back to all ops.
                    active = [op for op in ops if float(subw.get(op, 0.0)) > 0.0]
                    leaf.extend(active if active else ops)

                if "ast_non_structural" in top_enabled:
                    leaf.extend([
                        "bin_op_flip",
                        "int_literal_change",
                        "bool_flip",
                        "replace_by_constant",
                        "inject_control_flow",
                    ])

                if "llm_injection" in top_enabled:
                    leaf.append("llm_injection")

                # De-dup, preserve order.
                out: List[str] = []
                for s in leaf:
                    if s not in out:
                        out.append(s)
                return out

            def _select_strategy_avoiding_exhausted() -> Optional[str]:
                enabled = _enabled_leaf_strategies()
                candidates = [s for s in enabled if s not in exhausted_strategies]
                if not candidates:
                    return None

                # Prefer the configured distribution, but fall back to a remaining candidate.
                for _ in range(20):
                    s = mutator_pool.select_strategy()
                    if s not in exhausted_strategies:
                        return s
                return random.choice(candidates)

            # 2. Variants Loop
            for j in range(mutations_per_seed):
                variant_id = f"iter_{i+1}_var_{j+1}"
                
                # ------------------------------------------------------------------
                # Robust Mutation & Compilation Loop
                # ------------------------------------------------------------------
                max_retries = 10
                mutated_content = None
                current_strategy = None
                inapplicable_retries = 0
                skip_iteration_due_to_inapplicable = False

                def _is_duplicate_mutation(strategy: str, content: str) -> bool:
                    if not strategy or content is None:
                        return False
                    h = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
                    seen = seen_mutations_by_strategy.setdefault(strategy, set())
                    if h in seen:
                        return True
                    seen.add(h)
                    return False
                
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
                            current_strategy = _select_strategy_avoiding_exhausted()

                        if current_strategy is None:
                            logging.warning(
                                f"[{variant_id}] All enabled strategies are exhausted for this seed; stopping further variants."
                            )
                            skip_iteration_due_to_inapplicable = True
                            break
                        
                        # Log strategy
                        suffix = f" (Retry {attempt})" if attempt > 0 else ""
                        logging.info(f"  -> Variant {j+1}{suffix}: Strategy {current_strategy}")

                        # 2. Perform Mutation
                        if current_strategy == "llm_injection":
                            topology = extractor.extract_topology(seed_content)
                            mutated_content = injector.inject_topology(seed_content, topology)
                            if mutated_content is not None and _is_duplicate_mutation(current_strategy, mutated_content):
                                logging.info(
                                    f"    [Dup] Strategy {current_strategy} produced identical mutant; skipping this variant."
                                )
                                mutated_content = None
                                inapplicable_retries += 1
                                if inapplicable_retries >= max_retries:
                                    logging.warning(
                                        f"[{variant_id}] Duplicate mutant hit max retries ({max_retries}); skipping this iteration."
                                    )
                                    skip_iteration_due_to_inapplicable = True
                                    break
                                continue
                            break
                        
                        elif current_strategy == "ast_non_structural_noop":
                           stall_counter += 1
                           mutated_content = None
                           # Force retry by continuing? No, this strategy specifically means do nothing?
                           # If noop is selected, we skip.
                           inapplicable_retries += 1
                           if inapplicable_retries >= max_retries:
                               logging.warning(
                                   f"[{variant_id}] Strategy inapplicable hit max retries ({max_retries}); skipping this iteration."
                               )
                               skip_iteration_due_to_inapplicable = True
                               break
                           continue 

                        else: 
                            # Rust AST Mutation
                            rust_mode = current_strategy
                            bin_dir = Path("mutation/mutation-AST") 
                            with tempfile.TemporaryDirectory(prefix=f"trait_fuzzer_mut_{variant_id}_") as td:
                                output_temp = Path(td) / "mutant.rs"

                                # If we already know this mutator's candidate count for this seed,
                                # pick an unseen index to avoid re-sampling the same mutation point.
                                forced_index = None
                                cand_count = known_candidate_counts.get(current_strategy)
                                if cand_count is not None:
                                    used = used_indices_by_strategy.setdefault(current_strategy, set())
                                    if len(used) >= cand_count:
                                        exhausted_strategies.add(current_strategy)
                                        inapplicable_retries += 1
                                        logging.info(
                                            f"    [Exhausted] Strategy {current_strategy} has no remaining mutation points (count={cand_count}); retrying..."
                                        )
                                        if inapplicable_retries >= max_retries:
                                            logging.warning(
                                                f"[{variant_id}] Strategy inapplicable hit max retries ({max_retries}); skipping this iteration."
                                            )
                                            skip_iteration_due_to_inapplicable = True
                                            break
                                        continue

                                    # Choose a random unused index.
                                    for _ in range(20):
                                        idx = random.randrange(cand_count)
                                        if idx not in used:
                                            forced_index = idx
                                            break
                                    if forced_index is None:
                                        remaining = [k for k in range(cand_count) if k not in used]
                                        forced_index = random.choice(remaining)

                                cmd = [
                                    "cargo", "run", "--quiet", "--",
                                    "--input", str(seed_path.absolute()),
                                    "--output", str(output_temp.absolute()),
                                    "--mode", rust_mode,
                                    "--emit-choice",
                                ]

                                if forced_index is not None:
                                    cmd.extend(["--index", str(forced_index)])

                                proc = subprocess.run(
                                    cmd,
                                    cwd=str(bin_dir.absolute()),
                                    check=True,         # Will raise CalledProcessError on non-zero exit
                                    capture_output=True,
                                    text=True,
                                )

                                # Record which mutation point was actually sampled.
                                try:
                                    m = re.search(
                                        r"MUTATION_CHOICE\s+mode=(\S+)\s+count=(\d+)\s+index=(\d+)\s+mutated=(\d+)",
                                        proc.stderr,
                                    )
                                    if m is not None:
                                        count = int(m.group(2))
                                        index = int(m.group(3))
                                        known_candidate_counts[current_strategy] = count
                                        used_set = used_indices_by_strategy.setdefault(current_strategy, set())
                                        used_set.add(index)
                                        if count > 0 and len(used_set) >= count:
                                            exhausted_strategies.add(current_strategy)
                                except Exception:
                                    # Best-effort only; falling back to hash-based dedup is fine.
                                    pass

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
                                    inapplicable_retries += 1
                                    logging.info(
                                        f"    [No-Op] Strategy {current_strategy} inapplicable. Retrying..."
                                    )
                                    if inapplicable_retries >= max_retries:
                                        logging.warning(
                                            f"[{variant_id}] Strategy inapplicable hit max retries ({max_retries}); skipping this iteration."
                                        )
                                        skip_iteration_due_to_inapplicable = True
                                        break
                                    continue  # Retry loop

                                # Success case
                                if output_temp.exists():
                                    with open(output_temp, 'r') as f:
                                        mutated_content = f.read()

                                    if mutated_content is not None and _is_duplicate_mutation(current_strategy, mutated_content):
                                        logging.info(
                                            f"    [Dup] Strategy {current_strategy} produced identical mutant; skipping this variant."
                                        )
                                        mutated_content = None
                                        inapplicable_retries += 1
                                        if inapplicable_retries >= max_retries:
                                            logging.warning(
                                                f"[{variant_id}] Duplicate mutant hit max retries ({max_retries}); skipping this iteration."
                                            )
                                            skip_iteration_due_to_inapplicable = True
                                            break
                                        continue
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

                if skip_iteration_due_to_inapplicable:
                    break

                # B. Compilation & Analysis (Outside Retry Loop)
                if mutated_content is None:
                    logging.warning(f"[{variant_id}] Failed to produce mutation after {max_retries} attempts.")
                    continue

                try: 
                    # 3. Save & Compile
                    temp_src = Path(f"temp_{variant_id}.rs")
                    with open(temp_src, 'w') as f:
                        f.write(mutated_content)

                    # 3. Compile (oracle): stable once, +nightly once, +nightly with -Z next-solver once.
                    result_stable = compiler.compile(temp_src)

                    result_nightly = None
                    if enable_nightly_compile:
                        compiler_nightly = RustCompiler(
                            timeout=config["fuzzer"]["max_time_per_case_sec"],
                            rustc_cmd=nightly_rustc_cmd,
                        )
                        result_nightly = compiler_nightly.compile(temp_src)

                    result_next = None
                    if enable_next_solver:
                        compiler_next = RustCompiler(
                            timeout=config["fuzzer"]["max_time_per_case_sec"],
                            rustc_cmd=nightly_rustc_cmd,
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

                    # Overall status: take the worst one (useful for triage/persistence).
                    result = result_stable
                    for r in (result_nightly, result_next):
                        if r is not None and _rank(r.status) > _rank(result.status):
                            result = r

                    variant_by_mode = {"stable": result_stable}
                    if result_nightly is not None:
                        variant_by_mode["nightly"] = result_nightly
                    if result_next is not None:
                        variant_by_mode["next"] = result_next
                    
                    # 4. Categorize & persist
                    # Always keep HANG/CRASH(ICE) and ERROR. SUCCESS is also kept (capped)
                    # and additionally promoted into seeds/newN.
                    status_name = result.status.value.lower()
                    should_persist = True
                    # Allow explicitly disabling SUCCESS persistence (still can be promoted).
                    if result.status == CompilationStatus.SUCCESS and args.keep_success_cases == 0:
                        should_persist = False

                    # New policy: if the baseline seed already CRASH/HANGs, classify CRASH/HANG variants as "fate"
                    # to avoid extra (and often noisy) dedup logic.
                    if should_persist and result.status in (CompilationStatus.CRASH, CompilationStatus.HANG):
                        if _is_seed_fate():
                            status_name = "fate"
                            logging.info(
                                "[%s] Baseline already %s; classifying as fate",
                                variant_id,
                                result.status.value,
                            )

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
                    constraint_sites = int(complexity.extra.get("constraint_sites", 0))
                    constraint_choice_sum = int(complexity.extra.get("constraint_choice_sum", 0))

                    if temp_src.exists():
                        temp_src.unlink()
                    
                    if constraint_choice_sum > max_choice["constraint_choice_sum"]:
                        logging.info(
                            "New constraint-choice record! choice_sum=%d sites=%d",
                            constraint_choice_sum,
                            constraint_sites,
                        )
                        max_choice["constraint_choice_sum"] = max(
                            max_choice["constraint_choice_sum"],
                            constraint_choice_sum,
                        )
                        stall_counter = 0 
                    else:
                        stall_counter += 1
                    
                    if dest_case is not None:
                        with open(dest_case / "detail.log", 'w') as f:
                            f.write(f"Seed: {seed_path.name}\n")
                            f.write(f"Strategy: {current_strategy}\n")
                            f.write(f"Status: {result.status.value}\n")
                            f.write(f"Constraint Sites: {constraint_sites}\n")
                            f.write(f"Constraint Choice Sum: {constraint_choice_sum}\n")
                            f.write("\n=== rustc (stable) ===\n")
                            f.write(f"Command: {' '.join(map(str, compiler.rustc_cmd))}\n")
                            f.write(f"Status: {result_stable.status.value}\n")
                            f.write(f"Duration: {result_stable.duration:.4f}s\n")
                            f.write(f"Return code: {result_stable.return_code}\n")
                            f.write(f"Stdout:\n{result_stable.stdout}\n")
                            f.write(f"Stderr:\n{result_stable.stderr}\n")

                            if result_nightly is not None:
                                f.write("\n=== rustc (+nightly) ===\n")
                                f.write(f"Command: {' '.join(map(str, nightly_rustc_cmd))}\n")
                                f.write(f"Status: {result_nightly.status.value}\n")
                                f.write(f"Duration: {result_nightly.duration:.4f}s\n")
                                f.write(f"Return code: {result_nightly.return_code}\n")
                                f.write(f"Stdout:\n{result_nightly.stdout}\n")
                                f.write(f"Stderr:\n{result_nightly.stderr}\n")

                            if result_next is not None:
                                f.write("\n=== rustc (-Z next trait-solver) ===\n")
                                f.write(f"Command: {' '.join(map(str, nightly_rustc_cmd + [next_solver_flag]))}\n")
                                f.write(f"Status: {result_next.status.value}\n")
                                f.write(f"Duration: {result_next.duration:.4f}s\n")
                                f.write(f"Return code: {result_next.return_code}\n")
                                f.write(f"Stdout:\n{result_next.stdout}\n")
                                f.write(f"Stderr:\n{result_next.stderr}\n")

                    logging.info(
                        "[%s] Result: %s | choice_sum=%d sites=%d",
                        variant_id,
                        result.status.value,
                        constraint_choice_sum,
                        constraint_sites,
                    )

                    # Promote SUCCESS mutants into seeds/newN (rolling cap)
                    if promoted_dir is not None and result.status == CompilationStatus.SUCCESS:
                        try:
                            if max_promotions_per_seed <= 0:
                                raise RuntimeError("SUCCESS promotion disabled by max_promotions_per_seed <= 0")

                            promoted_so_far = int(promotions_by_seed.get(parent_key, 0))
                            if promoted_so_far >= max_promotions_per_seed:
                                logging.info(
                                    "[%s] Skip promote (seed cap reached: %d/%d): %s",
                                    variant_id,
                                    promoted_so_far,
                                    max_promotions_per_seed,
                                    seed_path.name,
                                )
                                raise RuntimeError("SUCCESS promotion seed cap reached")

                            # Roll to the next newN directory when the current one is full.
                            promoted_dir = maybe_roll_promoted_dir(
                                promoted_dir,
                                seeds_dir,
                                args.new_seeds_prefix,
                                args.new_seeds_max,
                            )

                            out_path = promoted_dir / f"seed_{variant_id}.rs"
                            if out_path.exists():
                                out_path = promoted_dir / f"seed_{variant_id}_{int(time.time())}.rs"
                            out_path.write_text(mutated_content, encoding='utf-8', errors='ignore')
                            # Make the newly promoted seed immediately eligible for selection.
                            try:
                                selector.add_seed(out_path)
                            except Exception:
                                pass

                            promotions_by_seed[parent_key] = promoted_so_far + 1
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
