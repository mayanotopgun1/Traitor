import shutil
import os
import argparse
from pathlib import Path

def clean_directory(path):
    path = Path(path)
    if path.exists():
        for item in path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        print(f"Cleaned {path}")
    else:
        print(f"Directory {path} does not exist")

def main():
    parser = argparse.ArgumentParser(description="Clean Trait-Fuzzer results")
    parser.add_argument("--all", action="store_true", help="Clean all results and logs")
    args = parser.parse_args()

    base_dir = Path(__file__).parent
    
    clean_directory(base_dir / "results" / "success")
    clean_directory(base_dir / "results" / "error")
    clean_directory(base_dir / "results" / "hang")
    clean_directory(base_dir / "results" / "crash")
    
    if args.all:
        clean_directory(base_dir / "logs")
        
    # Clean root artifacts
    project_root = base_dir.parent
    for ext in ["*.exe", "*.pdb", "*.rlib", "temp_*.rs"]:
        for f in project_root.glob(ext):
            try:
                f.unlink()
                print(f"Removed {f.name}")
            except Exception as e:
                print(f"Failed to remove {f.name}: {e}")

if __name__ == "__main__":
    main()
