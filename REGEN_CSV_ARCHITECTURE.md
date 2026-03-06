# Архитектура системы регенерации CSV (Версия 2.6)

**📌 Дополнительная документация по поддержке соавторства (Co-authorship):** см. [COAUTHORSHIP_FEATURE.md](COAUTHORSHIP_FEATURE.md)

**📋 Полная история изменений и исправлений:** см. [CHANGELOG.md](CHANGELOG.md)

**🆕 Март 6, 2026 - ИСПРАВЛЕНИЕ КРИТИЧЕСКИХ ОШИБОК В СИСТЕМЕ ИЗВЛЕЧЕНИЯ СЕРИЙ**

#### 1️⃣ Исправление приоритета паттернов (Pattern Scoring Fix)
- **Проблема:** Паттерны извлекающие служебные слова ("Тетралогия", "Дилогия") имели более высокий score чем паттерны извлекающие реальные названия серий
  - Файл: `"Янковский Дмитрий - Охотник (Тетралогия).fb2"`
  - Ожидается: `proposed_series="Охотник"` (реальное имя серии)
  - Было: `proposed_series=""` (fallback к metadata "Правила подводной охоты")
  
- **Корневая причина:** Функция `_score_pattern_match()` давала бонус +3 за "скобки серии" для всех паттернов типа `"Author - Title (Series. service_words)"`, даже если они извлекали служебное слово
  
- **Решение:** Модифицирована логика бонуса в `_score_pattern_match()`:
  ```python
  # Бонус +3 только если extracted_series НЕ является serve_word
  if pattern in bracket_series_patterns:
      # Проверяем что extracted_series это не service_word
      is_service_word = any(
          extracted_series_lower == sw.lower() 
          for sw in self.service_words
      )
      if not is_service_word:
          score += 3  # Только если это реальное имя серии
  ```
  
- **Результат:** Паттерн #10 "Author - Series (service_words)" теперь получает лучший score и выбирается вместо паттернов #11-14
- **Реализация:** [passes/pass2_series_filename.py](passes/pass2_series_filename.py) линия 1437-1448

#### 2️⃣ Исправление валидации с учётом контекста автора (Validation Context Fix)
- **Проблема:** Валидация отвергала серии которые выглядели как фамилии, даже если это были другие слова
  - Файл: `"Филимонов Олег - Злой среди чужих (Сид 1. ...)"`
  - Проблема: `AuthorName("Сид").is_valid` → `True` (плутал за фамилию)
  - Было: `proposed_series=""` (валидация отвергла "Сид" как потенциальную фамилию)
  
- **Решение:** Улучшена функция `_is_valid_series()` с поддержкой контекста автора:
  ```python
  def _is_valid_series(self, text, extracted_author=None, skip_author_check=False):
      # Если extracted_author передан и отличается от text (после нормализации)
      # → text это не автор, а серия!
      if extracted_author:
          extracted_author_normalized = AuthorName(extracted_author).normalized
          text_normalized = AuthorName(text).normalized
          if extracted_author_normalized != text_normalized:
              return True  # Разные люди → text это серия
  ```
  
- **Результат:** "Сид" принимается как валидная серия когда автор "Филимонов Олег"
- **Реализация:** [passes/pass2_series_filename.py](passes/pass2_series_filename.py) линия 1067-1180

#### 3️⃣ Исправление false-positive в проверке blacklist (Blacklist Word Boundary Fix)
- **Проблема:** Blacklist проверка использовала substring matching, что давала false-positive
  - `filename_blacklist` содержит: `"СИ"` (метатег самиздата)
  - Файл: `"Филимонов Олег - Злой среди чужих (Сид 1. ...)"`
  - Ошибка: Проверка находила `"СИ"` в `"Сид 1"` и отвергала всю серию!
  
- **Решение:** Изменена проверка на word boundary с использованием regex:
  ```python
  # Вместо: if bl_word.lower() in text_lower:
  # Теперь:
  pattern = r'(?:^|\s|\(|-)' + re.escape(bl_word_lower) + r'(?:\s|\)|$)'
  if re.search(pattern, text_lower):
      return False  # Отвергнуть только если целое слово
  ```
  
- **Результат:** "Сид" теперь не блокируется blacklist словом "СИ"
- **Реализация:** [passes/pass2_series_filename.py](passes/pass2_series_filename.py) линия 1105-1116

**🆕 Март 6, 2026 (Третья волна) - ИСПРАВЛЕНИЕ: Context-aware validation для серий**

#### 5️⃣ Context-Aware Series Validation (Pass2 Series Filename)
- **Проблема:** Серии которые выглядят как имена人  отвергались валидацией
  - Файл: `"Роберт Дж. Сойер\Сойер. Неандертальский параллакс 01. Гоминиды.fb2"`
  - Проблема: `proposed_series` была пуста вместо **"Неандертальский параллакс"**
  - Причина: Словосочетание "Неандертальский параллакс" выглядит как имя → валидация отвергала
  - Логика: `AuthorName('Неандертальский параллакс').is_valid = True` = похоже на фамилию
  
- **Корневая причина:** Валидация не получала контекст какой автор был уже определён
  - Когда предложенный автор "Сойер Роберт" ≠ "Неандертальский параллакс" → это другой объект!
  - Но валидация не знала об авторе и только видела "Коротко Имя" структуру
  
- **Решение:** Передано `extracted_author` во все вызовы `_is_valid_series()` для валидации metadata/fallback
  ```python
  # БЫЛО (неправильно):
  if self._is_valid_series(series):  # Без контекста - может быть названо как имя
  
  # СТАЛО (правильно):
  extracted_author = record.proposed_author if record.proposed_author else None
  if self._is_valid_series(series, extracted_author=extracted_author):  # С контекстом!
  ```
  
- **Результат:** "Неандертальский параллакс" теперь принимается как валидная серия когда автор "Сойер Роберт"
- **Реализация:** [passes/pass2_series_filename.py](passes/pass2_series_filename.py) обновлены все вызовы валидации с контекстом автора

**🆕 Март 6, 2026 (Вторая волна) - ИСПРАВЛЕНИЕ: Удаление конфликтующей metadata проверки в Pass4**

#### 4️⃣ Удаление METADATA AUTHOR CONFIRMATION Logic (Pass4 Optimization)
- **Проблема:** Pass4 содержал логику "METADATA AUTHOR CONFIRMATION" которая пыталась "улучшить" авторов через cross-check с metadata
  - Файл: `"Волков Тим\Земля живых.fb2"`
  - Проблема: proposed_author был **"Волков Вадим"** вместо правильного **"Волков Тим"**
  - Причина: Логика нашла в metadata "Вадима Волкова" вместо "Тима Волкова" и заменила!
  
- **Корневая причина:** Фундаментально неправильный подход в Pass4:
  - `author_source="folder_dataset"` означает авторитетный источник (user-created folder hierarchy)
  - Попытка улучшить через metadata разрушает уверенность в folder-based extraction
  - Это затратно по ресурсам (требует парсинга всех FB2 файлов)
  - И малоэффективно (metadata часто худшего качества, чем папки)
  
- **Решение:** Удалена вся "METADATA AUTHOR CONFIRMATION" логика:
  ```python
  # БЫЛО (неправильно):
  # Если в metadata найден автор с совпадающей фамилией → заменить!
  
  # СТАЛО (правильно):
  # folder_dataset → ОКОНЧАТЕЛЬНЫЙ источник, никогда не менять
  # filename → может проверить с metadata если extraction неполная
  # metadata → достаточен сам по себе, не нужна перепроверка
  ```
  
- **Результат:** Файл "Земля живых" теперь правильно сохраняет `proposed_author="Волков Тим"`
- **Реализация:** [passes/pass4_consensus.py](passes/pass4_consensus.py) удалена неправильная логика (строки ~104-144 в старой версии)

**🆕 Март 2, 2026 - ИСПРАВЛЕНИЕ: Штраф за blacklist в выборе паттернов**
- ✅ **Новый паттерн:** `"Author - Series service_words. Title"` для файлов типа `"Игнатов Михаил - Путь 10. Защитник. Второй пояс (СИ).fb2"`
  - Извлекает серию между автором и номером книги
  - Пример: `"Игнатов Михаил - Путь 10."` → `"Путь"`
  - Реализация: [passes/pass2_series_filename.py](passes/pass2_series_filename.py) метод `_apply_config_pattern()` (линия ~929-936)

- ✅ **Критический штраф за blacklist в scoring:**
  - Проблема: Паттерн `"Author - Title (Series. service_words)"` имел более высокий score (55) и извлекал `"СИ"` из скобок, несмотря на то что `"СИ"` в blacklist
  - Решение: Добавлен штраф `-100` за любое слово из blacklist_filename в функции `_score_pattern_match()`
  - Результат: Паттерны с blacklisted словами получают отрицательный или очень низкий score и не выбираются
  - Реализация: [passes/pass2_series_filename.py](passes/pass2_series_filename.py) метод `_score_pattern_match()` (линия ~1260-1272)

- ✅ **Дополнительная проверка blacklist:**
  - После выбора best_series по score, проверяется blacklist перед возвращением результата
  - Если result в blacklist → игнорируется и перейти к следующему правилу (Правило 1, 2, 3...)
  - Реализация: [passes/pass2_series_filename.py](passes/pass2_series_filename.py) линия ~752-760

- 📝 **Результаты:** 
  - Файлы Игнатова (Путь 1-16) теперь корректно показывают `proposed_series="Путь"` вместо `"СИ"`
  - Логика автоматически выбирает лучший паттерн без перестановок - всегда работает правильное ранжирование

**🆕 Февраль 26, 2026 - ИСПРАВЛЕНИЕ: Очистка номеров томов и метаданные для уточнения серий**
- ✅ **Новый метод для очистки:** `_clean_series_name()` удаляет паразитные номера томов из названий серий
  - Паттерн 1: `"Солдат удачи 3. Взор Тьмы"` → `"Солдат удачи"`
  - Паттерн 2: `"Вариант «Бис» 1"` → `"Вариант «Бис\"`
  - Паттерн 3: `"Земля 5"` → `"Земля"`
  - Реализация: [passes/pass2_series_filename.py](passes/pass2_series_filename.py) методы `_clean_series_name()` (линия ~134-185)

- ✅ **Поддержка depth=2 для папок коллекций (is_series_folder):**
  - Добавлена логика для папок типа `"Серия - «Боевая фантастика»"` содержащих файлы напрямую
  - Файлы на depth=2 теперь правильно обрабатываются с очисткой и валидацией
  - Реализация: [passes/pass2_series_filename.py](passes/pass2_series_filename.py) линия ~74-154

- ✅ **Метаданные для уточнения (не как основной источник):**
  - Метаданные используются для уточнения только если серия извлечена из имени файла
  - Если метаданные совпадают с очищенной версией → использу очищенную, но `series_source = "filename"`
  - Если очищенная версия невалидна → `series_source = "metadata"` (метаданные стали основным источником)
  - Реализация: 5-вариантная логика сравнения в `execute()` методе

- ✅ **Логика для сборников:**
  - Если `proposed_author` содержит "сборник" или "антология" → `proposed_series` всегда пуста
  - Реализация: [regen_csv.py](regen_csv.py) метод `_clear_series_for_compilations()` (линия ~173-186)

- 📝 **Результаты:** Анісімов файлы теперь имеют правильную серию `"Вариант «Бис»"` без номеров томов

**🆕 Февраль 26, 2026 - ИСПРАВЛЕНИЕ: Корректная обработка номеров книг в серийных файлах**
- ✅ **Новый паттерн:** `"Author - Title (Series service_words)"` для fichiers типа: `"Валериев Игорь - 2. Ермак. Поход (Ермак 4-6)"`
  - Отличие от похожего: без точки между серией и serve_word в скобках
  - Пример: `(Ермак 1-3)` вместо `(Ермак. Дилогия)`
- ✅ **Исправление паттерна:** `"Author - Series (service_words)"` теперь удаляет префиксы номеров
  - Проблема: `"Валериев Игорь - 2. Ермак. Поход"` извлекал `"2. Ермак. Поход"`
  - Решение: regex `^\s*\d+\s*[.,]\s*` удаляет `"1. "`, `"2. "`, `"3. "` и т.д.
  - Результат: все три файла теперь возвращают одну и ту же серию `"Ермак"` ✓
- 📝 **Реализация:** [passes/pass2_series_filename.py](passes/pass2_series_filename.py) методы `_apply_config_pattern()` (линия ~382-390)

**🆕 Февраль 26, 2026 - ИСПРАВЛЕНИЕ: Корректная обработка кавычек в извлечении серий**
- ✅ **PASS 2 для серий (из имён файлов):** Исправлена обработка внешних кавычек в паттернах "из цикла"
- ✅ Поддержка вложенных кавычек: `"Ведьма с «Летающей ведьмы»"` → корректно сохраняются внутренние кавычки
- ✅ Обработка парных и непарных кавычек:
  - Парные: `«Ведьма с «Летающей ведьмы»»` → `Ведьма с «Летающей ведьмы»` (обе внешние удалены)
  - Непарные: `«Ведьма с «Летающей ведьмы»` → `Ведьма с «Летающей ведьмы»` (первая « удалена)
- ✅ Реализация: логика с подсчетом количества открывающих и закрывающих кавычек

**🆕 Февраль 26, 2026 - НОВОЕ: Система извлечения СЕРИЙ**
- ✅ Параллельный конвейер для серий (аналог авторов)
- ✅ PASS 2 для серий: из структуры папок + из имён файлов
- ✅ PASS 3 для серий: нормализация названий с word boundaries
- ✅ **НОВОЕ (PASS 3):** Удаление аннотаций об авторстве из серий через series_cleanup_patterns
- ✅ Извлечение series из FB2 метаданных `<sequence>` в PASS 1
- ✅ **НОВОЕ:** PASS 4 для серий - селективный консенсус (Февраль 26)
  - Консенсус по `extracted_series_candidate` (depth >= 2 файлы)
  - Консенсус по `metadata_series` (files с одинаковой series в metadata)
  - Предотвращает over-application к нежелательным файлам
- 📄 Полная документация: раздел 7 "SERIES EXTRACTION SYSTEM" (включая 7.3-7.8)

## 🎯 FALLBACK ARCHITECTURE С ФЛАГОМ FALLBACK (Февраль 20, 2026)

### Архитектура: PRECACHE → PASS 2 автоматический fallback на filename

**Концепция:**
- **PRECACHE + PASS 1**: Пытаются извлечь автора из иерархии папок → если ничего не найдено, флаг `needs_filename_fallback=True`
- **PASS 2**: Автоматически переходит на парсинг имени файла ЕСЛИ PRECACHE не сработал
- **Логика**: Единый pipeline с автоматическим fallback - не два отдельных процесса, а один с conditional routing

**Реализация:**

1. **BookRecord расширен новым полем:**
   ```python
   @dataclass
   class BookRecord:
       ...existing fields...
       needs_filename_fallback: bool = False  # Флаг: PRECACHE не нашел автора?
   ```

2. **PASS 1 устанавливает флаг:**
   ```python
   # pass1_read_files.py
   record = BookRecord(
       ...other fields...,
       author_source=author_source or "",  # "" если папка не нашла
       needs_filename_fallback=(author == "")  # True если автор не найден
   )
   ```
   - Если `author == ""` → `needs_filename_fallback=True`
   - Если `author != ""` → `needs_filename_fallback=False` (у нас есть результат из папок)

3. **PASS 2 проверяет флаг перед пропуском:**
   ```python
   # pass2_filename.py execute()
   if record.author_source == "folder_dataset" and not getattr(record, 'needs_filename_fallback', False):
       skipped_count += 1
       continue  # Пропускаем: уже есть результат из папок
   
   # Иначе обработали файл (пытаемся извлечь из имени)
   author = self._extract_author_from_filename(filename_without_ext, fb2_path)
   if author:
       record.proposed_author = author
       record.author_source = "filename"
       record.needs_filename_fallback = False  # Очищаем флаг
   ```

**Исправление валидации имён (критическое для фамилий):**

**Проблема:** Функция `_looks_like_author_name()` требовала наличие известного **имени** (firstname) даже для однословных фамилий вроде "Демченко", блокируя их как "названия сборников".

**Было (неправильно):**
```python
if self.male_names or self.female_names:
    has_known_name = any(word in self.male_names or word in self.female_names 
                         for word in text.lower().split())
    if not has_known_name:
        return False  # ❌ блокирует "Демченко" (фамилия, не в списке имён)
```

**Стало (правильно):**
```python
text_words = text.lower().split()
if len(text_words) > 1:  # Многословные (например "Демченко Антон")
    # Проверяем наличие известного имени для фильтрации сборников
    if self.male_names or self.female_names:
        has_known_name = any(word in self.male_names or word in self.female_names 
                             for word in text_words)
        if not has_known_name:
            return False  # ✓ Блокирует "Боевая фантастика" (сборник)
# Однословные (фамилии) ВСЕГДА пропускают - это валидные авторские фамилии
```

**Логика:**
- `"Демченко"` (1 слово) → ✅ проходит (фамилия)
- `"Демченко Антон"` (2+ слова) → проверяем есть ли известное имя → ✅ "антон" в списке
- `"Боевая фантастика"` (2+ слова) → проверяем есть ли известное имя → ❌ ни "боевая" ни "фантастика" не в списке

**Результаты:**

| Метрика | Было | Стало | Улучшение |
|---------|------|-------|-----------|
| Файлов извлечено из имён файлов | 138 | 166 | +28 файлов (+20%) |
| Демченко файлы (Воздушный стрелок et al.) | metadata ❌ | filename ✅ | Исправлено |
| Другие однословные фамилии | Blokced ❌ | Allowed ✅ | Исправлено |
| PRECACHE + PASS 2 fallback логика | N/A | Реализовано | ✅ Рабочая |

**Пример потока для Демченко:**

```
File: "Демченко. Боярич (Воздушный стрелок 1-3).fb2"

STEP 1 - PRECACHE:
  ├─ Ищет папку "Демченко" в иерархии → не найдена
  └─ author_folder_cache["..."] = None

STEP 2 - PASS 1 (pass1_read_files.py):
  ├─ author = _get_author_for_file(...) → ""
  ├─ author_source = ""
  └─ BookRecord(author="", author_source="", needs_filename_fallback=True) ← FLAG SET

STEP 3 - PASS 2 (pass2_filename.py):
  ├─ Проверка пропуска: author_source="" (не "folder_dataset") → НЕ пропускаем
  ├─ filename = "Демченко. Боярич (Воздушный стрелок 1-3)"
  ├─ Анализ структуры: segments=['Демченко', 'Боярич'], pattern="Author. Title (Series)"
  ├─ Извлечение: author = "Демченко"
  ├─ Валидация _looks_like_author_name("Демченко"):
  │  └─ text_words.count = 1 → однов слово
  │  └─ ✅ return True (фамилия ВСЕГДА проходит)
  ├─ Валидация validate_author_name("Демченко") → ✅ True
  └─ record.proposed_author = "Демченко", author_source = "filename" ✅

RESULT: proposed_author = "Демченко Антон", author_source = "filename" ✓
                          (имя расширено из метаданных в PASS 3-5)
```

---

## 🔧 ИСПРАВЛЕНИЯ КРИТИЧЕСКИХ БАГОВ (Февраль 20, 2026 - Предыдущие)

### Баг 4: Priority Logic - PASS 3 добавляла metadata авторов к folder_dataset

**Проблема:** Когда автор найден из иерархии папок (author_source="folder_dataset"), PASS 3 нормализация добавляла соавторов из FB2 метаданных, нарушая приоритет `folder > filename > metadata`.

**Пример бага:**
```
Файл: Волков Тим\Бездна.fb2
metadata_authors: "Тим Волков; Ян Кулагин" (2 автора из FB2)
PASS 1 результат: author_source="folder_dataset", proposed_author="Волков Тим" (1 автор)
PASS 3 БУГ: proposed_author="Волков Тим, Кулагин Ян" ❌ (добавлен второй автор из metadata!)
```

**Причина:** `normalize_format()` в `author_normalizer_extended.py` была тонкая логика по восстановлению потеряных ФИ - когда слова из proposed_author совпадали с metadata авторами, она добавляла ВСЕХ авторов из metadata. Это правильно для случая "неполное ФИ" но неправильно для confident folder-derived author.

**Решение** (Commit a1f3cfd):
```python
# pass3_normalize.py
# Было: normalized = self.normalizer.normalize_format(original, record.metadata_authors)
# Теперь: 
metadata_for_normalization = "" if record.author_source == "folder_dataset" else record.metadata_authors
normalized = self.normalizer.normalize_format(original, metadata_for_normalization)
```
Если author_source="folder_dataset", передаем пустую строку для metadata_authors, предотвращая слияние авторов.

**Результат:**
- ✅ 420 записей обработано (autor-organized dataset)
- ✅ Все записи сохранили author_source="folder_dataset" без загрязнения metadata авторов
- ✅ Приоритет соблюдается: `folder > filename > metadata`

---

### Баг 1: Lowercase case-sensitivity в PRECACHE name validation

**Проблема:** PRECACHE загружал имена в capital form ("Дмитрий"), но PASS 2 проверял lowercase ("дмитрий"), всегда не находя совпадения.

**Причина:** Разница в case-handling между PRECACHE и PASS 2 validation.

**Решение** (Commit 42a69c2):
```python
# precache.py - _load_name_sets()
# Было: set(self.settings.get_male_names())
# Теперь: set(name.lower() for name in self.settings.get_male_names())
```

**Результат:**
- ✅ PASS 2 extraction улучшена с 1 до 502 авторов
- ✅ Пример: "Иванов Дмитрий - Империя Хоста.fb2"
  * Было: proposed_author = "Дмитрий" (incomplete, from metadata)
  * Теперь: proposed_author = "Иванов Дмитрий" (complete, from filename)

---

### Баг 2: Normalization ё → е в AuthorName

**Проблема:** `AuthorName.__init__()` заменяет ё на е в raw_name, но `_get_known_names()` загружал имена с ё, не совпадали при проверке.

**Причина:** Inconsistency между normalized raw_name и non-normalized known_names list.

**Решение** (Commit в процессе):
```python
# name_normalizer.py - _get_known_names()
# Было: set(w.lower() for w in (...) if w)
# Теперь: set(w.lower().replace('ё', 'е') for w in (...) if w)
```

**Результат:**
- ✅ Names с ё теперь правильно parse
- ✅ Пример: "Тё Илья - Абсолютная альтернатива.fb2"
  * Было: proposed_author = "Илья Те" (no normalization, treated as single surname)
  * Теперь: proposed_author = "Те Илья" (normalized to Фамилия Имя)

---

### Баг 3: Surname initials regex pattern

**Проблема:** Regex pattern для "Фамилия И.О." делал точку optional, что приводило к неправильному matching двух-буквенных слов.

**Причина:** `pattern_surname_initials` использовал `\.?` (optional dot).

**Решение** (Commit в процессе):
```python
# name_normalizer.py - _extract_parts()
# Было: r'^([А-Яа-яЁё]+)\s+([А-Яа-яЁё]\.?)\s*([А-Яа-яЁё]\.?)$'
# Теперь: r'^([А-Яа-яЁё]+)\s+([А-Яа-яЁё]\.)\s*([А-Яа-яЁё]\.)?$'
#                                        ↑ required dot (changed from \.?)
```

**Результат:**
- ✅ "Илья Те" больше не matches как "Илья (Т.)(е.)"
- ✅ Correctly processed as normal 2-word name requiring normalization

---

### Баг 4: PRECACHE не кэширует папки авторов (CRITICAL)

**Проблема:** PRECACHE возвращал "Cached 0 author folders" несмотря на наличие 68+ папок с авторами в иерархии. Из-за этого приоритет был нарушен: извлечение из метаданных использовалось вместо иерархии папок.

**Причина:** Метод `_contains_valid_name()` сравнивал capitalized имена (e.g., "Борис") с lowercase наборами (e.g., "борис"), всегда возвращая False.

**Решение** (Commit 7e61dba):
```python
# precache.py - _contains_valid_name()
# Было: 
#   word_clean = word.strip('.,;:!?')
#   if word_clean in self.male_names ...  # "Борис" vs "борис" → False!

# Теперь:
#   word_clean = word.strip('.,;:!?').lower()  # Добавлен .lower()!
#   if word_clean in self.male_names ...  # "борис" vs "борис" → True!
```

**Результат:**
- ✅ PRECACHE теперь кэширует 68 папок авторов (было 0)
- ✅ Приоритет восстановлен: папки > файлы > метаданные
- ✅ Пример фикса: "К повороту стоять! (Батыршин Борис)"
  * Было: author_source="metadata", author="Б. Беломор"
  * Теперь: author_source="folder_dataset", author="Батыршин Борис"

---

### Баг 5: Сокращённые имена авторов в папках игнорируются

**Проблема:** Папки типа "Ангелы в погонах (А.Михайловский, А.Харников)" не кэшировались, хотя содержали корректные авторские имена в сокращённой форме (Initial.Surname).

**Причина:** Валидация ищет полные имена вроде "Александр", но находит только "А" (первая буква), которая не в списке known names.

**Решение** (Commit 0c98caa):
```python
# precache.py - _contains_valid_name()
# Добавлена проверка regex pattern для сокращённых имён
import re
if re.search(r'[А-Я]\.* *[А-Я][а-яё]+', author_name):
    return True  # Matches "А.Михайловский" или "И.Николаев"
```

**Результат:**
- ✅ PRECACHE расширен с 68 до 74 папок
- ✅ 6 дополнительных папок с abbrev. авторами теперь кэшируются:
  * "Ангелы в погонах (А.Михайловский, А.Харников)" ✓
  * "Железный ветер (И.Николаев, А.Поволоцкий)" ✓
  * "Операция «Гроза плюс» (А.Михайловский, А.Харников)" ✓
  * и ещё 3 папки...
- ✅ Эти записи теперь показывают author_source="folder_dataset"

---

### Баг 6: Missing модуль file_structural_analysis.py

**Проблема:** `pass2_filename.py` импортировал `from .file_structural_analysis import analyze_file_structure, score_pattern_match`, но этот модуль никогда не был создан/закоммичен. Это вызывало ModuleNotFoundError при запуске pipeline.

**Причина:** Импорт добавлен в commit 0c913a3 (для sbornik detection), но модуль с функциями не был создан.

**Решение** (Commit 7e61dba):
```
Создан файл: passes/file_structural_analysis.py
Функции:
  - analyze_file_structure(filename, service_words) → Dict
    * Returns: structural info (brackets, dashes, dots, etc.)
  
  - score_pattern_match(struct, pattern, service_words) → float
    * Returns: match score 0.0-1.0 for pattern evaluation
```

**Результат:**
- ✅ Импорт разрешён, pipeline может стартовать
- ✅ PASS 2 использует structural analysis для matching паттернов
- ✅ Все 337 файлов обрабатываются успешно

---

## ИСПРАВЛЕНИЕ БАГОВ (Предыдущие исправления - Февраль 2026)

### Баг: Потеря соавторов во время нормализации (PASS 3)

**Проблема:** Соавторы, извлеченные из имен файлов (например, "Дмитрий Зурков, Игорь Черепнев"), теряли второго автора при прохождении через PASS 3 (Нормализация).

**Причина:** Метод `AuthorNormalizer.normalize_format()` в файле `author_normalizer_extended.py` обрабатывал только разделитель `;` (точка с запятой - из FB2 метаданных), но игнорировал разделитель `,` (запятая - из имен файлов).

**Fix:** Обновлен метод `normalize_format()` для работы с обоими разделителями:
- `;` (из FB2 метаданных)
- `,` (из извлечения имен файлов)

**Результат:** ✅ Оба автора сохраняются через все PASS'ы
```
Pass 2: "Дмитрий Зурков, Игорь Черепнев"      ← извлечено из имени файла
Pass 3: "Зурков Дмитрий, Черепнев Игорь"      ← нормализовано (оба авторов сохранены!)
Pass 4-6: "Зурков Дмитрий, Черепнев Игорь"    ← сохранены до конца
Final CSV: "Зурков Дмитрий, Черепнев Игорь"  ← в выходном файле оба автора
```

---

## ОБНОВЛЕНИЕ (Февраль 2026): Переход на модульную архитектуру

**Система полностью рефакторена на модульную 6-PASS архитектуру:**

```
Было:  regen_csv.py (1951 строк) ← Монолитный файл
Стало: passes/ (9 модулей = ~600 строк) ← Модульная система
```

**Ключевые изменения:**
- ✅ **folder_author_parser** → папка `passes/folder_author_parser/` (PASS0+PASS1+PASS2)
- ✅ Каждый PASS отдельный файл под `passes/`
- ✅ **orchestrator** `regen_csv.py` (158 строк) координирует все PASS'ы
- ✅ **precache.py** как отдельный модуль (PRECACHE фаза)
- ✅ Все модули независимо тестируемы
- ✅ CSV регенерация: 337 файлов, 291 (86.4%) из иерархии папок

**Смотри раздел 1 ниже для подробной архитектуры 2.0**

---

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

## 1. Архитектура 2.0: Модульная система PASS (Февраль 2026)

### 1.0 Структура проекта

CSV регенерация реализована как **6-PASS система с PRECACHE**, разбитая на независимые модули:

```
fb2parser/
├── passes/                               # PASS stages + folder_author_parser
│   ├── __init__.py                      # Экспорты всех PASS классов
│   │
│   ├── pass1_read_files.py              # PASS 1: Читать FB2, извлечь метаданные
│   ├── pass2_filename.py                # PASS 2: Извлечь авторов из имён файлов
│   ├── pass2_fallback.py                # PASS 2 Fallback: Метаданные как последняя надежда
│   ├── pass3_normalize.py               # PASS 3: Нормализовать имена авторов
│   ├── pass4_consensus.py               # PASS 4: Применить консенсус (с защитой)
│   ├── pass5_conversions.py             # PASS 5: Переприменить conversions
│   ├── pass6_abbreviations.py           # PASS 6: Развернуть сокращения
│   │
│   └── folder_author_parser/            # Парсинг имён папок (PASS0+PASS1+PASS2)
│       ├── __init__.py                  # Главная функция parse_author_from_folder_name()
│       ├── pass0_structural_analysis.py # PASS0: Анализ структуры (скобки, запятые, дефисы)
│       ├── pass1_pattern_selection.py   # PASS1: Выбор из 7 паттернов
│       └── pass2_author_extraction.py   # PASS2: Извлечение автора по паттерну
│
├── precache.py                          # PRECACHE: Кэшировать авторов из иерархии папок
├── regen_csv.py                         # Orchestrator: координирует все PASS'ы
└── ... (другие файлы)
```

### 1.1 Преимущества модульной архитектуры

| Характеристика | Было (монолит) | Стало (модули) |
|---|---|---|
| **Размер regen_csv.py** | 1951 строк | 158 строк |
| **Тестируемость** | Сложно | Каждый PASS независим |
| **Понятность** | Запутанный большой файл | Ясная структура |
| **Расширяемость** | Трудно добавлять | Легко добавлять новые PASS'ы |
| **Отладка** | Логирование смешано | Изолированные логи по PASS |

### 1.2 Процесс регенерации (Orchestrator)

```python
# regen_csv.py - главный орхестратор
RegenCSVService.regenerate():
    │
    ├─ PRECACHE (precache.py)
    │  └─ Кэшировать авторов из папок (74 папки)
    │     ├─ Сканить иерархию folder_parse_limit=3
    │     ├─ Парсить имена папок (folder_author_parser.parse_author_from_folder_name)
    │     └─ Вернуть Dict[Path, (author_name, confidence)]
    │
    ├─ PASS 1 (pass1_read_files.py)
    │  └─ Прочитать все FB2 файлы (337 файлов)
    │     ├─ Извлечь фабула, автор, серию из метаданных
    │     ├─ Определить автора FROM folder cache (приоритет: folder > metadata)
    │     └─ Вернуть List[BookRecord]
    │
    ├─ PASS 2 (pass2_filename.py)
    │  └─ Извлечь авторов из имён файлов
    │     ├─ Паттерны: " - ", ". ", ","
    │     └─ Только для records без folder_dataset
    │
    ├─ PASS 2 Fallback (pass2_fallback.py)
    │  └─ Обнаружение сборников + применение метаданных как последней надежды
    │     ├─ ПРОВЕРКА: Если 3+ авторов в метаданных И ключевые слова в имени → "Сборник"
    │     └─ ИНАЧЕ: Применить метаданные только если proposed_author всё ещё пуст
    │
    ├─ PASS 3 (pass3_normalize.py)
    │  └─ Нормализовать имена авторов
    │     └─ Использовать extractor._normalize_author_format()
    │
    ├─ PASS 4 (pass4_consensus.py)
    │  └─ Применить консенсус автора к группам в папках
    │     ├─ Защита: folder_dataset и metadata источники НЕ перезаписываются
    │     └─ Применять ТОЛЬКО к undetermined records (author_source="")
    │
    ├─ PASS 5 (pass5_conversions.py)
    │  └─ Переприменить author_surname_conversions
    │     └─ После PASS 4 (консенсус может изменить авторов)
    │
    ├─ PASS 6 (pass6_abbreviations.py)
    │  └─ Развернуть сокращения авторов
    │     ├─ Паттерн: "Фамилия И." → "Фамилия Имя"
    │     └─ Использовать словарь имён от существующих авторов
    │
    └─ SAVE CSV
       └─ Записать records в regen.csv
```

### 1.3 Статус PASS (данные из последней генерации)

| PASS | Описание | Записей | Успешно | Status |
|---|---|---|---|---|
| PRECACHE | Кэш иерархии папок | — | 74 папки | ✅ |
| PASS 1 | Читать FB2 | 337 | 337 | ✅ |
| PASS 2 | Из имён файлов | — | 46 обновлено | ✅ |
| PASS 2 FB | Обнаружение сборников | — | 1 обнаружено | ✅ |
| PASS 2 FB | Метаданные fallback | — | 45 обновлено | ✅ |
| PASS 3 | Нормализация | 337 | 337 | ✅ |
| PASS 4 | Консенсус | 337 | ~5-10 обновлено | ✅ |
| PASS 5 | Conversions | 337 | ~2-3 обновлено | ✅ |
| PASS 6 | Сокращения | 337 | ~0-2 обновлено | ✅ |

### 1.4 Источники авторов (author_source field)

Каждая запись помечена источником автора:

```
folder_dataset:  291  (86.4%)  ← из иерархии папок (PRECACHE + PASS1)
filename:         46  (13.6%)  ← из имён файлов (PASS2)
metadata:          0  (0%)     ← из метаданных FB2 (PASS2 Fallback)
collection:        1  (0.3%)   ← сборник/антология (PASS2 Fallback)
consensus:         0  (0%)     ← из консенсуса (PASS4)
```

---

## 2. Сравнение: name_normalizer.py vs author_utils.py

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

## 3. Параметры и списки из config.json

### 3.1 Критические параметры для regen_csv.py

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
  "collection_keywords": ["сборник", "антология", "коллекция", "собрание сочинений", "лучшее", "шедевры", "хиты", ...],
  "service_words": ["том", "книга", "часть", "ч", "кн", "vol", ...],
  "sequence_patterns": ["том \\d+", "книга \\d+", ...],
  "author_series_patterns_in_files": [...],
  "author_series_patterns_in_folders": [...],
  "author_name_patterns": [...]
}
```

### 3.2 Как использовать в regen_csv.py

```python
# Инициализация
settings = SettingsManager('config.json')
folder_parse_limit = settings.get_folder_parse_limit()           # Глубина парсинга папок
male_names = settings.get_male_names()                           # Мужские имена для определения значения автора
female_names = settings.get_female_names()                       # Женские имена для определения значения автора
surname_conversions = settings.get_author_surname_conversions()  # Конвертации фамилий
blacklist = settings.get_filename_blacklist()                    # Для фильтрации шума
collection_keywords = settings.get_list('collection_keywords')   # Для обнаружения сборников

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

# 4. Для обнаружения сборников (PASS 2 Fallback)
if author_count >= 3 and any(kw.lower() in filename.lower() for kw in collection_keywords):
    mark_as_collection()

# 5. Для определения глубины парсинга папок (PASS 1)
# folder_parse_limit = 3 → смотрим максимум 3 уровня вверх в папках
```

---

## 4. Подключаемые файлы и их функционал

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

## 5. Новая архитектура: 6 PASS системы

### 4.0 PRECACHE Phase: Построение иерархии авторских папок с валидацией

**Назначение:** Рекурсивное сканирование иерархии файлов ДО PASS 1 для кэширования авторских папок на основе проверки валидности имён.

**Выполняется:** ДО PASS 1, в методе `execute()` класса `Precache`

**Ключевое изменение (Февраль 2026):** Добавлена валидация имён перед HIGH-приоритетным кешированием

**Алгоритм:**
```
1. Загрузить списки male_names и female_names из config.json
   → 75 мужских имён, 60 женских имён

2. Рекурсивно пройти все папки в work_dir до folder_parse_limit уровней

3. Для каждой папки:
   a) Применить folder_name conversions ("Гоблин (MeXXanik)" → "Гоблин MeXXanik")
   b) Применить PASS0+PASS1+PASS2 structural analysis (см. раздел ниже)
   c) Проверить наличие FB2 файлов в папке

4. CRITICAL: Валидация перед HIGH-кешированием
   
   ✅ ЕСЛИ: папка содержит FB2 И имя парсится как автор И содержит валидное имя
      → Добавить в кэш с HIGH приоритетом: (author_name, "high")
      
   ❌ ЕСЛИ: папка содержит FB2 И имя парсится как автор НО БЕЗ валидных имён
      → НЕ кэшировать (пропустить)
      → Позволить файлам наследовать автора из родительской папки
      
   📌 ЕСЛИ: папка содержит валидное имя БЕЗ FB2 файлов в самой папке
      → Добавить в кэш с LOW приоритетом: (author_name, "low")
      → Используется как fallback при наследовании

5. Результат: self.author_folder_cache = {Path: (author_name, confidence)}

PRECACHE преимущества:
- ✅ Быстрое определение авторских папок в PASS 1 (кэш вместо повторного парсинга)
- ✅ Поддержание иерархии (все файлы под авторской папкой используют одного автора)
- ✅ Валидация имён (серии не блокируют наследование от родительского автора)
- ✅ Защита от ошибок (папка парсится один раз, consistency гарантирована)

Пример результата PRECACHE:
  Path("Books/Сапфир Олег")                      → ("Сапфир Олег", "high") ← валидно
  Path("Books/Сапфир Олег/Идеальный мир для Социопата") → НЕ кэшируется
     (парсится как "Социопата Идеальный", но содержит только одно имя "Социопата")
  Path("Books/Сборник книг")                    → не кэшируется (в blacklist)
  Path("Books/Петров И.")                       → ("Петров И.", "low")
```

**ВАЛИДАЦИЯ ИМЁН (Версия 2.2 - Февраль 20, 2026)**

```python
def _contains_valid_name(self, author_name: str) -> bool:
    """
    Проверить, содержит ли extracted author_name хотя бы одно валидное имя.
    
    Это предотвращает кеширование серий и сборников, у которых парсинг
    вернул text, похожий на авторское имя, но который на самом деле
    является названием серии.
    
    ВАЖНО: Версия 2.2 добавляет TWO критических улучшения:
    1. Case-insensitive сравнение (все имена convert to lowercase)
    2. Поддержка сокращённых имён (Initial.Surname паттерн)
    
    Примеры:
    - "Сапфир Олег" → ✅ True (оба слова - валидные имена)
    - "Идеальный мир для Социопата" → ❌ False (только "Социопата" валидно)
    - "Лекарь Виктор" → ✅ True ("Виктор" в male_names)
    - "А.Михайловский" → ✅ True (сокращённое имя: Initial.Surname)
    - "И.Николаев" → ✅ True (сокращённое имя: Initial.Surname)
    """
    # Проверка 1: Полная regex для сокращённых имён (NEW v2.2)
    import re
    if re.search(r'[А-Я]\.* *[А-Я][а-яё]+', author_name):
        return True  # Matches "А.Михайловский" или "И. Николаев"
    
    # Проверка 2: Стандартная валидация по словам (с lowercase conversion - FIX v2.2)
    words = author_name.split()
    for word in words:
        word_clean = word.strip('.,;:!?').lower()  # ← CRITICAL: .lower() added!
        if word_clean in self.male_names or word_clean in self.female_names:
            return True
    return False
```

**Критические баги, исправленные в v2.2:**

| № | Проблема | Причина | Решение | Результат |
|---|----------|---------|---------|-----------|
| 1 | PRECACHE возвращал 0 папок | Case-sensitivity: "Борис" ≠ "борис" | Add .lower() в валидации | 0 → 68 папок |
| 2 | Abbrev. имена игнорировались | "А" не в known_names | Regex для Initial.Surname | 68 → 74 папок |

**BEFORE (v2.1):**
```
PRECACHE._contains_valid_name("Батыршин Борис"):
  word_clean = "Батыршин"      # Ошибка: не convert to lower!
  if "Батыршин" in self.male_names → False ❌ (в списке "батыршин")
  return False → Папка НЕ кэшируется!

Результат: PRECACHE Cached 0 author folders
```

**AFTER (v2.2):**
```
PRECACHE._contains_valid_name("Батыршин Борис"):
  word_clean = "батыршин".strip().lower()  # ✅ Correct lowercase!
  if "батыршин" in self.male_names → False
  word_clean = "борис".strip().lower()     # ✅ Correct lowercase!
  if "борис" in self.male_names → True ✅
  return True → Папка кэшируется!

PRECACHE._contains_valid_name("А.Михайловский"):
  regex match r'[А-Я]\.* *[А-Я][а-яё]+' → Matches! ✅
  return True → Папка кэшируется!

Результат: PRECACHE Cached 74 author folders
```

**Практический пример фикса:**

Было (v2.1):
```
Папка: К повороту стоять! (Батыршин Борис)/
Содержит FB2 файлы: да
PASS2 парсит имя: "Батыршин Борис"
Валидация: word_clean="Батыршин" vs known_names → False ❌
Результат: Папка НЕ кэшируется

CSV result: author_source="metadata", author="Б. Беломор" ❌
```

Стало (v2.2):
```
Папка: К повороту стоять! (Батыршин Борис)/
Содержит FB2 файлы: да
PASS2 парсит имя: "Батыршин Борис"
Валидация: "борис" в male_names → True ✅
Результат: Папка кэшируется с HIGH приоритетом

CSV result: author_source="folder_dataset", author="Батыршин Борис" ✅
```

**PASS0+PASS1+PASS2 Structural Analysis (подробно)**

Система парсинга имён папок в `folder_author_parser.py`:

**PASS0: Найти все скобки и их позиции**
```python
# Input: "МВП-2 (1) Одиссея крейсера «Варяг» (Александр Чернов)"
# Результат PASS0:
parens = [
    (start=7, end=11, content='1'),
    (start=70, end=84, content='Александр Чернов')
]
```

**PASS1: Определить структурный паттерн**
```python
# Проверить паттерны:
patterns = [
    "Series (Author)",          # Последняя скобка в конце строки
    "(Series) Author",          # Первая скобка в начале
    "Author, Author",           # Запятая в скобке или без
    "Author - Folder Name",     # Дефис разделяет
    "Series",                   # Без скобок
]

# Для нашего примера:
last_paren_content = "Александр Чернов"
text_after_last_paren = ""  # пусто (пос скобкой ничего нет)
text_before_first_paren = "МВП-2 "  # есть текст

# Вывод: Соответствует паттерну "Series (Author)"
# Потому что: last_paren в конце строки И есть text ДО скобки
```

**PASS2: Извлечь значение по определённому паттерну**
```python
# Для паттерна "Series (Author)":
series = text_before_last_paren = "МВП-2"
author = last_paren_content = "Александр Чернов"

# Результат: "Александр Чернов"
```

**Защита от категорийных папок (Blacklist):**
```python
blacklist_starts = [
    'Серия', 'Сборник', 'Коллекция', 'Антология',
    'Цикл', 'Подборка', 'Архив', 'Разное', 'Другое',
]

# Если папка начинается с этих слов → возвращаем пусто (НЕ парсим как автора)
if name.lower().startswith(word.lower()):
    return ""
```

**Примеры работы PASS0+PASS1+PASS2:**
```
1. "Гоблин (MeXXanik)"
   PASS0: парens = [(7, 18, 'MeXXanik')]
   PASS1: Pattern = "Series (Author)" (text до скобки + скобка в конце)
   PASS2: author = "MeXXanik" ✅

2. "(Боевая фантастика) Петров И."
   PASS0: parens = [(0, 19, 'Боевая фантастика')]
   PASS1: Pattern = "(Series) Author" (скобка в начале)
   PASS2: author = "Петров И." ✅

3. "Белаш Александр, Людмила"
   PASS0: parens = [] (нет скобок)
   PASS1: Pattern = "Author, Author" (есть запятая)
   PASS2: authors = ["Белаш Александр", "Людмила"] → "Белаш Александр; Людмила Белаш" ✅

4. "Серия - Фантастика"
   PASS0: parens = []
   PASS1: Проверка blacklist: "Серия" в начале ✅
   PASS2: Возвращаем пусто (это НЕ автор) ❌
```

**Различие типов дефисов в паттернах (ВАЖНО!):**

Система различает два типа дефисов, которые имеют разное значение:

1. **Соединительный дефис (без пробелов)** - часть одного слова/серии
   ```
   "МВП-2"       ← дефис без пробелов, часть названия книги/серии
   "ФИ-1 Артём"  ← дефис связывает название и текст
   
   Обработка: Эти дефисы НЕ используются как разделители паттернов
              Текст перед дефисом НЕ считается отдельным автором
   ```

2. **Разделительный дефис (с пробелами)** - разделяет автора и название
   ```
   "Петров И. - Книга"      ← дефис с пробелами, разделитель
   "Гоблин - Адвокат Чехов" ← дефис с пробелами, разделитель
   
   Обработка: Этот дефис ЯВЛЯЕТСЯ разделителем в паттернах
              Текст ДО дефиса парсится как автор
              Текст ПОСЛЕ дефиса парсится как название/серия
   ```

**Примеры обработки:**

```
✅ Правильно распознаны:

"МВП-2 (1) Одиссея (Чернов)"
  1. PASS0: Найти скобки: [(7, 11, '1'), (70, 84, 'Чернов')]
  2. PASS1: "МВП-2" - это текст ДО скобки (часть названия)
           "(Чернов)" - это скобка в конце
           → Паттерн: "Series (Author)"
  3. PASS2: author = "Чернов" ✅
  Ключевой момент: "МВП-2" остаётся как часть series, не парсится как автор

"Гоблин - Адвокат Чехов (Серия 1-3)"
  1. PASS0: Найти скобки: [(29, 48, 'Серия 1-3')]
  2. PASS1: Есть дефис с пробелами " - " → паттерн может быть "Author - Title"
  3. Проверка: text берёто до дефиса, после дефиса
  → подбирается подходящий паттерн со скобкой в конце "Author - Series (service_words)"
  PASS2: author = "Гоблин", series = "Адвокат Чехов", service_word = "Серия 1-3" ✅

❌ Неправильно (как НЕ должно быть):

"МВП-2 (Чернов)"
  ЕСЛИ бы система обрабатывала "МВП-2" как отдельное слово:
  → Ошибка: author = "МВП" ← НЕПРАВИЛЬНО!
  
  Решение: Соединительный дефис (без пробелов) не разбивает слово
  → "МВП-2" остаётся вместе, текст ДО скобки = series
  → Правильно: author = "Чернов" из последней скобки
```

**Алгоритм обработки дефисов в PASS1:**

```python
# При определении паттерна, система проверяет:

# 1. Есть ли дефис с пробелами (разделитель)?
if ' - ' in name:  # Дефис с пробелами!
    # Может быть паттерн "Author - Title" или "Author - Series (Title)"
    parts = name.split(' - ')
    author_part = parts[0]  # Текст ДО разделителя
    rest = ' - '.join(parts[1:])  # Текст ПОСЛЕ разделителя
    # Дальше анализируем author_part и rest отдельно

# 2. Соединительные дефисы (без пробелов) игнорируются
else:
    # Все дефисы в этом слове - соединительные, часть текста
    # "МВП-2" рассматривается как одно целое
    # "ФИ-1 Артём" рассматривается как одно целое
    pass
```

**Критические правила PASS0+PASS1+PASS2:**
1. **Соединительный дефис (без пробелов) - НЕ разделитель:** "МВП-2" остаётся частью названия
2. **Разделительный дефис (с пробелами) - ЭТО разделитель:** "Автор - Название" разбивается
3. **Single-word паттерны по последней скобке:** "МВП-2 (Чернов)" → автор = "Чернов"
2. **Multi-author обрабатывается через запятую:** "Автор1, Автор2" → оба парсятся
3. **Blacklist категорий захватывается ПЕРВЫМ словом:** "Сборник Разных" → отвергнуто
4. **Неполные ФИ восстанавливаются позже в PASS 1:** "Белаш Александр, Людмила" → добавляется фамилия
5. **Скобки от 1 до N:** все найденные скобки учитываются (не только первая/последняя)

**Файл:** `folder_author_parser.py` функция `parse_author_from_folder_name()`

---

### 4.1 Общая схема (6-PASS Архитектура 2.0)

```
PASS 1: Консервативное определение автора (папка → пусто)
        ↓
        1. Проверить папки вверх до folder_parse_limit уровней
        2. Валидировать через metadata (если найдено в папке)
        3. Если папка дала результат + подтверждено metadata → используем
        4. Если папка дала результат БЕЗ подтверждения → отвергаем
        5. Если папка ничего не дала → возвращаем ПУСТО (not fallback!)
        Применить conversions: "Гоблин (MeXXanik)" → "Гоблин MeXXanik"
        → BookRecord(metadata_authors="", proposed_author="", author_source="")

PASS 2: Извлечение из имён файлов (filename ТОЛЬКО)
        ↓
        1. Для файлов с пустым proposed_author из PASS 1
        2. Извлечь автора из имени файла по паттернам
        3. Metadata используется для логирования, НЕ для отказа
        4. Если extraction успешен → используем (независимо от metadata)
        5. Если extraction не сработал → остается пусто
        → BookRecord(proposed_author="автор из filename", author_source="filename")

PASS 2 Fallback: Применить metadata как ПОСЛЕДНИЙ источник
        ↓
        1. Для файлов с пустым proposed_author (ни PASS1, ни PASS2 не дали)
        2. Применить metadata из FB2 как последний источник
        3. Metadata пройдет через PASS 3-6 вместе с остальными авторами
        → BookRecord(proposed_author="metadata_authors", author_source="metadata")

PASS 3: Нормализация авторов
        ↓
        1. Нормализация формата (Имя Фамилия → Фамилия Имя)
        2. Применение extractor._normalize_author_format()
        3. Работает со всеми авторами независимо от их источника

PASS 4: Применение консенсуса
        ↓
        1. Поиск группы файлов в одной папке
        2. Определение консенсусного автора
        3. Применение ко всей группе (если нет явного folder_dataset)

PASS 5: Повторное применение конвертаций фамилий
        ↓
        1. Второе применение surname_conversions (после консенсуса)
        2. Финальная нормализация после изменений в PASS 4

PASS 6: Раскрытие аббревиатур
        ↓
        1. Преобразование "А.Фамилия" → "Александр Фамилия"
        2. Требует словаря полных имён (build_authors_map)
        3. Финальная полировка перед сохранением

        ↓
CSV SAVE: Сохранение результата в regen.csv
```

### ⚠️ Архитектурные принципы PRECACHE + PASS 1-2-Fallback

**ЖЕЛЕЗНОЕ ПРАВИЛО: PRECACHE валидирует перед кешированием**

**0. PRECACHE (Построение иерархии с валидацией)**
   - Сканирует папки и парсит имена через PASS0+PASS1+PASS2
   - ✅ HIGH-кеш: папка содержит FB2 И parsed name содержит валидное имя
   - ❌ SKIP: папка содержит FB2 И parsed name БЕЗ валидного имени (серии!)
   - ⚠️ LOW-кеш: папка содержит валидное имя БЕЗ FB2 файлов в самой папке
   - Результат: author_folder_cache с ТОЛЬКО проверенными авторами

1. **PASS 1 работает с ВАЛИДИРОВАННЫМ кешом от PRECACHE**
   - PASS 1 получает кэш, где папки уже отфильтрованы по валидности имён
   - Ищет ПЕРВОГО валидного предка в иерархии файла
   - High-приоритетный кеш = папка с валидным автором И FB2 файлами
   - Low-приоритетный кеш = папка с валидным автором БЕЗ FB2 файлов (наследование)
   - Серии и сборники НЕ в кеше → не блокируют наследование
   - Если папка дает результат → проверяем metadata для подтверждения
   - Если папка НЕ дает результата → возвращаем ПУСТО (не fallback!)
   - Metadata используется ТОЛЬКО для подтвержения, НИКОГДА для отказа

2. **PASS 2 работает ТОЛЬКО с filename**
   - Извлечение из имени файла = база для filename source
   - Если extraction успешен → используем его
   - Metadata confirmation используется для логирования, НЕ для отказа

3. **PASS 2 Fallback применяет metadata в последнюю очередь**
   - ТОЛЬКО если PASS 1 + PASS 2 оба дали ПУСТО
   - Metadata затем обрабатывается как обычный результат через PASS 3-6

4. **PASS 3-6 работают с РЕЗУЛЬТАТОМ (proposed_author)**
   - Не возвращаются к filename или папке
   - Информация течет ТОЛЬКО вперед через PASS'ы
   - Источник (author_source) сохраняется как метаинформация

**Пример: Файл в папке "Идеальный мир для Социопата"**
```
PRECACHE (построение иерархии):
  Родитель: "Сапфир Олег" 
    - Парсится как: "Сапфир Олег" (оба слова валидные)
    - Содержит FB2: да
    → HIGH-кеш: ("Сапфир Олег", "high") ✅

  Ребенок: "Идеальный мир для Социопата"
    - Парсится как: "Социопата Идеальный" (только одно имя от second word)
    - Содержит FB2: да
    - Но "Идеальный" НЕ валидное имя
    → SKIP (не кешируется) ✅

PASS 1 (ищет автора):
  Файл: .../Идеальный мир для Социопата/1.fb2
  Ищет вверх по иерархии:
    1. /Идеальный мир для Социопата/ → НЕ в HIGH-кеше (пропущена в PRECACHE)
    2. /Сапфир Олег/ → НАЙДЕНО в HIGH-кеше → "Сапфир Олег" ✅
  
✅ ИТОГ: Правильный автор "Сапфир Олег" (наследован от родителя)
         Файл не блокирован series folder (потому что та не в кеше)
```

**Сравнение: БЕЗ валидации vs С валидацией**

```
БЕЗ валидации (v2.0):
  PRECACHE кэширует: ("Социопата Идеальный", "high") ← СЕРИЯ!
  ↓
  PASS1 находит свою папку → возвращает серию ❌

С валидацией (v2.1):
  PRECACHE пропускает кеширование (папка не проходит валидацию)
  ↓
  PASS1 НЕ находит свою папку → ищет выше → находит родителя ✅
```

### 4.2 Детальное описание каждого PASS

#### PASS 1: Определение автора по приоритету (использует ВАЛИДИРОВАННЫЙ кеш PRECACHE)

**ЖЕЛЕЗНОЕ ПРАВИЛО:** папка (из валидированного кеша PRECACHE) → файл → метаданные

**⚠️ ВАЖНО: Источник данных для PASS 1**
- PASS 1 использует **author_folder_cache из PRECACHE** (уже валидированный!)
- Кэш содержит ТОЛЬКО папки с валидными авторами (после проверки имён в PRECACHE)
- Папки без валидных имён (серии, сборники) НЕ в кеше → не блокируют наследование
- Алгоритм PASS 1: проходит вверх по иерархии папок, ищет ПЕРВОГО в кеше
- Результат: файлы в series folder наследуют автора от родительской папки

**⚠️ ВАЖНО: Источник FB2 файлов**
- FB2 файлы сканируются **в рабочей папке** (текущей директории `./`)
- **НЕ** используется `library_path` из config.json для сканирования!
- `library_path` используется только для определения относительных путей при сохранении в CSV
- Алгоритм: рекурсивно ищет все `*.fb2` файлы в текущей рабочей папке и её подпапках

**Входные данные:**
- Путь к FB2 файлу (найдено в рабочей папке)
- author_folder_cache из PRECACHE (валидированный кеш папок)
- folder_parse_limit = 3 (глубина поиска вверх по папкам)

**Алгоритм:**
```
1. Попытка 1: Поиск в ВАЛИДИРОВАННОМ кеше PRECACHE
   - Проверить папки вверх на folder_parse_limit уровней
   - Для каждой папки: ИСКАТЬ в author_folder_cache
   - ✅ ЕСЛИ НАЙДЕНА в кеше → (author_name, confidence) от PRECACHE
   - ❌ ЕСЛИ НЕ НАЙДЕНА → папка была пропущена PRECACHE (нет валидного имени)
   
   ПРИМЕР: Файл .../Идеальный мир для Социопата/1.fb2
   Ищет вверх:
     /Идеальный мир для Социопата/ → НЕ в кеше (PRECACHE пропустила - неправильное имя)
     /Сапфир Олег/ → НАЙДЕНО в кеше → "Сапфир Олег" ✅

2. Попытка 2: Парсинг названия файла
   - Если Попытка 1 не дала результата
   - Проверить имя файла на наличие автора (используя patterns)
   - ПРИМЕР: "Гоблин - Адвокат Чехов.fb2" → "Гоблин"
   - author_source = "filename"

3. Попытка 3: Метаданные FB2
   - Если Попытка 1 и 2 не дали результата
   - Извлечь авторов из //fb:author в title-info
   - ПРИМЕР: FB2 XML содержит <first-name>Петр</first-name><last-name>Гоблин</last-name>
     → "Петр Гоблин"
   - author_source = "metadata"

4. Применить conversions на КАЖДОМ шаге:
   - "Гоблин (MeXXanik)" → "Гоблин MeXXanik"

5. ⚠️ **КРИТИЧЕСКОЕ ПРАВИЛО:** Если авторов нет → proposed_author = **ПУСТО** (не "Сборник"!)
   - Это позволяет потоку дать PASS 2 возможность извлечь автора из имени файла
   - ❌ СТАРОЕ: proposed_author = "Сборник" → блокировал fallback в PASS 2 ✗
   - ✅ НОВОЕ: proposed_author = "" → позволяет PASS 2 Fallback работать ✓
   - "Сборник" применяется ТОЛЬКО в PASS 2 Fallback как последний источник
   - Примеры файлов, которые это исправило:
     * "Жеребьёв. Негоциант.fb2" → теперь правильно извлекается "Жеребьёв"  
     * "Логинов. СССР - ответный удар.fb2" → теперь "Логинов" вместо "СССР"

6. Создать BookRecord:
   - file_path = путь относительно library_path
   - metadata_authors = авторы из FB2 XML (хранять оригинал)
   - proposed_author = выбранный автор с применёнными conversions (или ПУСТО!)
   - author_source = "folder_dataset" / "filename" / "metadata" / "" (в зависимости от источника)
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

**⚠️ ВАЖНО: Парсит ТОЛЬКО имя файла, не полный путь!**
- На Windows пути содержат `\` (backslash), поэтому нужна обработка
- Извлекаем только basename: `record.file_path.replace('\\', '/').split('/')[-1]`
- Удаляем расширение: `filename.rsplit('.', 1)[0]`

**Входные данные:**
- Только имя файла (без пути и расширения)
- Примеры из Test1:
  - `Achtung! Manager in der Luft! (Комбат Найтов)`
  - `Активная разведка (Сезин Сергей, Черкунова Ольга)`
  - `Александр II Великий (Старец Виктор)`

**Паттерны (в порядке приоритета - проверяются по очередно):**

```
1. "Title (Author)" ← НАИВЫСШИЙ ПРИОРИТЕТ (есть в Test1!)
   Example: "Achtung! Manager in der Luft! (Комбат Найтов)"
   Использует: rfind('(') и rfind(')'), берёт ПОСЛЕДНЮЮ пару скобок
   Результат: "Комбат Найтов" → нормализовано в "Найтов Комбат"

2. "Author - Title"
   Example: "Авраменко Александр - Солдат удачи 1"
   Использует: split(' - ', 1), берёт первую часть
   Результат: "Авраменко Александр"

3. "Author. Title"
   Example: "Белоус. Последний шанс человечества"
   Использует: split('. ', 1), берёт первую часть
   Результат: "Белоус"

4. "Author, Author"
   Example: "Сергей Иванов, Иван Петров"
   Использует: split(',', 1), берёт первую часть
   Результат: "Сергей Иванов"
```

**Валидация извлеченного автора:**

После извлечения проверяются:
- ✅ Минимальная длина: `len(author) > 2` (исключить однобуквенные остатки)
- ✅ Не пустая строка
- ✅ Нет требуемой нормализации (с запятыми, инициалами и т.д.)

**Примеры из Test1:**

```
regen.csv source=filename:  45 записей

Примеры успешного парсинга:
  'Achtung! Manager in der Luft! (Комбат Найтов).fb2'
    → Извлечено: "Комбат Найтов"
    → Нормализовано: "Найтов Комбат"
    
  'Активная разведка (Сезин Сергей, Черкунова Ольга).fb2'
    → Извлечено: "Сезин Сергей, Черкунова Ольга"
    → Нормализовано: "Сезин Сергей, Черкунова Ольга"
    
  'Александр II Великий (Старец Виктор).fb2'
    → Извлечено: "Старец Виктор"
    → Нормализовано: "Старицын Виктор" (автоматическое преобразование)
```

**История исправлений:**

Bug #1 (Февраль 2026):
- ❌ БЫЛО: `.split('/')[-1]` не работает на Windows (пути содержат `\`)
- ❌ РЕЗУЛЬТАТ: парсер обрабатывал полный путь вместо имени файла
- ❌ ПРИМЕР: `"Серия - «Военная фантастика»\Achtung!(...).fb2".split('/')` вернул полный путь
  → Паттерн ` - ` совпал с "Серия"
- ✅ ИСПРАВЛЕНО: `replace('\\', '/').split('/')[-1]` + проверка обеих последовательностей

Bug #2 (Февраль 2026):
- ❌ БЫЛО: Нет паттерна для `(Author)` в скобках
- ❌ РЕЗУЛЬТАТ: 46 файлов из "Серия - Военная фантастика" получали `author="Серия"`
- ✅ ИСПРАВЛЕНО: Добавлен паттерн "Title (Author)" с наивысшим приоритетом
  → Использует rfind() для ПОСЛЕДНЕЙ пары скобок (обрабатывает названия с скобками)
  → Результат: все 46 файлов теперь имеют правильных авторов

**Логика реализации (pass2_filename.py):**

```python
class Pass2Filename:
    def execute(self, records):
        for record in records:
            # Skip если уже есть folder_dataset
            if record.author_source == "folder_dataset":
                continue
            
            # Skip если уже есть автор
            if record.proposed_author:
                continue
            
            # Получить только имя файла (не полный путь!)
            filename = record.file_path.replace('\\', '/').split('/')[-1]
            filename_without_ext = filename.rsplit('.', 1)[0]
            
            # Попробовать извлечь автора (проверяет паттерны по приоритету)
            author = self._extract_author_from_filename(filename_without_ext)
            
            if author:
                record.proposed_author = author
                record.author_source = "filename"
    
    def _extract_author_from_filename(self, filename):
        # 1. ПЕРВЫЙ ПРИОРИТЕТ: "Title (Author)"
        if '(' in filename and ')' in filename:
            start = filename.rfind('(')  # Последняя открывающая скобка
            end = filename.rfind(')')    # Последняя закрывающая скобка
            if start < end:
                author = filename[start+1:end].strip()
                if author and len(author) > 2:
                    return author
        
        # 2. "Author - Title"
        if ' - ' in filename:
            author = filename.split(' - ', 1)[0].strip()
            if author and len(author) > 2:
                return author
        
        # 3. "Author. Title"
        if '. ' in filename:
            author = filename.split('. ', 1)[0].strip()
            if author and len(author) > 2:
                return author
        
        # 4. "Author, Author"
        if ',' in filename:
            author = filename.split(',', 1)[0].strip()
            if author and len(author) > 2:
                return author
        
        return ""
```

**Результаты:**
- ✅ 45 авторов извлечены из имён файлов
- ✅ 0 ошибочных "Серия" (исправлено в Feb 2026)
- ✅ Паттерн `(Author)` работает правильно
   - ✅ ЕСЛИ найдено слово в author_names (известных именах/фамилиях) → принять автора

2. Проверка по структуре имени:
   - ЕСЛИ нет известных имен → проверить структурно похоже ли на имя
   - Требует: содержит буквы, 2-100 символов, без опасных символов
   - ✅ ЕСЛИ выглядит как имя ИЖ НЕ похоже на серию → принять автора

3. Проверка что это НЕ серия:
   - ❌ Если содержит слова из blacklist (сборник, компиляция, etc) → отвергнуть
   - ❌ Если это 2-3 слова БЕЗ известных имен и похоже на описание → отвергнуть
   - ✅ ВАЖНО: Single-word surnames (фамилии одного слова) ПРИНИМАЮТСЯ!
     · Пример: "Жеребьёв" (одно слово) → ✅ принял  
     · Пример: "Боевая фантастика" (два слова, нет известных имен) → ❌ отвергнут как серия
```

### Динамическая генерация регулярных выражений из описаний паттернов

**Новая возможность:** Пользователь может добавлять новые паттерны напрямую в `config.json` без изменения кода системы. Система автоматически генерирует для них регулярные выражения.

**Как это работает:**

```python
def _generate_regex_from_pattern_desc(self, pattern_desc: str) -> Tuple[str, List[str]]:
    """
    Автоматически генерирует regex из текстового описания паттерна.
    
    Примеры преобразований:
    - "Author, Author" → ^(?P<author>[^,]+?)\s*,\s*(?P<author2>.+)$
    - "Series (Author)" → ^(?P<series>[^(]+?)\s*\((?P<author>[^)]+)\)$
    - "Title - Author" → ^(?P<title>[^()]+?)\s*\-\s*(?P<author>[^,\-()]+?)$
    
    Placeholders, которые распознаются:
    - Author, Author2 → Группа автора (не содержит запятые, дефисы, скобки)
    - Series → Группа серии (не содержит скобки)
    - Title → Группа названия (не содержит скобки)
    - Name, Surname → Отдельные слова (без пробелов)
    - Folder Name → Любой текст (жадный поиск)
    
    Разделители распознаются автоматически:
    - Запятая: , → \s*,\s* (пробелы = необязательны)
    - Дефис: - → \s*-\s*
    - Точка: . → \.
    - Скобки: () → сохраняются как часть regex
    """
```

**Пример добавления нового паттерна в config.json:**

```json
{
  "author_series_patterns_in_folders": [
    {"pattern": "Series (Author)"},
    {"pattern": "Series (Author, Author)"},
    {"pattern": "(Surname) (Name)"},
    {"pattern": "Author - Folder Name"},
    {"pattern": "MyCustom Pattern (Author) - Title"}  ← НОВЫЙ ПАТТЕРН!
  ]
}
```

**Механизм выбора паттерна (Priority-based selection):**

⚠️ **КРИТИЧЕСКИ ВАЖНО:** Выбор НЕ зависит от порядка паттернов в списке!

Система оценивает **качество совпадения** по 3 критериям:

1. **Специфичность паттерна (Priority):** 
   - 100 points: Паттерны с группой `series` (выглядят как "Series (Author)")
   - 50 points: Паттерны с группой `folder_name` (выглядят как "Author - Folder Name")  
   - 10 points: Простые паттерны (выглядят как "Author, Author")

2. **Количество совпадённых групп:** 
   - Берётся как второй критерий (тай-брейкер)
   - Паттерн с 3 совпадёнными группами > паттерн с 2 группами

3. **Порядок в списке:**
   - НЕ используется! (проверяются ВСЕ паттерны независимо)

**Пример приоритизации:**

```
Папка: "Второй сибирский (Емельянов Антон, Савинов Сергей)"

Паттернов, которые совпадают:
- "Author, Author"         → quality_score = (10, 2)
- "Series (Author, Author)" → quality_score = (100, 3)  ← ВЫБРАН! (100 > 10)

Результат:
- series: "Второй сибирский"
- author: "Емельянов Антон"
- author2: "Савинов Сергей"
```

**Проверенные паттерны (hardcoded, всегда имеют приоритет):**

Система сначала пробует найти паттерн в предопределённом списке (эти регулярные выражения оптимизированы и протестированы):

```python
patterns_map = {
    # Папки (folder patterns)
    "Author, Author": r'^(?P<author>[^,]+?)\s*,\s*(?P<author2>.+)$',
    "(Surname) (Name)": r'^(?P<author>\S+)\s+(?P<author2>\S+)$',
    "Author - Folder Name": r'^(?P<author>[^-]+?)\s*-\s*(?P<folder_name>.+)$',
    "Series (Author)": r'^(?P<series>[^(]+?)\s*\((?P<author>[^)]+)\)$',
    "Series (Author, Author)": r'^(?P<series>[^(]+?)\s*\((?P<author>[^,]+?)\s*,\s*(?P<author2>[^)]+)\)$',
    "(Series) Author": r'^\((?P<series>[^)]+)\)\s*(?P<author>.+)$',
    "Series": r'^(?P<series>.+)$',
    
    # Файлы (file patterns)
    "(Author) - Title": r'^\((?P<author>[^)]+)\)\s*-\s*(?P<title>.+)$',
    "Author - Title": r'^(?P<author>.*?)\s*-\s*(?P<title>[^(]+)(?:\(.*\))?$',
    # ... другие паттерны ...
}
```

**Если паттерн не найден в hardcoded liste → используется автогенерация:**

```python
# Для новых паттернов из config.json
regex, groups = self._generate_regex_from_pattern_desc(pattern_desc)
# Система работает с ними так же, как с predefined паттернами
```

**Ограничения и советы:**

⚠️ **Эти конструкции НЕ поддерживаются:**
- Специальные regex символы в разделителях (кроме `. - ,`)
- Вложенные скобки (только одна пара на паттерн)
- Символы кроме латинских букв, цифр, пробелов, точек, дефисов, запятых

✅ **Советы при добавлении новых паттернов:**
- Используйте точные названия placeholders: Author, Series, Title, Name, Surname, Folder Name
- Помещайте важные данные в скобки если нужна чёткая граница: "Series (Author)"
- Разделяйте группы точными символами: `-`, `,`, `.` (не другими символами)
- Ставьте более специфичные паттерны (с "Series") ВЫ́ШЕ по специфичности (система выберет их)

**Тестирование новых паттернов:**

```bash
# Запустить тесты автогенерации
python test_auto_pattern_generation.py

# Или прямо в коде:
service = RegenCSVService()
pattern_desc = "My Custom (Author) - Title"
regex, groups = service._file_pattern_to_regex(pattern_desc)
print(f"Regex: {regex}")
print(f"Groups: {groups}")
```

---

**Critical moment: Single-word surnames vs. Series names**

Система должна различать:
- **Single-word surname:** "Жеребьёв", "Иванов", "Смирнов" (имена авторов)
- **Multi-word phrase:** "Боевая фантастика", "Другой мир" (названия серий)

Эвристика `_looks_like_series_name()`:
```python
# Проверяем: есть ли известные имена в тексте?
words_in_author_names = count(known_first_names_found)

# Результат:
- Если words > 0 → это имя (например "Иван Петров" содержит "иван")
- Если words == 0 И 2-3 слова → может быть серией (например "Боевая фантастика")
- Если words == 0 И 1 слово → это фамилия, НЕ серия! (например "Жеребьёв")
  
⚠️ ПОЧЕМУ одно слово = фамилия?
- author_names содержит ТОЛЬКО ИМЕ́НА (first names) — Иван, Петр, Сергей, etc.
- Фамилии редко встречают в этом списке (специально именно first names)
- Поэтому check "words_in_author_names == 0" для одного слова = скорее всего фамилия
- Серии обычно многословные описания, редко одно слово
```

**Примеры валидации:**

```
Случай 1: Single-word surname
Text: "Жеребьёв"
- Contains known first name? NO
- Structurally looks like name? YES (буквы, правильная длина)
- Looks like series name? NO (1 слово одно)
- РЕЗУЛЬТАТ: ✅ ПРИНЯЛ как автора

Случай 2: Multi-word description
Text: "Боевая фантастика"
- Contains known first name? NO
- Structurally looks like name? YES (буквы)
- Looks like series name? YES (2 слова, no known names) 
- РЕЗУЛЬТАТ: ❌ ОТВЕРГНУЛ как серию

Случай 3: First name present
Text: "Иван Петров"
- Contains known first name? YES ("иван")
- РЕЗУЛЬТАТ: ✅ ПРИНЯЛ (не нужна даже проверка структуры)

Случай 4: Part of known name
Text: "Земляной Андрей, Орлов Борис"
- Contains "андрей"? YES (в author_names)
- РЕЗУЛЬТАТ: ✅ ПРИНЯЛ (содержит известное имя)
```

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

**Фича 3: Обнаружение сборников (Sbornik Detection) в PASS 2 - Февраль 20, 2026**

**Проблема:** Некоторые файлы с названиями вроде "Боевая фантастика - лучшее.fb2" могут быть ошибочно распознаны как имена авторов, даже когда в метаданных есть реальные авторы (4+ человека).

**Решение:** Добавлена валидация в PASS 2 - требование, чтобы извлеченный текст содержал ХОТЯ БЫ ОДНО известное имя из списков PRECACHE (male_names/female_names).

**Как это работает:**

```python
class Pass2Filename:
    def __init__(self, settings, logger, work_dir, 
                 male_names=None, female_names=None):
        self.male_names = male_names or set()
        self.female_names = female_names or set()
    
    def _looks_like_author_name(self, text: str) -> bool:
        """Проверить, выглядит ли текст как имя автора"""
        # ... стандартные проверки (длина, буквы, не цифры) ...
        
        # НОВОЕ: Проверка наличия известных имен
        if self.male_names or self.female_names:
            text_words = set(text.lower().split())
            has_known_name = any(
                word in self.male_names or word in self.female_names
                for word in text_words
            )
            if not has_known_name:
                return False  # Не автор - это название коллекции/серии!
        
        return True
```

**Примеры результатов:**

```
Тест 1: Название коллекции содержит нарицательные слова
Input:    "фантастика Боевая"
male/female names check: 
  - "фантастика" ∉ (male_names ∪ female_names) ✗
  - "боевая" ∉ (male_names ∪ female_names) ✗
Output:   False → ОТКЛОНЕНО! ✅

Тест 2: Реальное имя автора
Input:    "Михаил Атаманов"
male/female names check:
  - "михаил" ∈ male_names ✓
Output:   True → ПРИНЯТО! ✅

Тест 3: Еще одно названиеколлекции
Input:    "Боевая романс"
male/female names check:
  - "боевая" ∉ (male_names ∪ female_names) ✗
  - "романс" ∉ (male_names ∪ female_names) ✗
Output:   False → ОТКЛОНЕНО! ✅

Тест 4: Имя одного слова
Input:    "Олег Сапфир"  (или просто "Олег")
male/female names check:
  - "олег" ∈ male_names ✓
Output:   True → ПРИНЯТО! ✅
```

**Реальный пример из CSV:**

```
File: "Боевая фантастика - лучшее.fb2"
metadata_authors: "Михаил  Атаманов; Михаил  Михеев; Ярослав  Горбачев; Владимир  Поселягин"

ДО (без валидации):
  PASS 1: proposed_author = "" 
  PASS 2: pattern '(Title - Collection)' → extracted "фантастика Боевая"
  PASS 2 validation: ОТСУТСТВОВАЛА → extracted как есть ✗

ПОСЛЕ (с валидацией):
  PASS 1: proposed_author = ""
  PASS 2: pattern '(Title - Collection)' → extracted "фантастика Боевая"
  PASS 2 validation: has_known_name = False → ОТКЛОНЕНО! ✓
  PASS 2 Fallback: proposed_author = "" → применяет metadata
  Результат: proposed_author = "Сборник", author_source = "collection" ✅
```

**Интеграция с PRECACHE:**

```python
# В regen_csv.py (orchestrator):

# Загрузить имена в PRECACHE
precache = Precache(work_dir, settings, logger, folder_parse_limit)
author_folder_cache = precache.execute()

# Передать в PASS 2 для валидации
pass2 = Pass2Filename(
    settings, logger, work_dir,
    male_names=precache.male_names,      # ← 75 имен
    female_names=precache.female_names   # ← 60 имен
)
pass2.execute(records)
```

**Статистика:**

```
Пример из Test1 dataset (672 файлов):
- PRECACHE loaded: 75 male names, 60 female names
- Валидация отклонила: 0 ошибочных извлечений  
- Сборники правильно обнаружены в PASS 2 Fallback ✅
- Full pipeline: все 6 PASS'ов выполнены успешно ✅
```

---

#### PASS 2 Fallback: Применить metadata как последний источник, обнаружение сборников

**Назначение:** 
1. Обнаружить файлы-сборники (3+ авторов в метаданных + ключевые слова в имени)
2. Применить metadata из FB2 файла как крайний источник для остальных файлов

**Условие срабатывания:**
```
IF proposed_author == ""  (пусто после PASS 1 И PASS 2)
   ├─ PASS 1 (folder_author_parser): ничего не вернул
   └─ PASS 2 (filename parsing): ничего не вернул
   THEN:
     ├─ ПРОВЕРКА СБОРНИКА: IF metadata_authors имеет 3+ авторов И filename содержит keywords
     │   └─ → proposed_author = "Сборник", author_source = "collection"
     └─ ИНАЧЕ: применяем metadata как обычно
         └─ → proposed_author = metadata_authors, author_source = "metadata"
```

**Конфигурация (config.json):**

Добавлен новый массив `collection_keywords` для обнаружения сборников:

```json
"collection_keywords": [
    "сборник",
    "антология",
    "коллекция",
    "собрание сочинений",
    "избранное",
    "лучшее",
    "шедевры",
    "хиты",
    "популярные",
    "топ",
    "классика",
    "полное собрание",
    ...
]
```

**Алгоритм (pass2_fallback.py):**

```python
class Pass2Fallback:
    def __init__(self, logger):
        self.logger = logger
        self.settings = SettingsManager('config.json')
        self.collection_keywords = self.settings.get_list('collection_keywords')
    
    def _is_collection_file(self, filename: str) -> bool:
        """Проверить наличие ключевых слов сборника в имени файла (case-insensitive)"""
        filename_lower = filename.lower()
        for keyword in self.collection_keywords:
            if keyword.lower() in filename_lower:
                return True
        return False
    
    def _count_authors(self, authors_str: str) -> int:
        """Подсчитать авторов (разделены '; ' или ', ')"""
        if not authors_str or authors_str == "[unknown]":
            return 0
        if "; " in authors_str:
            return len([a for a in authors_str.split("; ") if a.strip()])
        elif ", " in authors_str:
            return len([a for a in authors_str.split(", ") if a.strip()])
        return 1 if authors_str.strip() else 0
    
    def execute(self, records):
        for record in records:
            # Пропускаем если уже есть автор из PASS 1 или PASS 2
            if record.proposed_author:
                continue
            
            # Проверка на сборник: 3+ авторов + ключевые слова
            author_count = self._count_authors(record.metadata_authors)
            filename = os.path.basename(record.file_path) if record.file_path else ""
            
            if author_count >= 3 and self._is_collection_file(filename):
                # Это сборник/антология
                record.proposed_author = "Сборник"
                record.author_source = "collection"
            
            # Применить metadata как fallback
            elif record.metadata_authors and record.metadata_authors != "[unknown]":
                record.proposed_author = record.metadata_authors
                record.author_source = "metadata"
            else:
                record.proposed_author = ""
                record.author_source = ""
```

**Критические правила:**

1. **Обнаружение сборников - приоритет**
   - ✅ ПРОВЕРЯЕМ сборник ДО применения metadata
   - ✅ Условия: 3+ авторов И ключевые слова одновременно
   - Примеры срабатывания:
     * "Хиты Военной фантастики.fb2" (5 авторов + "хиты") → "Сборник"
     * "Лучшие произведения фантастов.fb2" (4 автора + "лучшие") → "Сборник"
   - Примеры, которые НЕ срабатывают:
     * "Соавторская книга (Петров, Иванов).fb2" (2 автора = мало) → применяем metadata
     * "Собрание сочинений Гоблина.fb2" (1 автор + "собрание") → применяем metadata

2. **Metadata применяется ТОЛЬКО если оба PASS 1 и PASS 2 дали ПУСТО**
   - ❌ НЕ перезаписываем успешный результат из PASS 1 или PASS 2
   - ✅ ИСПОЛЬЗУЕМ metadata ТОЛЬКО как крайний источник
   - ✅ author_source остаётся "folder_dataset" или "filename" если там был результат

3. **Metadata позже проходит нормализацию через PASS 3-6**
   - Установленные в Fallback авторы идут в PASS 3 для нормализации формата
   - Затем PASS 4 применяет консенсус
   - PASS 5-6 раскрывают аббревиатуры
   - Итоговый результат:
     - "Иван Петров" (metadata) → PASS 3 → "Петров Иван" (нормализовано)

**Результаты (из реального запуска Test1):**

- ✅ 1 файл обнаружен как сборник ("Хиты Военной фантастики.fb2" с 5 авторами)
- ✅ 45 записей применили metadata как последний источник
- ✅ Метаданные из этих файлов успешно распарсились и нормализовались
- ✅ Консенсус (PASS 4) дополнительно улучшил результаты
- Результат: В итоговом CSV 337 записей, где 291 (86.4%) из папок, 46 (13.6%) из имён файлов, 1 сборник

---

#### PASS 3: Нормализация авторов

**Назначение:** Нормализовать формат имён авторов в стандартный вид: "Фамилия Имя".

**Поддержка соавторства (Co-authorship):** PASS 3 полностью поддерживает соавторов, разделённых запятой.

**Условие срабатывания:**
```
Для каждого BookRecord:
  1. Если proposed_author == "Сборник" → пропустить (метка без автора)
  2. Если proposed_author != "" → нормализовать
```

**Алгоритм (pass3_normalize.py):**

Использует класс `author_normalizer_extended.AuthorNormalizer` для работы:

```python
class Pass3Normalize:
    def execute(self, records):
        normalizer = author_normalizer_extended.AuthorNormalizer()
        for record in records:
            # Пропускаем "Сборник" и пустые
            if record.proposed_author in ["Сборник", ""]:
                continue
            
            # Нормализовать в формат "Фамилия Имя"
            # Поддерживает оба разделителя: '; ' и ', '
            normalized = normalizer.normalize_format(
                record.proposed_author,
                record.metadata_authors
            )
            
            if normalized != record.proposed_author:
                # Если изменилось
                record.proposed_author = normalized
```

**Примеры нормализации:**

```
Одиночные авторы:
"Иван Петров"       → "Петров Иван"
"Петров И."         → "Петров И."              (аббревиатуры не меняются)
"Гоблин"            → "Гоблин"                 (одно слово - не меняется)
"Молчанов, Виктор"  → "Молчанов Виктор"       (убирает запятые)

Соавторы (разделитель '; ' из FB2 метаданных):
"Земляной Андрей; Живой Алексей" → "Земляной Андрей, Живой Алексей"

Соавторы (разделитель ', ' из имён файлов) - ✅ БЕЗ ПОТЕРЬ:
"Дмитрий Зурков, Игорь Черепнев" → "Зурков Дмитрий, Черепнев Игорь" (оба сохранены)

Восстановление потерянных соавторов из metadata:
  filename: "Белаш. Капитан Удача 1..."  → extracted: "Белаш Людмила"
  metadata: "Людмила Белаш; Александр Белаш"
  
  result:  "Белаш Александр, Белаш Людмила"  ← оба восстановлены И отсортированы!
```

**Фича 1: Восстановление потерянных соавторов (новое, Февраль 20, 2026)**

Когда PASS 2 извлекает только одного автора из filename, но metadata содержит нескольких авторов:
- Система определяет пересечение слов между proposed_author и metadata_authors_list
- Если найдено совпадение → использует ВСЕ авторов из metadata (полный список)
- Каждого нормализует и сортирует

**Пример:**
```python
metadata_authors = "Людмила Белаш; Александр Белаш"
proposed_author = "Белаш Людмила" 
                  ↓
В metadata есть совпадение по слову "Белаш"
                  ↓
Используются ВСЕ авторы: ["Людмила Белаш", "Александр Белаш"]
                  ↓
Нормализуются: ["Белаш Людмила", "Белаш Александр"]
                  ↓
Сортируются: ["Белаш Александр", "Белаш Людмила"]
                  ↓
Результат: "Белаш Александр, Белаш Людмила"
```

**Фича 2: Алфавитная сортировка соавторов (новое, Февраль 20, 2026)**

Все соавторы (как при разделителе, так и при восстановлении из metadata) 
сортируются по алфавиту перед объединением в результирующую строку.

**Примеры сортировки:**
```
"Живой Алексей, Прозоров Александр"  → "Живой Алексей, Прозоров Александр"
"Прозоров Александр, Живой Алексей"  → "Живой Алексей, Прозоров Александр"  (переупорядочено)

"Зурков Дмитрий, Черепнев Игорь"     → "Зурков Дмитрий, Черепнев Игорь"     (уже в порядке)
"Черепнев Игорь, Зурков Дмитрий"     → "Зурков Дмитрий, Черепнев Игорь"     (переупорядочено)
```

**Баг-фикс (Февраль 20, 2026):** 

Метод `normalize_format()` теперь:
1. ✅ Обрабатывает ОБА разделителя:
   - `;` (точка с запятой) - из FB2 метаданных
   - `,` (запятая) - из извлечения имён файлов (PASS 2)
2. ✅ Восстанавливает потерянных соавторов из metadata
3. ✅ Сортирует результаты по алфавиту

Ранее метод игнорировал разделитель `,` и не восстанавливал соавторов из metadata.

**Источник нормализации:**
- Использует встроенный словарь имён и фамилий
- Применяет правила русского языка (окончания, ударения)
- Сохраняет multi-author форматы (с `, ` separator)
- При необходимости восстанавливает неполные ФИ из metadata_authors

**Фича 3: Расширенная обработка соавторов (Февраль 25-26, 2026)**

**Коммиты:**
- `3c2f61e` - Restore co-authors from metadata for shared surname filenames
- `939a5c5` - Sort restored co-authors alphabetically in PASS 3
- `aeba759` - PASS 3: Use metadata for co-author expansion in filename source
- `07a2082` - Fix co-author normalization: proper ФИ format and surname-based sorting
- `b2c2af8` - Add surname root matching for plural/declined surnames (e.g., Каменские)
- `336221b` - Simplify surname sorting: always use first word as surname
- `d1984da` - Use metadata to restore incomplete author names in folder_dataset sources

**Проблемы и их решения:**

1. **Потеря соавторов с одинаковой фамилией**
   - **Было:** "Белаш" (из filename) → расширялся только в первого автора из metadata
   - **Теперь:** Определяется, что это surname-only, восстанавливаются ВСЕ авторы с этой фамилией
   - **Логика:** Если proposed_author = 1 слово + metadata содержит несколько авторов → восстановить всех
   - **Код:** `pass3_normalize.py` lines 63-130

2. **Множественные и склоняемые фамилии (Каменские, Демидова)**
   - **Было:** "Каменские" (множественное число) не совпадало с "Каменский"/"Каменская"
   - **Теперь:** Функция `extract_surname_root()` удаляет окончания и сравнивает корни
   - **Примеры:** 
     - "Каменские" → "Камен" (корень)
     - "Каменский" → "Камен" (корень)
     - "Каменская" → "Камен" (корень)
   - **Результат:** Все три совпадают, восстанавливаются оба автора
   - **Код:** `pass3_normalize.py` lines 77-99

3. **Неправильная сортировка соавторов**
   - **Было:** Сортировка "Ильин" < "Ипатова" давала "Ипатова, Ильин" (неправильный порядок И < П)
   - **Был баг:** Функция `get_surname_key()` пыталась определять фамилию по окончаниям (-ов, -ска и т.д.)
     и возвращала разные типы (строку для однословных, кортеж для двусловных)
   - **Теперь:** 
     1. После PASS 3 нормализации ПЕРВОЕ слово ВСЕГДА фамилия
     2. `get_surname_key()` всегда возвращает кортеж `(surname, rest)`
     3. Сортировка работает корректно: Ильин < Ипатова < ...
   - **Код:** `author_normalizer_extended.py` lines 145-161

4. **Неполные ФИ в folder_dataset источниках**
   - **Было:** "Белаш Александр, Людмила" → результат был "Белаш Александр, Людмила" (неполное)
   - **Теперь:** PASS 3 передаёт metadata для folder_dataset с разделителями
   - **Логика:** Если multi-author в folder_dataset, используется metadata для восстановления неполных имён
   - **Результат:** "Белаш Александр, Белаш Людмила" (оба полные)
   - **Код:** `pass3_normalize.py` lines 137-143

**Полный алгоритм восстановления соавторов (февраль 25-26, 2026):**

```
Входные данные PASS 3:
  proposed_author = "Белаш" (1 слово из filename)
  metadata_authors = "Людмила Белаш; Александр Белаш"
  author_source = "filename"

ШАГ 1: Проверка - это surname-only?
  len(proposed_author.split()) == 1  → TRUE
  и metadata_authors не пусто       → TRUE
  
ШАГ 2: Найти всех авторов с этой фамилией в metadata
  candidate_root = extract_surname_root("Белаш") = "Белаш"
  matching_authors = [
    "Людмила Белаш" (рут "Белаш" совпадает),
    "Александр Белаш" (рут "Белаш" совпадает)
  ]

ШАГ 3: Нормализовать и сортировать
  Нормализация каждого:
    "Людмила Белаш" → "Белаш Людмила"
    "Александр Белаш" → "Белаш Александр"
  
  Сортировка по первому слову (фамилия):
    ("белаш", "александр") < ("белаш", "людмила")
    → ["Белаш Александр", "Белаш Людмила"]

ВЫХОД PASS 3:
  proposed_author = "Белаш Александр, Белаш Людмила"
  author_source = "filename"
```

**Второй сценарий: folder_dataset с неполным ФИ**

```
Входные данные PASS 3:
  proposed_author = "Белаш Александр, Людмила" (из папки)
  metadata_authors = "Людмила Белаш; Александр Белаш"
  author_source = "folder_dataset"

ШАГ 1: Обнаружение разделителя
  ", " присутствует → это multi-author

ШАГ 2: Передача metadata для восстановления
  has_separator = true
  Вызов: normalize_format("Белаш Александр, Людмила", "Людмила Белаш; Александр Белаш")

ШАГ 3: Для каждого автора проверка - полное ФИ?
  "Белаш Александр" (2 слова) → стандартная нормализация
  "Людмила" (1 слово) → ПОИСК в metadata
    найдено: "Людмила Белаш"
    восстановлено: "Людмила Белаш"

ШАГ 4: Нормализация и сортировка
  После нормализации: ["Белаш Астухов", "Белаш Людмила"]
  Сортировка: ["Белаш Александр", "Белаш Людмила"]

ВЫХОД PASS 3:
  proposed_author = "Белаш Александр, Белаш Людмила"
  author_source = "folder_dataset"
```

**Третий сценарий: Разные фамилии (Ипатова/Ильин)**

```
Входные данные PASS 3:
  proposed_author = "Ипатова Наталия, Ильин Сергей"
  metadata_authors = "Наталия Ипатова; Сергей Ильин"
  author_source = "filename"

ШАГ 1: Обнаружение разделителя ", "
  Обработка каждого автора отдельно

ШАГ 2: Нормализация каждого
  "Ипатова Наталия" → уже в ФИ формате → "Ипатова Наталия"
  "Ильин Сергей" → уже в ФИ формате → "Ильин Сергей"

ШАГ 3: Сортировка по фамилии (первое слово)
  ("ипатова", "наталия") → "ипатова"
  ("ильин", "сергей") → "ильин"
  
  Сравнение: "ильин" < "ипатова" (И < П в алфавите)
  
  Сортированный порядок: ["Ильин Сергей", "Ипатова Наталия"]

ВЫХОД PASS 3:
  proposed_author = "Ильин Сергей, Ипатова Наталия"  ← ПРАВИЛЬНЫЙ ПОРЯДОК
  author_source = "filename"
```

#### PASS 4: Применение консенсуса

**Назначение:** Применить консенсусный выбор автора для файлов в группе папок (для файлов, где автор не определён из надёжного источника).

**Проблема, которую решает:** 
- Если в папке есть 5 файлов "Гоблина" (из папки) и 1 файл "Другого автора" (из метаданных) - какого выбрать для последнего?
- Консенсус использует мажоритарное решение

**⚠️ КРИТИЧЕСКОЕ ПРАВИЛО:** Консенсус применяется ТОЛЬКО к файлам без надёжного источника

```
✅ author_source="folder_dataset" → НЕПРИКОСНОВЕНЕН (не переписываем)
✅ author_source="metadata"      → НЕПРИКОСНОВЕНЕН (не переписываем)
❌ author_source=""              → может получить consensus
❌ author_source="filename"      → может получить consensus
```

**Алгоритм (pass4_consensus.py):**

```python
class Pass4Consensus:
    def execute(self, records):
        # Сгруппировать по папке (file_path.parent)
        folders = {}
        for record in records:
            folder = Path(record.file_path).parent
            if folder not in folders:
                folders[folder] = []
            folders[folder].append(record)
        
        # Для каждой группы папки
        for folder, group in folders.items():
            # Отобрать файлы с author_source="folder_dataset" или "metadata"
            determined = [r for r in group 
                         if r.author_source in ["folder_dataset", "metadata"]]
            
            # Остальные файлы - кандидаты для консенсуса
            undetermined = [r for r in group 
                           if r.author_source in ["", "filename"]]
            
            if determined and undetermined:
                # Найти консенсусного автора (самый частый в determined)
                consensus_author = self._find_consensus(determined)
                
                # Применить консенсус к undetermined файлам
                for record in undetermined:
                    if record.proposed_author:  # Если есть какой-то автор
                        record.proposed_author = consensus_author
                        record.author_source = "consensus"
```

**Пример:**

```
Папка: /Books/Гоблин/
  book1.fb2 → author="Гоблин", source="folder_dataset" ← НЕ МЕНЯТЬ
  book2.fb2 → author="Гоблин", source="metadata"      ← НЕ МЕНЯТЬ
  book3.fb2 → author="", source=""                     ← Кандидат для consensus
  book4.fb2 → author="Другой", source="filename"      ← Кандидат для consensus

Консенсус для determined (book1, book2): "Гоблин"
Применяем к undetermined:
  book3.fb2 → author="Гоблин", source="consensus"  ✅
  book4.fb2 → author="Гоблин", source="consensus"  ✅

Результат: все файлы с правильным автором "Гоблин"
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

#### PASS 5: Переприменение конвертаций фамилий

**Назначение:** Переприменить конвертации фамилий к авторам после консенсуса (может понадобиться, если консенсус изменил автора).

**Логика:**
```
PASS 1: Применяем surname_conversions при чтении FB2 файла
PASS 5: Переприменяем после консенсуса
  - Причина: Консенсус (PASS 4) может изменить автора
  - Нужно убедиться что новый автор прошел через conversions
```

**Алгоритм (pass5_conversions.py):**

```python
class Pass5Conversions:
    def execute(self, records):
        # Переприменить conversions после consensus
        for record in records:
            # Пропускаем "Сборник" и пустые
            if record.proposed_author in ["Сборник", ""]:
                continue
            
            # Применить конвертации фамилий
            converted = self._apply_conversions(record.proposed_author)
            
            if converted != record.proposed_author:
                record.proposed_author = converted
```

**Конвертации фамилий:**

Используется словарь из `config.json` "surname_conversions":
```json
{
  "Старец": "Старицын",
  "Сезин": "Сезин",
  ...
}
```

**Пример:**
```
Консенсус выбрал: "Старец Виктор"
PASS 5: Применить conversions → "Старицын Виктор"
```

---

#### PASS 6: Раскрытие аббревиатур и расширение неполных имён

**Назначение:** 
1. Раскрыть аббревиатуры автора (например "И.Петров" → "Иван Петров")
2. **Расширить неполные имена** (например "Живой" → "Живой Алексей") используя информацию из других файлов в наборе

**Поддержка соавторства:** ✅ PASS 6 полностью поддерживает расширение соавторов, разделённых `, ` или `; `

**Алгоритм (pass6_abbreviations.py):**

```
Двухпроходная система:

ШАГ 1: Собрать authors_map из ВСЕ ХФайлов (прямой и обратный проход)
   - Проходит по ВСЕМ records перед началом расширения
   - Собирает все полные имена авторов
   - Группирует по фамилии: {фамилия.lower() → [полные_имена]}
   - Позволяет расширять файлы, используя авторов, которые появятся позже

ШАГ 2: Расширить аббревиатуры и неполные имена (используя полный authors_map)
   - Для каждого автора:
     * Если есть точка → раскрыть аббревиатуру
     * Если одно слово → расширить через authors_map (выбрать самое полное имя)
     * Иначе → оставить как есть
   - Поддержка соавторов через разделители
```

**Примеры:**

```
AUTHORS_MAP (построен из всех файлов):
  живой → [Живой, Живой Алексей]
  петров → [Петров, Петров Иван, Петров Сергей]
  гоблин → [Гоблин MeXXanik]

РАСШИРЕНИЕ (PASS 6):
  Одиночные авторы:
    "И.Петров"       → "Иван Петров"        (аббревиатура)
    "Живой"          → "Живой Алексей"      ✨ (неполное имя, выбрано самое полное)
    "Петров Иван"    → не меняется          (уже полное)
  
  Соавторы:
    "Живой, Прозоров Александр" 
      → "Живой Алексей, Прозоров Александр"  ✨ (расширены оба)
    
    "Живой Алексей; Прозоров А."
      → "Живой Алексей; Прозоров Александр"  (один был неполный, один аббревиатура)
```

**Выбор лучшего имени:**

Когда для фамилии найдено несколько вариантов (например, одно слово и полное имя), выбирается **самое полное** - с максимальным числом слов:

```
authors_map["живой"] = ["Живой", "Живой Алексей"]
  ↓
max(..., key=lambda x: len(x.split()))
  ↓
выбрано: "Живой Алексей" (2 слова > 1 слова)
```

---

## 6. Класс BookRecord

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

## 7. SERIES EXTRACTION SYSTEM (Февраль 26, 2026)

### 7.0 Новая архитектура: Параллельный конвейер для серий

**Принцип:** Аналогично авторам, серии извлекаются из 3 источников с приоритизацией.

**Приоритет источников для series:**
```
folder_dataset > filename > metadata
```

### 7.1 PASS 1: Извлечение series из FB2 метаданных

**Новое в PASS 1:** Добавлено извлечение `metadata_series` из FB2 XML.

**Метод:** `FB2AuthorExtractor._extract_series_from_metadata(fb2_path)`

С парсирует элемент `<sequence>` из блока `<title-info>`:
```xml
<sequence name="ISCARIOT" number="1"/>
```

**Результат в BookRecord:**
```python
metadata_series = "ISCARIOT"  # ← Извлечено из FB2 XML
proposed_series = ""           # ← Пока пусто, заполнится в Pass2/Pass3
series_source = ""             # ← Пока пусто, определится в Pass2/Pass3
```

**Примеры:**
```
File: Волков Тим/ISCARIOT/1. Выжить любой.fb2
  metadata_series: "ISCARIOT"
  
File: Волков Тим/Бездна.fb2
  metadata_series: ""  (нет <sequence> в FB2)
```

### 7.2 SERIES PASS 2 (from Folders): Извлечение из структуры папок

**Модуль:** `passes/folder_series_parser/` (PASS0+PASS1+PASS2 архитектура)

**Назначение:** Извлечь серию из имени папки, используя паттерны.

**Логика:** Анализирует предпоследнюю папку в пути файла как потенциальную серию.

```
file_path: "Волков Тим/ISCARIOT/1. Выжить любой.fb2"
                      ↑^^^^^^^^^
                      серия извлекается отсюда
```

**Паттерны в order_priority:**
1. `"Series (Author)"` - серия в начале, автор в скобках: `"Война в Космосе (Волков)"`
2. `"[Series]"` - квадратные скобки: `"[ISCARIOT]"`  
3. `"Series - Description"` - разделено дефисом: `"Война в Космосе - Эпизод 1"`
4. `"Series"` - просто название папки

**Валидация:** Проверяет что найденная серия НЕ совпадает с именем автора (используя `AuthorName`).

**Результат:**
```python
proposed_series = "ISCARIOT"
series_source = "folder_dataset"
```

### 7.3 SERIES PASS 2 (from Filename): Извлечение из имён файлов

**Класс:** `Pass2SeriesFilename` (passes/pass2_series_filename.py)

**Назначение:** Для файлов БЕЗ folder_dataset серии, попытаться извлечь из имени файла.

**Паттерны извлечения (в порядке приоритета):**
1. `"[Серия]"` в квадратных скобках в начале: `"[War in Space] First Book.fb2"`
2. `"Title (Series)"` в скобках в конце: `"Book Title (Странник 4-5).fb2"`
3. `"Series. Title"` - серия перед точкой: `"Пленники Зоны. Кровь цвета хаки.fb2"`

**Используемые списки из config.json:**
- `collection_keywords` - для исключения сборников из результатов
- `service_words` - для исключения служебных слов (том, книга, выпуск)

**Валидация:** Проверяет что найденное значение:
- ✅ НЕ в списке `collection_keywords`
- ✅ НЕ в списке `service_words`  
- ✅ НЕ похоже на имя автора (через `AuthorName`)

**Результат:**
```
filename: "Волков Тим\Пленники Зоны. Кровь цвета хаки.fb2"
  ↓
proposed_series = "Пленники Зоны"
series_source = "filename"
```

### 7.3.1 КРИТИЧЕСКИЙ ФИКС (Февраль 26, 2026): Корректная обработка кавычек в паттернах "из цикла"

**Проблема:** Паттерн `"из цикла «值»"` или `"из серии «значение»"` неправильно обрабатывал вложенные кавычки (guillemets).

**Примеры проблемы:**
```
Filename: "Романы из цикла «Ведьма с «Летающей ведьмы»»"
  ❌ БЫЛО: series = "" (не извлекалось вообще)
  ✅ СТАЛО: series = "Ведьма с «Летающей ведьмы»"

Filename: "Романы из цикла «Отрок»"
  ✅ БЫЛО и СТАЛО: series = "Отрок"
```

**Корень问題: Парсинг guillemets (« U+00AB и » U+00BB)**

Изначально использовался character class `[«"]` в regex, но это неправильно обрабатывал Unicode guillemets:
```python
# ❌ НЕПРАВИЛЬНО - character class не распознает Unicode guillemets
pattern = r'из\s+(?:цикла|серии)\s+[«"](.+)[«"]'
#                             ↑    ↑           это не работает с guillemets
```

**Решение (Февраль 26, 2026):**

1. **Упростить regex (не полагаться на character class):**
   ```python
   # ✅ ПРАВИЛЬНО - просто извлекаем все после "из цикла"
   cycle_match = re.search(r'из\s+(?:цикла|серии)\s+(.+)', content_in_brackets, re.IGNORECASE)
   if cycle_match:
       series_candidate = cycle_match.group(1).strip()
   ```

2. **Умная обработка внешних кавычек (сохранение внутренних):**
   ```python
   # Подсчитываем количество открывающих « и закрывающих »
   open_count = series_candidate.count('«')
   close_count = series_candidate.count('»')
   
   # Случай 1: Парные внешние кавычки («...»)
   # Примеры: "«Отрок»" (1«,1»), "«Ведьма с «Ведьмы»»" (2«,2»)
   if (open_count > 0 and open_count == close_count and 
       series_candidate.startswith('«') and series_candidate.endswith('»')):
       # Удаляем первую « и последнюю »
       series_candidate = series_candidate[1:-1]
   
   # Случай 2: Непарные - больше открывающих («...«...»)
   # Пример: "«Ведьма с «Летающей ведьмы»" (2«,1»)
   # Первая « это внешняя, остальные внутренние
   elif open_count > close_count and series_candidate.startswith('«'):
       # Удаляем только первую открывающую «
       series_candidate = series_candidate[1:]
   ```

**Примеры обработки:**

| Input | open_count | close_count | Действие | Output |
|-------|-----------|------------|---------|--------|
| `«Отрок»` | 1 | 1 | Парная → удалить обе | `Отрок` |
| `«Артуа»` | 1 | 1 | Парная → удалить обе | `Артуа` |
| `«Ведьма с «Ведьмы»»` | 2 | 2 | Парная → удалить обе | `Ведьма с «Ведьмы»` |
| `«Ведьма с «Летающей ведьмы»` | 2 | 1 | Непарная → удалить первую | `Ведьма с «Летающей ведьмы»` |
| `Ведьма с «Летающей ведьмы»` | 0 | 1 | Нет открывающей | (как есть) |

**Тестовые примеры из реальной базы:**

```csv
# Line 66: Парная структура (equals)
Filename: Корн Владимир - Артуа... (Романы из цикла «Артуа»)
→ proposed_series: "Артуа" ✅

# Line 70: Парная структура с другим префиксом
Filename: Красницкий Евгений - Отрок... (Романы + из цикла «Отрок»)
→ proposed_series: "Отрок" ✅

# Line 81: Вложенные кавычки (непарные)
Filename: Лысак Сергей - Снежная Королева (Романы из цикла «Ведьма с «Летающей ведьмы»)
→ proposed_series: "Ведьма с «Летающей ведьмы»" ✅
```

**Реализация в коде (passes/pass2_series_filename.py, строки ~119-130):**

```python
cycle_match = re.search(r'из\s+(?:цикла|серии)\s+(.+)', content_in_brackets, re.IGNORECASE)
if cycle_match:
    series_candidate = cycle_match.group(1).strip()
    # Удаляем внешние кавычки в зависимости от структуры
    open_count = series_candidate.count('«')
    close_count = series_candidate.count('»')
    
    # Если количество кавычек совпадает - удаляем первую и последнюю как пару
    if (open_count > 0 and open_count == close_count and 
        series_candidate.startswith('«') and series_candidate.endswith('»')):
        series_candidate = series_candidate[1:-1]
    # Если открывающих больше чем закрывающих, первая « это внешняя
    elif open_count > close_count and series_candidate.startswith('«'):
        series_candidate = series_candidate[1:]
        
    series_candidate = series_candidate.strip()
```

### 7.4 SERIES PASS 3: Нормализация названий серий

**Класс:** `Pass3SeriesNormalize` (passes/pass3_series_normalize.py)

**Назначение:** Стандартизировать формат названий серий.

**Нормализация (в порядке применения):**

1. **Удалить лишние пробелы:**
   ```
   "Война  в  Космосе" → "Война в Космосе"
   ```

2. **Удалить номеры выпусков в конце:**
   ```
   "Война в Космосе (1-3)" → "Война в Космосе"
   "Странник (тетралогия)" → "Странник"
   ```

3. **Удалить скобки с информацией об авторстве/сотрудничестве (Февраль 26, 2026):**
   Использует `series_cleanup_patterns` из config.json для удаления аннотаций о соавторах.
   ```
   "Лорд Системы (соавтор Яростный Мики)" → "Лорд Системы"
   "War in Space (with author X)" → "War in Space"
   "Серия (с участием Иванов)" → "Серия"
   ```
   
   **Конфигурация (config.json):**
   ```json
   "series_cleanup_patterns": [
     "\\s*\\(соавтор[ы]?[^)]*\\)\\s*",
     "\\s*\\(автор[ы]?[^)]*\\)\\s*",
     "\\s*\\(с участием[^)]*\\)\\s*",
     "\\s*\\(co-?author[s]?[^)]*\\)\\s*",
     "\\s*\\(with [^)]*\\)\\s*",
     "\\s*\\(by [^)]*\\)\\s*"
   ]
   ```
   
   **Реализация:** Все скобки с этими ключевыми словами удаляются до обработки служебных слов.

4. **Удалить служебные слова в конце (с word boundaries):**
   ```
   "Война и Мир том 1" → "Война и Мир"
   "Альпинист книга 2" → "Альпинист"  ← word boundary предотвращает обрезание 'т' в конце
   ```

5. **Применить conversions из config.json (если определены):**
   ```
   series_conversions: {
     "Война в космосе": "War in Space",
     "СЕРИЯ  (старая)": "СЕРИЯ"
   }
   ```

**Критический фикс (Февраль 26, 2026):**
- ❌ БЫЛО: regex без word boundaries обрезал слова как "Альпинист" → "Альпинис"
- ✅ ИСПРАВЛЕНО: Использование `\b` (word boundaries) в regex
  ```python
  pattern = r'\s*\b' + re.escape(word) + r'\b(\s+\d+)?\s*$'
  ```

**Результаты normalization:**
```
Input:  "Альпинист (Книга 1)"
Output: "Альпинист"

Input:  "Война и Мир   том   1"
Output: "Война и Мир"

Input:  "Лорд Системы (соавтор Яростный Мики)"
Output: "Лорд Системы"  ← (соавтор...) удалена

Input:  "Война в космосе"  (if conversion exists)
Output: "War in Space"
```

### 7.5 Статистика Series Extraction на Test1 (52 файла)

```
Total records: 52

series_source distribution:
├─ folder_dataset:  47  (90.4%)  ← из структуры папок
├─ filename:         1  (1.9%)   ← из имён файлов
└─ (empty):          4  (7.7%)   ← без серии (сборники или без паттерна)

metadata_series:
├─ заполнено:       48  (92.3%)  ← есть <sequence> в FB2
└─ пусто:            4  (7.7%)   ← нет series в метаданных
```

**Примеры результатов:**

```csv
file_path,metadata_series,proposed_series,series_source
Волков Тим\ISCARIOT\1. Выжить любой.fb2,ISCARIOT,ISCARIOT,folder_dataset
Волков Тим\Ай да Пушкин!\1. ...,Ай да Пушкин!,Ай да Пушкин!,folder_dataset
Волков Тим\Альпинист\1. ...,Альпинист,Альпинист,folder_dataset
Волков Тим\Пленники Зоны. Кровь цвета хаки.fb2,,Пленники Зоны,filename
Волков Тим\Бездна.fb2,,,,
```

### 7.6 Интеграция в Orchestrator (regen_csv.py)

**Порядок выполнения** (после PASS 2 Fallback для авторов):

```python
# SERIES EXTRACTION
print("[SERIES] Extracting series from folder structure...")
for record in self.records:
    # Extract from file path structure (similar to folder_author_parser)
    series, source = parse_series_from_folder_name(...)
    if series:
        record.proposed_series = series
        record.series_source = source

print("[SERIES] Extracting series from filenames...")
pass2_series = Pass2SeriesFilename(self.logger)
pass2_series.execute(self.records)

print("[SERIES] Normalizing series names...")
pass3_series = Pass3SeriesNormalize(self.logger)
pass3_series.execute(self.records)

# PASS 3-6 для авторов (не затрагивают series)
```

### 7.7 Файлы системы series

```
passes/
├── folder_series_parser/          ← Новая папка! Аналог folder_author_parser для серий
│   ├── __init__.py                  (parse_series_from_folder_name())
│   ├── pass0_structural_analysis.py (анализ структуры папки)
│   ├── pass1_pattern_selection.py   (выбор подходящего паттерна)
│   └── pass2_series_extraction.py   (извлечение серии с валидацией от автора)
├── pass2_series_filename.py       ← Новый файл! Извлечение из имён файлов
└── pass3_series_normalize.py      ← Новый файл! Нормализация серий

fb2_author_extractor.py
├── _extract_series_from_metadata()   ← Новый метод! Парсинг <sequence> из FB2
```

### 7.8 PASS 4: Применение консенсуса к сериям (Февраль 26, 2026)

**Класс:** `Pass4Consensus` (passes/pass4_consensus.py)

**Назначение:** Применить консенсус-серии к файлам БЕЗ proposed_series в одной папке.

**Проблема, которую решает:**
- Файл "Неандертальский параллакс (сборник)" извлекает серию из имени, но заблокирован blacklist'ом
- Другие файлы в папке "Гоминиды", "Люди", "Гибриды" имеют ту же серию в метаданных
- **Решение:** Применить консенсус ТОЛЬКО к файлам, чьи `extracted_series_candidate` совпадают с найденным консенсусом

**Архитектура (2-уровневый consensus):**

**Уровень 1: Консенсус на основе extracted_series_candidate (для depth ≥ 2 файлов)**

Процедура:
```python
for folder, group_records in groups.items():
    # Шаг 1: Посчитать сколько раз встречается каждый candidate
    candidates_count = {}
    for record in group_records:
        if record.extracted_series_candidate:
            candidate = record.extracted_series_candidate
            candidates_count[candidate] = candidates_count.get(candidate, 0) + 1
    
    # Шаг 2: Только candidates which appear 2+ times (true consensus)
    consensus_candidates = {
        candidate: count 
        for candidate, count in candidates_count.items() 
        if count >= 2
    }
    
    # Шаг 3: Apply ONLY to files whose extracted_series_candidate matches consensus
    for record in group_records:
        if (not record.proposed_series and 
            record.extracted_series_candidate in consensus_candidates):
            record.proposed_series = record.extracted_series_candidate
            record.series_source = "consensus"
```

**Ключевое правило:** Консенсус применяется **ТОЛЬКО** если:
1. ✅ Файл НЕ имеет `proposed_series` (пусто)
2. ✅ Файл имеет `extracted_series_candidate`
3. ✅ Этот candidate встречается 2+ раза в группе папок

**Это предотвращает:** Применение "Неандертальский параллакс" к файлу "Ката Бинду" который имеет другой candidate или вообще его не имеет.

**Уровень 2: Консенсус на основе metadata_series (для depth 2 файлов без candidates)**

Процедура:
```python
for folder, group_records in groups.items():
    # Шаг 1: Посчитать сколько раз встречается каждый metadata_series
    metadata_series_count = {}
    for record in group_records:
        # Только series которые уже привели к proposed_series
        if record.metadata_series and record.proposed_series == record.metadata_series:
            series = record.metadata_series
            metadata_series_count[series] = metadata_series_count.get(series, 0) + 1
    
    # Шаг 2: Only series that appear 2+ times
    consensus_metadata_series = {
        series: count 
        for series, count in metadata_series_count.items() 
        if count >= 2
    }
    
    # Шаг 3: Apply to files with empty proposed_series if they have matching metadata_series
    for record in group_records:
        if (not record.proposed_series and 
            record.metadata_series in consensus_metadata_series):
            record.proposed_series = record.metadata_series
            record.series_source = "consensus"
```

**Примеры работы консенсуса:**

**Пример 1: Сойер - консенсус с extracted_series_candidate**
```
Папка: Роберт Дж. Сойер (45 файлов)

Файлы:
├─ Неандертальский параллакс (сборник).fb2
│  ├─ extracted_series_candidate: "Неандертальский параллакс"  ← extracted!
│  ├─ metadata_series: ""  ← collection keyword блокирует
│  ├─ proposed_series: ""  ← было пусто
│  └─ [ПОСЛЕ PASS 4] → proposed_series: "Неандертальский параллакс" (consensus!)

├─ Гоминиды.fb2
│  ├─ extracted_series_candidate: "Неандертальский параллакс"
│  ├─ metadata_series: "Неандертальский параллакс"
│  └─ proposed_series: "Неандертальский параллакс"  ← было

├─ Люди.fb2
│  ├─ extracted_series_candidate: "Неандертальский параллакс"
│  ├─ metadata_series: "Неандертальский параллакс"
│  └─ proposed_series: "Неандертальский параллакс"  ← было

├─ Ката Бинду.fb2
│  ├─ extracted_series_candidate: "Ката Бинду"  ← ДРУГОЙ candidate!
│  ├─ metadata_series: ""
│  ├─ proposed_series: ""
│  └─ [ПОСЛЕ PASS 4] → proposed_series: ""  ← НЕ применён (другой candidate)
```

**Статистика:** 
- Консенсус найдена "Неандертальский параллакс" (встречается 3+ раза)
- Применена только к сборнику (whose candidate matches)
- "Ката Бинду" осталась пустой (her candidate не совпадает)
✅ **Результат:** Правильное разграничение серий

**Пример 2: Группа файлов с одинаковой metadata_series**
```
Папка: Волков Тим

Файлы:
├─ ISCARIOT 01.fb2
│  ├─ proposed_series: "ISCARIOT" (из папки)
│  └─ metadata_series: "ISCARIOT"

├─ ISCARIOT 02.fb2
│  ├─ proposed_series: "ISCARIOT" (из папки)
│  └─ metadata_series: "ISCARIOT"

├─ Сборник.fb2
│  ├─ proposed_series: ""  ← сборник заблокирован
│  ├─ metadata_series: "ISCARIOT"  ← но metadata есть!
│  └─ [ПОСЛЕ PASS 4] → proposed_series: "ISCARIOT" (consensus по metadata!)
```

**Внутренняя структура BookRecord:**

```python
@dataclass
class BookRecord:
    # ... другие поля ...
    
    # Series fields
    metadata_series: str = ""           # Из FB2 <sequence>
    proposed_series: str = ""           # Финальная серия (эволюция)
    series_source: str = ""             # Источник: folder_dataset/filename/metadata/consensus
    
    # Internal field для consensus
    extracted_series_candidate: str = ""  # Серия извлечённая из filename (БЕЗ валидации)
                                           # Заполняется в PASS 2, используется в PASS 4
```

**Файлы, затронутые PASS 4:**
- `passes/pass4_consensus.py` - Добавлены две процедуры консенсуса (extracted + metadata)
- `passes/pass2_series_filename.py` - Установка `extracted_series_candidate` для depth 2 файлов
- `passes/pass1_read_files.py` - Добавление `extracted_series_candidate` поля в BookRecord

---

## 8. CSV Выход: Структура файла

### 8.1 Перечень колонок (в порядке слева направо)

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


### 8.2 Примеры строк CSV

```csv
file_path,metadata_authors,proposed_author,author_source,metadata_series,proposed_series,series_source,file_title
Гоблин (MeXXanik)/Адвокат Чехов/book1.fb2,Петр Гоблин (MeXXanik),Гоблин MeXXanik,folder_dataset,Адвокат Чехов,Адвокат Чехов,folder_dataset,Адвокат Чехов
Развлечение/Книга от файла.fb2,Неизвестный Автор,Развлечение,filename,,Развлечение,filename,Книга от файла
Сборник/book3.fb2,Иван Петров,Петров Иван,metadata,,Петров Иван,metadata,Третья книга
Компиляция/Серия1/book4.fb2,Петр Гоблин,Гоблин MeXXanik,consensus,Серия1,Сборник,consensus,Четвертая
```

### 8.3 Эволюция `proposed_author` и `proposed_series` по PASS

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

### 8.4 Порядок сохранения

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

## 9. Smart Encoding Detection для FB2 файлов

### 9.0 Проблема с кодировками

FB2 файлы могут содержать текст в разных кодировках:
- **UTF-8** (современный стандарт, рекомендуется)
- **CP1251** (Windows-1251, часто используется в русских текстах)

**Старый подход (priority-based):**
```
Попробовать UTF-8
    → Если ошибка декодирования → попробовать CP1251
    → Если обе ошибки → гарантированный сбой для обоих кодеков
```

Проблема: лучше выбирается не по результату, а по порядку.

### 9.1 Новый подход: Validation-Based Encoding Detection

**Алгоритм:**
```
1. Попытка 1: UTF-8 со strict режимом декодирования
   - Если успешно → используем UTF-8
   - Если ошибка → Попытка 2

2. Попытка 2: CP1251 со strict режимом декодирования
   - Если успешно → используем CP1251
   - Если ошибка → КРИТИЧЕСКАЯ ОШИБКА (файл повреждён)

Результат: Первый успешный декодер используется
Гарантия: UTF-8 приоритет, но CP1251 работает как fallback
```

**Реализация:**
```python
def _detect_and_decode(file_path: Path, content: bytes) -> str:
    """Определить кодировку и декодировать с гарантией успеха."""
    
    # Попытка 1: UTF-8
    try:
        return content.decode('utf-8')
    except UnicodeDecodeError:
        pass  # Попробуем CP1251
    
    # Попытка 2: CP1251
    try:
        return content.decode('cp1251')
    except UnicodeDecodeError:
        # Обе кодировки не сработали - критическая ошибка
        self.logger.log(f"[Кодировка] ОШИБКА: {file_path} не декодируется")
        return None  # или вернуть с заменой символов

# Применение ко всем методам чтения FB2:
- _extract_author_from_metadata() ✅
- _extract_all_authors_from_metadata() ✅  
- _extract_title_from_fb2() ✅
```

**Результаты:**
```
ДО:  6 файлов с ошибками кодирования
ПОСЛЕ: 0 файлов с ошибками кодирования (100% успех)
```

**Примеры проблемных файлов, которые теперь работают:**
```
1. "Зорич Александр, Жарковский Сергей - Коллективная безопасность.fb2"
   - Требил CP1251
   - ✅ Теперь: "Зорич Александр; Жарковский Сергей"

2. Файлы с русскими символами (ё, й, ш, щ, ю, ц, х)
   - ✅ Все корректно декодируются
```

---

## 10. Примеры использования параметров

### 8.1 Пример 1: Проверка на мусор

```python
blacklist = settings.get_filename_blacklist()
# blacklist = ["компиляция", "сборник", "антология", ...]

if any(word in proposed_author.lower() for word in blacklist):
    # Это скорее всего название папки, а не автор
    skip_record = True
```

### 8.2 Пример 2: Определение порядка имени/фамилии

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

### 8.3 Пример 3: Применение конвертаций

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

### 8.4 Пример 4: Определение глубины парсинга папок

```python
folder_parse_limit = settings.get_folder_parse_limit()  # 3

file_path = Path("Гоблин (MeXXanik)/Адвокат Чехов/book.fb2")

# Поиск автора вверх на максимум 3 уровня
for i in range(min(folder_parse_limit, len(file_path.parts)-1)):
    parent = file_path.parents[i]
    # Анализировать parent для поиска автора
```

---

## 11. Интеграция с другими модулями

### 9.1 Зависимости в __init__

```python
from settings_manager import SettingsManager
from logger import Logger
from fb2_author_extractor import FB2AuthorExtractor
from author_normalizer_extended import AuthorNormalizerExtended  # Новый объединённый модуль
```

### 9.2 Инициализация в RegenCSVService.__init__

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

## 12. Изменение архитектуры

### 10.1 ДО (старая система - удаляется)

```
regen_csv.py (1459 строк)
├── Парсинг папок (PASS 1) ❌ УДАЛИТЬ
├── Обработка FB2 (PASS 2) ❌ УДАЛИТЬ
├── Нормализация (PASS 3)  ✅ СОХРАНИТЬ
├── Консенсус (PASS 4)     ✅ СОХРАНИТЬ
├── Конвертации (PASS 5)   ✅ СОХРАНИТЬ
└── Раскрытие (PASS 6)     ✅ СОХРАНИТЬ
```

### 10.2 ПОСЛЕ (новая система - создаётся)

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

## 13. Взаимодействие компонентов

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

## 14. Критические параметры конфига, используемые в regen_csv.py

| Параметр | Тип | Используется в | Функция | Пример |
|---|---|---|---|---|
| `folder_parse_limit` | int | PASS 1 (stub) | Глубина поиска папок | 3 |
| `author_surname_conversions` | Dict | PASS 1, 5 | Конвертация фамилий | `{"Гоблин (MeXXanik)": "Гоблин MeXXanik"}` |
| `male_names` | List | PASS 3, 6 | Определение порядка имён | `["Александр", "Андрей", ...]` |
| `female_names` | List | PASS 3, 6 | Определение порядка имён | `["Александра", "Анна", ...]` |
| `filename_blacklist` | List | PASS 1, 3 | Фильтрация мусора | `["сборник", "антология", ...]` |
| `collection_keywords` | List | PASS 2 Fallback | Обнаружение сборников | `["сборник", "хиты", "лучшее", ...]` |
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

## 15. Исправления и улучшения логики парсинга (Feb 2026)

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

### 11.6 Commit 2df775d + 3206d72: Обнаружение сборников в PASS 2 Fallback (Feb 2026)

**Новая функциональность:** PASS 2 Fallback теперь обнаруживает файлы-сборники/антологии

**Проблема:** Файлы с 3+ авторами в метаданных (сборники), но с названиями типа "Хиты фантастики" должны быть помечены как "Сборник", а не как список каждого автора.

**Решение:**

1. **Добавлена конфигурация `collection_keywords` в config.json:**
   - 30 ключевых слов для обнаружения сборников (русские и английские)
   - Примеры: "сборник", "антология", "хиты", "лучшее", "шедевры", "коллекция", "собрание сочинений"

2. **Реализованы методы в Pass2Fallback:**
   ```python
   def _count_authors(authors_str: str) -> int:
       """Подсчёт авторов, разделённых '; ' или ', '"""
       
   def _is_collection_file(filename: str) -> bool:
       """Проверка наличия ключевых слов сборника в имени файла (case-insensitive)"""
   ```

3. **Обновлена логика execute():**
   - Если 3+ авторов И ключевые слова в filename → `proposed_author = "Сборник"`, `author_source = "collection"`
   - Иначе применяется metadata как раньше

**Результаты:**
```
Файл: "Хиты Военной фантастики.fb2"
Metadata: "Александр Михайловский; Александр Харников; Рустам Максимов; Влад Савин; Комбат Найтов" (5 авторов)

Обнаружено:
- author_count = 5 (≥ 3) ✓
- filename содержит "хиты" (ключевое слово) ✓
- Итог: proposed_author = "Сборник", author_source = "collection"
```

**Обработка многоавторских произведений:**

Файлы с 2 авторами (соавторство) НЕ помечаются как сборники, а обрабатываются как обычные многоавторские работы:
```
Filename: "Земляной, Живой - Академик.fb2"
Authors: 2 (< 3) → Не сборник
Результат: 
  proposed_author: "Земляной Андрей, Живой Алексей"
  author_source: "filename"
```

**Критические правила:**
- ✅ Сборники обнаруживаются ДО применения metadata
- ✅ Условия: 3+ авторов И ключевые слова ОДНОВРЕМЕННО
- ✅ Защита от ложных срабатываний на файлы с легитимными 3-мя соавторами без ключевых слов

---

### 11.7 Feature: Sbornik Detection с валидацией известных имен в PASS 2 (Fe 20, 2026)

**Проблема:** Некоторые файлы с названиями типа "Боевая фантастика - лучшее.fb2" при ошибочном парсинге могут быть распознаны как авторы (например, "фантастика Боевая"), даже когда в метаданных есть реальные 4+ авторов.

**Root cause:** PASS 2 (_looks_like_author_name) проверял структурные признаки имени (буквы, длина, нет цифр) но НЕ проверял, что текст содержит РЕАЛЬНОЕ ИМЯ из списка известных имен.

**Решение:**

1. **Обновлен Pass2Filename.__init__():**
   ```python
   def __init__(self, settings, logger, work_dir, 
                male_names=None, female_names=None):
       # Новые параметры для валидации
       self.male_names = male_names or set()
       self.female_names = female_names or set()
   ```

2. **Обновлены в Pass2Filename._looks_like_author_name():**
   ```python
   # НОВОЕ: Валидация наличия известных имен
   if self.male_names or self.female_names:
       text_words = set(text.lower().split())
       has_known_name = any(
           word in self.male_names or word in self.female_names
           for word in text_words
       )
       if not has_known_name:
           return False  # Не параметрь - это название коллекции!
   
   return True
   ```

3. **Обновлена передача данных в regen_csv.py (orchestrator):**
   ```python
   # PRECACHE загружает 75 мужских имен + 60 женских имен
   precache = Precache(work_dir, settings, logger, folder_parse_limit)
   author_folder_cache = precache.execute()
   
   # Передаём в PASS 2 для валидации извлеченного текста
   pass2 = Pass2Filename(
       settings, logger, work_dir,
       male_names=precache.male_names,        # ← 75 мужских имен
       female_names=precache.female_names    # ← 60 женских имен
   )
   pass2.execute(records)
   ```

**Примеры валидации:**

```
Тест 1: Название коллекции (без известных имен)
Input:    "фантастика Боевая"
has_known_name check:
  - "фантастика" ∉ (male_names ∪ female_names) ✗
  - "боевая" ∉ (male_names ∪ female_names) ✗
Result:   False → ОТКЛОНЕНО ✅

Тест 2: Реальное имя автора
Input:    "Михаил Атаманов"
has_known_name check:
  - "михаил" ∈ male_names ✓
Result:   True → ПРИНЯТО ✅

Тест 3: Еще одно название коллекции
Input:    "Боевая романс"
has_known_name check:
  - "боевая" ∉ (male_names ∪ female_names) ✗
  - "романс" ∉ (male_names ∪ female_names) ✗
Result:   False → ОТКЛОНЕНО ✅

Тест 4: Имя одного слова (фамилия + известное имя)
Input:    "Олег Сапфир" (or just "Олег")
has_known_name check:
  - "олег" ∈ male_names ✓
Result:   True → ПРИНЯТО ✅
```

**Реальный результат из Test1 (672 файлов):**

```
Файл: "Боевая фантастика - лучшее.fb2"
Metadata: "Михаил  Атаманов; Михаил  Михеев; Ярослав  Горбачев; Владимир  Поселягин" (4 автора)

PASS 1: proposed_author = "" (не найдено в иерархии папок)
PASS 2 (старо БЕЗ валидации имен):
  - pattern matching: extracted "фантастика Боевая" ❌
  - _looks_like_author_name("фантастика Боевая") => TRUE (неправильно!)
  - Result: proposed_author = "фантастика Боевая" ❌

PASS 2 (НОВОЕ С валидацией имен):
  - pattern matching: extracted "фантастика Боевая"
  - has_known_name check: "фантастика" ∉ male_names, "боевая" ∉ female_names ✗
  - _looks_like_author_name("фантастика Боевая") => FALSE (правильно!) ✅
  - Result: proposed_author = "" (пусто, пропускаем)

PASS 2 Fallback (срабатывает теперь):
  - proposed_author = "" → проверяем метаданные
  - author_count = 4 (≥ 3)
  - filename содержит "лучшее" (collection keyword) ✓
  - Result: proposed_author = "Сборник", author_source = "collection" ✅

Final CSV:
  proposed_author: "Сборник"
  author_source: "collection"
  metadata_authors: "Михаил  Атаманов; Михаил  Михеев; Ярослав  Горбачев; Владимир  Поселягин"
```

**Статистика успешного выполнения:**

```
Test1 dataset (672 файлов):
- PRECACHE loaded: 75 male names, 60 female names ✓
- PASS 1: 0 авторов из иерархии папок
- PASS 2: 1 автор извлечен из filename валидированных методом
  (все остальные отклонены как названия коллекций)
- PASS 2 Fallback: Применены метаданные для 671 файла
- Full pipeline: все 6 PASS'ов выполнены успешно ✅
```

**Критические моменты реализации:**

- ✅ Валидация происходит ПОСЛЕ извлечения паттернов (не мешает парсингу)
- ✅ Требует УКАЗАНИЯ всего текста проверки слова (splitting по пробелам)
- ✅ Case-insensitive сравнение (приводим к lower() перед проверкой)
- ✅ При отсутствии name lists (пустой male_names/female_names) система работает как раньше (backward compatible)

---

## Готово.


## 16. Обработка соавторства (Co-authorship)

### 12.1 Проблема

При наличии нескольких авторов в одной папке (например, 'Белаш Александр, Людмила') система должна корректно обрабатывать оба имени в полном формате ФИ.
