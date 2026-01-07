import argparse
import subprocess
import os
import sys

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
MUTATOR_BIN = os.path.join(PROJECT_ROOT, "mutation", "mutation-AST", "target", "debug", "mutation-ast")
DEFAULT_INPUT = os.path.join(BASE_DIR, "type-trait.rs")

def get_unique_filename(base_dir, prefix="mutated_output", extension=".rs"):
    """
    生成一个唯一的文件名，格式为: mutated_output_1.rs, mutated_output_2.rs...
    避免覆盖已存在的文件。
    """
    counter = 1
    while True:
        file_name = f"{prefix}_{counter}{extension}"
        full_path = os.path.join(base_dir, file_name)
        if not os.path.exists(full_path):
            return full_path, file_name
        counter += 1

def main():
    parser = argparse.ArgumentParser(description="Test a mutation operator on a Rust file.")
    # 这里为了方便，把 strategy 还是保留为位置参数，你习惯用位置参数
    parser.add_argument("strategy", help="Name of the mutation strategy (e.g., bin_op_flip)")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Path to input Rust file")
    
    args = parser.parse_args()

    # 1. 检查 Mutator 二进制文件是否存在
    if not os.path.exists(MUTATOR_BIN):
        print(f"Error: Mutation binary not found at {MUTATOR_BIN}")
        print("Please build it using 'cargo build' in the mutation-AST directory.")
        sys.exit(1)

    # 2. 检查输入文件是否存在
    if not os.path.exists(args.input):
        print(f"Error: Input file not found at {args.input}")
        sys.exit(1)

    # 3. 获取唯一的输出路径（带编号）
    output_path, output_filename = get_unique_filename(BASE_DIR)

    print(f"--- Testing Strategy: {args.strategy} ---")
    print(f"Input:  {args.input}")
    print(f"Output: {output_path}")  # 打印将要生成的文件名
    
    cmd = [
        MUTATOR_BIN,
        "--input", args.input,
        "--output", output_path,  # 使用动态生成的路径
        "--mode", args.strategy
    ]

    try:
        # 运行 Rust 工具
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("Mutation execution successful.")
        
        # 检查文件是否真的生成了
        if os.path.exists(output_path):
            print(f"\n=== Content of {output_filename} ===")
            with open(output_path, "r") as f:
                content = f.read()
                # 简单的行号显示
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    print(f"{i+1:3}: {line}")
            print("============================\n")
            
            print(f"[Success] Saved to: {output_filename}")
        else:
            print("Error: The mutation tool finished successfully but the output file was not created.")

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