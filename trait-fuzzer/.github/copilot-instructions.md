# Copilot Instructions for trait-fuzzer

## Project Overview
- **trait-fuzzer** is a Rust trait system fuzzer, orchestrated by Python scripts and extensible mutation engines.
- The core workflow is: select a seed, mutate it (AST/LLM), compile/test, and triage results.
- Major directories:
  - `mutation/`: Mutation logic, including AST-based and LLM-based mutators.
  - `results/`: Stores categorized outputs (crash, hang, miscompilation, etc.).
  - `seeds/`: Input Rust code samples for mutation.
  - `utils/`: Compiler and helper utilities.
  - `logs/`: Fuzzer and run logs.

## Architecture & Patterns
- **Mutation Pipeline**: All mutators follow a `Collect -> Select -> Mutate` pattern, managed by the `Mutator` trait (see `mutation/mutation-AST/ADDING_NEW_MUTATOR.md`).
- **Strategy Selection**: `MutatorPool` (Python) probabilistically selects mutation strategies and sub-strategies, configurable via `config.json`.
- **Extensibility**: To add a new mutator, implement the Collector/Applier/Mutator pattern and register in the pool.
- **Result Organization**: Each run's output is stored in a structured directory tree under `results/` by type and case.

## Developer Workflows
- **Run Fuzzer**: `python3 main.py --config config.json` (see `main.py` for CLI options).
- **Clean Results**: `python3 clean.py` or use `clean_directory()` for targeted cleanup.
- **Probe Compilation**: Use `probe.sh <file.rs>` to profile/validate a Rust file in isolation.
- **Config**: Tuning is via `config.json` (mutation weights, compiler flags, paths, etc.).

## Project-Specific Conventions
- Mutators are organized by type (structural, injection, LLM) and follow strict interface patterns.
- All logs and results are timestamped and stored under `logs/` and `results/`.
- Fuzzer supports both stable and nightly Rust, with optional next-solver flag.
- New mutators should be documented in `mutation/mutation-AST/ADDING_NEW_MUTATOR.md`.

## Integration Points
- External tools: `rustc`, `summarize` (for profiling), Python 3, and optionally LLM APIs.
- All mutation and compilation logic is orchestrated via Python, but mutator logic can be in Rust.

## Key Files
- `main.py`: Fuzzer entry point and orchestration logic.
- `mutation/mutator_pool.py`: Strategy selection and mutator management.
- `mutation/mutation-AST/ADDING_NEW_MUTATOR.md`: Guide for adding new mutators.
- `probe.sh`: Standalone Rust file probe and profiling script.
- `config.json`: All runtime and mutation configuration.

---

For unclear workflows or missing conventions, check the above files or ask for clarification. Please suggest improvements if you find gaps in these instructions.
