
import argparse
import subprocess
import shutil
import sys
import os
from pathlib import Path
import tempfile

# Embedded test case from lifetime_test.rs
TEST_CONTENT = r"""fn simple(x: i32, y: f64) {}

struct Foo;
impl Foo {
    fn method(&self, z: i32) {}
}

trait Bar {
    fn bar(&self);
}

impl Bar for Foo {
    fn bar(&self) {}
}
"""

def main():
    parser = argparse.ArgumentParser(description="Test Mutation 4 (LifetimeMutator).")
    parser.add_argument("--index", type=int, default=None, help="Force specific mutation index")
    
    args = parser.parse_args()
    
    # Create temp seed file
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".rs") as tmp_seed:
        tmp_seed.write(TEST_CONTENT)
        seed_path = Path(tmp_seed.name)
        
    print(f"Created temp seed at {seed_path} with content:\n---\n{TEST_CONTENT}---")
    
    # Locate mutation-AST binary logic
    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent # Traitor/trait-fuzzer
    mutation_crate = project_root / "mutation" / "mutation-AST"
    
    if not mutation_crate.exists():
        print(f"Error: Mutation crate not found at {mutation_crate}")
        try:
            os.remove(seed_path)
        except: pass
        sys.exit(1)
        
    # Use a temp file for output
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".rs") as tmp_out:
        output_path = Path(tmp_out.name)
        
    try:
        # Build cargo command
        cargo_cmd = [
            "cargo", "run", "--quiet", "--bin", "mutation-ast", "--",
            "--input", str(seed_path),
            "--output", str(output_path),
            "--mode", "lifetime_obfuscation"
        ]
        
        if args.index is not None:
            cargo_cmd.extend(["--index", str(args.index)])
            
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
            print("Mutation skipped (No valid mutation points found or coin flip failed).")
            print("Stderr info:", result.stderr)
 
        # Show diff or content
        print("\n=== Mutated Content Preview ===")
        mutated_content = output_path.read_text("utf-8")
        print(mutated_content)
        print("===============================\n")
        
    finally:
        if seed_path.exists():
            os.remove(seed_path)
        if output_path.exists():
            os.remove(output_path)

if __name__ == "__main__":
    main()
