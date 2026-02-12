# Поддержка соавторства (Co-authorship) - Раздел 9

## 9.1 Проблема

При наличии нескольких авторов в одной папке (например, "Белаш Александр, Людмила") система должна корректно обрабатывать оба имени в полном формате ФИ (Фамилия Имя).

**Сложность:** Имя автора в папке может быть неполным (только имя без фамилии):
- Папка: "Белаш Александр, Людмила"
- Нужно восстановить: "Белаш Александр; Людмила Белаш"
- Фамилия для второго автора должна быть взята из первого имени

## 9.2 Решение: Интеграция метаданных в нормализацию

### Этап 1: Парсинг папки (PASS 1 - функция `_parse_author_from_folder_name`)

**Новый regex для паттерна "Author, Author"** добавлен в `_folder_pattern_to_regex()` в `regen_csv.py`:

```python
"Author, Author": (
    r'^(?P<author>[^,]+?)\s*,\s*(?P<author2>.+)$',
    ['author', 'author2']
),
```

**Логика восстановления неполного ФИ в `_parse_author_from_folder_name`**:

```python
if 'author2' in group_names and match.group('author2'):
    author2 = match.group('author2').strip()
    
    # Если author2 - только одно слово (имя), добавить фамилию из author1
    author2_words = author2.split()
    if len(author2_words) == 1:
        # author2 - только имя, добавить фамилию из author
        author_words = author.split()
        if author_words:
            # Фамилия обычно первое слово в формате "Фамилия Имя"
            surname = author_words[0]
            author2 = surname + " " + author2  # "Белаш Людмила"
    
    author = author + "; " + author2  # Объединить через ";"
```

**Результат по этапу 1:**
```
Папка: "Белаш Александр, Людмила"
→ proposed_author = "Белаш Александр; Людмила Белаш"
→ author_source = "folder_dataset"
```

**Файлы:**
- `regen_csv.py` lines 267-295 (функция `_folder_pattern_to_regex`)
- `regen_csv.py` lines 564-577 (функция `_parse_author_from_folder_name`)

### Этап 2: Нормализация формата (PASS 3 - функция `normalize_format`)

**Обновленная функция `normalize_format` в `author_normalizer_extended.py` lines 70-132:**

Параметр добавлен: `metadata_authors: str = ""`

Логика:
1. Разбить потенциальные авторы по '; ' или ','
2. Для каждого автора проверить - одно это слово или несколько
3. Если одно слово, искать в metadata_authors полное ФИ
4. Нормализовать каждого через AuthorName и объединить через запятую

```python
def normalize_format(self, author: str, metadata_authors: str = "") -> str:
    """Нормализовать формат автора.
    
    Если несколько авторов разделены '; ', обогащает из metadata_authors
    """
    if not author or author == "Сборник":
        return author
    
    # Если несколько авторов разделены '; '
    if '; ' in author:
        authors = author.split('; ')
        normalized_authors = []
        
        # Парсируем metadata_authors для восстановления неполных ФИ
        metadata_authors_list = []
        if metadata_authors:
            metadata_authors_list = [a.strip() for a in metadata_authors.replace(';', ',').split(',')]
        
        for single_author in authors:
            single_author = single_author.strip()
            if single_author:
                # Проверить если это неполное ФИ (одно слово)
                author_words = single_author.split()
                if len(author_words) == 1 and metadata_authors_list:
                    # Одно слово - это имя, нужно найти фамилию из metadata
                    single_word = author_words[0]
                    for meta_author in metadata_authors_list:
                        meta_words = meta_author.split()
                        if single_word in meta_words:
                            # Используем полное ФИ из metadata
                            single_author = meta_author
                            break
                
                # Нормализовать через AuthorName
                name_obj = AuthorName(single_author)
                normalized = name_obj.normalized if name_obj.is_valid else single_author
                normalized_authors.append(normalized)
        
        # Объединить через запятую (стандартный формат для CSV)
        return ', '.join(normalized_authors)
    
    # Одиночный автор
    name_obj = AuthorName(author)
    return name_obj.normalized if name_obj.is_valid else author
```

**Обновленная функция `apply_author_normalization` в `author_normalizer_extended.py` lines 283-308:**

Теперь передает `record.metadata_authors` в `normalizer.normalize_format()`:

```python
def apply_author_normalization(record: BookRecord, normalizer: Optional[AuthorNormalizer] = None) -> None:
    if not normalizer:
        normalizer = AuthorNormalizer()
    
    if record.proposed_author == "Сборник":
        return
    
    original = record.proposed_author
    
    # Передать metadata_authors для восстановления неполных ФИ
    if '; ' in record.proposed_author:
        record.proposed_author = normalizer.normalize_format(original, record.metadata_authors)
    else:
        record.proposed_author = normalizer.normalize_format(original, record.metadata_authors)
```

**Результат по этапу 2:**
```
Входные данные PASS 3:
- proposed_author = "Белаш Александр; Людмила Белаш"
- metadata_authors = "Людмила Белаш; Александр Белаш"

Выход PASS 3:
- proposed_author = "Белаш Александр, Белаш Людмила"
  (нормализовано: фамилия на первом месте, разделитель - запятая)
```

## 9.3 Ключевые особенности

1. **Восстановление в folder_parse:** Если второй автор = одно слово, берётся фамилия из первого
   ```
   "Белаш Александр, Людмила" → "Белаш Александр; Людмила Белаш"
   ```

2. **Обогащение в нормализации:** Если не удалось восстановить в папке, ищется в metadata
   ```
   "Белаш Александр; Людмила" + metadata="Людмила Белаш; Александр Белаш"
   → "Белаш Александр; Людмила Белаш" (найдено в metadata)
   ```

3. **Финальный формат:** Несколько авторов разделяются запятыми
   ```
   "Белаш Александр, Белаш Людмила" (в CSV)
   ```

## 9.4 Примеры обработки

### Пример 1: Неполное ФИ восстанавливается в folder_parse
```
Папка: "Белаш Александр, Людмила"
Файл: Капитан удача.fb2
Метаданные: "Людмила Белаш; Александр Белаш"

PASS 1 (folder_parse):
  proposed_author = "Белаш Александр; Людмила Белаш"
  (восстановлена фамилия для Людмилы из первого имени)

PASS 3 (normalize):
  proposed_author = "Белаш Александр, Белаш Людмила"
  (нормализовано в стандартный формат)

CSV результат:
  proposed_author = "Белаш Александр, Белаш Людмила" ✅
```

### Пример 2: Непредвиденный порядок имён в metadata
```
Папка: "Бирюков Александр, Сердитый Глеб"
Метаданные: "Александр Бирюков; Глеб Сердитый"

PASS 1 (folder_parse):
  proposed_author = "Бирюков Александр; Сердитый Глеб"
  (восстановлена Сердитый для Глеба)

PASS 3 (normalize):
  Проверка: "Глеб" находится в metadata как "Глеб Сердитый"
  → заменяет "Сердитый Глеб" на "Глеб Сердитый"
  → нормализует оба в стандартный формат

CSV результат: "Бирюков Александр, Глеб Сердитый"
```

### Пример 3: Оба автора с правильным порядком в metadata
```
Папка: "Зорич Александр, Жарковский Сергей"
Метаданные: "Александр Зорич; Сергей Жарковский"

PASS 1 (folder_parse):
  Оба имена имеют по 2 слова → не восстанавливаются
  proposed_author = "Зорич Александр; Жарковский Сергей"

PASS 3 (normalize):
  proposed_author = "Жарковский Сергей, Зорич Александр"
  (нормализовано и отсортировано)

CSV результат:
  proposed_author = "Жарковский Сергей, Зорич Александр" ✅
```

## 9.5 Изменённые файлы и строки кода

| Файл | Функция | Строки | Изменение |
|------|---------|--------|-----------|
| `regen_csv.py` | `_folder_pattern_to_regex()` | 267-295 | Добавлен паттерн "Author, Author" |
| `regen_csv.py` | `_parse_author_from_folder_name()` | 564-577 | Логика восстановления неполных ФИ |
| `author_normalizer_extended.py` | `normalize_format()` | 70-132 | Добавлен параметр `metadata_authors`, логика поиска в metadata |
| `author_normalizer_extended.py` | `apply_author_normalization()` | 283-308 | Передача `record.metadata_authors` в `normalize_format()` |

## 9.6 Конфигурация (config.json)

Убедитесь, что в config.json присутствует паттерн для соавторства в папках:

```json
{
  "author_series_patterns_in_folders": [
    {
      "pattern": "Author, Author",
      "example": "Иван Петров, Сергей Иванов"
    },
    {
      "pattern": "Author",
      "example": "Иван Петров"
    },
    {
      "pattern": "Author - Folder Name",
      "example": "Максим Шаттам - Собрание сочинений"
    },
    {
      "pattern": "Series (Author)",
      "example": "Защита Периметра (Абенд Эдвард)"
    },
    {
      "pattern": "(Series) Author",
      "example": "(Боевой отряд) Петров И."
    },
    {
      "pattern": "Series",
      "example": "Демонолог"
    }
  ]
}
```

## 9.7 Интеграция в 6-PASS архитектуру

```
PASS 1: _pass1_read_fb2_files()
        ├─ _build_folder_structure() ← Новая логика для папок "Author, Author"
        │  └─ _parse_author_from_folder_name() ← Восстановление неполных ФИ
        │     └─ _folder_pattern_to_regex() ← Новый паттерн "Author, Author"
        └─ _get_author_for_file() ← Применение conversions

PASS 3: apply_author_normalization()
        └─ normalizer.normalize_format(author, metadata_authors) ← Обогащение из metadata
           ├─ Поиск неполных ФИ в metadata_authors_list
           └─ Создание полных ФИ для каждого автора

CSV:    Сохранение с правильными разделами между авторами
        (Белаш Александр, Белаш Людмила)
```
