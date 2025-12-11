import hashlib
import json
import logging
from pathlib import Path
from collections import defaultdict

class Deduplicator:
    def __init__(self, results_dir: Path):
        self.results_dir = results_dir

    def deduplicate(self, category="crash"):
        """
        Scans the results directory for the given category (crash, error, hang),
        hashes their stderr/output, and groups duplicates.
        """
        category_dir = self.results_dir / category
        if not category_dir.exists():
            logging.warning(f"Category directory {category_dir} does not exist.")
            return {}

        hashes = defaultdict(list)
        
        for case_dir in category_dir.iterdir():
            if not case_dir.is_dir():
                continue
            
            detail_log = case_dir / "detail.log"
            if not detail_log.exists():
                continue
            
            # Simple deduplication strategy: Hash the Stderr content.
            # In a real compiler fuzzer, we might mask line numbers or temporary variables using regex.
            try:
                content = detail_log.read_text(encoding='utf-8')
                # Extract stderr part (simple parsing assumption)
                if "Stderr:" in content:
                    stderr_content = content.split("Stderr:")[1]
                else:
                    stderr_content = content # Fallback
                
                # Normalize: remove whitespace to avoid minor formatting diffs
                normalized = "".join(stderr_content.split())
                
                file_hash = hashlib.md5(normalized.encode('utf-8')).hexdigest()
                hashes[file_hash].append(case_dir.name)
                
            except Exception as e:
                logging.error(f"Failed to process {case_dir}: {e}")

        return hashes

    def save_report(self, unique_bugs, output_file="deduplication_report.json"):
        """
        Saves the deduplication report.
        """
        report = {
            "total_unique": len(unique_bugs),
            "groups": unique_bugs
        }
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=4)
        
        print(f"Deduplication complete. Found {len(unique_bugs)} unique signatures.")

if __name__ == "__main__":
    # Test run
    logging.basicConfig(level=logging.INFO)
    deduper = Deduplicator(Path("trait-fuzzer/results"))
    unique = deduper.deduplicate("error") # Test on errors since we have them
    deduper.save_report(unique)
