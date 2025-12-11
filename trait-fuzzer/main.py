import sys
import os
import json
import logging
import argparse
import random
import shutil
import subprocess
from pathlib import Path

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

class SeedSelector:
    def __init__(self, seeds_dir: Path):
        self.seeds = list(seeds_dir.glob("*.rs"))
        self.scores = {}
        
    def _calculate_scores(self):
        logging.info("Calculating TTDN scores for all seeds...")
        for seed in self.seeds:
            try:
                content = seed.read_text(encoding='utf-8', errors='ignore')
                ttdn = TTDNModel()
                ttdn.load_from_source(content)
                complexity = ttdn.calculate_complexity()
                # Score = (Depth * 20 + Cycles)^3 for aggressive bias
                base_score = complexity['depth'] * 20 + complexity['cycles']
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

def main():
    parser = argparse.ArgumentParser(description="Trait-Fuzzer V1.0")
    parser.add_argument("--config", default="trait-fuzzer/config.json", help="Path to configuration file")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        setup_logging(config)
        logging.info("Trait-Fuzzer started with config: %s", args.config)
        
        # Initialize components
        compiler = RustCompiler(timeout=config["fuzzer"]["max_time_per_case_sec"])
        mutator_pool = MutatorPool(config)
        llm_connector = LLMConnector(config)
        
        # LLM Agents
        extractor = ExtractorAgent(llm_connector)
        injector = InjectorAgent(llm_connector)
        revision = RevisionAgent(llm_connector)

        # Seeds
        seeds_dir = Path(config["paths"]["seeds"])
        results_dir = Path(config["paths"]["results"])
        
        selector = SeedSelector(seeds_dir)
        if not selector.seeds:
            logging.warning("No seeds found in %s", seeds_dir)
            return

        logging.info("Found %d seeds", len(selector.seeds))
        
        # State tracking
        max_complexity = {"depth": 0, "cycles": 0}
        stall_counter = 0
        stall_threshold = config["fuzzer"]["stall_threshold"]

        # Config Parameters
        iterations = config["fuzzer"]["iterations"]
        mutations_per_seed = config["fuzzer"].get("mutations_per_seed", 1)
        seed_strategy = config["fuzzer"].get("seed_selection_strategy", "random")

        # Fuzzing Loop
        for i in range(iterations):
            # 1. Select Seed
            seed_path = selector.select(seed_strategy)
            
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
                            current_strategy = "llm_injection"
                            # Only warn once per stalled variant
                            if attempt == 0:
                                logging.warning(f"[{variant_id}] Stagnation detected (Stall: {stall_counter}). Forcing LLM Strategy.")
                            stall_counter = 0 
                        else:
                            current_strategy = mutator_pool.select_strategy()
                        
                        # Log strategy
                        suffix = f" (Retry {attempt})" if attempt > 0 else ""
                        logging.info(f"  -> Variant {j+1}{suffix}: Strategy {current_strategy}")

                        # 2. Perform Mutation
                        output_temp = Path(f"temp_mutant_{variant_id}.rs")
                        
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
                            bin_dir = Path("trait-fuzzer/mutation/mutation-AST") 
                            
                            cmd = [
                                "cargo", "run", "--quiet", "--", 
                                "--input", str(seed_path.absolute()), 
                                "--output", str(output_temp.absolute()), 
                                "--mode", rust_mode
                            ]
                            
                            proc = subprocess.run(
                                cmd, 
                                cwd=str(bin_dir.absolute()), 
                                check=True,         # Will raise CalledProcessError on non-zero exit
                                capture_output=True,
                                text=True
                            )
                            
                            # Check for No-Op
                            if "No mutation performed" in proc.stderr:
                                logging.info(f"    [No-Op] Strategy {current_strategy} inapplicable. Retrying...")
                                continue # Retry loop

                            # Success case
                            if output_temp.exists():
                                with open(output_temp, 'r') as f:
                                    mutated_content = f.read()
                                output_temp.unlink()
                                break # Mutated successfully
                            else:
                                logging.error(f"[{variant_id}] Rust mutation tool produced no output")
                                continue

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

                    result = compiler.compile(temp_src)
                    
                    # 4. Categorize
                    dest_dir = results_dir / result.status.value.lower()
                    dest_case = dest_dir / f"case_{variant_id}"
                    dest_case.mkdir(parents=True, exist_ok=True)
                    
                    shutil.copy(seed_path, dest_case / "before.rs")
                    shutil.copy(temp_src, dest_case / "after.rs")
                    
                    if temp_src.exists():
                        temp_src.unlink()

                    # 5. TTDN & Complexity
                    ttdn = TTDNModel()
                    ttdn.load_from_source(mutated_content)
                    complexity = ttdn.calculate_complexity()
                    
                    current_depth = complexity['depth']
                    current_cycles = complexity['cycles']
                    
                    if current_depth > max_complexity["depth"] or current_cycles > max_complexity["cycles"]:
                        logging.info(f"New Complexity Record! Depth: {current_depth}, Cycles: {current_cycles}")
                        max_complexity["depth"] = max(max_complexity["depth"], current_depth)
                        max_complexity["cycles"] = max(max_complexity["cycles"], current_cycles)
                        stall_counter = 0 
                    else:
                        stall_counter += 1
                    
                    with open(dest_case / "detail.log", 'w') as f:
                        f.write(f"Seed: {seed_path.name}\n")
                        f.write(f"Strategy: {current_strategy}\n")
                        f.write(f"Status: {result.status.value}\n")
                        f.write(f"TTDN Depth: {current_depth}\n")
                        f.write(f"TTDN Cycles: {current_cycles}\n")
                        f.write(f"Stdout:\n{result.stdout}\n")
                        f.write(f"Stderr:\n{result.stderr}\n")

                    logging.info(f"[{variant_id}] Result: {result.status.value} | Depth: {current_depth}")

                except Exception as e:
                    logging.error(f"[{variant_id}] Variant compilation/analysis failed: {e}")

        logging.info("Trait-Fuzzer finished.")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
