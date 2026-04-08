"""
PASS 2: Extract authors from file names.

Uses structural analysis to match filename against all known patterns
in config.json author_series_patterns_in_files, then extracts author
based on best pattern match.

⚠️ CRITICAL RULE: Folder hierarchy extraction (folder_dataset source) is AUTHORITATIVE
and takes absolute priority over all other sources including filename extraction.
Files with author_source="folder_dataset" are NEVER modified in this pass.
This reflects the user's explicit folder structure which is the most reliable source.
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
    """PASS 2: Extract authors from filenames.
    
    CRITICAL RULE: Files with author_source="folder_dataset" are NEVER modified.
    Folder hierarchy extraction is the most reliable source and takes absolute priority.
    Only files without folder_dataset source (empty, metadata, filename, etc.) can be processed.
    """
    
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
        self.collection_keywords = settings.get_list('collection_keywords') or []  # Load from config
        self.male_names = male_names or set()
        self.female_names = female_names or set()
        self.name_particles = (
            settings.get_name_particles()
            if hasattr(settings, 'get_name_particles')
            else frozenset({'де', 'ди', 'дю', 'ду', 'да', 'дер', 'ден', 'дель', 'дела',
                            'делла', 'дэлла', 'дос', 'дас', 'дэ', 'ван', 'фон',
                            'ля', 'ле', 'ла', 'мак', 'о'})
        )
        self.patterns = self._load_patterns()
        # Precomputed lowercase set of collection keywords for fast lookup in _looks_like_author_name
        self._collection_kw_lower = {k.lower() for k in self.collection_keywords}
        # Author cache: maps abbreviated/partial names to full names
        # e.g., {"А. Живой" -> "Живой Алексей", "Живой" -> "Живой Алексей"}
        self.author_cache = {}
        # Single reusable extractor — avoids re-reading config.json per file
        self._extractor = FB2AuthorExtractor()
    
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
    
    def prebuild_author_cache(self, records: List) -> None:
        """Pre-scan all FB2 files to build author cache BEFORE main processing.

        This ensures that even if a file has bad/missing metadata, its authors
        can be resolved from sibling files in the same folder that DO have good metadata.

        Strategy: for each record, read FB2 metadata and cache all author names
        (full name, surname, each word) so they're available during execute().

        Args:
            records: List of BookRecord objects
        """
        if not self.work_dir:
            return

        print("[PASS 2] Pre-building author cache from FB2 metadata...")
        cached_count = 0

        for record in records:
            fb2_path = self.work_dir / record.file_path
            if not fb2_path.exists():
                continue

            try:
                fb2_authors_str = self._extractor._extract_all_authors_from_metadata(fb2_path)

                if not fb2_authors_str:
                    continue

                fb2_authors = [a.strip() for a in fb2_authors_str.split(';') if a.strip()]

                for author in fb2_authors:
                    if not author:
                        continue
                    author_lower = author.lower().strip()
                    # Cache full name
                    self.author_cache[author_lower] = author
                    # Cache each word (surname, firstname) separately.
                    # Always store the word-keyed entry with THAT WORD FIRST (ФИ convention):
                    # "Хуан Франсиско Феррандис" → cache["феррандис"] = "Феррандис Хуан Франсиско"
                    # so that single-surname lookups get the canonical ФИ form.
                    author_words = author.split()
                    for idx, part in enumerate(author_words):
                        if len(part) > 2:
                            part_lower = part.lower()
                            if part_lower not in self.author_cache:
                                if idx == 0:
                                    self.author_cache[part_lower] = author
                                else:
                                    rest = [w for i, w in enumerate(author_words) if i != idx]
                                    self.author_cache[part_lower] = part + ' ' + ' '.join(rest)
                    cached_count += 1

            except Exception:
                pass

        print(f"[PASS 2] Pre-cache built: {len(self.author_cache)} entries from {cached_count} authors")

    def _validate_and_expand_author(self, extracted_author: str, fb2_path: Optional[Path]) -> str:
        """Validate and potentially expand author name using FB2 metadata and cache.
        
        Strategy:
        1. Check author cache first (compiled from previous files)
        2. If not in cache, try to expand from FB2 metadata
        3. Compare with FB2 metadata authors to find matching record
        4. If found with better form (fuller name), use and cache that instead
        
        SPECIAL CASE: If extracted is single word (surname) and metadata has multiple
        authors with this surname, DON'T expand here - leave for PASS 3 restoration.
        
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
                # Extract authors from FB2 metadata (reuse shared extractor)
                fb2_authors_str = self._extractor._extract_all_authors_from_metadata(fb2_path)
                
                if fb2_authors_str:
                    # Parse FB2 authors (separated by '; ')
                    fb2_authors = [a.strip() for a in fb2_authors_str.split(';') if a.strip()]
                    
                    # SPECIAL CASE: If extracted is single word and metadata has multiple co-authors
                    # with this word, DON'T expand - leave surname-only for PASS 3 restoration
                    if len(extracted_author.split()) == 1 and len(fb2_authors) > 1:
                        # Check if this single word matches multiple FB2 authors
                        extracted_words = {extracted_lower}
                        matching_count = 0
                        for fb2_author in fb2_authors:
                            fb2_words = set(fb2_author.lower().split())
                            if extracted_words.issubset(fb2_words):
                                matching_count += 1
                        
                        # If matches multiple authors, don't expand
                        if matching_count > 1:
                            return extracted_author  # Return surname-only, let PASS 3 handle restoration
                    
                    # Exact match - return as is
                    for fb2_author in fb2_authors:
                        if fb2_author.lower() == extracted_lower:
                            self._add_to_author_cache(extracted_author, fb2_author)
                            return fb2_author  # Return FB2 version (better normalization)
                    
                    # Partial match - check if extracted is substring of any FB2 author
                    # This handles cases like \"Демченко\" matching \"Демченко Антон\" (single-word expansion)
                    # BUT: Do NOT allow reversed word order like "Гулевич Александр" → "Александр Гулевич"
                    for fb2_author in fb2_authors:
                        fb2_lower = fb2_author.lower()
                        extracted_words_list = extracted_lower.split()
                        fb2_words_list = fb2_lower.split()
                        
                        # Only expand if:
                        # 1. Extracted is SINGLE WORD (legitimate expansion like "Демченко" → "Демченко Антон")
                        # 2. OR first words match AND same number of words (order preserved in both)
                        if len(extracted_words_list) == 1:
                            # Single word expansion - check if it's in FB2 author
                            if extracted_lower in fb2_words_list:
                                # Put the matched surname FIRST (ФИ convention).
                                # FB2 metadata often stores names in ИФ order ("Хуан Франсиско Феррандис"),
                                # but canonical format is ФИ ("Феррандис Хуан Франсиско").
                                match_idx = fb2_words_list.index(extracted_lower)
                                if match_idx > 0:
                                    rest = [w for i, w in enumerate(fb2_author.split()) if i != match_idx]
                                    reordered = fb2_author.split()[match_idx] + ' ' + ' '.join(rest)
                                    self._add_to_author_cache(extracted_author, reordered)
                                    return reordered
                                self._add_to_author_cache(extracted_author, fb2_author)
                                return fb2_author  # Use fuller name from FB2
                        elif (len(extracted_words_list) == len(fb2_words_list) and 
                              extracted_words_list[0] == fb2_words_list[0]):
                            # Multi-word with matching first word (likely normalized case variation)
                            self._add_to_author_cache(extracted_author, fb2_author)
                            return fb2_author
                        # Otherwise: different number of words OR reversed order → skip (don't match)
                    
                    # PARTICLE MATCHING: if extracted contains a name particle (де, ван, фон…),
                    # check if the "particle tail" (from first particle onwards) appears verbatim in
                    # any metadata author. This catches compound surnames like:
                    #   "Жиро де л Эн" (filename) vs "Аликс де л'Эн" (metadata)
                    # Both share the tail "делэн" after apostrophe+space normalization.
                    if self.name_particles:
                        _apo = str.maketrans({"'": "", "\u2019": "", "\u02bc": ""})
                        for fb2_author in fb2_authors:
                            fb2_norm = fb2_author.lower().translate(_apo).replace(' ', '')
                            for i, w in enumerate(extracted_lower.split()):
                                if w in self.name_particles:
                                    tail = ' '.join(extracted_lower.split()[i:]).translate(_apo).replace(' ', '')
                                    if tail and tail in fb2_norm:
                                        self.logger.log(
                                            f"[PASS 2] Particle-tail match: '{extracted_author}' → "
                                            f"'{fb2_author}' (tail='{tail}')"
                                        )
                                        self._add_to_author_cache(extracted_author, fb2_author)
                                        return fb2_author
                                    break  # only check from the FIRST particle
            
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
            # EXCEPTION: if ALL words start with uppercase AND ≤3 words AND none is a
            # collection/genre keyword → treat as proper name (proper-name typography).
            # Handles foreign/exotic names absent from Russian dictionaries:
            # "Ровена Бергман", "Линдквист Йон Айвиде", "Тисако Вакатакэ" etc.
            text_words_orig = text.split()
            all_capitalized = all(w[0].isupper() for w in text_words_orig if w)
            if all_capitalized and len(text_words) <= 3:
                if not any(w in self._collection_kw_lower for w in text_words):
                    return True  # Proper-name pattern: all words capitalised, ≤3 words

            # Require at least one known first name OR a known name particle (de, van, von…)
            # to filter out collection titles like "Боевая фантастика".
            # Particles count as valid name-components (they are part of proper names).
            if self.male_names or self.female_names:
                has_known_name = any(
                    word in self.male_names
                    or word in self.female_names
                    or word in self.name_particles
                    for word in text_words
                )
                if not has_known_name:
                    return False  # Not an author name - likely a collection title
        # Single word always passes (it's a surname, which is valid author name)
        
        return True
    
    def _is_incomplete_name(self, author: str) -> bool:
        """Check if author name is incomplete (only surname, initials, etc).
        
        Examples of incomplete:
        - "Живой" (single word/surname only)
        - "Кумин" (single word)
        - "Михеев М." (surname + initial)
        - "М. Живой" (initial + surname)
        
        Examples of complete:
        - "Живой Алексей" (surname + first name)
        - "Демченко Антон" (surname + first name)
        
        Args:
            author: Author name to check
            
        Returns:
            True if incomplete, False if complete
        """
        if not author:
            return True
        
        words = author.split()
        
        # Single word → incomplete (only surname or initial)
        if len(words) == 1:
            return True
        
        # Two words: check if any is just initial (single letter + dot or single letter)
        # "Кумин. И" or "М. Кумин" or "И М" → incomplete
        # "Живой Алексей" → complete
        has_short = any(
            (len(w) == 1 and w.isalpha()) or  # Single letter like "И"
            (len(w) == 2 and w[1] == '.' and w[0].isalpha())  # Initial like "И."
            for w in words
        )
        
        if has_short:
            # Есть короткое слово — но если есть хотя бы ДВА полных слова (len > 2),
            # это скорее всего формат "Фамилия Имя М." (отчество-инициаль) → полное имя.
            full_words = [w for w in words if len(w) > 2]
            if len(full_words) >= 2:
                return False  # "Форд Джон М." — полное имя с инициалью отчества
            return True  # At least one word is short → incomplete name
        
        # All words are full words → complete
        return False
    
    def _expand_initial_surnames(self, author_str: str, metadata_authors: str) -> tuple:
        """Expand 'Initial.Surname' tokens (like 'Г.Диксон') using metadata authors.

        Handles multi-author strings like "Гаррисон Гарри, Г.Диксон" — expands any
        token that matches the pattern Letter.Surname against the metadata author list.

        Args:
            author_str: Author string, possibly multi-author like "Гаррисон Гарри, Г.Диксон"
            metadata_authors: Raw metadata authors string ("Гордон Диксон; Гарри Гаррисон")

        Returns:
            Tuple (expanded_str, was_expanded)
        """
        if not metadata_authors:
            return author_str, False

        # Parse metadata authors (separated by "; " or ";")
        meta_list = [a.strip() for a in metadata_authors.replace('; ', ';').split(';') if a.strip()]

        # Split input by ", " to handle each author token separately
        parts = [p.strip() for p in author_str.split(',')]
        expanded_parts = []
        was_expanded = False

        for part in parts:
            if not part:
                continue

            # Detect "X.Surname" pattern (single uppercase letter + dot + surname)
            # e.g., "Г.Диксон", "H.Harrison"
            dot_idx = part.find('.')
            if (dot_idx == 1 and part[0].isupper() and
                    len(part) > 2 and part[2:3].isupper()):
                initial = part[0].lower()
                surname = part[dot_idx + 1:].lower()
                # Find metadata author with this surname AND a name starting with initial
                found = None
                for meta_author in meta_list:
                    meta_words = meta_author.lower().split()
                    if (any(w == surname for w in meta_words) and
                            any(w.startswith(initial) and w != surname for w in meta_words)):
                        found = meta_author
                        break
                if found:
                    expanded_parts.append(found)
                    was_expanded = True
                    continue

            expanded_parts.append(part)

        result = ', '.join(expanded_parts)
        return result, was_expanded

    def _try_expand_from_metadata(self, incomplete_author: str, metadata_authors: str) -> str:
        """Try to expand incomplete author name from metadata.
        
        If incomplete_author is like "Живой" or "Кумин. И", find the full version
        in metadata_authors and return it.
        
        Args:
            incomplete_author: Short name from filename ("Кумин" or "Михеев М.")
            metadata_authors: Full authors string from FB2 metadata ("Вячислав Кумин; ...")
            
        Returns:
            Full author name if found, otherwise original incomplete_author
        """
        if not metadata_authors:
            return incomplete_author
        
        # Extract surnames from incomplete_author
        incomplete_parts = incomplete_author.split()
        
        # Take first word (usually surname) for matching
        surname_candidate = incomplete_parts[0].lower()
        
        # Split metadata into individual authors (separated by "; " or ", ")
        meta_authors = [a.strip() for a in metadata_authors.replace('; ', '|').replace(', ', '|').split('|')]
        
        for meta_author in meta_authors:
            if not meta_author:
                continue
            
            meta_words = meta_author.split()
            
            # Try to find matching surname in metadata
            # E.g., if looking for "Кумин", check if metadata has "...Кумин..."
            for idx, word in enumerate(meta_words):
                if word.lower() == surname_candidate:
                    # Found match!
                    # Always put the matched surname FIRST (ФИ convention).
                    # Metadata stores names in ИФ order ("Хуан Франсиско Феррандис"),
                    # but our canonical format is ФИ ("Феррандис Хуан Франсиско").
                    if idx == 0:
                        return meta_author  # Already in ФИ order
                    else:
                        rest = [w for i, w in enumerate(meta_words) if i != idx]
                        return word + ' ' + ' '.join(rest)
        
        # No clear match found - return original
        return incomplete_author
    
    def _is_collection(self, file_path: str, file_title: str) -> bool:
        """Return True when the file is a true anthology/collection.

        Criterion: the filename (without extension) OR the book title contains
        at least one of the collection_keywords from config.json.
        Co-authored books with 3+ authors but without those keywords are NOT
        considered collections — they are 'Соавторство'.

        Args:
            file_path: Relative file path (may contain directory separators)
            file_title: Book title extracted from FB2 metadata (may be empty)

        Returns:
            True  → assign "Сборник"
            False → assign "Соавторство"
        """
        if not self.collection_keywords:
            return False

        # Check in filename (basename, no extension) and in book title
        filename_noext = file_path.replace('\\', '/').split('/')[-1].rsplit('.', 1)[0].lower()
        title_lower = (file_title or '').lower()

        for kw in self.collection_keywords:
            kw_l = kw.lower()
            if kw_l in filename_noext or kw_l in title_lower:
                return True

        return False

    def _count_authors(self, authors_str: str) -> int:
        """Count number of authors in metadata authors string.
        
        Authors are separated by "; " (fb2 metadata) or ", " (filename/metadata)
        
        Args:
            authors_str: String with authors (e.g. "Author 1; Author 2; Author 3")
            
        Returns:
            Number of authors found
        """
        if not authors_str or authors_str == "[unknown]":
            return 0
        
        # Count authors separated by "; " or ", "
        if "; " in authors_str:
            return len([a for a in authors_str.split("; ") if a.strip()])
        elif ", " in authors_str:
            return len([a for a in authors_str.split(", ") if a.strip()])
        else:
            return 1 if authors_str.strip() else 0
    
    def execute(self, records: List) -> None:
        """Execute PASS 2: Extract authors from filenames.
        
        CRITICAL RULE: folder_dataset source is AUTHORITATIVE and NEVER OVERWRITTEN!
        
        Folder hierarchy extraction indicates the user explicitly created folder structure
        for this author. This is the most reliable source and takes absolute priority.
        
        Processing order for each record:
        1. If author_source == "folder_dataset" → SKIP (never override, keep as-is)
        2. Try to extract author from filename using structural analysis
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
        error_count = 0
        test_count = 0
        
        for i, record in enumerate(records):
            # Skip files with folder_dataset source ONLY if:
            # 1. NOT a fallback situation (folder extraction found something valid)
            # 2. AND filename doesn'tcontain multi-author pattern (comma in non-extension parts)
            
            is_multiauthor_pattern = False
            filename_for_check = record.file_path.replace('\\', '/').split('/')[-1]  # basename only
            if '. ' in filename_for_check:
                before_extension = filename_for_check.rsplit('.', 1)[0]  # remove .fb2
                # Check if there's a comma indicating multi-author pattern
                if ', ' in before_extension:
                    is_multiauthor_pattern = True
            
            # Skip if folder_dataset source AND not a fallback AND single-author filename
            if (record.author_source == "folder_dataset" and 
                not getattr(record, 'needs_filename_fallback', False) and
                not is_multiauthor_pattern):
                skipped_count += 1
                continue
            
            # CHECK: Is this file a collection/anthology or co-authored book?
            # Rule: 3+ authors in metadata → either "Сборник" (if keywords in filename/title)
            #                               or "Соавторство" (regular multi-author book)
            author_count = self._count_authors(record.metadata_authors)
            if author_count >= 3:
                if self._is_collection(record.file_path, getattr(record, 'file_title', '')):
                    record.proposed_author = "Сборник"
                else:
                    record.proposed_author = "Соавторство"
                record.author_source = "collection"
                record.needs_filename_fallback = False
                processed_count += 1
                continue  # Skip regular filename parsing for collections/co-authored
            
            # Try to extract from filename (NOT full path!)
            # Handle both Windows (\) and Unix (/) path separators
            filename = record.file_path.replace('\\', '/').split('/')[-1]  # Get basename only
            filename_without_ext = filename.rsplit('.', 1)[0]  # Remove extension
            
            # Construct full FB2 path for metadata validation
            fb2_path = None
            if self.work_dir:
                fb2_path = self.work_dir / record.file_path
            
            author = self._extract_author_from_filename(filename_without_ext, fb2_path)
            
            if author:
                # Successfully extracted from filename
                # IMPORTANT: NEVER OVERWRITE folder_dataset source!
                # Folder hierarchy extraction is AUTHORITATIVE and should never be changed
                if record.author_source != "folder_dataset":
                    # Check if extracted author is incomplete (single name, initials, etc.)
                    expanded_author = author
                    use_hybrid_source = False
                    
                    # STEP 1: Expand "Initial.Surname" tokens (e.g., "Г.Диксон" → "Гордон Диксон")
                    if record.metadata_authors:
                        new_author, was_init_expanded = self._expand_initial_surnames(author, record.metadata_authors)
                        if was_init_expanded:
                            expanded_author = new_author
                            use_hybrid_source = True

                    # STEP 2: Traditional incomplete name expansion (single word, pure initial, etc.)
                    if not use_hybrid_source and self._is_incomplete_name(expanded_author):
                        if record.metadata_authors:
                            expanded = self._try_expand_from_metadata(expanded_author, record.metadata_authors)
                            if expanded and expanded != expanded_author:
                                expanded_author = expanded
                                use_hybrid_source = True  # Mark as hybrid source

                    # No folder_dataset - use filename extraction
                    # This OVERRIDES metadata (FILE -> METADATA priority)
                    record.proposed_author = expanded_author
                    record.author_source = "filename_meta_confirmed" if use_hybrid_source else "filename"
                    record.needs_filename_fallback = False  # Clear the fallback flag since we found something
                    processed_count += 1
                    
                    # BUILD AUTHOR CACHE: Track this extraction for future abbreviation expansion
                    # This helps expand abbreviated names in subsequent files
                    # e.g., if we extract "Живой Алексей", cache that we've seen this full form
                    self._build_author_cache_from_extraction(expanded_author)
                # else: Already has folder_dataset source - NEVER override it, keep existing
            else:
                # Filename extraction failed (author is empty)
                # Fallback: Use metadata if available (with hybrid source)
                if (record.author_source != "folder_dataset" and 
                    record.metadata_authors and 
                    not record.proposed_author):  # Only if not already set
                    # Use metadata as fallback, mark as hybrid (filename attempt + metadata fallback)
                    if self._count_authors(record.metadata_authors) >= 3:
                        if self._is_collection(record.file_path, getattr(record, 'file_title', '')):
                            record.proposed_author = "Сборник"
                        else:
                            record.proposed_author = "Соавторство"
                        record.author_source = "collection"
                    else:
                        record.proposed_author = record.metadata_authors
                        record.author_source = "metadata"  # Couldn't extract from filename
                    record.needs_filename_fallback = False
                    processed_count += 1
                # else: keep existing (might be metadata or empty)
        
        print(f"[PASS 2] Extracted {processed_count} authors from filenames, skipped {skipped_count} folder_dataset records, errors: {error_count}")
    
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
                # If author contains a dot, take only the part before it
                if '. ' in author:
                    author = author.split('. ', 1)[0].strip()
        
        # Pattern: "Author - Title"
        elif pattern == "Author - Title":
            if ' - ' in filename:
                author = filename.split(' - ', 1)[0].strip()
                # If author contains a dot, take only the part before it (e.g., "Жеребьёв. Я" -> "Жеребьёв")
                if '. ' in author:
                    author = author.split('. ', 1)[0].strip()
        
        # Pattern: "Author - Series.Title"
        elif pattern == "Author - Series.Title":
            if ' - ' in filename:
                author = filename.split(' - ', 1)[0].strip()
                # If author contains a dot, take only the part before it
                if '. ' in author:
                    author = author.split('. ', 1)[0].strip()
        
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
                    # If author contains a dot, take only the part before it
                    if '. ' in author:
                        author = author.split('. ', 1)[0].strip()
        
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
                # If author contains a dot, take only the part before it
                if '. ' in author:
                    author = author.split('. ', 1)[0].strip()
        
        # Pattern: "Author - Title. Title (Series)" (with dot in title)
        elif pattern == "Author - Title. Title (Series)":
            if ' - ' in filename:
                author = filename.split(' - ', 1)[0].strip()
                # If author contains a dot, take only the part before it
                if '. ' in author:
                    author = author.split('. ', 1)[0].strip()
        
        # Pattern: "Author. Title (Series)" (NO service words)
        elif pattern == "Author. Title (Series)":
            if '. ' in filename:
                author = filename.split('. ', 1)[0].strip()
        
        # Pattern: "Author, Author - Title (Series)" (NO service words)
        elif pattern == "Author, Author - Title (Series)":
            if ', ' in filename:
                # Extract both authors separated by comma
                before_dash = filename.split(' - ', 1)[0].strip()
                # If any author contains a dot, take only the part before it
                authors = []
                for a in before_dash.split(', '):
                    a = a.strip()
                    if '. ' in a:
                        a = a.split('. ', 1)[0].strip()
                    authors.append(a)
                author = ', '.join(authors)  # Return both: "Author1, Author2"
        
        # Pattern: "Author - Title (Series. service_words)"
        elif pattern == "Author - Title (Series. service_words)":
            if ' - ' in filename:
                author = filename.split(' - ', 1)[0].strip()
                # If author contains a dot, take only the part before it
                if '. ' in author:
                    author = author.split('. ', 1)[0].strip()
        
        # Pattern: "Author. Title (Series. service_words)"
        elif pattern == "Author. Title (Series. service_words)":
            if '. ' in filename:
                author = filename.split('. ', 1)[0].strip()
        
        # Pattern: "Author, Author - Title (Series. service_words)"
        elif pattern == "Author, Author - Title (Series. service_words)":
            if ', ' in filename:
                # Extract both authors separated by comma
                before_dash = filename.split(' - ', 1)[0].strip()
                # If any author contains a dot, take only the part before it
                authors = []
                for a in before_dash.split(', '):
                    a = a.strip()
                    if '. ' in a:
                        a = a.split('. ', 1)[0].strip()
                    authors.append(a)
                author = ', '.join(authors)  # Return both: "Author1, Author2"
        
        # Return only if non-empty and valid author name
        if author and len(author) > 2:
            return author
        return ""
    
    def _clean_filename_for_extraction(self, filename: str) -> str:
        """Remove blacklist markers from filename before pattern matching.
        
        CRITICAL: Blacklist markers like "(СИ)" add extra blocks to the filename structure,
        which breaks block-count-based pattern matching. They must be removed BEFORE tokenization.
        
        This affects how blocks are counted:
        - "Автор - Название (СИ)" has 2 blocks IF we remove "(СИ)" first
        - "Автор - Название (СИ)" has 3 blocks if we keep "(СИ)" as a separate block
        
        Args:
            filename: Original filename
            
        Returns:
            Filename with blacklist markers removed
        """
        import re
        
        cleaned = filename
        
        # Remove blacklist elements from the END of filename
        # Start from the end and remove matching blacklist patterns
        # Only remove if they appear at END of string (after all meaningful content)
        
        # Pattern 1: "(СИ)" or variations at the end
        cleaned = re.sub(r'\s*\(СИ\)\s*$', '', cleaned, flags=re.IGNORECASE)
        
        # Pattern 2: Other known meta-patterns that shouldn't create extra blocks
        # Remove tags/meta in parens at the end
        cleaned = re.sub(r'\s*\([^)]*издание[^)]*\)\s*$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*\(пер\.\s*[^)]*\)\s*$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*\(перевод[^)]*\)\s*$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*\(пер\)\s*$', '', cleaned, flags=re.IGNORECASE)
        
        return cleaned.strip()
    
    def _extract_author_from_filename(self, filename: str, fb2_path: Optional[Path] = None) -> str:
        """Extract author name from filename using BLOCK-LEVEL pattern matching.
        
        Algorithm:
        1. CLEAN filename from blacklist markers (like "(СИ)") to preserve block count
        2. Tokenize cleaned filename into blocks (delimited by ' - ', '. ', parens)
        3. Score each pattern against blocks via BlockLevelPatternMatcher
        4. Take best-score match (threshold 0.6)
        5. TITLE-AS-AUTHOR GUARD: compare extracted candidate against FB2 <book-title>.
           When two patterns tie (e.g. "Author - Title" vs "Title - Author" both score 0.73
           for a two-block filename), the first pattern in config.json wins by default.
           If that first-winner extracts the book title as "author", retry without
           patterns whose name starts with "Title" → correct pattern wins the retry.
        6. VALIDATE extracted name (_looks_like_author_name + validate_author_name)
        7. EXPAND abbreviated/incomplete names via FB2 metadata and author cache
        
        Args:
            filename: Filename without extension
            fb2_path: Path to FB2 file for book-title guard + metadata expansion (optional)
        
        Returns:
            Author name or empty string
        """
        if not filename:
            return ""
        
        try:
            # Import block-level matcher
            try:
                from block_level_pattern_matcher import BlockLevelPatternMatcher
            except ImportError:
                from ..block_level_pattern_matcher import BlockLevelPatternMatcher
            import re
            
            # CRITICAL: Remove blacklist markers from filename BEFORE pattern matching
            # "(СИ)" at the end creates an extra block that breaks pattern matching!
            cleaned_filename = self._clean_filename_for_extraction(filename)
            
            # Create matcher with service words and known author names
            matcher = BlockLevelPatternMatcher(
                service_words=list(self.service_words),
                male_names=self.male_names,
                female_names=self.female_names
            )
            
            # Find best pattern match using block-level comparison on CLEANED filename
            best_score, best_pattern, author, series = matcher.find_best_pattern_match(cleaned_filename, self.patterns)
            
            # Need minimum score threshold to proceed
            if best_score < 0.6:  # Threshold for block matching
                #self.logger.log(f"[PASS 2] Block score too low: {best_score:.2f} < 0.6 for '{filename}'")
                return ""
            
            # Validate extracted author
            if not author or not author.strip():
                #self.logger.log(f"[PASS 2] No author block extracted for '{filename}'")
                return ""
            
            author = author.strip()
            
            # TITLE-AS-AUTHOR GUARD: <book-title> from FB2 metadata can NEVER be an author.
            # This catches tie-breaking mistakes: e.g. "Алдерман Наоми - Сила" scores equally
            # for "Author - Title" and "Title - Author"; if the winning candidate equals the
            # real book title, the pattern order chose wrong — reject it and try again
            # without that candidate pattern.
            if fb2_path and fb2_path.exists():
                try:
                    book_title = self._extractor._extract_title_from_fb2(fb2_path)
                    # Strip trailing [...] noise (e.g. "[litres]", "[СИ]") before comparing.
                    _book_title_clean = re.sub(r'\s*\[.*?\]\s*$', '', book_title.strip()) if book_title else ''
                    # Also strip trailing (...) noise (e.g. "(ЛП)", "(СИ)", "(альт. перевод)")
                    # so "Спасение (ЛП)" → "Спасение" can be matched against extracted author.
                    _book_title_no_parens = re.sub(r'\s*\([^)]*\)\s*$', '', _book_title_clean).strip()
                    # Normalise ё→е before comparing so "Звёздочка" matches "Звездочка"
                    def _yo(s: str) -> str:
                        return s.lower().replace('ё', 'е')
                    _title_matches_author = (
                        (_book_title_clean and _yo(_book_title_clean) == _yo(author)) or
                        (_book_title_no_parens and _yo(_book_title_no_parens) == _yo(author))
                    )
                    if _title_matches_author:
                        self.logger.log(
                            f"[PASS 2] Rejected author '{author}' — matches book-title from FB2 "
                            f"(pattern='{best_pattern}'). Retrying without Title-first patterns."
                        )
                        # Retry: exclude patterns whose name starts with "Title"
                        filtered_patterns = [
                            p for p in self.patterns
                            if not (p.get('pattern', '') if isinstance(p, dict) else p).startswith('Title')
                        ]
                        best_score, best_pattern, author, series = matcher.find_best_pattern_match(
                            cleaned_filename, filtered_patterns
                        )
                        if best_score < 0.6 or not author or not author.strip():
                            return ""
                        author = author.strip()
                        # Sanity check: still the book title?
                        if author.lower() in (_book_title_clean.lower(), _book_title_no_parens.lower()):
                            return ""
                except Exception:
                    pass
            
            # Handle comma-separated authors (co-authorship)
            if ', ' in author:
                authors = [a.strip() for a in author.split(', ')]
                validated_authors = []
                
                for single_author in authors:
                    looks_like = self._looks_like_author_name(single_author)
                    is_valid = validate_author_name(single_author) if single_author else False
                    if single_author and looks_like and is_valid:
                        expanded = self._validate_and_expand_author(single_author, fb2_path)
                        validated_authors.append(expanded)
                    elif single_author:
                        validated_authors.append(single_author)
                
                if validated_authors:
                    author = ', '.join(validated_authors)
                    self.logger.log(f"[PASS 2] ✓ Extracted '{author}' from '{filename}' (block-level)")
                    return author
                # else: validation failed, fall through
            
            # Single author case
            if author and self._looks_like_author_name(author) and validate_author_name(author):
                author = self._validate_and_expand_author(author, fb2_path)
                self.logger.log(f"[PASS 2] ✓ Extracted '{author}' from '{filename}' (block-level)")
                return author
            else:
                #self.logger.log(f"[PASS 2] Block extraction failed validation for '{author}' from '{filename}'")
                return ""
        
        except ImportError as e:
            self.logger.log(f"[PASS 2] ImportError: BlockLevelPatternMatcher - {e}")
            return ""
        except Exception as e:
            import traceback
            self.logger.log(f"[PASS 2] Block-level matching error for '{filename}': {e}")
            traceback.print_exc()
            return ""
        
        self.logger.log(f"[PASS 2 DEBUG] No pattern match {'(score=' + str(best_score) + ')' if best_score > 0 else ''}")
        
        return ""
