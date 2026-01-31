
import argparse
import subprocess
import shutil
import sys
import os
from pathlib import Path
import tempfile

def main():
    parser = argparse.ArgumentParser(description="Test Mutation 1 (AddTrait/AddImpl) with specific settings.")
    parser.add_argument("--selected", required=True, help="Path to the seed file")
    parser.add_argument("--addwhat", required=True, choices=["addtrait", "addimpl"], help="Mutation type")
    parser.add_argument("--mode", type=int, default=None, help="Trait pattern index (if addtrait). 0=Basic, 1=Assoc, 2=GAT, 3=AssocConst")
    
    args = parser.parse_args()
    
    seed_path = Path(args.selected).resolve()
    if not seed_path.exists():
        print(f"Error: Seed file {seed_path} not found.")
        sys.exit(1)
        
    cmd_mode = ""
    if args.addwhat == "addtrait":
        cmd_mode = "add_trait"
    elif args.addwhat == "addimpl":
        cmd_mode = "add_impl"
        
    print(f"Testing {cmd_mode} on {seed_path.name}...")
    
    # Locate mutation-AST binary logic
    # Assuming this script is in Traitor/trait-fuzzer/test/
    # The mutation crate is in ../mutation/mutation-AST/
    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent # Traitor/trait-fuzzer
    mutation_crate = project_root / "mutation" / "mutation-AST"
    
    if not mutation_crate.exists():
        print(f"Error: Mutation crate not found at {mutation_crate}")
        sys.exit(1)
        
    # Use a temp file for output
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".rs") as tmp:
        output_path = Path(tmp.name)
        
    try:
        # Build cargo command
        cargo_cmd = [
            "cargo", "run", "--quiet", "--bin", "mutation-ast", "--",
            "--input", str(seed_path),
            "--output", str(output_path),
            "--mode", cmd_mode
        ]
        
        if args.mode is not None:
            cargo_cmd.extend(["--pattern-index", str(args.mode)])
            
        print(f"Running: {' '.join(cargo_cmd)}")
        
        # Execute
        result = subprocess.run(
            cargo_cmd,
            cwd=str(mutation_crate),
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print("Mutation failed (Process Error)!")
            print("Stderr:", result.stderr)
            print("Stdout:", result.stdout)
            sys.exit(1)
            
        if "Mutation successful." in result.stderr:
            print("Mutation successful!")
        else:
            print("Mutation skipped (No valid mutation points found).")
            print("Stderr info:", result.stderr)

        
        # Show diff or content
        print("\n=== Mutated Content Preview ===")
        mutated_content = output_path.read_text("utf-8")
        print(mutated_content)
        print("===============================\n")
        
    finally:
        if output_path.exists():
            os.remove(output_path)

if __name__ == "__main__":
    main()
