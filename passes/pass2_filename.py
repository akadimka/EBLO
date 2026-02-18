"""
PASS 2: Extract authors from file names.
"""

from typing import List


class Pass2Filename:
    """PASS 2: Extract authors from filenames for records without folder_dataset."""
    
    def __init__(self, settings, logger):
        """Initialize PASS 2.
        
        Args:
            settings: SettingsManager instance
            logger: Logger instance
        """
        self.settings = settings
        self.logger = logger
    
    def execute(self, records: List) -> None:
        """Execute PASS 2: Extract authors from filenames.
        
        Args:
            records: List of BookRecord objects to process
        """
        print("[PASS 2] Extracting authors from filenames...")
        
        processed_count = 0
        
        for record in records:
            # Skip files with folder_dataset source
            if record.author_source == "folder_dataset":
                continue
            
            # Skip if already has author
            if record.proposed_author:
                continue
            
            # Try to extract from filename (NOT full path!)
            # Handle both Windows (\) and Unix (/) path separators
            filename = record.file_path.replace('\\', '/').split('/')[-1]  # Get basename only
            filename_without_ext = filename.rsplit('.', 1)[0]  # Remove extension
            
            author = self._extract_author_from_filename(filename_without_ext)
            
            if author:
                record.proposed_author = author
                record.author_source = "filename"
                processed_count += 1
        
        self.logger.log(f"[PASS 2] Extracted {processed_count} authors from filenames")
    
    def _extract_author_from_filename(self, filename: str) -> str:
        """Extract author name from filename using simple patterns.
        
        Patterns (in order of priority):
        - "Title (Author)" → Author (most common in Test1)
        - "Author - Title" → Author
        - "Author. Title" → Author
        - "Author, Author" → First Author
        
        Args:
            filename: Filename without extension
        
        Returns:
            Author name or empty string
        """
        if not filename:
            return ""
        
        # Pattern: "Title (Author)" ← Most common in Test1
        # Example: "Achtung! Manager in der Luft! (Комбат Найтов)"
        if '(' in filename and ')' in filename:
            start = filename.rfind('(')  # Find LAST opening parenthesis
            end = filename.rfind(')')    # Find LAST closing parenthesis
            if start < end and start != -1:
                author = filename[start+1:end].strip()
                if author and len(author) > 2:
                    return author
        
        # Pattern: "Author - Title"
        if ' - ' in filename:
            parts = filename.split(' - ', 1)
            author = parts[0].strip()
            if author and len(author) > 2:
                return author
        
        # Pattern: "Author. Title"
        if '. ' in filename:
            parts = filename.split('. ', 1)
            author = parts[0].strip()
            if author and len(author) > 2:
                return author
        
        # Pattern: "Author, Author"
        if ',' in filename:
            parts = filename.split(',', 1)
            author = parts[0].strip()
            if author and len(author) > 2:
                return author
        
        return ""
