#!/usr/bin/env python3
"""
CSV Regeneration Service - 6-PASS Architecture 2.0 (Modular Edition)

PRECACHE + PASS 1-6 system with each PASS in separate module.

Reference: REGEN_CSV_ARCHITECTURE.md
"""

import csv
import sys
from pathlib import Path

from settings_manager import SettingsManager
from logger import Logger
from fb2_author_extractor import FB2AuthorExtractor

from precache import Precache
from passes import (
    Pass1ReadFiles,
    Pass2Filename,
    Pass2Fallback,
    Pass3Normalize,
    Pass4Consensus,
    Pass5Conversions,
    Pass6Abbreviations,
)


class RegenCSVService:
    """Service for CSV regeneration using 6-PASS architecture."""
    
    def __init__(self, config_path: str = 'config.json'):
        """Initialize the service.
        
        Args:
            config_path: Path to config.json
        """
        self.config_path = Path(config_path)
        self.settings = SettingsManager(config_path)
        self.logger = Logger()
        self.extractor = FB2AuthorExtractor(config_path)
        
        # Working directory (where FB2 files are scanned from)
        self.work_dir = Path(self.settings.get_last_scan_path())
        self.folder_parse_limit = self.settings.get_folder_parse_limit()
        
        # Records list
        self.records = []
        
        # Author folder cache from PRECACHE
        self.author_folder_cache = {}
        
        # CSV output path - ALWAYS in project directory
        self.project_dir = Path(__file__).parent
        self.output_csv = self.project_dir / "regen.csv"
    
    def regenerate(self) -> bool:
        """Execute full CSV regeneration pipeline.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            print("\n" + "="*80)
            print("  CSV REGENERATION - 6-PASS SYSTEM (Modular)")
            print(f"  Work folder: {self.work_dir}\n")
            print("="*80 + "\n")
            
            self.logger.log("=== Starting CSV regeneration ===")
            
            # ===== PRECACHE =====
            precache = Precache(self.work_dir, self.settings, self.logger, 
                               self.folder_parse_limit)
            self.author_folder_cache = precache.execute()
            self.logger.log("[OK] Author folder hierarchy cached")
            
            # ===== PASS 1 =====
            pass1 = Pass1ReadFiles(self.work_dir, self.author_folder_cache,
                                  self.extractor, self.logger, 
                                  self.folder_parse_limit)
            self.records = pass1.execute()
            
            if not self.records:
                self.logger.log("[X] No FB2 files found")
                return False
            
            self.logger.log(f"[OK] PASS 1: Read {len(self.records)} files")
            
            # ===== PASS 2 =====
            pass2 = Pass2Filename(self.settings, self.logger, self.work_dir,
                                male_names=precache.male_names,
                                female_names=precache.female_names)
            pass2.execute(self.records)
            self.logger.log("[OK] PASS 2: Authors extracted from filenames")
            
            # ===== PASS 2 Fallback =====
            pass2_fallback = Pass2Fallback(self.logger)
            pass2_fallback.execute(self.records)
            self.logger.log("[OK] PASS 2 Fallback: Metadata applied")
            
            # ===== PASS 3 =====
            pass3 = Pass3Normalize(self.logger)
            pass3.execute(self.records)
            self.logger.log("[OK] PASS 3: Authors normalized")
            
            # ===== PASS 4 =====
            pass4 = Pass4Consensus(self.logger)
            pass4.execute(self.records)
            self.logger.log("[OK] PASS 4: Consensus applied")
            
            # ===== PASS 5 =====
            pass5 = Pass5Conversions(self.logger)
            pass5.execute(self.records)
            self.logger.log("[OK] PASS 5: Conversions re-applied")
            
            # ===== PASS 6 =====
            pass6 = Pass6Abbreviations(self.logger)
            pass6.execute(self.records)
            self.logger.log("[OK] PASS 6: Abbreviations expanded")
            
            # ===== Save CSV =====
            self._save_csv()
            self.logger.log(f"[OK] CSV saved to {self.output_csv}")
            
            print(f"\n✅ CSV regeneration completed successfully!")
            print(f"   Output: {self.output_csv}")
            print(f"   Records: {len(self.records)}")
            print("="*80 + "\n")
            
            return True
            
        except Exception as e:
            self.logger.log(f"[ERROR] CSV regeneration failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _save_csv(self) -> None:
        """Save records to CSV file."""
        
        # Sort by file_path
        self.records.sort(key=lambda r: r.file_path)
        
        # Write to CSV
        with open(self.output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write header
            writer.writerow([
                'file_path',
                'metadata_authors',
                'proposed_author',
                'author_source',
                'metadata_series',
                'proposed_series',
                'series_source',
                'file_title'
            ])
            
            # Write data
            for record in self.records:
                writer.writerow([
                    record.file_path,
                    record.metadata_authors,
                    record.proposed_author,
                    record.author_source,
                    record.metadata_series,
                    record.proposed_series,
                    record.series_source,
                    record.file_title
                ])


def main():
    """Main entry point."""
    config_path = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    
    service = RegenCSVService(config_path)
    success = service.regenerate()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
