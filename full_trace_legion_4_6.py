#!/usr/bin/env python3
"""Full trace through all passes for Legion 4-6 file."""

from pathlib import Path
from passes.pass1_read_files import Pass1ReadFiles
from passes.pass2_filename import Pass2Filename
from passes.pass2_fallback import Pass2Fallback
from passes.pass3_normalize import Pass3Normalize
from passes.pass4_consensus import Pass4Consensus
from passes.pass5_conversions import Pass5Conversions
from passes.pass6_abbreviations import Pass6Abbreviations
from precache import Precache
from fb2_author_extractor import FB2AuthorExtractor
from settings_manager import SettingsManager
from logger import Logger

work_dir = Path(r"C:\Users\dmitriy.murov\Downloads\TriblerDownloads\Test1")
settings = SettingsManager('config.json')
logger = Logger()
extractor = FB2AuthorExtractor('config.json')

# PRECACHE
precache = Precache(work_dir, settings, logger, settings.get_folder_parse_limit())
author_folder_cache = precache.execute()

# PASS 1
pass1 = Pass1ReadFiles(work_dir, author_folder_cache, extractor, logger, settings.get_folder_parse_limit())
records = pass1.execute()

# Find only Legion 4-6
records = [r for r in records if "Живой, Прозоров. Легион (Легион 4-6)" in r.file_path]

if records:
    record = records[0]
    
    print("=" * 100)
    print(f"TRACING: {Path(record.file_path).name}")
    print("=" * 100)
    
    print(f"\nInitial (from PASS 1):")
    print(f"  proposed_author: '{record.proposed_author}'")
    print(f"  author_source: '{record.author_source}'")
    
    # PASS 2
    pass2 = Pass2Filename(settings, logger, work_dir, male_names=precache.male_names, female_names=precache.female_names)
    pass2.execute([record])
    print(f"\nAfter PASS 2:")
    print(f"  proposed_author: '{record.proposed_author}'")
    print(f"  author_source: '{record.author_source}'")
    
    # PASS 2 Fallback
    pass2_fallback = Pass2Fallback(logger)
    pass2_fallback.execute([record])
    print(f"\nAfter PASS 2 Fallback:")
    print(f"  proposed_author: '{record.proposed_author}'")
    
    # PASS 3
    pass3 = Pass3Normalize(logger)
    pass3.execute([record])
    print(f"\nAfter PASS 3:")
    print(f"  proposed_author: '{record.proposed_author}'")
    
    # PASS 4
    # Need to group with other records for consensus to work
    all_records = pass1.execute()  # Get all records for context
    pass4 = Pass4Consensus(logger)
    pass4.execute(all_records)
    # Find our record again
    our_record = [r for r in all_records if "Живой, Прозоров. Легион (Легион 4-6)" in r.file_path][0]
    print(f"\nAfter PASS 4:")
    print(f"  proposed_author: '{our_record.proposed_author}'")
    
    # PASS 5
    pass5 = Pass5Conversions(settings, logger)
    pass5.execute([our_record])
    print(f"\nAfter PASS 5:")
    print(f"  proposed_author: '{our_record.proposed_author}'")
    
    # PASS 6
    pass6 = Pass6Abbreviations(settings, logger)
    pass6.execute([our_record])
    print(f"\nAfter PASS 6:")
    print(f"  proposed_author: '{our_record.proposed_author}'")
    
    print(f"\n{'='*100}")
    print(f"FINAL: '{our_record.proposed_author}'")
    author_count = len([a for a in our_record.proposed_author.split(', ') if a.strip()])
    print(f"Author count: {author_count}")
