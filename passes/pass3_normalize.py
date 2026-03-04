"""
PASS 3: Normalize author names to standard format.
"""

from typing import List, Optional
from author_normalizer_extended import AuthorNormalizer
from settings_manager import SettingsManager


class Pass3Normalize:
    """PASS 3: Normalize author names to standard format.
    
    Transform author names from various formats to standard "Фамилия Имя" format:
    - "Иван Петров" → "Петров Иван"
    - "А.Михайловский; А.Харников" → "Михайловский А., Харников А." (multi-author)
    """
    
    def __init__(self, logger):
        """Initialize PASS 3.
        
        Args:
            logger: Logger instance
        """
        self.logger = logger
        try:
            self.settings = SettingsManager('config.json')
        except:
            self.settings = None
        self.normalizer = AuthorNormalizer(self.settings)
    
    def execute(self, records: List) -> None:
        """Execute PASS 3: Normalize author names.
        
        Transform author format and handle multi-author cases.
        Handles both separators: '; ' (from folder parsing) and ', ' (from filename/metadata).
        
        Args:
            records: List of BookRecord objects to process
        """
        print("[PASS 3] Normalizing author names...")
        
        normalized_count = 0
        
        for record in records:
            if not record.proposed_author or record.proposed_author == "Сборник":
                continue
            
            original = record.proposed_author
            
            # Check for multi-author cases with different separators
            # '; ' comes from folder_author_parser (temporary separator)
            # ', ' comes from filename or metadata
            # 
            # Metadata handling strategy:
            # - folder_dataset: never use metadata (folder extraction is authoritative)
            # - filename (multi-author): never use metadata (don't replace with list)
            # - filename (single-word): allow metadata (for expanding incomplete names)
            # - metadata source: always use metadata (for normalization/conversions)
            
            # Special case: filename extraction of shared surname (like "Белаш", "Каменские")
            # If proposed_author is single word (surname only) and metadata has multiple
            # authors with this surname, restore them all
            if (record.author_source == "filename" and 
                len(record.proposed_author.strip().split()) == 1 and
                record.metadata_authors):
                # Check if metadata authors share the same surname
                surname_candidate = record.proposed_author.strip()
                # Handle both separators: '; ' and ', '
                if '; ' in record.metadata_authors:
                    metadata_authors_list = [a.strip() for a in record.metadata_authors.split('; ')]
                elif ', ' in record.metadata_authors:
                    metadata_authors_list = [a.strip() for a in record.metadata_authors.split(', ')]
                else:
                    metadata_authors_list = [record.metadata_authors.strip()]
                
                def extract_surname_root(name: str):
                    """Extract surname root for fuzzy matching.
                    
                    Handles Russian surname variations:
                    - "Каменские" → "Камен"
                    - "Каменский" → "Камен"
                    - "Каменская" → "Камен"
                    """
                    words = name.split()
                    if not words:
                        return name.lower()
                    
                    # Get last word (likely surname after normalization or as-is from filename)
                    surname = words[-1] if len(words) > 1 else words[0]
                    surname_lower = surname.lower()
                    
                    # Remove common Russian surname endings
                    for ending in ('ские', 'ский', 'ского', 'скому', 'ским', 'ске',
                                   'ская', 'скую', 'ской',
                                   'ое', 'ого', 'ому', 'ым', 'ом',
                                   'ий', 'ого', 'ому', 'ым', 'ом'):
                        if surname_lower.endswith(ending):
                            return surname_lower[:-len(ending)]
                    
                    return surname_lower
                
                matching_authors = []
                candidate_root = extract_surname_root(surname_candidate)
                
                for a in metadata_authors_list:
                    # Check if surname root matches
                    # Support both exact word match and root-based matching
                    author_words = a.split()
                    author_root = extract_surname_root(a)
                    
                    # Match if: exact word found OR root matches
                    if surname_candidate in author_words or author_root == candidate_root:
                        matching_authors.append(a)
                
                # If multiple authors with this surname in metadata, restore them
                if len(matching_authors) > 1:
                    # Normalize each author to "Фамилия Имя" format and sort by surname
                    normalized_authors = []
                    for author in matching_authors:
                        normalized = self.normalizer.normalize_format(author)
                        normalized_authors.append(normalized)
                    
                    # Sort by surname (first word for Russian names after normalization)
                    def get_surname_key(author_str):
                        words = author_str.split()
                        return words[0].lower() if words else author_str.lower()
                    
                    normalized_authors.sort(key=get_surname_key)
                    record.proposed_author = '; '.join(normalized_authors)
                    # Mark that this was restored - don't skip normalization as it's already done
                    record.skip_normalization = False
                else:
                    record.skip_normalization = False
            else:
                record.skip_normalization = False
            
            if record.author_source == "folder_dataset":
                # For folder_dataset with multi-author, use metadata to fix incomplete names
                # Example: "Белаш Александр, Людмила" + metadata → "Белаш Александр, Белаш Людмила"
                has_separator = ', ' in record.proposed_author or '; ' in record.proposed_author
                if has_separator:
                    metadata_for_normalization = record.metadata_authors
                else:
                    metadata_for_normalization = ""
            elif record.author_source == "filename":
                # For filename: use metadata strategy depends on structure
                has_separator = ', ' in record.proposed_author or '; ' in record.proposed_author
                
                if has_separator:
                    # Co-authors from filename: DO use metadata to expand surnames to full names
                    # Example: "Демидова, Конторович" + metadata → can become "Демидова Нина, Конторович Александр"
                    metadata_for_normalization = record.metadata_authors
                else:
                    # Single author from filename: only use metadata if incomplete (single word)
                    # This handles surname-only extractions that might be restored in lines 63-92
                    author_words = len(record.proposed_author.strip().split())
                    if author_words == 1:
                        # Single incomplete name - can use metadata for expansion
                        metadata_for_normalization = record.metadata_authors
                    else:
                        # Full author name already extracted - don't override with metadata
                        metadata_for_normalization = ""
            else:
                metadata_for_normalization = record.metadata_authors
            
            if '; ' in record.proposed_author or ', ' in record.proposed_author:
                # Determine separator
                sep = '; ' if '; ' in record.proposed_author else ', '
                # Only normalize if not restored from metadata (which are already correct)
                if not getattr(record, 'skip_normalization', False):
                    normalized = self.normalizer.normalize_format(record.proposed_author, metadata_for_normalization)
                else:
                    # Already restored from metadata with correct format, don't transform
                    normalized = record.proposed_author
            else:
                # Single author
                normalized = self.normalizer.normalize_format(record.proposed_author, metadata_for_normalization)
            
            if normalized and normalized != record.proposed_author:
                record.proposed_author = normalized
                normalized_count += 1
        
        self.logger.log(f"[PASS 3] Normalized {normalized_count} author names")
