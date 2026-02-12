# Архитектура новой системы регенерации CSV

## ⚠️ КРИТИЧЕСКОЕ: Источник FB2 файлов vs Сохранение результатов

### Чтение FB2 файлов

**Все FB2 файлы сканируются из рабочей папки, определяемой параметром config.json:**

```json
"last_scan_path": "C:/Users/dmitriy.murov/Downloads/TriblerDownloads/Test1"
```

- **last_scan_path** = рабочая папка, где находятся FB2 файлы (переменная)
- **library_path** = НЕ используется для сканирования файлов!
- Алгоритм: рекурсивно ищет все `*.fb2` в `last_scan_path` и его подпапках
- При сохранении в CSV используется относительный путь от `last_scan_path`

### ⭐ Сохранение CSV файла

**CSV файл ВСЕГДА сохраняется в папку ПРОЕКТА (c:\\Temp\\fb2parser), независимо от last_scan_path!**

```
c:\Temp\fb2parser\regen.csv  ← ФИКСИРОВАННОЕ МЕСТО
                              (не зависит от config.json)
```

**Причина:**
- Результаты работы должны быть в одном месте
- project_dir определяется как папка скрипта `regen_csv.py`
- Это гарантирует, что CSV всегда доступен в репозитории проекта

---

## 1. Сравнение: name_normalizer.py vs author_utils.py

### Проблема: Функциональное пересечение

Оба файла содержат логику нормализации авторов, но с разными подходами:

| Характеристика  | `name_normalizer.py`              | `author_utils.py`                       |
|---              |---                                |---                                      |
| **Класс**       | `AuthorName`                      | `AuthorUtils`                           |
| **Фокус**       | Нормализация одного имени         | Применение преобразований к записям     |
| **Поля**        | `.raw_name`, `.normalized`        | Работает с `BookRecord`                 |
| **Валидация**   | Проверка на мусор/blacklist       | Консенсус между файлами                 |
| **Конфиг**      | Самостоятельная загрузка (static) | Через `SettingsManager`                 |
| **Зависимости** | Только config.json                | `SettingsManager`, `FB2AuthorExtractor` |

### Рекомендация: ОБЪЕДИНИТЬ В ОДИН ФАЙЛ

✅ **Предложение:** Переименовать `author_utils.py` → `author_normalizer_extended.py` и расширить его функционалом:

```python
# Базовые функции нормализации
- normalize_single_name()        # Из name_normalizer.py
- validate_author_name()         # Из name_normalizer.py
- apply_surname_conversions()    # Из author_utils.py

# Функции обработки записей
- apply_surname_conversions_to_records()
- expand_abbreviated_authors()
- apply_author_consensus()
- build_authors_map()
```

**Преимущества:**
- Одна точка входа для всех нормализаций
- Единый способ работы с конфигом
- Нет дублирования логики

---

## 2. Параметры и списки из config.json

### 2.1 Критические параметры для regen_csv.py

```json
{
  "folder_parse_limit": 3,
  "author_surname_conversions": {
    "Гоблин (MeXXanik)": "Гоблин MeXXanik",
    "Айзенберг": "Берг",
    "Старец": "Старицын"
  },
  "male_names": ["Александр", "Андрей", "Артем", "Василий", ...],
  "female_names": ["Александра", "Алиса", "Анна", "Виктория", ...],
  "filename_blacklist": ["компиляция", "сборник", "антология", "загрузки", ...],
  "service_words": ["том", "книга", "часть", "ч", "кн", "vol", ...],
  "sequence_patterns": ["том \\d+", "книга \\d+", ...],
  "author_series_patterns_in_files": [...],
  "author_series_patterns_in_folders": [...],
  "author_name_patterns": [...]
}
```

### 2.2 Как использовать в regen_csv.py

```python
# Инициализация
settings = SettingsManager('config.json')
folder_parse_limit = settings.get_folder_parse_limit()           # Глубина парсинга папок
male_names = settings.get_male_names()                           # Мужские имена для определения значения автора
female_names = settings.get_female_names()                       # Женские имена для определения значения автора
surname_conversions = settings.get_author_surname_conversions()  # Конвертации фамилий
blacklist = settings.get_filename_blacklist()                    # Для фильтрации шума

# Примеры использования:
# 1. Для валидации авторского имени (не мусор ли)
if name in blacklist:
    skip_name()

# 2. Для определения порядка "Имя Фамилия" vs "Фамилия Имя"
if first_word.lower() in male_names:
    order = "Имя Фамилия"
else:
    order = "Фамилия Имя"

# 3. Для конвертации известных фамилий
if original_author in surname_conversions:
    canonical_author = surname_conversions[original_author]

# 4. Для определения глубины парсинга папок (PASS 1)
# folder_parse_limit = 3 → смотрим максимум 3 уровня вверх в папках
```

---

## 3. Подключаемые файлы и их функционал

### 3.1 `settings_manager.py` - SettingsManager

**Инициализация:**
```python
from settings_manager import SettingsManager
settings = SettingsManager('config.json')
```

**Основные методы:**
```python
# Параметры парсинга
settings.get_folder_parse_limit()        # → int (значение из config.json: 3)
settings.get_generate_csv()              # → bool (генерировать ли CSV)

# Списки из конфига
settings.get_male_names()                 # → List[str]
settings.get_female_names()               # → List[str]
settings.get_filename_blacklist()         # → List[str]
settings.get_service_words()              # → List[str]
settings.get_author_surname_conversions() # → Dict[str, str]

# Пути и каталоги
settings.get_library_path()              # → str
settings.get_last_scan_path()            # → str
settings.get_genres_file_path()          # → str

# Работа с окнами
settings.set_window_size(name, w, h)
settings.get_window_sizes()
```

### 3.2 `fb2_author_extractor.py` - FB2AuthorExtractor

**Инициализация:**
```python
from fb2_author_extractor import FB2AuthorExtractor
extractor = FB2AuthorExtractor('config.json')
```

**Основные методы:**

```python
# ✅ ИСПОЛЬЗУЕМ В regen_csv.py:

# 1. Извлечение автора по приоритету: папка → файл → метаданные (PASS 1)
author, source = extractor.resolve_author_by_priority(fb2_filepath, folder_parse_limit)
# Результат: (автор, "folder" / "filename" / "metadata")

# 2. Нормализация формата автора ("Иван Петров" → "Петров Иван")
normalized = extractor._normalize_author_format(author_string)

# 4. Расширение аббревиатур ("А.Фамилия" → "Александр Фамилия")
expanded = extractor.expand_abbreviated_author(abbreviated, authors_map)

# 5. Получение всех известных имён (для валидации)
all_names = extractor.all_names  # Set из male_names + female_names

# 6. Проверка фамилии в известных авторах
is_author = extractor.is_author(name)


```

### 3.3 `author_processor.py` - AuthorProcessor

**Используется внутри FB2AuthorExtractor.**

**Методы которые могут быть полезны:**
```python
processor = self.extractor.author_processor

# Нормализация текста (замена ё→е, etc)
normalized_text = processor.normalize_text(text)

# Определение пола по имени
gender = processor.determine_gender(first_name)  # → 'M', 'F', 'U' (Unknown)
```

### 3.4 `logger.py` - Logger

**Логирование событий:**
```python
from logger import Logger
logger = Logger()

logger.log("Сообщение")                    # Обычное логирование
logger.log("Ошибка!", "error")             # Ошибка
logger.log("[PASS 1] Обработка файлов")    # С префиксом
```

---

## 4. Новая архитектура: 6 PASS системы

### 4.1 Общая схема

```
PASS 1: Определение автора по приоритету (папка → файл → метаданные)
        ↓
        1. Проверить папки вверх до folder_parse_limit уровней
        2. Если не найдено → проверить имя файла
        3. Если не найдено → извлечь из метаданных FB2
        Применить conversions: "Гоблин (MeXXanik)" → "Гоблин MeXXanik"
        → BookRecord(metadata_authors, proposed_author, author_source)

PASS 2: ❌ ОТКЛЮЧЕН
        → Остается заглушка (для совместимости логирования)

PASS 3: Нормализация авторов
        ↓
        Нормализация формата (Имя Фамилия → Фамилия Имя)
        Применение extractor._normalize_author_format()

PASS 4: Применение консенсуса
        ↓
        Поиск группы файлов в одной папке
        Определение консенсусного автора
        Применение ко всей группе (если нет явного folder_dataset)

PASS 5: Применение конвертаций фамилий
        ↓
        Второе применение surname_conversions (после консенсуса)
        Финальная нормализация

PASS 6: Раскрытие аббревиатур
        ↓
        Преобразование "А.Фамилия" → "Александр Фамилия"
        Требует словаря полных имён (build_authors_map)

        ↓
CSV SAVE: Сохранение результата
```

### 4.2 Детальное описание каждого PASS

#### PASS 1: Определение автора по приоритету

**ЖЕЛЕЗНОЕ ПРАВИЛО:** папка → файл → метаданные

**⚠️ ВАЖНО: Источник FB2 файлов**
- FB2 файлы сканируются **в рабочей папке** (текущей директории `./`)
- **НЕ** используется `library_path` из config.json для сканирования!
- `library_path` используется только для определения относительных путей при сохранении в CSV
- Алгоритм: рекурсивно ищет все `*.fb2` файлы в текущей рабочей папке и её подпапках

**Входные данные:**
- Путь к FB2 файлу (найдено в рабочей папке)
- folder_parse_limit = 3 (глубина поиска вверх по папкам)

**Алгоритм:**
```
1. Попытка 1: Парсинг иерархии папок (ВАРИАНТ B - Папка автора как целая иерархия)
   - Проверить папки вверх на folder_parse_limit уровней
   - ⚠️ ЗАЩИТА: Пропустить папки в filename_blacklist ("сборник", "компиляция", "антология")
   - Найти папку с названием автора (используя patterns)
   - ЕСЛИ НАЙДЕНА → author_source = "folder_dataset" (этот автор для ВСЕЙ иерархии под ней)
   - ПРИМЕР: /Books/Гоблин (MeXXanik)/Адвокат Чехов/book.fb2
     → Найти "Гоблин (MeXXanik)" на уровне 2 → folder_dataset="Гоблин (MeXXanik)"
     → ВСЕ файлы под "Гоблин (MeXXanik)/" получат этот folder_dataset

2. Попытка 2: Парсинг названия файла
   - Если Попытка 1 не дала результата
   - Проверить имя файла на наличие автора (используя patterns)
   - ПРИМЕР: "Гоблин - Адвокат Чехов.fb2" → "Гоблин"
   - author_source = "filename"

3. Попытка 3: Метаданные FB2
   - Если Попытка 1 и 2 не дали результата
   - Извлечь авторов из //fb:author в title-info
   - ПРИМЕР: FB2 XML содержит <first-name>Петр</first-name><last-name>Гоблин (MeXXanik)</last-name>
     → "Петр Гоблин (MeXXanik)"
   - author_source = "metadata"

4. Применить conversions на КАЖДОМ шаге:
   - "Гоблин (MeXXanik)" → "Гоблин MeXXanik"

5. Если авторов нет → proposed_author = "Сборник"

6. Создать BookRecord:
   - file_path = путь относительно library_path
   - metadata_authors = авторы из FB2 XML (хранять оригинал)
   - proposed_author = выбранный автор с применёнными conversions
   - author_source = "folder_dataset" / "filename" / "metadata" (в зависимости от источника)
   - file_title = название из FB2
```

**Пример 1: Поиск по папкам (множество авторских папок в одной библиотеке)**
```
Структура библиотеки:
/Books/
  ├─ Гоблин (MeXXanik)/
  │   ├─ Адвокат Чехов/book1.fb2
  │   ├─ Трое в лодке/book2.fb2
  │   └─ Серия/book3.fb2
  ├─ Другой Автор/
  │   ├─ Его Первая Книга/book4.fb2
  │   └─ Его Вторая Книга/book5.fb2
  └─ Третий/
      └─ book6.fb2

Обработка каждого файла в PASS 1:

Файл: book1.fb2 (/Books/Гоблин (MeXXanik)/Адвокат Чехов/book1.fb2)
  parents[0] = "Адвокат Чехов"
  parents[1] = "Гоблин (MeXXanik)" ← НАЙДЕНО! (не в blacklist)
  
  author_source = "folder_dataset"
  proposed_author = "Гоблин (MeXXanik)" → conversions → "Гоблин MeXXanik"
  ✅ Результат: folder_dataset="Гоблин MeXXanik" для ВСЕХ файлов под этой папкой

Файл: book4.fb2 (/Books/Другой Автор/Его Первая Книга/book4.fb2)
  parents[0] = "Его Первая Книга"
  parents[1] = "Другой Автор" ← НАЙДЕНО! (другой автор)
  
  author_source = "folder_dataset"
  proposed_author = "Другой Автор" → conversions → "Другой Автор"
  ✅ Результат: folder_dataset="Другой Автор" (ОТДЕЛЬНАЯ группа от book1)

Файл: book6.fb2 (/Books/Третий/book6.fb2)
  parents[0] = "Третий"
  parents[1] = "Books" → не похож на автора
  
  author_source = "folder_dataset" (найдено)
  proposed_author = "Третий"
  ✅ Результат: folder_dataset="Третий"

⭐ КЛЮЧЕВОЙ РЕЗУЛЬТАТ:
  - Все book1, book2, book3 получат folder_dataset="Гоблин MeXXanik"
  - All book4, book5 получат folder_dataset="Другой Автор"
  - book6 получит folder_dataset="Третий"
  - КАЖДАЯ авторская папка = отдельная группа!
```

**Пример 2: Защита от сборников в blacklist**
```
Структура:
/Books/
  └─ Сборник Разных Авторов/          ← В blacklist!
      ├─ Гоблин - Первая книга.fb2
      ├─ Другой - Вторая книга.fb2
      └─ Третий - Третья книга.fb2

Обработка: book.fb2 (Гоблин - Первая книга.fb2)
  parents[0] = "Гоблин - Первая книга.fb2" (сам файл)
  parents[1] = "Сборник Разных Авторов" ← В blacklist? ("Сборник") → ПРОПУСТИТЬ!
  
  ❌ Попытка 1 не дала результата (защита сработала)
  ✅ Переходим на Попытку 2: парсинг имени файла
  
  author = "Гоблин" (из "Гоблин - Первая книга.fb2")
  author_source = "filename"
```

#### PASS 2: Извлечение авторов из имён файлов (АКТИВЕН)

**Назначение:** Для файлов БЕЗ folder_dataset попытаться извлечь автора из имени файла по паттернам.

**Входные данные:**
- имя файла (без расширения)
- Набор паттернов из config.json: `author_series_patterns_in_files`
- Все BookRecords (для расширения авторов через соседние файлы)

**Паттерны в config.json (приоритет - по порядку, лучший паттерн выбирается по количеству совпадённых групп):**

```json
"author_series_patterns_in_files": [
  {"pattern": "(Author) - Title"},
  {"pattern": "Author - Title"},
  {"pattern": "Author. Title"},
  {"pattern": "Title (Author)"},
  {"pattern": "Title - (Author)"},
  {"pattern": "Author - Series.Title"},
  {"pattern": "Author. Series. Title"},
  {"pattern": "Author, Author. Title. (Series)"},
  {"pattern": "Author. Title. (Series)"},
  {"pattern": "Author - Title (Series. service_words)"},          ← 3 группы (наиболее полный)
  {"pattern": "Author. Title (Series. service_words)"},           ← 3 группы
  {"pattern": "Author, Author - Title (Series. service_words)"}  ← 3 группы (для multi-author)
]
```

**Логика выбора паттерна:**
1. Перебрать ВСЕ паттерны и проверить их на совпадение с именем файла
2. Найти паттерн с МАКСИМАЛЬНЫМ количеством совпадённых групп
3. ПРИОРИТЕТ: Паттерн с 3+ группами (автор + название + серия) > паттерн с 2 группами (автор + название)
4. **Пример:** Файл "Земляной Андрей - Проект «Оборотень» (Странник 1-3) - 2021.fb2"
   - Паттерн "Author - Title" → 2 группы, но захватывает весь текст до последней скобки (НЕПРАВИЛЬНО)
   - Паттерн "Author - Title (Series. service_words)" → 3 группы ✅ ВЫБРАН (разрешает текст после скобки)

**Regex для паттернов (в _file_pattern_to_regex):**

```python
{
    "Author - Title (Series. service_words)": (
        r'^(?P<author>[^-]+?)\s*-\s*(?P<title>[^(]+?)\s*\((?P<series>[^)]+)\)(?:\s*-\s*.+)?$',
        ['author', 'title', 'series']
    ),
    "Author. Title (Series. service_words)": (
        r'^(?P<author>[^.]+)\.\s*(?P<title>[^(]+?)\s*\((?P<series>[^)]+)\)$',
        ['author', 'title', 'series']
    ),
    "Author, Author - Title (Series. service_words)": (
        r'^(?P<author>[^-]+?\s*,\s*[^-]+?)\s*-\s*(?P<title>[^(]+?)\s*\((?P<series>[^)]+)\)(?:\s*-\s*.+)?$',
        ['author', 'title', 'series']
    ),
}
```

**Ключевые особенности:**
- ✅ `(?:\s*-\s*.+)?$` в конце позволяет дополнительный текст после скобки (например "- 2021")
- ✅ `[^-]+?` для автора использует non-greedy поиск до первого `-`
- ✅ Для multi-author паттерна разрешена запятая в группе автора

**Алгоритм PASS 2:**

```
Для каждого BookRecord с author_source != "folder_dataset":
  1. Получить имя файла (без расширения)
  2. Извлечь автора по лучшему совпадающему паттерну:
     _extract_author_from_filename_by_patterns(filename)
     
  3. Если автор найден:
     a) Очистить от паразитных символов: _clean_author_name()
        - Убрать цитаты: «» " '
        - Убрать содержимое скобок: (xxx) → пусто
        - Убрать trailing dots: "Демченко." → "Демченко"
        - Убрать unneeded commas: "Демченко," → "Демченко"
        - Нормализовать whitespace: multiple spaces → single space
        
     b) Обработать несколько авторов: _process_and_expand_authors()
        - Шаг 0: Удалить дубликаты в исходной строке ("Автор, Автор" → "Автор")
        - Шаг 1: Разбить по запятым на отдельные авторов
        - Шаг 2: Расширить каждого (попытаться найти полное имя в metadata):
          · Для 1-слова (фамилия): искать в metadata и соседних файлах
          · Для 2-слов: проверить если это полное имя или 2 разных автора
        - Шаг 3: Удалить дубликаты post-expansion (сохраняя порядок)
        - Шаг 3.5: ⭐ ОТСОРТИРОВАТЬ авторов по алфавиту (A-Z, А-Я)
        - Шаг 4: Объединить с разделителем "; " (точка-запятая-пробел)
        
  4. Установить: record.proposed_author = final_author
     record.author_source = "filename"
```

**Примеры обработки PASS 2:**

```
Случай 1: Простой multi-author файл
Filename: "Земляной Андрей, Орлов Борис - Академик (Странник 4-5) - 2022.fb2"
  Extracted: "Земляной Андрей, Орлов Борис"
  Cleaned: "Земляной Андрей, Орлов Борис"
  Expanded: "Земляной Андрей; Орлов Борис" (нашли в metadata)
  Sorted: "Земляной Андрей; Орлов Борис"
  ✅ Final: "Земляной Андрей; Орлов Борис"

Случай 2: 2-word name - может быть одним автором
Filename: "Авраменко Александр - Солдат удачи (Солдат удачи. Тетралогия).fb2"
Metadata: "Александр Авраменко"
  Extracted: "Авраменко Александр"
  Cleaned: "Авраменко Александр"
  Expansion check: 2 слова найдены в metadata как один автор ("Александр Авраменко")
  ✅ Final: "Авраменко Александр" (в format of metadata или нормализовано)

Случай 3: Single surname - расширить полным именем
Filename: "Демченко - Боярич (Воздушный стрелок 1-3).fb2"
Metadata: "Антон Демченко"
  Extracted: "Демченко"
  Cleaned: "Демченко"
  Expanded: Ищем "Демченко" в metadata → "Антон Демченко"
  ✅ Final: "Демченко Антон" (нормализовано)

Случай 4: Parasitic symbols
Filename: "Демченко. Боярич (Воздушный стрелок 1-3).fb2"
Metadata: "Антон Демченко"
  Extracted: "Демченко"
  Cleaned: "Демченко" (trailing dot removed)
  Expanded: "Демченко Антон"
  ✅ Final: "Демченко Антон"
```

**Сортировка авторов по алфавиту (Шаг 3.5):**

Когда несколько авторов найдены, они автоматически сортируются в алфавитном порядке:

```
Unsorted:  "Прозоров Александр; Живой Алексей"
Sorted:    "Живой Алексей; Прозоров Александр"  ← А < П

Unsorted:  "Орлов Борис; Земляной Андрей"  
Sorted:    "Земляной Андрей; Орлов Борис"   ← З < О
```

**Функция сортировки:**
```python
# После этапа 3 (удаление дубликатов):
unique_authors.sort()  # ← встроенная Python функция, работает по Unicode

# Результат объединяется с разделителем "; "
return "; ".join(unique_authors)
```

#### PASS 3: Нормализация авторов

**Алгоритм:**
```
Для каждого BookRecord:
  1. Если proposed_author == "Сборник" → пропустить
  2. Применить extractor._normalize_author_format(proposed_author)
     Нормализует: "Иван Петров" → "Петров Иван"
     Сохраняет аббревиатуры: "Петров И." → "Петров И."
  3. Если changed → логирование "[PASS 3] Нормализация: 'было' → 'стало'"
```

**Примеры:**
```
"Иван Петров"       → "Петров Иван"
"Петров Иван Сергеевич" → "Петров Иван"  (с опциональным отчеством)
"Петров И."         → "Петров И."          (не меняется)
"Гоблин"            → "Гоблин"             (одно слово - не меняется)
```

#### PASS 4: Применение консенсуса

**Проблема:** Если 5 файлов одного автора в одной папке, но 1 файл имеет другого автора в метаданных → какого выбрать?

**⚠️ КРИТИЧЕСКОЕ ПРАВИЛО:** Консенсус применяется ТОЛЬКО к файлам с author_source="filename" или "metadata"

**Если author_source="folder_dataset" → НЕ переписывать!** Это уже окончательное значение.

**Алгоритм:**
```
1. Сгруппировать BookRecords по папке (file_path.parent)
2. Для каждой группы файлов:
   a) Отфильтровать файлы с author_source="folder_dataset" → пропустить их
   b) Для оставшихся файлов (source="filename" или "metadata"):
      - Найти консенсусного автора (самый частый)
      - Применить нормализацию к автору
      - Применить консенсус ко всем оставшимся файлам группы
      - Установить author_source = "consensus"
```

**Почему это важно:**
Если в папке есть files с folder_dataset и без:
```
/Books/Серия1/
  book1.fb2 → author_source="folder_dataset" ("Гоблин") ← НЕ МЕНЯТЬ!
  book2.fb2 → author_source="metadata" ("Другой")     ← применить консенсус
  book3.fb2 → author_source="metadata" ("Гоблин")     ← применить консенсус
  
  Консенсус для book2, book3: "Гоблин" (2 из 2 оставшихся = 100%)
  Результат: book1 остаётся "Гоблин" (folder_dataset), book2,3 → "Гоблин" (consensus)
```

**Пример:**
```
Папка: /Серия - Фантастически боевик/
  book1.fb2 → proposed_author = "Гоблин MeXXanik", author_source = "metadata"
  book2.fb2 → proposed_author = "MeXXanik Гоблин", author_source = "metadata"
  book3.fb2 → proposed_author = "Гоблин", author_source = "metadata"
  book4.fb2 → proposed_author = "Гоблин MeXXanik", author_source = "metadata"
  book5.fb2 → proposed_author = "Другой Автор", author_source = "metadata"

Консенсус: "Гоблин MeXXanik" (3 из 5)
Результат: ВСЕ 5 файлов → proposed_author = "Гоблин MeXXanik", author_source = cons
```

#### PASS 5: Применение конвертаций фамилий (Второе применение)

**Алгоритм:**
```
1. Для каждого BookRecord:
   a) Если proposed_author == "Сборник" → пропустить
   b) Применить author_utils.apply_surname_conversions(proposed_author)
   c) Если changed → логирование
   d) Затем применить extractor._normalize_author_format() на результат
```

**Почему два раза?**
- PASS 1: Применяем сразу при чтении FB2
- PASS 5: Переприменяем после консенсуса (может понадобиться, если консенсус изменил автора)

**Пример:**
```
После PASS 4: proposed_author = "Гоблин (MeXXanik)"
PASS 5: Применить conversions → "Гоблин MeXXanik"
```

#### PASS 6: Раскрытие аббревиатур

**Алгоритм:**
```
1. Построить словарь полных имён из всех proposed_author и метаданных:
   authors_map = {
     "петров": ["Петров Иван", "Петров Сергей"],
     "гоблин": ["Гоблин MeXXanik"]
   }

2. Для каждого BookRecord:
   a) Если proposed_author содержит точку (аббревиатура):
      "И.Петров" → "Иван Петров" (поиск в authors_map)
   b) Если не найдено → оставить как есть
   c) Если changed → логирование
```

**Примеры:**
```
"И.Петров"       → "Иван Петров"   (найдено в authors_map)
"С.Гоблин"       → остаётся как есть (не найдено)
"Гоблин MeXXanik" → не меняется (нет точек)
```

---

## 5. Класс BookRecord

```python
@dataclass
class BookRecord:
    """Запись о книге с прогрессивным заполнением на разных PASS."""
    
    file_path: str              # Путь к FB2 файлу (относительно library_path)
    metadata_authors: str       # Исходные авторы из FB2 XML
    proposed_author: str        # Предложенный итоговый автор (evolves через PASS)
    author_source: str          # Источник: "metadata", "folder_dataset", "filename", etc
    file_title: str             # Название книги из title-info
    file_path_normalized: str   # Нормализованный путь (опционально)
```

**Как заполняется:**

```
PASS 1:
  file_path = "Гоблин/Адвокат Чехов/book.fb2"
  metadata_authors = "Петр Гоблин (MeXXanik)"
  proposed_author = "Петр Гоблин MeXXanik"    ← conversions применены
  author_source = "metadata"
  file_title = "Адвокат Чехов"

PASS 3:
  proposed_author = "Гоблин MeXXanik Петр"    ← normalized format

PASS 4:
  (без изменений в этом примере, консенсус совпал)

PASS 5:
  proposed_author = "Гоблин MeXXanik"         ← conversions переприменены

PASS 6:
  (без изменений, нет аббревиатур)

```

---

## 6. CSV Выход: Структура файла

### 6.1 Перечень колонок (в порядке слева направо)

| № | Колонка | Тип | Описание | Пример |
|---|---------|-----|---------|--------|
| 1 | `file_path` | str | Путь к FB2 файлу относительно library_path | `Гоблин (MeXXanik)/Адвокат Чехов/book1.fb2` |
| 2 | `metadata_authors` | str | Оригинальные авторы из FB2 XML (неизменяемое) | `Петр Гоблин (MeXXanik)` |
| 3 | `proposed_author` | str | Финальный автор после всех PASS (эволюция по PASS) | `Гоблин MeXXanik` |
| 4 | `author_source` | str | Источник автора (PASS 1 результат) | `folder_dataset` / `filename` / `metadata` / `consensus` |
| 5 | `metadata_series` | str | Оригинальное название серии из FB2 XML (неизменяемое) | `Адвокат Чехов` |
| 6 | `proposed_series` | str | Финальная серия после всех PASS (эволюция по PASS) | `Адвокат Чехов` |
| 7 | `series_source` | str | Источник серии (PASS 1 результат) | `folder_dataset` / `filename` / `metadata` / `consensus` |
| 8 | `file_title` | str | Название книги (из FB2 title-info) | `Первое дело` |


### 6.2 Примеры строк CSV

```csv
file_path,metadata_authors,proposed_author,author_source,metadata_series,proposed_series,series_source,file_title
Гоблин (MeXXanik)/Адвокат Чехов/book1.fb2,Петр Гоблин (MeXXanik),Гоблин MeXXanik,folder_dataset,Адвокат Чехов,Адвокат Чехов,folder_dataset,Адвокат Чехов
Развлечение/Книга от файла.fb2,Неизвестный Автор,Развлечение,filename,,Развлечение,filename,Книга от файла
Сборник/book3.fb2,Иван Петров,Петров Иван,metadata,,Петров Иван,metadata,Третья книга
Компиляция/Серия1/book4.fb2,Петр Гоблин,Гоблин MeXXanik,consensus,Серия1,Сборник,consensus,Четвертая
```

### 6.3 Эволюция `proposed_author` и `proposed_series` по PASS

```
PASS 1 (init):    author: "Петр Гоблин (MeXXanik)" (с conversions) → "Гоблин MeXXanik"
                  series: "Адвокат Чехов" → "Адвокат Чехов"
                  author_source = "folder_dataset", series_source = "folder_dataset"

PASS 2 (filename): author: "Гоблин MeXXanik" → "Гоблин MeXXanik" (из имени файла)
                  Если несколько авторов:
                    - "Гоблин, Петров" → "Гоблин MeXXanik; Петров Иван" (sorted alphabetically!)
                  series: извлечено из скобок в имени файла
                  author_source = "filename"

PASS 3:           author: "Гоблин MeXXanik" → "MeXXanik Гоблин" (нормализация формата)
                  series: без изменений
                  (если нужна перестановка)

PASS 4:           author: "MeXXanik Гоблин" → "Гоблин MeXXanik" (консенсус применен)
                  series: без изменений (может измениться позже)
                  author_source = "consensus", series_source = "consensus" (если был consensus)

PASS 5:           author: "Гоблин MeXXanik" → "Гоблин MeXXanik" (conversions переприменены)
                  series: без изменений

PASS 6:           author: "Г.MeXXanik" → "Гоблин MeXXanik" (аббревиатуры раскрыты)
                  series: без изменений

FINAL CSV ROW:    file_path | metadata_authors | proposed_author | author_source | metadata_series | proposed_series | series_source | file_title

⭐ КЛЮЧЕВОЕ ИЗМЕНЕНИЕ В PASS 2:
   - Multi-author файлы теперь обрабатываются через прямой паттерн
   - Авторы автоматически СОРТИРУЮТСЯ по алфавиту перед объединением
   - Разделитель: "; " (точка-запятая-пробел), НЕ запятая
   - Пример: "Земляной Андрей, Орлов Борис" → "Земляной Андрей; Орлов Борис"
```

### 6.4 Порядок сохранения

```python
# После завершения всех PASS:
# 1. Отсортировать records по file_path (для консистентности)
# 2. Открыть файл CSV (обычно regen.csv или с timestamp)
# 3. Написать header: file_path,metadata_authors,proposed_author,author_source,metadata_series,proposed_series,series_source,file_title
# 4. Для каждого BookRecord:
#    - Экранировать значения (кавычки если содержит запятую)
#    - Написать строку CSV в порядке: file_path, metadata_authors, proposed_author, author_source, metadata_series, proposed_series, series_source, file_title
# 5. Закрыть файл
```

---

## 7. Примеры использования параметров

### 7.1 Пример 1: Проверка на мусор

```python
blacklist = settings.get_filename_blacklist()
# blacklist = ["компиляция", "сборник", "антология", ...]

if any(word in proposed_author.lower() for word in blacklist):
    # Это скорее всего название папки, а не автор
    skip_record = True
```

### 6.2 Пример 2: Определение порядка имени/фамилии

```python
male_names = set(n.lower() for n in settings.get_male_names())
female_names = set(n.lower() for n in settings.get_female_names())
all_names = male_names | female_names

author = "Иван Петров"
first_word = author.split()[0].lower()

if first_word in all_names:
    order = "Имя Фамилия"  # Иван - известное имя
    # Преобразовать в "Петров Иван"
else:
    order = "Фамилия Имя или неизвестно"
```

### 6.3 Пример 3: Применение конвертаций

```python
conversions = settings.get_author_surname_conversions()
# conversions = {
#     "Гоблин (MeXXanik)": "Гоблин MeXXanik",
#     "Айзенберг": "Берг",
#     ...
# }

original = "Петр Гоблин (MeXXanik)"
if "Гоблин (MeXXanik)" in original:
    converted = original.replace("Гоблин (MeXXanik)", conversions["Гоблин (MeXXanik)"])
    # Результат: "Петр Гоблин MeXXanik"
```

### 6.4 Пример 4: Определение глубины парсинга папок

```python
folder_parse_limit = settings.get_folder_parse_limit()  # 3

file_path = Path("Гоблин (MeXXanik)/Адвокат Чехов/book.fb2")

# Поиск автора вверх на максимум 3 уровня
for i in range(min(folder_parse_limit, len(file_path.parts)-1)):
    parent = file_path.parents[i]
    # Анализировать parent для поиска автора
```

---

## 7. Интеграция с другими модулями

### 7.1 Зависимости в __init__

```python
from settings_manager import SettingsManager
from logger import Logger
from fb2_author_extractor import FB2AuthorExtractor
from author_normalizer_extended import AuthorNormalizerExtended  # Новый объединённый модуль
```

### 7.2 Инициализация в RegenCSVService.__init__

```python
class RegenCSVService:
    def __init__(self, settings_manager=None):
        self.settings = settings_manager or SettingsManager('config.json')
        self.logger = Logger()
        self.extractor = FB2AuthorExtractor('config.json')
        self.normalizer = AuthorNormalizerExtended(self.settings, self.extractor)
        
        # Параметры
        self.folder_parse_limit = self.settings.get_folder_parse_limit()
        self.data_dir = Path(self.settings.get_library_path())
        self.output_csv = Path(self.settings.get_last_scan_path()) / "regen.csv"
```

---

## 8. Изменение архитектуры

### 8.1 ДО (старая система - удаляется)

```
regen_csv.py (1459 строк)
├── Парсинг папок (PASS 1) ❌ УДАЛИТЬ
├── Обработка FB2 (PASS 2) ❌ УДАЛИТЬ
├── Нормализация (PASS 3)  ✅ СОХРАНИТЬ
├── Консенсус (PASS 4)     ✅ СОХРАНИТЬ
├── Конвертации (PASS 5)   ✅ СОХРАНИТЬ
└── Раскрытие (PASS 6)     ✅ СОХРАНИТЬ
```

### 8.2 ПОСЛЕ (новая система - создаётся)

```
author_normalizer_extended.py (объединённый)
├── AuthorName (из name_normalizer.py)
├── AuthorNormalizerExtended (новый класс)
│   ├── normalize_single_name()
│   ├── validate_author_name()
│   ├── apply_surname_conversions()
│   ├── apply_surname_conversions_to_records()
│   ├── expand_abbreviated_authors()
│   └── apply_author_consensus()
└── Вспомогательные функции

regen_csv.py (новый - ~500 строк)
├── BookRecord
├── RegenCSVService
│   ├── PASS 1: _read_fb2_files()
│   │
│   ├── PASS 2: _extract_author_from_filename_by_patterns()
│   │   ├── _file_pattern_to_regex()          ← new: паттерны -> regex
│   │   ├── _clean_author_name()              ← new: убрать паразитные символы
│   │   ├── _expand_author_to_full_name()     ← new: расширить из metadata
│   │   └── _process_and_expand_authors()     ← new: оркестрировать pipeline
│   │
│   ├── PASS 3: _normalize_authors()
│   ├── PASS 4: _apply_consensus()
│   ├── PASS 5: _apply_conversions()
│   ├── PASS 6: _expand_abbreviations()
│   ├── _read_fb2_metadata()
│   ├── _save_csv()
│   └── regenerate()
└── if __name__ == "__main__": service.regenerate()

settings_manager.py          ← без изменений
fb2_author_extractor.py      ← используется как зависимость
logger.py                    ← без изменений
```

**Новые функции в PASS 2:**

| Функция | Параметры | Возвращает | Назначение |
|---------|-----------|-----------|-----------|
| `_file_pattern_to_regex()` | pattern_desc: str | Tuple[str, List[str]] | Конвертировать описание паттерна ("Author - Title") в regex с группами |
| `_extract_author_from_filename_by_patterns()` | filename: str | Optional[str] | Извлечь автора из имени файла по наиболее полному паттерну (по количеству групп) |
| `_clean_author_name()` | extracted_author: str | str | Очистить от цитат, скобок, trailing dots, нормализовать whitespace |
| `_expand_author_to_full_name()` | partial_author: str, metadata_authors: str | str | Расширить "Фамилия" до "Фамилия Имя" используя metadata |
| `_process_and_expand_authors()` | cleaned_author: str, current_record: BookRecord, all_records: List[BookRecord] | str | Полный pipeline: split → expand → deduplicate → **sort** → join с "; " |

**Ключевые особенности новой логики PASS 2:**

✅ Лучший паттерн выбирается по количеству совпадённых групп (3 группы > 2 группы)
✅ Автоматическое расширение неполных фамилий через metadata и соседние файлы
✅ **Сортировка авторов по алфавиту перед объединением**
✅ Разделитель "; " (точка-запятая-пробел) для multi-author записей
✅ Дедупликация авторов на каждом шаге
```

---

## 9. Взаимодействие компонентов

```
┌─────────────────────────────────────┐
│  RegenCSVService.regenerate()       │
│  Главный цикл обработки CSV         │
└──────────────────┬──────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
   PASS 1-6            Settings & Config
   read & process      SettingsManager
        │              │
        ├→ Logger       ├→ folder_parse_limit
        │              ├→ male_names
        └→ FB2AuthorExtractor
           │            ├→ female_names
           ├→ _normalize_author_format()
           │            ├→ author_surname_conversions
           └→ expand methods
                        ├→ filename_blacklist
                        └→ service_words

   AuthorNormalizerExtended
   ├→ apply_surname_conversions()
   ├→ apply_author_consensus()
   ├→ expand_abbreviated_authors()
   └→ build_authors_map()
```

---

## 10. Критические параметры конфига, используемые в regen_csv.py

| Параметр | Тип | Используется в | Функция | Пример |
|---|---|---|---|---|
| `folder_parse_limit` | int | PASS 1 (stub) | Глубина поиска папок | 3 |
| `author_surname_conversions` | Dict | PASS 1, 5 | Конвертация фамилий | `{"Гоблин (MeXXanik)": "Гоблин MeXXanik"}` |
| `male_names` | List | PASS 3, 6 | Определение порядка имён | `["Александр", "Андрей", ...]` |
| `female_names` | List | PASS 3, 6 | Определение порядка имён | `["Александра", "Анна", ...]` |
| `filename_blacklist` | List | PASS 1, 3 | Фильтрация мусора | `["сборник", "антология", ...]` |
| `library_path` | str | PASS 1 | Папка с FB2 файлами | `"C:/Users/.../EBook Library"` |
| `generate_csv` | bool | Главный цикл | Генерировать ли CSV | `true` |
| `author_series_patterns_in_files` | List[Dict] | PASS 2 | Паттерны для извлечения авторов из имён файлов | [см. ниже] |

### 10.1 Паттерны для PASS 2: author_series_patterns_in_files

После исправления (Feb 2026):

```json
"author_series_patterns_in_files": [
  {
    "pattern": "(Author) - Title",
    "example": "(Иван Петров) - История России.fb2"
  },
  {
    "pattern": "Author - Title",
    "example": "Иван Петров - История России.fb2"
  },
  {
    "pattern": "Author. Title",
    "example": "Белоус. Последний шанс человечества.fb2"
  },
  {
    "pattern": "Title (Author)",
    "example": "Война и мир (Лев Толстой).fb2"
  },
  {
    "pattern": "Title - (Author)",
    "example": "Война и мир - (Лев Толстой).fb2"
  },
  {
    "pattern": "Author - Series.Title",
    "example": "Авраменко Александр - Солдат удачи 1. Солдат удачи.fb2"
  },
  {
    "pattern": "Author. Series. Title",
    "example": "Анисимов. Вариант «Бис» 2. Год мертвой змеи.fb2"
  },
  {
    "pattern": "Author, Author. Title. (Series)",
    "example": "Живой, Прозоров. Легион (Легион 1-3).fb2"
  },
  {
    "pattern": "Author. Title. (Series)",
    "example": "Анисимов. Вариант «Бис» 2. Год мертвой змеи.fb2"
  },
  {
    "pattern": "Author - Title (Series. service_words)",
    "example": "Авраменко Александр - Солдат удачи (Солдат удачи. Тетралогия).fb2",
    "note": "FIXED Feb 2026: Теперь позволяет текст после скобки (e.g., ' - 2021')"
  },
  {
    "pattern": "Author. Title (Series. service_words)",
    "example": "Демченко. Хольмградские истории (Хольмградские истории. Трилогия).fb2"
  },
  {
    "pattern": "Author, Author - Title (Series. service_words)",
    "example": "Земляной Андрей, Орлов Борис - Академик (Странник 4-5) - 2022.fb2",
    "note": "NEW Feb 2026: Паттерн для multi-author файлов с серией в скобках"
  }
]
```

**Изменения в Feb 2026:**
- ✅ Исправлен regex для "Author - Title (Series. service_words)" - теперь позволяет текст после закрывающей скобки
- ✅ Добавлен новый паттерн "Author, Author - Title (Series. service_words)" для multi-author файлов
- ✅ Все паттерны теперь учитывают возможность служебных слов в series (том, книга, часть, тетралогия, дилогия, и т.д.)

---

## 11. Исправления и улучшения логики парсинга (Feb 2026)

### 11.1 Commit 5431307: Исправление потери фамилии при расширении имени

**Проблема:** "Иванов Дмитрий" из файла → "Дмитрий" в выводе

**Причина:** Функция `_expand_author_to_full_name()` заменяла более полную версию из имени файла на менее полную из метаданных.

**Решение:**
```python
# Добавлена проверка количества слов перед заменой
if len(words) > len(full_name_words):
    return partial_author  # Более полная версия из filename
else:
    return full_name  # Более полная версия из metadata
```

**Результат:** "Иванов Дмитрий" остаётся неизменным

---

### 11.2 Commit 0e2478a: Сохранение порядка слов в имени

**Проблема:** "Тё Илья" из файла → "Илья Те" (перепутанный порядок слов)

**Причина:** Функция находила оба слова в метаданных но в другом порядке, возвращала версию из метаданных.

**Решение:**
```python
# Проверка если одни и те же слова в разном порядке
partial_words_set = set(w.lower() for w in words)
full_name_words_set = set(w.lower() for w in full_name_words)
if (len(words) == len(full_name_words) and 
    partial_words_set == full_name_words_set):
    return partial_author  # Сохраняем порядок из filename
```

**Результат:** "Те Илья" сохраняет правильный порядок слов

---

### 11.3 Commit 8b3875b: Сбор всех соавторов-однофамильцев

**Проблема:** Filename "Белаш" + metadata "Людмила Белаш; Александр Белаш" → только один автор

**Причина:** Функция возвращалась сразу после первого совпадения в цикле.

**Решение:**
```python
matching_authors = []  # Собираем ВСЕ авторов
for full_name in metadata_authors_list:
    if surname_matches(full_name, surname):
        matching_authors.append(full_name)

# Если нашли авторов - вернуть их
if matching_authors:
    if len(matching_authors) > 1:
        matching_authors.sort()
        return "; ".join(matching_authors)
```

**Результат:** "Александр Белаш; Людмила Белаш" (оба соавтора), отсортированы

---

### 11.4 Commit 1d0d26f: Дебаг и оптимизация PASS 2 - кеширование папок + поддержка неизвестных авторов

**Проблемы:**
1. Папка "Жеребьёв" парсилась для каждого файла отдельно (неэффективно)
2. "Жеребьёв" не в known_authors → `_contains_author_name()` возвращал False
3. CSV ошибочно показывал proposed_author = "ЛенИздат" (из папки) вместо "Жеребьёв"

**Решения:**

#### A. Кеширование результатов парсинга папок в PASS 2
```python
folder_cache = {}  # Ключ: папка, Значение: автор

for folder_path in parts_to_check:
    if folder_path in folder_cache:
        parsed_author = folder_cache[folder_path]
    else:
        parsed_author = self._parse_author_from_folder_name(folder_name)
        folder_cache[folder_path] = parsed_author  # Кешируем
```

**Эффект:** Каждая папка парсится один раз для всех файлов внутри неё → консистентность и оптимизация

#### B. Нормализация диакритики в `_contains_author_name()`
```python
def _normalize_diacritics(self, text: str) -> str:
    """Жеребьёв → жеребьев"""
    nfd = unicodedata.normalize('NFD', text)
    return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')

# В проверке:
text_normalized = self._normalize_diacritics(text_lower)
```

**Эффект:** "Жеребьёв" (с ё) теперь совпадает с "жеребьев" (без диакритики) в конфиге

#### C. Поддержка неизвестных авторов через `_looks_like_author_name()`
```python
# Проверяет структуру имени БЕЗ требования быть в known_authors
def _looks_like_author_name(self, text: str) -> bool:
    if len(text) < 2 or len(text) > 100:
        return False
    has_letter = any(c.isalpha() for c in text)
    if not has_letter:
        return False
    # Нет подозрительных символов и чисел
    return True

# В extraction:
if self._contains_author_name(author) or self._looks_like_author_name(author):
    best_author = author
```

**Эффект:** "Жеребьёв" теперь извлекается из filename даже если не в known_authors

**Результат:**
```
proposed_author: "Владислав Жеребьев" (вместо ошибочного "ЛенИздат")
normalized_author: "Жеребьев Владислав"
source: "filename"
```

---

### 11.5 Commit 9bd28a8: Поддержка множественного числа фамилий для соавторов

**Проблема:** Filename "Каменские - Витязь.fb2" (множественное число) + metadata "Юрий Каменский; Вера Каменская" → оба автора теряются

**Причина:** "Каменские" не совпадал с "Каменский" или "Каменская"

**Решения:**

#### A. Функция `_extract_surname_from_fullname()` - правильное извлечение фамилии
```python
def _extract_surname_from_fullname(self, full_name: str) -> str:
    """Извлекает фамилию из полного имени, проверяя каждое слово против known_names
    
    Логика:
    1. Разбиваем на слова
    2. Ищем какое слово есть в known_names (это ИМЯ)
    3. Остальное = ФАМИЛИЯ
    4. Пропускаем инициалы (А., А.В., А.В.М.)
    
    Работает для любого порядка:
    - "Юрий Каменский" → "Каменский"
    - "Каменский Юрий" → "Каменский"
    - "А.В. Чехов" → "Чехов"
    - "Чехов А.В." → "Чехов"
    """
```

**Ключевая особенность:** Не предполагает, что фамилия всегда в конце или в начале - проверяет против `known_names`

#### B. Функция `_normalize_surname_endings()` - нормализация окончаний
```python
def _normalize_surname_endings(self, surname: str) -> str:
    """Удаляет гендерные окончания русских фамилий
    
    Каменские → Каменск (множественное число)
    Каменский → Каменск (мужское)
    Каменская → Каменск (женское)
    Кольцкие → Кольц
    Кольцкий → Кольц
    Кольцкая → Кольц
    """
```

#### C. Обновлена `_expand_author_to_full_name()` для использования новых функций
```python
# Извлекаем фамилию правильно
metadata_surname = self._extract_surname_from_fullname(full_name)
metadata_surname_normalized = self._normalize_surname_endings(metadata_surname)

# Сравниваем нормализованные корни
if surname_normalized_lower == metadata_surname_normalized_lower:
    matching_authors.append(full_name)
```

**Результат:**
```
filename: "Каменские - Витязь специального назначения.fb2"
proposed_author: "Юрий Каменский; Вера Каменская"
normalized_author: "Каменская Вера, Каменский Юрий"
```

**Преимущества:**
- Универсальная логика для любого порядка слов в имени
- Правильная обработка инициалов и гендерных окончаний
- Собирает ВСЕ соавторов с одинаковой фамилией

---

## Готово.
