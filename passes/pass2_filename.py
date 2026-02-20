"""
PASS 2: Extract authors from file names.

Uses structural analysis to match filename against all known patterns
in config.json author_series_patterns_in_files, then extracts author
based on best pattern match.
"""

from typing import List, Optional
from pathlib import Path
from .file_structural_analysis import analyze_file_structure, score_pattern_match

try:
    from name_normalizer import validate_author_name
except ImportError:
    from ..name_normalizer import validate_author_name

try:
    from fb2_author_extractor import FB2AuthorExtractor
except ImportError:
    from ..fb2_author_extractor import FB2AuthorExtractor


class Pass2Filename:
    """PASS 2: Extract authors from filenames for records without folder_dataset."""
    
    # Words that indicate the extracted text is NOT an author name
    # IMPORTANT: Use COMPLETE meaningful keywords only, avoid words that are common surnames
    # e.g. "романов/романа/романы" is too dangerous (conflicts with surname "Романов")
    NON_AUTHOR_KEYWORDS = {
        'трилогия', 'дилогия', 'пенталогия', 'тетралогия',
        'сборник', 'авторский', 'авторская', 'авторское',
        'цикл', 'цикла', 'циклов',
        'серия', 'серии', 'сборка',
        'компиляция', 'сборка', 'сборки',
        # Removed: 'романы', 'романа', 'романов' - too common in surnames
        'книг', 'книга', 'книги',
        'издание', 'издания', 'переиздание',
    }
    
    def __init__(self, settings, logger, work_dir: Optional[Path] = None, male_names: set = None, female_names: set = None):
        """Initialize PASS 2.
        
        Args:
            settings: SettingsManager instance
            logger: Logger instance
            work_dir: Working directory with FB2 files (optional, for metadata validation)
            male_names: Set of known male names for author validation (optional)
            female_names: Set of known female names for author validation (optional)
        """
        self.settings = settings
        self.logger = logger
        self.work_dir = Path(work_dir) if work_dir else None
        self.service_words = settings.get_service_words() if hasattr(settings, 'get_service_words') else []
        self.male_names = male_names or set()
        self.female_names = female_names or set()
        self.patterns = self._load_patterns()
        # Author cache: maps abbreviated/partial names to full names
        # e.g., {"А. Живой" -> "Живой Алексей", "Живой" -> "Живой Алексей"}
        self.author_cache = {}
    
    def _load_patterns(self) -> List[dict]:
        """Load author_series_patterns_in_files from config."""
        try:
            return self.settings.get_author_series_patterns_in_files()
        except:
            return []
    
    def _extract_surname(self, author_name: str) -> str:
        """Extract surname from author name.
        
        Handles formats:
        - "Surname Name" -> "Surname"
        - "Name Surname" -> "Surname"  (if starts with lowercase, reverse order)
        - "Surname" -> "Surname"
        
        For Cyrillic names, typically surname comes first.
        
        Args:
            author_name: Full author name
            
        Returns:
            Surname or first word if unclear
        """
        if not author_name or not author_name.strip():
            return ""
        
        parts = author_name.strip().split()
        if not parts:
            return ""
        
        # For Cyrillic names, surname is typically first
        # Return first part as surname (most reliable)
        return parts[0]
    
    def _sort_coauthors_by_surname(self, authors_str: str) -> str:
        """Sort comma-separated authors by surname (alphabetically).
        
        Args:
            authors_str: Authors separated by ', '
            
        Returns:
            Authors sorted by surname, still separated by ', '
        """
        if not authors_str or ', ' not in authors_str:
            return authors_str
        
        authors = [a.strip() for a in authors_str.split(', ')]
        if len(authors) <= 1:
            return authors_str
        
        # Sort by surname (first word)
        try:
            sorted_authors = sorted(authors, key=lambda x: self._extract_surname(x).lower())
            return ', '.join(sorted_authors)
        except Exception as e:
            self.logger.log(f"[PASS 2] WARNING: Failed to sort co-authors '{authors_str}': {e}")
            return authors_str
    
    def _add_to_author_cache(self, extracted: str, expanded: str) -> None:
        """Add author mapping to cache.
        
        Args:
            extracted: Original extracted name (may be abbreviated)
            expanded: Full expanded name
        """
        if not extracted or not expanded:
            return
        
        extracted_lower = extracted.lower().strip()
        expanded_lower = expanded.lower().strip()
        
        # Only cache if they differ
        if extracted_lower != expanded_lower:
            self.author_cache[extracted_lower] = expanded
    
    def _build_author_cache_from_extraction(self, author_str: str) -> None:
        """Build cache from successfully extracted author(s).
        
        For each author name (even in co-author lists), cache the full name
        and also cache the surname alone for future abbreviation expansion.
        
        Examples:
        - "Живой Алексей" -> cache "живой алексей" and "живой"
        - "Живой Алексей, Прозоров Александр" -> cache both authors and surnames
        
        Args:
            author_str: Successfully extracted author string (may contain multiple authors)
        """
        if not author_str:
            return
        
        # Split by comma-space to handle co-authors
        authors = [a.strip() for a in author_str.split(', ')]
        
        for author in authors:
            if not author:
                continue
            
            author_lower = author.lower().strip()
            
            # Cache the full name
            self.author_cache[author_lower] = author
            
            # Also cache each word (surname, name) separately
            parts = author.split()
            for part in parts:
                if len(part) > 2:  # Skip very short parts (initials like "А.")
                    part_lower = part.lower()
                    # Don't override existing full-name entries
                    if part_lower not in self.author_cache:
                        self.author_cache[part_lower] = author
    
    def _validate_and_expand_author(self, extracted_author: str, fb2_path: Optional[Path]) -> str:
        """Validate and potentially expand author name using FB2 metadata and cache.
        
        Strategy:
        1. Check author cache first (compiled from previous files)
        2. If not in cache, try to expand from FB2 metadata
        3. Compare with FB2 metadata authors to find matching record
        4. If found with better form (fuller name), use and cache that instead
        
        Args:
            extracted_author: Author name extracted from filename
            fb2_path: Path to FB2 file for metadata validation
            
        Returns:
            Validated/expanded author name or original if not found
        """
        if not extracted_author:
            return extracted_author
        
        extracted_lower = extracted_author.lower().strip()
        
        # STEP 1: Check author cache first (knowledge from other files)
        if extracted_lower in self.author_cache:
            return self.author_cache[extracted_lower]
        
        # STEP 2: Try FB2 metadata if available
        if fb2_path and fb2_path.exists():
            try:
                # Extract authors from FB2 metadata
                extractor = FB2AuthorExtractor()
                fb2_authors_str = extractor._extract_all_authors_from_metadata(fb2_path)
                
                if fb2_authors_str:
                    # Parse FB2 authors (separated by '; ')
                    fb2_authors = [a.strip() for a in fb2_authors_str.split(';') if a.strip()]
                    
                    # Exact match - return as is
                    for fb2_author in fb2_authors:
                        if fb2_author.lower() == extracted_lower:
                            self._add_to_author_cache(extracted_author, fb2_author)
                            return fb2_author  # Return FB2 version (better normalization)
                    
                    # Partial match - check if extracted is substring of any FB2 author
                    # This handles cases like \"Демченко\" matching \"Демченко Антон\"
                    for fb2_author in fb2_authors:
                        fb2_lower = fb2_author.lower()
                        
                        # Check if extracted author is a word in FB2 author name
                        extracted_words = set(extracted_lower.split())
                        fb2_words = set(fb2_lower.split())
                        
                        # If all extracted words are in FB2 author, use the fuller FB2 version
                        if extracted_words and extracted_words.issubset(fb2_words):
                            self._add_to_author_cache(extracted_author, fb2_author)
                            return fb2_author  # Use fuller name from FB2
            
            except Exception as e:
                self.logger.log(f"[PASS 2] WARNING: Failed to validate author against FB2: {e}")
        
        # No match in cache or FB2, return original extraction
        return extracted_author
    
    def _looks_like_author_name(self, text: str) -> bool:
        """Check if text looks like an author name (structural validation).
        
        Args:
            text: Text to check
        
        Returns:
            True if looks like author name, False otherwise
        """
        if not text or len(text) < 2:
            return False
        
        # Check for trailing punctuation
        if text.endswith('.') or text.endswith(','):
            return False
        
        # Check for leading numbers - patterns like "1-3 Name" are not author names
        if text[0].isdigit():
            return False
        
        # Check if it starts with Cyrillic or Latin letter (required for author names)
        first_char = text[0]
        if not first_char.isalpha():
            return False
        
        # Check for non-author keywords - but only as WHOLE WORDS, not substrings
        # This prevents "Романов" from matching "романов" in "романы"
        text_lower = text.lower().strip()
        text_words = set(text_lower.split())
        
        for keyword in self.NON_AUTHOR_KEYWORDS:
            if keyword in text_words:
                return False
        
        # Check that it has at least one letter (not just numbers)
        has_letter = any(c.isalpha() for c in text)
        if not has_letter:
            return False
        
        # SBORNIK DETECTION: Verify extracted text looks like author name, not collection title
        # This prevents collection titles like "Боевая фантастика" from being extracted as authors
        # Strategy:
        # 1. Single word (just surname) → always allow (e.g., "Демченко")
        # 2. Multiple words → require at least one known first name (e.g., "Демченко Антон")
        # This way surnames like "Демченко" pass, but collection titles don't
        text_normalized = text.lower()
        text_words = text_normalized.split()
        
        if len(text_words) > 1:  # Multi-word - likely "FirstName LastName" or "Title Words"
            # Require at least one known first name to filter out collection titles
            if self.male_names or self.female_names:
                has_known_name = any(
                    word in self.male_names or word in self.female_names
                    for word in text_words
                )
                if not has_known_name:
                    return False  # Not an author name - likely a collection title
        # Single word always passes (it's a surname, which is valid author name)
        
        return True
    
    def execute(self, records: List) -> None:
        """Execute PASS 2: Extract authors from filenames.
        
        PRIORITY: FILE -> METADATA (never the other way!)
        
        For each record:
        1. If author_source == "folder_dataset" → skip (already has from PASS 1)
        2. ALWAYS try to extract from filename using structural analysis
        3. If extraction succeeds → set as author, source="filename" (OVERRIDES metadata)
        4. If extraction fails → keep what was (metadata or empty)
        
        Also builds author cache during execution for use with abbreviations.
        
        Args:
            records: List of BookRecord objects to process
        """
        print("[PASS 2] Extracting authors from filenames (structural analysis)...")
        
        # Debug: Log loaded patterns
        print(f"[PASS 2 DEBUG] Loaded {len(self.patterns)} patterns")
        print(f"[PASS 2 DEBUG] Service words count: {len(self.service_words)}")
        
        # Count source distribution
        source_counts = {}
        for r in records:
            source = getattr(r, 'author_source', '')
            source_counts[source] = source_counts.get(source, 0) + 1
        print(f"[PASS 2 DEBUG] Record sources BEFORE: {source_counts}")
        
        processed_count = 0
        skipped_count = 0
        
        for i, record in enumerate(records):
            # Skip files with folder_dataset source ONLY if fallback is NOT needed
            # needs_filename_fallback = True means folder parse found NOTHING, try filename anyway
            if record.author_source == "folder_dataset" and not getattr(record, 'needs_filename_fallback', False):
                skipped_count += 1
                continue
            
            # Try to extract from filename (NOT full path!)
            # Handle both Windows (\) and Unix (/) path separators
            filename = record.file_path.replace('\\', '/').split('/')[-1]  # Get basename only
            filename_without_ext = filename.rsplit('.', 1)[0]  # Remove extension
            
            # Debug: Log first 3 files
            if i < 3:
                # Encode safely for Windows console
                try:
                    print(f"[PASS 2 DEBUG] File {i+1}: {filename_without_ext}")
                except UnicodeEncodeError:
                    # Fallback: skip printing if encoding fails
                    pass
            
            # Construct full FB2 path for metadata validation
            fb2_path = None
            if self.work_dir:
                fb2_path = self.work_dir / record.file_path
            
            author = self._extract_author_from_filename(filename_without_ext, fb2_path)
            
            if author:
                # Successfully extracted from filename
                # This OVERRIDES metadata (FILE -> METADATA priority)
                record.proposed_author = author
                record.author_source = "filename"
                record.needs_filename_fallback = False  # Clear the fallback flag since we found something
                processed_count += 1
                
                # BUILD AUTHOR CACHE: Track this extraction for future abbreviation expansion
                # This helps expand abbreviated names in subsequent files
                # e.g., if we extract "Живой Алексей", cache that we've seen this full form
                self._build_author_cache_from_extraction(author)
                
                if i < 3:
                    print(f"[PASS 2 DEBUG]   -> Extracted: {author}")
            elif i < 3:
                print(f"[PASS 2 DEBUG]   -> No match")
            # else: keep existing (might be metadata or empty)
        
        print(f"[PASS 2] Extracted {processed_count} authors from filenames, skipped {skipped_count} folder_dataset records")
    
    def _extract_author_from_filename(self, filename: str, fb2_path: Optional[Path] = None) -> str:
        """Extract author name from filename using structural pattern matching.
        
        1. Analyze filename structure
        2. Score all patterns from config
        3. Pick best matching pattern
        4. Extract author based on that pattern
        5. VALIDATE that extracted name is a real author name
        6. Optionally expand/validate using FB2 metadata
        
        Args:
            filename: Filename without extension
            fb2_path: Path to FB2 file for metadata validation/expansion (optional)
        
        Returns:
            Author name or empty string
        """
        if not filename:
            return ""
        
        # Analyze structure
        struct = analyze_file_structure(filename, self.service_words)
        
        # Score all patterns
        best_pattern = None
        best_score = 0.0
        
        for pattern_obj in self.patterns:
            pattern = pattern_obj.get('pattern', '')
            score = score_pattern_match(struct, pattern, self.service_words)
            
            if score > best_score:
                best_score = score
                best_pattern = pattern
        
        # Extract author based on best matching pattern
        if best_pattern and best_score > 0.3:  # Minimum threshold
            author = self._extract_by_pattern(filename, best_pattern, struct)
            
            # Handle comma-separated authors (co-authorship)
            if author and ', ' in author:
                authors = [a.strip() for a in author.split(', ')]
                validated_authors = []
                
                for single_author in authors:
                    # VALIDATE each author independently
                    if single_author and self._looks_like_author_name(single_author) and validate_author_name(single_author):
                        # Validate and expand using FB2 metadata if available
                        expanded = self._validate_and_expand_author(single_author, fb2_path)
                        validated_authors.append(expanded)
                    elif single_author:
                        # Keep as-is if validation fails (some edge cases)
                        validated_authors.append(single_author)
                
                if validated_authors:
                    # Return validated co-authors
                    author = ', '.join(validated_authors)
                    self.logger.log(f"[PASS 2] Extracted '{author}' from '{filename}' using pattern '{best_pattern}' (score={best_score:.2f})")
                    return author
                # If validation fails for all co-authors, fall through
            # Single author case
            if author and self._looks_like_author_name(author) and validate_author_name(author):
                # Validate and expand using FB2 metadata if available
                author = self._validate_and_expand_author(author, fb2_path)
                self.logger.log(f"[PASS 2] Extracted '{author}' from '{filename}' using pattern '{best_pattern}' (score={best_score:.2f})")
                return author
            elif author:
                # Extracted but failed validation
                self.logger.log(f"[PASS 2 DEBUG] Extracted '{author}' from '{filename}' but failed validation")
            else:
                self.logger.log(f"[PASS 2 DEBUG] Extraction failed for pattern '{best_pattern}' (score={best_score:.2f})")
        else:
            self.logger.log(f"[PASS 2 DEBUG] No pattern match {'(score=' + str(best_score) + ')' if best_score > 0 else ''}")
        
        return ""
    
    def _extract_by_pattern(self, filename: str, pattern: str, struct: dict) -> str:
        """Extract author from filename based on matched pattern.
        
        Args:
            filename: Full filename without extension
            pattern: Matched pattern string
            struct: Analyzed structure
        
        Returns:
            Author name or empty string
        """
        
        author = ""
        
        # Pattern: "(Author) - Title"
        if pattern == "(Author) - Title":
            if ' - ' in filename:
                before_dash = filename.split(' - ', 1)[0]
                author = before_dash.strip().strip('()')
        
        # Pattern: "Author - Title"
        elif pattern == "Author - Title":
            if ' - ' in filename:
                author = filename.split(' - ', 1)[0].strip()
        
        # Pattern: "Author - Series.Title"
        elif pattern == "Author - Series.Title":
            if ' - ' in filename:
                author = filename.split(' - ', 1)[0].strip()
        
        # Pattern: "Author. Title"
        elif pattern == "Author. Title":
            if '. ' in filename:
                author = filename.split('. ', 1)[0].strip()
        
        # Pattern: "Title (Author)"
        elif pattern == "Title (Author)":
            if '(' in filename and ')' in filename:
                start = filename.rfind('(')
                end = filename.rfind(')')
                if start < end:
                    author = filename[start+1:end].strip()
        
        # Pattern: "Title - (Author)"
        elif pattern == "Title - (Author)":
            if ' - (' in filename:
                parts = filename.split(' - (')
                if len(parts) == 2:
                    author = parts[1].rstrip(')').strip()
        
        # Pattern: "Author. Series. Title"
        elif pattern == "Author. Series. Title":
            if '. ' in filename:
                author = filename.split('. ', 1)[0].strip()
        
        # Pattern: "Author, Author. Title (Series)"
        elif pattern == "Author, Author. Title (Series)":
            if ', ' in filename:
                # Extract both authors separated by comma
                before_period = filename.split('. ', 1)[0].strip()
                authors = [a.strip() for a in before_period.split(', ')]
                author = ', '.join(authors)  # Return both: "Author1, Author2"
        
        # Pattern: "Author. Title. (Series)"
        elif pattern == "Author. Title. (Series)":
            if '. ' in filename:
                author = filename.split('. ', 1)[0].strip()
        
        # Pattern: "Author - Title (Series)" (NO service words)
        elif pattern == "Author - Title (Series)":
            if ' - ' in filename:
                author = filename.split(' - ', 1)[0].strip()
        
        # Pattern: "Author - Title. Title (Series)" (with dot in title)
        elif pattern == "Author - Title. Title (Series)":
            if ' - ' in filename:
                author = filename.split(' - ', 1)[0].strip()
        
        # Pattern: "Author. Title (Series)" (NO service words)
        elif pattern == "Author. Title (Series)":
            if '. ' in filename:
                author = filename.split('. ', 1)[0].strip()
        
        # Pattern: "Author, Author - Title (Series)" (NO service words)
        elif pattern == "Author, Author - Title (Series)":
            if ', ' in filename:
                # Extract both authors separated by comma
                before_dash = filename.split(' - ', 1)[0].strip()
                authors = [a.strip() for a in before_dash.split(', ')]
                author = ', '.join(authors)  # Return both: "Author1, Author2"
        
        # Pattern: "Author - Title (Series. service_words)"
        elif pattern == "Author - Title (Series. service_words)":
            if ' - ' in filename:
                author = filename.split(' - ', 1)[0].strip()
        
        # Pattern: "Author. Title (Series. service_words)"
        elif pattern == "Author. Title (Series. service_words)":
            if '. ' in filename:
                author = filename.split('. ', 1)[0].strip()
        
        # Pattern: "Author, Author - Title (Series. service_words)"
        elif pattern == "Author, Author - Title (Series. service_words)":
            if ', ' in filename:
                # Extract both authors separated by comma
                before_dash = filename.split(' - ', 1)[0].strip()
                authors = [a.strip() for a in before_dash.split(', ')]
                author = ', '.join(authors)  # Return both: "Author1, Author2"
        
        # Return only if non-empty and valid author name
        if author and len(author) > 2:
            return author
        return ""
