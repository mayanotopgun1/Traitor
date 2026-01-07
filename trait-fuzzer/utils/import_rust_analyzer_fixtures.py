import argparse
import shutil
from pathlib import Path


def _is_internal_only_seed_text(head: str) -> bool:
    internal_features = (
        "rustc_attrs",
        "lang_items",
        "intrinsics",
        "core_intrinsics",
        "rustc_private",
    )
    if "#![feature(" in head and any(f in head for f in internal_features):
        return True

    internal_attr_markers = (
        "#[rustc_",
        "#![rustc_",
        "#[lang =",
        "#![no_core]",
        "#![rustc_attrs]",
    )
    if any(m in head for m in internal_attr_markers):
        return True

    if 'extern "rust-intrinsic"' in head:
        return True

    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Import rust-analyzer fixtures/test_data .rs files into seeds/")
    parser.add_argument("--ra-root", required=True, help="Path to rust-analyzer repository root")
    parser.add_argument(
        "--out",
        default="seeds/rust-analyzer-fixtures",
        help="Output directory under trait-fuzzer (default: seeds/rust-analyzer-fixtures)",
    )
    parser.add_argument(
        "--include-non-test-data",
        action="store_true",
        help="Also include .rs outside test_data/ (not recommended; may include harness code)",
    )
    parser.add_argument(
        "--skip-internal-only",
        action="store_true",
        help="Skip seeds that look like internal-only rustc feature usage",
    )
    args = parser.parse_args()

    ra_root = Path(args.ra_root).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not ra_root.exists() or not ra_root.is_dir():
        raise SystemExit(f"Invalid --ra-root: {ra_root}")

    # Prefer `**/test_data/**/*.rs`: usually single-file snippets.
    rs_files = list(ra_root.rglob("test_data/**/*.rs"))
    if args.include_non_test_data:
        rs_files += list(ra_root.rglob("*.rs"))

    # De-dup
    rs_files = list(dict.fromkeys(rs_files))

    copied = 0
    skipped_internal = 0
    skipped_nonfile = 0

    for src in rs_files:
        if not src.is_file():
            skipped_nonfile += 1
            continue

        # Keep stable relative layout under output dir
        try:
            rel = src.relative_to(ra_root)
        except ValueError:
            rel = Path(src.name)

        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        if args.skip_internal_only:
            try:
                head = src.read_text(encoding="utf-8", errors="ignore")[:8000]
            except Exception:
                head = ""
            if _is_internal_only_seed_text(head):
                skipped_internal += 1
                continue

        shutil.copy2(src, dst)
        copied += 1

    print(f"Imported {copied} .rs files into {out_dir}")
    if args.skip_internal_only:
        print(f"Skipped internal-only-like seeds: {skipped_internal}")
    if skipped_nonfile:
        print(f"Skipped non-files: {skipped_nonfile}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
