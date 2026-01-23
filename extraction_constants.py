"""
Константы для извлечения авторов и серий из различных источников.

Определяет приоритеты источников и конфигурацию уровня уверенности.
"""


class AuthorExtractionPriority:
    """
    Приоритет источников для извлечения авторов.
    
    Числовое значение определяет порядок: выше число = выше приоритет.
    Порядок обработки: от 1 к 3 (но выбирается по наибольшему приоритету).
    """
    FOLDER_STRUCTURE = 1    # Уровень 1: структура папок
    FILENAME = 2            # Уровень 2: название файла
    FB2_METADATA = 3        # Уровень 3: метаданные FB2
    
    # Порядок итерации для попытки извлечения (от низшего к высшему приоритету)
    ORDER = [FOLDER_STRUCTURE, FILENAME, FB2_METADATA]
    
    # Человеко-читаемые названия
    NAMES = {
        FOLDER_STRUCTURE: 'folder',
        FILENAME: 'filename',
        FB2_METADATA: 'metadata'
    }
    
    @classmethod
    def get_name(cls, priority: int) -> str:
        """Получить текстовое название по приоритету."""
        return cls.NAMES.get(priority, 'unknown')
    
    @classmethod
    def is_valid(cls, priority: int) -> bool:
        """Проверить, корректный ли приоритет."""
        return priority in cls.NAMES


class SeriesExtractionPriority:
    """
    Приоритет источников для извлечения серий.
    
    Аналогично авторам, но может иметь отличающиеся приоритеты.
    """
    FOLDER_STRUCTURE = 1    # Уровень 1: структура папок
    FILENAME = 2            # Уровень 2: название файла
    FB2_METADATA = 3        # Уровень 3: метаданные FB2
    
    ORDER = [FOLDER_STRUCTURE, FILENAME, FB2_METADATA]
    
    NAMES = {
        FOLDER_STRUCTURE: 'folder',
        FILENAME: 'filename',
        FB2_METADATA: 'metadata'
    }
    
    @classmethod
    def get_name(cls, priority: int) -> str:
        """Получить текстовое название по приоритету."""
        return cls.NAMES.get(priority, 'unknown')
    
    @classmethod
    def is_valid(cls, priority: int) -> bool:
        """Проверить, корректный ли приоритет."""
        return priority in cls.NAMES


class ConfidenceLevel:
    """Уровни уверенности для результатов извлечения."""
    
    # Структура папок обычно менее надежна
    FOLDER_MIN = 0.60
    FOLDER_MAX = 0.80
    
    # Имя файла - средняя надежность
    FILENAME_MIN = 0.60
    FILENAME_MAX = 0.80
    
    # Метаданные FB2 - самые надежные
    FB2_MIN = 0.70
    FB2_MAX = 0.95
    
    # Минимальная уверенность для принятия результата
    MIN_ACCEPTABLE = 0.50


class FilterReason:
    """Причины, по которым значение может быть отфильтровано."""
    
    IN_BLACKLIST = 'in_blacklist'           # Совпадает с файлом в черном списке
    EMPTY_VALUE = 'empty_value'             # Пустое значение
    INVALID_FORMAT = 'invalid_format'       # Некорректный формат
    LOW_CONFIDENCE = 'low_confidence'       # Низкая уверенность
    BLACKLIST_KEYWORDS = 'blacklist_keywords'  # Содержит слова из черного списка


class ExtractionResult:
    """Базовая структура результата извлечения."""
    
    def __init__(
        self,
        value: str,
        priority: int,
        raw_value: str = None,
        confidence: float = 0.7,
        pattern_used: str = None,
        pattern_index: int = None,
        extracted_groups: dict = None,
        is_filtered: bool = False,
        filter_reasons: list = None
    ):
        """
        Инициализация результата извлечения.
        
        Args:
            value: Извлеченное и нормализованное значение
            priority: Приоритет источника (из AuthorExtractionPriority или SeriesExtractionPriority)
            raw_value: Оригинальное значение до нормализации
            confidence: Уровень уверенности (0.0 - 1.0)
            pattern_used: Использованный паттерн (текст)
            pattern_index: Индекс паттерна в списке
            extracted_groups: Все группы, извлеченные из regex
            is_filtered: Было ли отфильтровано
            filter_reasons: Список причин фильтрации
        """
        self.value = value
        self.priority = priority
        self.raw_value = raw_value or value
        self.confidence = confidence
        self.pattern_used = pattern_used
        self.pattern_index = pattern_index
        self.extracted_groups = extracted_groups or {}
        self.is_filtered = is_filtered
        self.filter_reasons = filter_reasons or []
    
    def to_dict(self) -> dict:
        """Преобразовать в словарь."""
        return {
            'value': self.value,
            'priority': self.priority,
            'raw_value': self.raw_value,
            'confidence': self.confidence,
            'pattern_used': self.pattern_used,
            'pattern_index': self.pattern_index,
            'extracted_groups': self.extracted_groups,
            'is_filtered': self.is_filtered,
            'filter_reasons': self.filter_reasons
        }
    
    def __repr__(self) -> str:
        """Строковое представление."""
        status = "FILTERED" if self.is_filtered else "OK"
        priority_name = AuthorExtractionPriority.get_name(self.priority)
        return f"ExtractionResult({self.value}, priority={priority_name}, conf={self.confidence:.2f}, {status})"
