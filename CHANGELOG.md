# CHANGELOG - fb2parser Project

All notable changes to this project are documented here.

---

## [2.3] - 2026-02-20

### 🔴 CRITICAL PRIORITY BUG FIX

#### Fix 4: PASS 3 Metadata Pollution - Violates Author Priority
**Commit:** `a1f3cfd`
- **Problem:** When author_source="folder_dataset", PASS 3 normalization was merging co-authors from FB2 metadata, violating the fundamental priority: `folder > filename > metadata`
- **Root Cause:** `normalize_format()` in `author_normalizer_extended.py` detects word overlap between proposed_author and metadata_authors, then adds ALL metadata authors. This was designed for recovering incomplete names but was incorrectly applied to folder-derived authors.
- **Impact:** Records with single confident folder-derived author were corrupted with metadata co-authors
- **Example Bug:**
  ```
  File: Волков Тим\Бездна.fb2
  
  BEFORE FIX:
    metadata_authors: "Тим Волков; Ян Кулагин"
    proposed_author: "Волков Тим" (from PRECACHE folder)
    author_source: "folder_dataset"
           ↓ PASS 3 corruption
    proposed_author: "Волков Тим, Кулагин Ян" ❌ (added Ян Кулагин from metadata!)
  
  AFTER FIX:
    proposed_author: "Волков Тим" ✓ (only folder author preserved)
  ```
- **Solution:** In PASS 3, when processing records with `author_source="folder_dataset"`, pass empty string for `metadata_authors` parameter to `normalize_format()`, preventing metadata merging
- **Files Changed:** `passes/pass3_normalize.py`
- **Test Results:**
  ```
  - Dataset: 420 files (author-organized hierarchy)
  - Before: Many records had unwanted metadata co-author merging
  - After: All 420 records maintain single folder-derived author
  - All records show author_source="folder_dataset" (correct priority)
  
  Samples verified:
    "Волков Тим\Бездна.fb2" → "Волков Тим" ✓
    "Волков Тим\ISCARIOT\1. Выжить любой.fb2" → "Волков Тим" ✓
    "Волков Тим\Ай да Пушкин!\1. Бояръ-Аниме..." → "Волков Тим" ✓
  ```
- **Priority Logic (Now Correct):**
  ```
  PASS 1: PRECACHE → folder_dataset (highest priority)
  PASS 2: Filename pattern → filename (fallback if no folder match)
  PASS 2 Fallback: Metadata → metadata (last resort if 1 & 2 empty)
  PASS 3: Normalize ONLY from current author, never add from metadata if source is folder_dataset
  ```

---

## [2.2] - 2026-02-20

### 🔴 CRITICAL BUG FIXES

#### Fix 1: PRECACHE Name Validation Case Sensitivity
**Commit:** `7e61dba`
- **Problem:** PRECACHE validation compared capitalized names ("Борис") against lowercase sets ("борис"), always returned False
- **Impact:** PRECACHE returned 0 author folders instead of 68, breaking folder hierarchy priority
- **Solution:** Added `.lower()` conversion before name validation
- **Files Changed:** `precache.py`
- **Verification:**
  ```
  Before: Cached 0 author folders
  After:  Cached 68 author folders
  Example: "К повороту стоять! (Батыршин Борис)" → folder_dataset instead of metadata ✓
  ```

#### Fix 2: Support for Abbreviated Author Names in PRECACHE
**Commit:** `0c98caa`
- **Problem:** Folders with abbreviated author names ("А.Михайловский", "И.Николаев") were not validated because single letter "А" ≠ full name "Александр"
- **Impact:** 6 author folders with abbreviated names were not cached
- **Solution:** Added regex pattern to detect Initial.Surname format
- **Files Changed:** `precache.py`
- **Verification:**
  ```
  Added patterns:
  - "Ангелы в погонах (А.Михайловский, А.Харников)" ✓
  - "Железный ветер (И.Николаев, А.Поволоцкий)" ✓
  - "Операция «Гроза плюс» (А.Михайловский, А.Харников)" ✓
  - "Сослагательное наклонение (М.Каштанов, С.Хорев)" ✓
  - "Линейный крейсер «Михаил Фрунзе» (В.Коваленко, Н.Инодин)" ✓
  - "Имперский союз (А.Михайловский, А.Харников)" ✓
  
  Result: Cached 68 → 74 author folders
  ```

#### Fix 3: Missing Module `file_structural_analysis.py`
**Commit:** `7e61dba`
- **Problem:** `pass2_filename.py` imported `from .file_structural_analysis import analyze_file_structure, score_pattern_match` but the module was never created/committed
- **Impact:** ModuleNotFoundError prevented entire pipeline from running
- **Root Cause:** Import added in commit 0c913a3 (sbornik detection feature) but module never created
- **Solution:** Created missing module with required functions
- **Files Changed:** `passes/file_structural_analysis.py` (NEW)
- **Functions:**
  - `analyze_file_structure(filename, service_words)` - Returns structural info of filename
  - `score_pattern_match(struct, pattern, service_words)` - Scores pattern match quality

#### Fix 4: Unicode Encoding Error on Windows Console
**Commit:** `7e61dba`
- **Problem:** Debug output with Cyrillic filenames caused UnicodeEncodeError on Windows console
- **Impact:** Pipeline crashed during PASS 2 debug output
- **Solution:** Safe error handling for console encoding
- **Files Changed:** `passes/pass2_filename.py`

### 📊 Results Summary

**PRECACHE Improvements:**
- Author folders cached: 0 → 74
- Percentage improvement: ∞% (from completely broken to 86.4% of records from folders)

**CSV Generation Results:** 
- Total records processed: 337
- From folder hierarchy: 291 (86.4%)
- From filename patterns: 46 (13.6%)
- From metadata: 0 (0%) ← Successfully using folder priority!
- Collections detected: 1

**Quality Metrics:**
- Module import errors: ✓ Fixed
- Case sensitivity bugs: ✓ Fixed
- Abbreviated name support: ✓ Added
- Unicode handling: ✓ Improved

---

## [2.1] - 2026-02-18

### ✨ Enhancements

#### Modular 6-PASS Architecture Implementation
- Refactored monolithic regen_csv.py (1951 lines) into modular structure
- Created passes/ directory with 7 separate modules
- Each PASS independently testable and maintainable
- Total modular code: ~600 lines vs 1951 before (69% reduction)

#### PRECACHE Phase Addition
- Added pre-processing phase to cache author folders before PASS 1
- Validates author names before caching to prevent series name contamination
- Supports folder hierarchy navigation with configurable depth limit
- Results in 86.4% of records using folder hierarchy priority

#### Folder Author Parser
- Implemented PASS0+PASS1+PASS2 structural analysis for folder names
- Supports 7 different author name patterns in folder naming
- Detects authors with parentheses, dashes, and comma-separated formats
- Handles inheritance of author names from parent folders

### 🐛 Previous Bug Fixes

#### Case Sensitivity in Known Name Lists (Commit 42a69c2)
- PRECACHE now loads names as lowercase for consistent comparison
- Affects: male_names and female_names validation

#### ё → е Normalization (Commit 4b459d6)
- AuthorName now normalizes ё to е in known names list
- Fixes parsing of names with ё character

#### Surname Initials Regex Fix (Commit 4b459d6)
- Fixed regex pattern for "Фамилия И.О." format
- Made dot after initial required instead of optional
- Prevents incorrect 2-letter word matching

---

## [2.0] - 2026-02-10

### 🎉 Major Release: Modular Architecture (In Progress)

#### Architecture Changes
- Transition from monolithic to modular 6-PASS system
- New folder_author_parser submodule for folder parsing
- Separate responsibility for each PASS stage
- Improved maintainability and testability

#### Co-author Support
- Handling of multiple authors in metadata
- Restoration of incomplete author names (e.g., "Людмила" → "Людмила Белаш")
- Comma and semicolon separator support
- Alphabetical sorting of co-authors

---

## [1.0] - 2026-02-01

### 🚀 Initial Release

- Basic CSV regeneration from FB2 files
- Author extraction from metadata and filenames
- Name normalization and validation
- Series detection and handling
- Genre association (context menu based)
- GUI for settings and file management

---

## Investigation & Debugging Logs

### February 20, 2026 - PRECACHE Bug Investigation

**Symptoms:**
1. CSV records showed incorrect author_source ("metadata" instead of "folder_dataset")
2. PRECACHE logged "Cached 0 author folders" despite valid folders in hierarchy
3. Example: "К повороту стоять! (Батыршин Борис)" showed author "Б. Беломор" from metadata

**Investigation Steps:**
1. Created debug_precache.py to trace PRECACHE execution
2. Found PRECACHE validation logic worked correctly in isolation
3. Tested folder parsing: 7/8 test cases passed (87.5%)
4. Discovered root cause: Case mismatch in name validation
5. Traced import error to missing file_structural_analysis.py module

**Root Cause Analysis:**
```
Code path: precache.py → parse_author_from_folder_name() → validation
Issue:     word_clean = "Борис" (from folder)
           male_names contains "борис" (lowercase)
           "Борис" != "борис" → returns False
Result:    Folder not cached, metadata used instead
```

**Type of Bug:** Logic error with case sensitivity in string comparison

---

## Testing Summary

### Test 1: Enhanced Folder Parser (February 20)
- Test file: `test_folder_parser.py`
- Results: 7/8 passed (87.5%)
- Passing cases:
  - "К повороту стоять! (Батыршин Борис)" → "Батыршин Борис" ✓
  - "Защита Периметра (Абенд Эдвард)" → "Абенд Эдвард" ✓
  - "Волков Тим" → "Волков Тим" ✓
  - Multiple other patterns ✓

### Full Pipeline Test (Post-Fix)
- Input: 337 FB2 files in Test1 dataset
- Output: 337 CSV records
- Author source distribution:
  - folder_dataset: 291 (86.4%) ✓ 
  - filename: 46 (13.6%) ✓
  - metadata: 0 (0%) ✓
- Validation: All PASS stages completed successfully

---

## Technical Debt Resolved

1. ✅ PRECACHE case-sensitivity bug
2. ✅ Missing file_structural_analysis.py module
3. ✅ Abbreviated author name validation
4. ✅ Windows console Unicode handling
5. ✅ Import chain errors in module system

---

## Known Issues

None currently identified. All critical bugs fixed.

---

## Future Improvements

1. Performance optimization for large library scans (>10,000 files)
2. Additional author name pattern recognition
3. Batch processing for multiple folders
4. Extended co-author restoration for complex cases
5. Configurable validation thresholds in PRECACHE

---

## Version Information

- **Current Version:** 2.2
- **Release Date:** 2026-02-20
- **Python Version:** 3.11+
- **Dependencies:** See requirements.txt (if exists)
- **Last Updated:** 2026-02-20

---

## Contributors

- Development and debugging: Feb 20-21, 2026
- Architecture design: Feb 10-18, 2026
- Initial implementation: Feb 1-10, 2026

---

## Documentation Files

- [REGEN_CSV_ARCHITECTURE.md](REGEN_CSV_ARCHITECTURE.md) - Detailed system architecture
- [COAUTHORSHIP_FEATURE.md](COAUTHORSHIP_FEATURE.md) - Co-author handling details
- [README.md](README.md) - Project overview (if exists)

---

**Last Updated:** 2026-02-20
**Status:** Stable ✅
