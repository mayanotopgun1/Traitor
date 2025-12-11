import argparse
import subprocess
import os
import sys
import shutil

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
MUTATOR_BIN = os.path.join(PROJECT_ROOT, "mutation", "mutation-AST", "target", "debug", "mutation-ast.exe")
DEFAULT_INPUT = os.path.join(BASE_DIR, "type-trait.rs")
TEMP_OUTPUT = os.path.join(BASE_DIR, "mutated_output.rs")

def main():
    parser = argparse.ArgumentParser(description="Test a mutation operator on a Rust file.")
    parser.add_argument("strategy", help="Name of the mutation strategy (e.g., bin_op_flip)")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Path to input Rust file")
    
    args = parser.parse_args()

    if not os.path.exists(MUTATOR_BIN):
        print(f"Error: Mutation binary not found at {MUTATOR_BIN}")
        print("Please build it using 'cargo build' in the mutation-AST directory.")
        sys.exit(1)

    if not os.path.exists(args.input):
        print(f"Error: Input file not found at {args.input}")
        sys.exit(1)

    print(f"--- Testing Strategy: {args.strategy} ---")
    print(f"Input: {args.input}")
    
    cmd = [
        MUTATOR_BIN,
        "--input", args.input,
        "--output", TEMP_OUTPUT,
        "--mode", args.strategy
    ]

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("Mutation execution successful.")
        
        if os.path.exists(TEMP_OUTPUT):
            print("\n=== Mutated Code Content ===")
            with open(TEMP_OUTPUT, "r") as f:
                content = f.read()
                # Simple syntax highlighting for console
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    print(f"{i+1:3}: {line}")
            print("============================\n")
            
            # Optional: Clean up
            # os.remove(TEMP_OUTPUT) 
        else:
            print("Error: Output file was not created.")

    except subprocess.CalledProcessError as e:
        print(f"Mutation failed with exit code {e.returncode}")
        print("STDERR:")
        print(e.stderr)
        print("STDOUT:")
        print(e.stdout)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
