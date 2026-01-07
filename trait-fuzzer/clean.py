import shutil
import os
import argparse
from pathlib import Path


def remove_files_by_patterns(directory: Path, patterns):
    directory = Path(directory)
    if not directory.exists():
        return

    for pat in patterns:
        for f in directory.glob(pat):
            if not f.is_file():
                continue
            try:
                f.unlink()
                print(f"Removed {f.relative_to(directory)}")
            except Exception as e:
                print(f"Failed to remove {f}: {e}")

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
    clean_directory(base_dir / "results_night" / "success")
    clean_directory(base_dir / "results_night" / "error")
    
    if args.all:
        clean_directory(base_dir / "logs")
        
    # Clean fuzzer working-directory artifacts.
    # These are produced by rustc and/or the mutation pipeline when runs are interrupted.
    # Examples:
    # - temp_iter_35_var_3 (binary)
    # - libtemp_iter_32_var_4.rlib
    remove_files_by_patterns(
        base_dir,
        patterns=[
            "libtemp*.rlib",
            "libtemp*.rmeta",
            "libtemp*.d",
        ],
    )

    # Remove files or directories in the trait-fuzzer directory that start with 'temp'
    for item in base_dir.iterdir():
        if item.name.startswith("temp"):
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                    print(f"Removed directory {item.name}")
                else:
                    item.unlink()
                    print(f"Removed file {item.name}")
            except Exception as e:
                print(f"Failed to remove {item.name}: {e}")

    # Legacy: also clean a small set of common artifacts in the repo root.
    # Keep it conservative to avoid deleting unrelated build outputs.
    project_root = base_dir.parent
    remove_files_by_patterns(project_root, patterns=["temp_*.rs", "libtemp*.rlib"])

if __name__ == "__main__":
    main()
