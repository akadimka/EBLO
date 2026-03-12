"""
Block-Level Pattern Matching for Authors and Series Extraction.

Разбивает filename/pattern на БЛОКИ и сравнивает структуры для точного извлечения.

Blocks are structural elements separated by delimiters like:
- ' - ' (space-dash-space)
- '. ' (dot-space)
- '(' and ')' (parentheses)
- ',' (comma)

Example:
  Filename: "Янковский Дмитрий - Охотник (Тетралогия)"
  Blocks: ["Янковский Дмитрий", "Охотник", "(Тетралогия)"]
  
  Pattern: "Author - Title (Series.service_words)"
  Block-types: ["Author", "Title", "(Series)"]
  
  Match block 0 (filename) to block 0 (pattern) → "Янковский Дмитрий" is Author
"""

from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import re


@dataclass
class Block:
    """Structural block from text."""
    text: str              # Raw text of block
    block_type: str        # Type: "Author", "Title", "Series", "service_words", etc.
    position: int          # Position in block list
    is_parenthesized: bool # True if wrapped in ()
    
    def __repr__(self):
        return f'Block("{self.text}", type={self.block_type})'


class BlockLevelPatternMatcher:
    """Match filename against patterns using block-level structural comparison."""
    
    # Common Russian words that typically appear in titles, not author names
    TITLE_KEYWORDS = {
        'битва', 'война', 'король', 'королевство', 'императорь', 'империя',
        'мир', 'мира', 'небесный', 'звезда', 'звезд', 'звёзд', 'звёзда',
        'край', 'земля', 'земли', 'ночь', 'день', 'огонь', 'вода',
        'молния', 'гром', 'шторм', 'ураган', 'зима', 'лето', 'весна', 'осень',
        'город', 'замок', 'дворец', 'храм', 'церковь', 'святилище',
        'квест', 'поиск', 'охота', 'охотник', 'путешествие', 'путь',
        'магия', 'магический', 'чарованный', 'чародей', 'волшебник',
        'герой', 'герои', 'боец', 'боцена', 'воїн', 'война'
    }
    
    def __init__(self, service_words: List[str] = None):
        """Initialize matcher.
        
        Args:
            service_words: List of service words (series markers like "Тетралогия", "Дилогия")
        """
        self.service_words = set(w.lower() for w in (service_words or []))
    
    def tokenize_filename(self, filename: str) -> List[Block]:
        """Break filename into structural blocks.
        
        Splits on major delimiters:
        1. ' - ' (space-dash-space) → block separator ("Author - Title")
        2. '. ' (dot-space) → block separator ("Author. Title")
        3. () → treated as block (with type hint)
        
        Examples:
            "Янковский Дмитрий - Охотник (Тетралогия)" → 3 blocks
            "Мах. Квест империя" → 2 blocks
        
        Args:
            filename: Filename string
            
        Returns:
            List of Block objects
        """
        if not filename:
            return []
        
        # Remove .fb2 if present
        text = filename.rstrip('.fb2') if filename.endswith('.fb2') else filename
        text = text.strip()
        
        blocks = []
        
        # Choose primary delimiter (priority: ' - ' > '. ')
        if ' - ' in text:
            parts = text.split(' - ')
        elif '. ' in text:
            parts = text.split('. ')
        else:
            parts = [text]
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            # Check if this part contains parentheses
            if '(' in part and ')' in part:
                # Extract parenthesized content
                match = re.search(r'\(([^)]+)\)', part)
                if match:
                    paren_content = match.group(1)
                    remainder = part[:match.start()] + part[match.end():]
                    remainder = remainder.strip()
                    
                    # Add remainder as block
                    if remainder:
                        blocks.append(Block(
                            text=remainder,
                            block_type="text",
                            position=len(blocks),
                            is_parenthesized=False
                        ))
                    
                    # Add parenthesized content as separate block
                    blocks.append(Block(
                        text=paren_content,
                        block_type="parenthesized",
                        position=len(blocks),
                        is_parenthesized=True
                    ))
            else:
                # Regular text block
                blocks.append(Block(
                    text=part,
                    block_type="text",
                    position=len(blocks),
                    is_parenthesized=False
                ))
        
        return blocks
    
    def tokenize_pattern(self, pattern: str) -> List[Dict]:
        """Break pattern into structural block types.
        
        Splits pattern on same delimiters as filename, but tracks expected TYPE.
        
        Example:
            "Author - Title (Series. service_words)"
            → [
                {"type": "Author", "text": "Author", "position": 0, "parenthesized": False},
                {"type": "Title", "text": "Title", "position": 1, "parenthesized": False},
                {"type": "Series", "text": "Series", "position": 2, "parenthesized": True}
              ]
        
        Args:
            pattern: Pattern string (e.g., "Author - Title (Series)")
            
        Returns:
            List of dicts with {type, text, position, parenthesized}
        """
        if not pattern:
            return []
        
        pattern_blocks = []
        
        # Split on ' - '
        dash_parts = pattern.split(' - ')
        
        for part_idx, part in enumerate(dash_parts):
            part = part.strip()
            if not part:
                continue
            
            # Split on '. ' within this part
            dot_parts = part.split('. ')
            
            for sub_idx, sub_part in enumerate(dot_parts):
                sub_part = sub_part.strip()
                if not sub_part:
                    continue
                
                # Check for parentheses
                if '(' in sub_part and ')' in sub_part:
                    match = re.search(r'\(([^)]+)\)', sub_part)
                    if match:
                        paren_content = match.group(1)
                        remainder = sub_part[:match.start()] + sub_part[match.end():]
                        remainder = remainder.strip()
                        
                        # Add remainder
                        if remainder:
                            block_type = self._normalize_block_type(remainder)
                            pattern_blocks.append({
                                "type": block_type,
                                "text": remainder,
                                "position": len(pattern_blocks),
                                "parenthesized": False
                            })
                        
                        # Add parenthesized content
                        block_type = self._normalize_block_type(paren_content)
                        pattern_blocks.append({
                            "type": block_type,
                            "text": paren_content,
                            "position": len(pattern_blocks),
                            "parenthesized": True
                        })
                else:
                    block_type = self._normalize_block_type(sub_part)
                    pattern_blocks.append({
                        "type": block_type,
                        "text": sub_part,
                        "position": len(pattern_blocks),
                        "parenthesized": False
                    })
        
        return pattern_blocks
    
    def _normalize_block_type(self, text: str) -> str:
        """Determine block type from pattern text.
        
        Recognizes:
        - "Author", "Author," → "Author"
        - "Title" → "Title"
        - "Series", "Series." → "Series"
        - "service_words" → "service_words"
        
        Args:
            text: Pattern text (e.g., "Author" or "Series. service_words")
            
        Returns:
            Normalized block type
        """
        text_lower = text.lower().strip(',. ')
        
        if 'author' in text_lower:
            return "Author"
        elif 'series' in text_lower:
            return "Series"
        elif 'title' in text_lower:
            return "Title"
        elif 'service_words' in text_lower:
            return "service_words"
        else:
            return "Title"  # Default to Title if unclear
    
    def score_pattern_match(self, filename: str, pattern: str) -> Tuple[float, Optional[str], Optional[str], Optional[str]]:
        """Score how well filename matches pattern structure.
        
        Returns: (score, pattern, matched_author_block, matched_series_block)
        
        Algorithm:
        1. Tokenize filename → list of blocks
        2. Tokenize pattern → list of block types
        3. Match blocks to block types
        4. Score based on:
           - Number of blocks matching
           - Types matching expected types
           - Service words detection
        5. Return highest score + extracted values
        
        Args:
            filename: Filename to match
            pattern: Pattern template
            
        Returns:
            (score_0_to_1, pattern, matched_author_block, matched_series_block, type_match_count)
        """
        filename_blocks = self.tokenize_filename(filename)
        pattern_blocks = self.tokenize_pattern(pattern)
        
        if not filename_blocks or not pattern_blocks:
            return 0.0, pattern, None, None
        
        # Hard rule: # of blocks must match
        if len(filename_blocks) != len(pattern_blocks):
            return 0.0, pattern, None, None
        
        # Score each block match
        score = 0.0
        max_score = 0.0
        author_block = None
        series_block = None
        type_match_count = 0  # Count how many blocks had correct type match
        
        for fname_block, pblock in zip(filename_blocks, pattern_blocks):
            max_score += 1.0
            
            # Match parenthesization
            if fname_block.is_parenthesized == pblock['parenthesized']:
                score += 0.5
            
            # Match block type expectation
            fname_type = self._guess_block_type(fname_block.text)
            expected_type = pblock['type']
            
            if fname_type == expected_type:
                score += 0.5  # Type matches!
                type_match_count += 1  # Track for tie-breaking
                
                # Track which block is Author/Series
                if expected_type == "Author":
                    author_block = fname_block.text
                elif expected_type == "Series":
                    series_block = fname_block.text
        
        normalized_score = score / max_score if max_score > 0 else 0.0
        # Store type_match_count as attribute on return value for tie-breaking
        self._last_type_match_count = type_match_count
        return normalized_score, pattern, author_block, series_block
    
    def _guess_block_type(self, block_text: str) -> str:
        """Guess what type a block is based on content.
        
        Heuristics:
        - Contains service words (Тетралогия, Дилогия) → Series
        - Contains parenthesized numbers (1-3, 2) → Series
        - Contains known names/surnames → Author
        - Contains title keywords → Title
        - Otherwise → Title
        
        Args:
            block_text: Text of the block
            
        Returns:
            Guessed type: "Author", "Series", or "Title"
        """
        text_lower = block_text.lower()
        
        # Check for service words (series markers)
        for word in self.service_words:
            if word in text_lower:
                return "Series"
        
        # Check for number patterns (1-3, 1, vol. 2, etc.)
        if re.search(r'\d+[-–—]\d+|\b\d+$|\bvol\.\s+\d+', block_text):
            return "Series"
        
        # Check for title keywords - if present, likely Title, not Author
        text_words = set(text_lower.split())
        if any(word in self.TITLE_KEYWORDS for word in text_words):
            return "Title"
        
        # Check if looks like author (simple heuristic: has 2+ words, Cyrillic)
        words = block_text.split()
        if len(words) >= 2:
            # Likely "Surname Name" format
            if all(self._is_cyrillic_word(w) for w in words[:2]):
                return "Author"
        
        # Single Russian word of 3+ chars (relaxed) → likely surname
        if len(words) == 1 and len(block_text) >= 3:
            if self._is_cyrillic_word(block_text):
                # Additional check: make sure it's not a common title keyword
                if text_lower not in self.TITLE_KEYWORDS:
                    return "Author"
        
        return "Title"
    
    def _is_cyrillic_word(self, word: str) -> bool:
        """Check if word is Cyrillic."""
        return any('\u0400' <= c <= '\u04FF' for c in word)
    
    def find_best_pattern_match(self, filename: str, patterns: List[Dict]) -> Tuple[float, str, Optional[str], Optional[str]]:
        """Find best matching pattern for filename and extract Author/Series.
        
        Uses scoring with tie-breaking:
        1. Primary: pattern match score (0-1)
        2. Secondary: number of blocks with correct type match
        
        Args:
            filename: Filename to match
            patterns: List of pattern dicts with 'pattern' key
            
        Returns:
            (best_score, best_pattern, extracted_author, extracted_series)
        """
        best_score = 0.0
        best_pattern = None
        best_author = None
        best_series = None
        best_type_matches = 0  # Tie-breaker: count of blocks with correct type
        
        for pattern_obj in patterns:
            pattern = pattern_obj.get('pattern', '')
            score, matched_pattern, author, series = self.score_pattern_match(filename, pattern)
            
            # Primary check: higher score
            if score > best_score:
                best_score = score
                best_pattern = matched_pattern
                best_author = author
                best_series = series
                best_type_matches = getattr(self, '_last_type_match_count', 0)
            # Tie-breaking: if same score, prefer more type matches
            elif score == best_score and score > 0.0:
                current_type_matches = getattr(self, '_last_type_match_count', 0)
                if current_type_matches > best_type_matches:
                    best_pattern = matched_pattern
                    best_author = author
                    best_series = series
                    best_type_matches = current_type_matches
        
        return best_score, best_pattern, best_author, best_series


__all__ = [
    'Block',
    'BlockLevelPatternMatcher',
]
