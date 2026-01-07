import os
import glob
import sys

def main():
    # 获取脚本所在的目录 (确保只清理当前文件夹)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 定义匹配模式：mutated_output_ 开头，.rs 结尾
    pattern = os.path.join(base_dir, "mutated_output_*.rs")
    
    # 查找所有匹配的文件
    files = glob.glob(pattern)
    
    print(f"--- 正在扫描目录: {base_dir} ---")
    
    if not files:
        print("未找到任何 'mutated_output_*.rs' 文件，无需清理。")
        return

    print(f"发现 {len(files)} 个文件，准备删除...")
    
    deleted_count = 0
    for file_path in files:
        try:
            # 获取文件名用于显示
            file_name = os.path.basename(file_path)
            os.remove(file_path)
            print(f" [已删除] {file_name}")
            deleted_count += 1
        except OSError as e:
            print(f" [删除失败] {file_name}: {e}")

    print("-" * 30)
    print(f"清理完成！共删除了 {deleted_count} 个文件。")

if __name__ == "__main__":
    main()