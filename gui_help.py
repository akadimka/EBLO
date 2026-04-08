"""
Окно справки — структурированное описание программы EBook Library Organizer.

Архитектура окна:
  ┌─[Дерево разделов]──┬──[Текст описания]─────────────────┐
  │  ▶ О программе     │  # Заголовок раздела               │
  │  ▶ Меню            │  Текст...                          │
  │  ▶ Модули          │                                    │
  │  ▶ Алгоритм        │                                    │
  └─────────────────────┴────────────────────────────────────┘

Содержимое встроено прямо в код — не требует внешних .md файлов.
"""

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

try:
    from window_persistence import setup_window_persistence
    from settings_manager import SettingsManager
except ImportError:
    from .window_persistence import setup_window_persistence
    from .settings_manager import SettingsManager


# ---------------------------------------------------------------------------
# Справочное содержимое: list of (section_title, subsection_title, text)
# section_title=None  →  раздел верхнего уровня (отображается как категория)
# ---------------------------------------------------------------------------

HELP_TREE = [
    # ── Раздел «О программе» ─────────────────────────────────────────────
    ("О программе", None, ""),   # заголовок категории — текст не показывается
    ("О программе", "Назначение", """\
EBook Library Organizer — инструмент организации коллекции FB2-книг.

Программа решает три задачи:

  1. НОРМАЛИЗАЦИЯ — автоматически определяет автора и серию каждой книги,
     опираясь на структуру папок, имя файла и мета-теги внутри FB2.
     Результат — единый формат «Фамилия Имя», устранение дубликатов и опечаток.

  2. СИНХРОНИЗАЦИЯ — перекладывает файлы в иерархию
       Библиотека / Автор / Серия / Книга.fb2
     и одновременно обновляет мета-теги FB2 (<author>, <sequence>)
     и базу данных SQLite.

  3. АНАЛИТИКА — дашборд, поиск по метаданным, трекер новых книг,
     обнаружение пропусков в сериях, OPDS-каталог для читалок,
     проверка целостности FB2, рейтинги с Fantlab.ru.
"""),

    ("О программе", "Технологии", """\
  • Python 3.13, Tkinter (GUI)
  • SQLite (.library_cache.db) — хранение нормализованных метаданных
  • FB2 XML — парсинг через регулярные выражения (без lxml)
  • Fantlab.ru REST API — онлайн-рейтинги (без ключа)
  • OPDS 1.2 Atom — экспорт каталога для e-reader приложений
  • Git — версионирование, репозиторий на GitHub (akadimka/EBLO)
"""),

    # ── Меню программы ────────────────────────────────────────────────────
    ("Меню", None, ""),
    ("Меню", "Файл", """\
  • Новая сессия        — сбросить текущие результаты
  • Открыть результаты  — загрузить ранее сохранённый CSV
  • Сохранить результаты— сохранить текущий CSV
  • Загрузка жанров     — импортировать genres.xml
  • Настройки           — открыть окно настроек (config.json)
  • Выход
"""),
    ("Меню", "Действия", """\
  • Сканирование    — запустить полный pipeline (PASS 1–6):
                      читает FB2, определяет авторов и серии,
                      нормализует, строит CSV, открывает окно нормализации.

  • Нормализация    — открыть окно просмотра и редактирования результатов
                      (таблица с фильтром, кнопки: Создать CSV, Получить имена,
                       Битые файлы, Великомученницы, Дубликаты, Удалить пустые папки).

  • Синхронизация   — переложить файлы по целевой структуре папок,
                      обновить FB2-теги и записать данные в БД.

  • База данных     — просмотр содержимого SQLite (.library_cache.db):
                      вкладки «Книги» и «Серии».
"""),
    ("Меню", "Жанры", """\
  • Менеджер жанров — загрузить genres.xml, просмотреть дерево жанров,
                      присвоить жанр папке вручную.
"""),
    ("Меню", "Лог", """\
  • Показать лог — окно с хронологическим журналом всех операций.
                   Буфер — последние 10 000 строк (deque), обновление
                   батчами каждые 100 мс для минимальной нагрузки на UI.
"""),
    ("Меню", "Библиотека", """\
  • Статистика              — дашборд: итоговые карточки + топ авторов/серий,
                              распределение жанров и источников авторов.

  • Поиск по метаданным     — форма с полями автор/название/серия/жанр,
                              поиск через LIKE в БД (до 2000 результатов),
                              кнопка «Рейтинг (Fantlab)» для выбранной книги.

  • Новые книги             — книги, добавленные в БД за последние N дней;
                              сортировка по любому столбцу, открытие в Explorer.

  • Серии с пробелами       — серии, в которых пропущены порядковые номера
                              (<sequence number="N"/>);
                              показывает: автор, серия, имеющиеся №, пропущенные №.

  • Проверка целостности FB2 — сканирует папку, проверяет каждый FB2:
                               XML-корректность, наличие <title-info>, <book-title>,
                               непустой <author>; возможность удалить битые файлы.

  • Генератор OPDS-каталога — создаёт набор статических Atom XML-файлов
                              по стандарту OPDS 1.2 (каталог по авторам и сериям)
                              для подключения в Marvin, PocketBook и т.п.

  • Помощь                  — это окно.
"""),

    # ── Модули ────────────────────────────────────────────────────────────
    ("Модули", None, ""),
    ("Модули", "gui_main.py", """\
Главное окно приложения (класс MainWindow).

  • Создаёт меню, основной интерфейс (дерево папок / listbox-режим).
  • Запускает фоновую очистку БД от orphaned записей при старте.
  • Открывает все дочерние окна по командам меню.
  • Хранит ссылки на SettingsManager, Logger, GenresManager.
  • Дебаунс (400 мс) при изменении пути к папке.
"""),
    ("Модули", "regen_csv.py", """\
Сервис генерации нормализованных метаданных (класс RegenCSVService).

  Метод generate_csv(folder_path) запускает цепочку PASS:
    Precache → Pass1 → Pass2(filename) → Pass2(fallback)
             → Pass2(series_filename) → Pass3(normalize)
             → Pass3(series_normalize) → Pass4(consensus)
             → Pass5(conversions) → Pass6(abbreviations)

  Возвращает список BookRecord — по одному на каждый FB2-файл.
  Опционально записывает regen.csv.
"""),
    ("Модули", "passes/ — конвейер PASS", """\
Каждый PASS — отдельный класс в папке passes/.

  pass1_read_files.py     — параллельное (ThreadPoolExecutor) чтение FB2;
                            заполняет BookRecord.metadata_* и series_number;
                            определяет author из кэша папок (Precache).

  pass2_filename.py       — извлечение автора из имени файла:
                            блочный pattern-matching (BlockLevelPatternMatcher).
                            Защита от записи <book-title> как автора:
                            если кандидат совпадает с FB2-заголовком книги —
                            повторный поиск без паттернов «Title-first».
                            Раскрытие инициалов (_expand_initial_surnames):
                              "Г.Диксон" → "Гордон Диксон"
                              источник = filename_meta_confirmed.
                            Если ≥ 3 авторов в метаданных:
                              • ключевые слова в имени/заголовке → "Сборник"
                              • без ключевых слов → "Соавторство".

  pass2_fallback.py       — для файлов без автора из папки/filename:
                            пытается взять автора из FB2-метаданных.

  pass2_series_filename.py — извлечение серии из имени файла и папки.
                             Вызов _propagate_ancestor_folder_authors()
                             в самом начале: поднимается по дереву папок,
                             первая папка с именем-автором устанавливает
                             folder_dataset для всех файлов в поддереве.
                             Иерархические серии: «ОсновнаяСерия\\N. Подсерия».
                             Вариантные папки (СИ, ЛП и т.п.) наследуют
                             серию родительской папки (variant_folder_keywords).
                             _unify_folder_series_source() перекрывает слабые
                             источники (metadata, filename, consensus)
                             авторитетным значением из folder_dataset /
                             folder_hierarchy.

  pass3_normalize.py      — нормализация формата «Фамилия Имя»,
                            сортировка авторов, конвертация ё→е.

  pass3_series_normalize.py — очистка названий серий:
                             удаление trailing №/N, нормализация разделителей.

  pass4_consensus.py      — консенсус: если у N файлов одна папка и разные
                            авторы — выбирается наиболее частый.
                            Кэш нормализации (_series_norm_cache).
                            Очистка folder_hierarchy-серий со встроенным
                            именем автора (рекламные папки издателя):
                            если имя автора найдено в proposed_series
                            (первые 4 символа, устойчиво к склонению) —
                            серия заменяется на metadata_series или сбрасывается.
                            Иерархическая унификация: «Серия» + «Серия\Подсерия»
                            → canonical = кратчайший вариант (работает для
                            разделителей '. ' и '\').

  pass5_conversions.py    — финальные преобразования (транслитерация и т.п.)

  pass6_abbreviations.py  — раскрытие аббревиатур «А.Фамилия» → «Имя Фамилия»
                            по словарям male_names / female_names.
"""),
    ("Модули", "fb2_author_extractor.py", """\
Низкоуровневый парсинг FB2 XML (класс FB2AuthorExtractor).

  _extract_all_metadata_at_once(path)
      Читает файл один раз, извлекает одновременно:
        title     — <book-title>
        authors   — все <author> (first-name + last-name)
        series    — <sequence name="...">
        series_number — <sequence number="N">
        genre     — <genre>
      Возвращает dict. Используется в Pass1.

  Кодировка: автодетект UTF-8 / CP-1251; fallback replace.
  Единственный экземпляр создаётся в regen_csv.py и передаётся во все PASS.
"""),
    ("Модули", "synchronization.py", """\
Синхронизация библиотеки (класс SynchronizationService).

  synchronize(records, progress_callback)
      1. Очистка БД от orphaned записей
      2. Дедупликация — поиск дублей по (author, series, title)
      3. Перемещение файлов: shutil.move() в структуру Автор/Серия/
      4. Патч FB2-тегов: перезаписывает <author> и <sequence> в XML,
         сохраняя исходную кодировку (UTF-8 / CP-1251) и BOM
      5. Запись в БД: executemany INSERT с series_number
      6. Очистка пустых папок

  sync_database_with_library()  — удаляет orphaned записи (файлы исчезли).
                                  Вызывается при старте приложения.

  БД: .library_cache.db (SQLite)
  Таблица books: id, author, series, series_number, title,
                 file_path, file_hash, genre, added_date, ...
"""),
    ("Модули", "precache.py", """\
Предварительный анализ структуры папок (класс Precache).

  Строит словарь {папка → (author, source)} до запуска Pass1.
  Используется для быстрого определения автора по иерархии:
    Библиотека/Иванов Иван/  →  author = "Иванов Иван"

  Папки с ключевыми словами из filename_blacklist пропускаются.
"""),
    ("Модули", "passes/folder_author_parser/", """\
Парсер авторов из структуры папок (4 шага):

  pass0_structural_analysis.py — анализ глубины и структуры иерархии.
  pass1_pattern_selection.py   — выбор подходящего паттерна из config.json.
  pass2_author_extraction.py   — извлечение имени автора.
  validation.py                — валидация (черный список, формат имени).
"""),
    ("Модули", "passes/folder_series_parser/", """\
Парсер серий из структуры папок (3 шага):

  pass0_structural_analysis.py — анализ глубины.
  pass1_pattern_selection.py   — выбор паттерна.
  pass2_series_extraction.py   — извлечение названия серии.
"""),
    ("Модули", "block_level_pattern_matcher.py", """\
Блочный сопоставитель паттернов (класс BlockLevelPatternMatcher).

  Разбивает имя файла на структурные блоки:
    ["Янковский Дмитрий", "Охотник", "(Тетралогия)"]

  Токенизирует паттерны (Author / Title / Series),
  вычисляет score (0–1) совпадения структуры с паттерном.
  Порог по умолчанию: 0.6.
  Возвращает отдельно блок автора и блок серии.

  Обеспечивает 93 % точность (157/168 файлов) на типичной коллекции.
"""),
    ("Модули", "settings_manager.py", """\
Менеджер конфигурации (класс SettingsManager).

  Читает / записывает config.json.
  Ключевые методы:
    get_library_path()             — целевая папка библиотеки
    get_last_scan_path()           — последняя сканированная папка
    get_settings_file_path()       — путь к файлу настроек (config.json)
    get_genres_file_path()         — путь к файлу жанров (genres.xml)
    get_male_names() / get_female_names() — словари имён
    get_filename_blacklist()       — слова-исключения (Том, Часть, …)
    get_no_series_folder_names()   — имена папок «Вне серии» / «Без серии»
    get_author_series_patterns_in_files() — паттерны для filename
    get_author_series_patterns_in_folders() — паттерны для папок
    auto_init_file_paths()         — авто-определение путей при запуске
"""),
    ("Модули", "gui_normalizer.py", """\
Окно нормализации (класс CSVNormalizerApp).

  • Таблица с фильтром (Фильтр: поле — фильтрует по всем столбцам).
  • Пагинация: первые 1000 строк + кнопка «Загрузить ещё».
  • StdoutRedirector: перехватывает print() из PASS, батчи 100 мс.
  • Кнопки:
      Создать CSV       — запустить полный pipeline в фоновом потоке
      Получить имена    — открыть NamesDialog (редактирование словарей имён)
      Битые файлы       — открыть BrokenFilesWindow
      Великомученницы   — файлы, у которых все авторы — женские имена
      Дубликаты         — DuplicateFinderWindow
      Удалить пустые папки
      Логи

NamesDialog:
  • Открывается через «Получить имена»; запускает полный pipeline
    (Pass1–Pass6) через csv_service.generate_csv(output_csv_path=None) —
    результаты идентичны CSV-файлу.
  • Показывает только авторов, у которых хотя бы одно слово имени
    отсутствует в словарях male_names / female_names.
  • Кликабельные блоки слов → добавить в мужской или женский список.
  • Кнопка «Сверить онлайн» — запускает Wikidata-поиск по требованию
    (ранее поиск запускался автоматически при открытии диалога).
  • Цветные строки + тултипы: зелёный=найден, персиковый=неизвестен,
    розовый=ошибка сети; тултип динамически описывает смысл цвета.
"""),
    ("Модули", "gui_dashboard.py", """\
Окно статистики (DashboardWindow).

  6 карточек: книг, авторов, серий, жанров, % в сериях, % известных авторов.
  4 вкладки: топ авторов, топ серий, жанры, источники авторов.
  Данные загружаются в фоновом потоке из SQLite.
  Кнопка «Обновить» — повторная загрузка.
"""),
    ("Модули", "gui_search.py", """\
Поиск по метаданным (SearchWindow).

  Форма: автор / название / серия / жанр (все поля необязательны).
  Запрос: SELECT ... WHERE author LIKE ? AND title LIKE ? ... LIMIT 2000.
  Сортировка по клику на заголовок столбца.
  Двойной клик / кнопка → открыть папку в Explorer.
  Кнопка «Рейтинг (Fantlab)» → FantlabWindow для выбранной книги.
"""),
    ("Модули", "gui_series_gaps.py", """\
Серии с пробелами (SeriesGapsWindow).

  Читает из БД поля series, series_number.
  Группирует по (author, series), переводит series_number в int,
  находит пробелы в числовой последовательности.
  Настраиваемый порог — минимальное количество книг в серии (по умолчанию 2).
  Показывает: автор | серия | имеющиеся номера | пропущенные номера.
"""),
    ("Модули", "gui_new_books.py", """\
Новые книги (NewBooksWindow).

  Показывает книги, добавленные в БД за последние N дней (настраивается спиннером).
  Запрос: SELECT ... WHERE added_date >= ?
  Двойной клик → Explorer. Сортировка по любому столбцу.
"""),
    ("Модули", "gui_integrity_check.py", """\
Глубокая проверка FB2 (IntegrityCheckWindow).

  Для каждого .fb2 файла в папке проверяет:
    1. XML-корректность (xml.etree.ElementTree)
    2. Наличие блока <title-info>
    3. Непустой <book-title>
    4. Наличие хотя бы одного непустого <author>
    5. Декларация кодировки не противоречит содержимому

  Кнопка «Удалить выделенные» — физическое удаление с диска.
  Кнопка «Остановить» — прервать сканирование.
"""),
    ("Модули", "opds_generator.py", """\
Генератор OPDS-каталога (OPDSGeneratorWindow / generate_opds()).

  Создаёт набор статических XML-файлов стандарта OPDS 1.2 (Atom):
    catalog.xml         — корневой навигационный фид
    by_author.xml       — индекс авторов
    by_series.xml       — индекс серий
    author_<hash>.xml   — фид приобретения для каждого автора
    series_<hash>.xml   — фид для каждой серии

  Книги в сериях сортируются по series_number.
  Готовый каталог подключается в Marvin, PocketBook, Kybook и т.п.
"""),
    ("Модули", "fantlab_client.py", """\
Клиент Fantlab.ru (FantlabWindow).

  Поиск: GET https://api.fantlab.ru/search-works?q=QUERY
  Детали: GET https://api.fantlab.ru/work/ID
    → рейтинг, количество голосов, количество отзывов, описание, жанры.

  Кэш в памяти (_search_cache, _rating_cache) исключает повторные запросы.
  Кнопка «Открыть на Fantlab.ru» — запускает браузер.
  Открывается из SearchWindow или самостоятельно.
"""),
    ("Модули", "gui_broken_files.py", """\
Битые файлы (BrokenFilesWindow).

  Отображает файлы, которые pipeline не смог прочитать (ошибка парсинга,
  повреждённая кодировка, нулевой размер).
  Столбцы: путь к файлу | причина ошибки.
  Кнопка «Удалить» — удалить выбранные файлы.
"""),
    ("Модули", "gui_duplicate_finder.py", """\
Поиск дубликатов (DuplicateFinderWindow).

  Ищет дубликаты по хешу файла (SHA-256) и/или по совпадению
  (author, series, title).
  Позволяет выбрать, какие копии удалить.
"""),
    ("Модули", "genres_manager.py / gui_genres.py", """\
Менеджер жанров.

  genres_manager.py  — загрузка genres.xml FB2-стандарта, поиск жанра по коду.
  gui_genres.py      — окно с деревом жанров, назначение жанра папке/файлу.
  genre_assign.py    — фоновый поток назначения жанра через FB2 XML-патч.
"""),
    ("Модули", "name_normalizer.py", """\
Нормализатор имён авторов.

  Нормализует строку в формат «Фамилия Имя»:
    • Максимум 2 слова (игнорирует отчество)
    • Конвертация ё→е
    • Определение позиции имени по словарям male_names / female_names
    • Обработка аббревиатур «А.Фамилия»
    • Сортировка при 2 авторах
    • Специальный случай «К. Роберт Карgilл»:
        инициал + имя + фамилия → «Каргилл К. Роберт»
    • «Коллектив авторов» / «Collective Authors» → «Сборник»

  Если авторов ≥ 3:
    • ключевые слова (сборник, антология …) в имени файла / заголовке
      → "Сборник"
    • без ключевых слов → "Соавторство"
"""),
    ("Модули", "gender_lookup.py", """\
Онлайн-определение пола автора (класс GenderLookupService).

  Источник: Wikidata MediaWiki API (Genderize.io удалён).

  Алгоритм поиска (_wikidata_lookup):
    Стратегия 1 — wbsearchentities по полному имени автора (ru, до 5 кандидатов).
    Стратегия 2 — list=search по самому длинному слову (фамилия) + фильтр:
                  лейбл (ru|en) кандидата должен содержать ВСЕ слова автора.
                  Находит авторов с отчеством в Wikidata («Жозе Агуалуза» →
                  «Жозе Эдуардо Агуалуза»).
    Шаг 2 — wbgetentities: P31=Q5 (человек), P21 (пол), labels (ru|en).

  Throttle: ≥ 1.1 сек между запросами (_wd_lock + монотонные часы).
  Кеш: _cache["_wd_" + author.lower()] на всю сессию.

  LookupResult:
    gender_ru   — «Мужской» / «Женский» / None
    first_name  — первое слово ru-лейбла из Wikidata (имя, не фамилия)
    source      — "wikidata" | ""
    status      — found / unknown / error / pending

  lookup_authors_async(items, on_result, on_done) — запускает поток,
    не блокирует UI; on_done(False) вызывается по завершении.
"""),
    ("Модули", "author_processor.py / author_utils.py", """\
  author_processor.py  — ExtractionResult, приоритеты источников,
                         extract_author_from_filepath / extract_author_from_filename.
  author_utils.py      — утилиты: нормализация дефисов, очистка скобок,
                         fuzzy-проверка совпадения (SequenceMatcher, порог 70 %).
"""),
    ("Модули", "series_processor.py / series_summary.py", """\
  series_processor.py — извлечение и очистка серий из строк разных форматов.
  series_summary.py   — группировка записей по сериям, формирование отчёта
                        для CSV.
"""),
    ("Модули", "logger.py", """\
Логер (класс Logger).

  Хранит сообщения в deque(maxlen=10 000).
  Методы: log(message), get_messages().
  StdoutRedirector в gui_normalizer.py перехватывает sys.stdout
  и отправляет в Logger батчами каждые 100 мс через threading.Lock.
"""),
    ("Модули", "window_persistence.py / window_manager.py", """\
  window_persistence.py — сохранение и восстановление геометрии окон
                          (позиция + размер) через config.json.
                          Функции: setup_window_persistence(),
                                   save_window_geometry(),
                                   restore_window_geometry().

  window_manager.py     — реестр открытых окон, предотвращение дубликатов,
                          регистрация главного окна.
"""),
    ("Модули", "settings_manager.py / config.json", """\
  Конфигурационный файл config.json содержит:
    library_path, last_scan_path   — папки
    settings_file_path             — путь к файлу настроек (config.json)
    genres_file_path               — путь к файлу жанров (genres.xml)
    male_names, female_names       — словари имён (для нормализации)
    filename_blacklist             — стоп-слова
    service_words                  — служебные слова (Том, Часть, …)
    no_series_folder_names         — имена папок «без серии»
                                     (Вне серии, Без серии, Standalone, …)
    author_series_patterns_in_files   — паттерны для filename
    author_series_patterns_in_folders — паттерны для папок
    generate_csv                   — флаг сохранения regen.csv
    window_geometries              — сохранённые позиции окон
"""),

    # ── Pipeline ─────────────────────────────────────────────────────────
    ("Алгоритм pipeline", None, ""),
    ("Алгоритм pipeline", "Обзор", """\
Полная цепочка обработки (запускается кнопкой «Сканирование»):

  ┌──────────────────────────────────────────────────────┐
  │  1. Precache                                         │
  │     Анализ папок → словарь {папка → автор}           │
  │                                                       │
  │  2. Pass 1 — Read Files (параллельно, до 8 потоков)  │
  │     Читает каждый FB2 один раз, заполняет BookRecord: │
  │       metadata_authors, metadata_series, series_number│
  │       title, genre, proposed_author (из папки)        │
  │                                                       │
  │  3. Pass 2 — Filename                                 │
  │     Уточняет proposed_author из имени файла;          │
  │     если ≥ 3 авторов в мета → "Сборник"              │
  │                                                       │
  │  4. Pass 2 — Fallback                                 │
  │     Для файлов без автора — берёт из FB2 metadata     │
  │                                                       │
  │  5. Pass 2 — Series Filename                          │
  │     Определяет proposed_series из имени файла / папки │
  │                                                       │
  │  6. Pass 3 — Normalize                                │
  │     Нормализует proposed_author → «Фамилия Имя»      │
  │                                                       │
  │  7. Pass 3 — Series Normalize                         │
  │     Очищает proposed_series: trailing №, пробелы      │
  │                                                       │
  │  8. Pass 4 — Consensus                                │
  │     Голосование по папкам, выравнивание авторов       │
  │                                                       │
  │  9. Pass 5 — Conversions                              │
  │     Транслитерация, прочие финальные преобразования   │
  │                                                       │
  │ 10. Pass 6 — Abbreviations                            │
  │     А.Фамилия → Имя Фамилия (по словарям)            │
  └──────────────────────────────────────────────────────┘
  Результат — список BookRecord, которые отображаются
  в таблице нормализации и используются при синхронизации.
"""),
    ("Алгоритм pipeline", "Определение автора", """\
Приоритет источников автора (от высшего к низшему):

  1. folder_dataset            — автор получен из имени папки-предка
                                 (_propagate_ancestor_folder_authors):
                                 первая папка в пути, распознанная как
                                 «Фамилия Имя», отдаётся всем файлам
                                 в её поддереве (наивысший приоритет).

  2. folder_hierarchy          — автор установлен иерархией папок через
                                 folder_author_parser (Precache/Pass 1).

  3. metadata_folder_confirmed — автор из папки подтверждён метаданными
                                 нескольких файлов в той же папке.

  4. filename_meta_confirmed   — автор извлечён из имени файла, но инициалы
                                 раскрыты по FB2-метаданным:
                                   "Г.Диксон" → "Гордон Диксон"

  5. filename                  — извлечён из имени файла по паттернам
                                 (BlockLevelPatternMatcher).

  6. metadata                  — взят из FB2 <author> (менее надёжный,
                                 часто пустой или некорректный).

  7. collection                — файл имеет ≥ 3 авторов в метаданных:
                                   • ключевые слова в имени/заголовке
                                     → "Сборник"
                                   • без ключевых слов → "Соавторство"

  8. consensus                 — усреднение по папке (Pass 4).

  9. (пусто)                   — автор не найден.

  Источник хранится в BookRecord.author_source и в БД.
"""),
    ("Алгоритм pipeline", "Определение серии", """\
Алгоритм поиска серии (от высшего приоритета к низшему):

  1. folder_dataset / folder_hierarchy — серия из структуры папок
       (_unify_folder_series_source перекрывает metadata, filename,
       consensus для всех файлов в одной папке).

  2. filename — из имени файла по паттернам (Pass 2 Series Filename):
       "Автор - Серия 1. Название.fb2"
       "Автор. Серия. Название.fb2"

  3. metadata — из <sequence name="..."> в FB2 → series_number.

  4. consensus — большинство по папке (Pass 4).

  Иерархические серии:
    Если папка-автор → папка-серия → подпапки-подсерий →
    итоговая серия: «ОсновнаяСерия\\N. Подсерия»
    Пример: Отрок_Сотник\\1. Отрок, Отрок_Сотник\\2. Сотник

  Очистка рекламных folder_hierarchy папок (Pass 4):
    Папки вида «Fanzon. Фэнтези Стивена Браста» содержат имя автора
    в названии — это маркетинговое оформление, а не серия.
    Если proposed_series (source=folder_hierarchy) содержит слово,
    совпадающее по первым 4 символам с именем автора,
    серия заменяется на metadata_series (если есть) или сбрасывается.

  Вариантные подпапки (СИ, ЛП, альт., черновик и т.п.):
    Распознаются по ключевым словам из variant_folder_keywords
    (config.json). Вместо собственного имени наследуют серию
    родительской папки.

  Источник хранится в BookRecord.series_source.
  series_number — номер тома / части (integer string).
"""),

    # ── Настройки и конфигурация ─────────────────────────────────────────
    ("Настройки", None, ""),
    ("Настройки", "Основные параметры", """\
Все настройки хранятся в config.json в корне проекта.

  library_path        — целевая папка, куда перекладываются книги
                        после синхронизации
                        Пример: D:\\Книги\\Библиотека

  last_scan_path       — папка, которая сканируется по умолчанию
                        (обновляется автоматически)

  settings_file_path   — путь к файлу настроек config.json;
                        при изменении все последующие сохранения
                        пишутся в новый файл.
                        При первом запуске определяется автоматически.

  genres_file_path     — путь к файлу жанров genres.xml.
                        При первом запуске определяется автоматически.

  generate_csv         — true/false: сохранять regen.csv после генерации

  folder_parse_limit   — сколько уровней вверх просматривать
                        при поиске автора в папках (по умолчанию 3)
"""),
    ("Настройки", "Словари имён", """\
  male_names   — список мужских имён в нижнем регистре
                 Используется для определения порядка «Фамилия Имя»
                 и категории пола.

  female_names — список женских имён в нижнем регистре.

  Пополнить словари можно через:
    Нормализация → кнопка «Получить имена» → диалог NamesDialog
    (слово из proposed_author + выбор пола → кнопка «Пополнить списки»)
"""),
    ("Настройки", "Стоп-слова и паттерны", """\
  filename_blacklist   — слова, которые НЕ могут быть именем автора
                         (Том, Часть, Выпуск, Сборник, …)

  service_words        — служебные слова в паттернах серий
                         (Кн., Т., Ч., …)

  no_series_folder_names — имена папок, которые обозначают отсутствие серии.
                           Книга в такой папке гарантированно получает
                           пустую серию; filename-паттерны не применяются.
                           По умолчанию: «Вне серии», «Без серии»,
                           «Standalone», «Отдельные произведения» и др.
                           Редактируется через Настройки → вкладка «Списки».

  variant_folder_keywords — ключевые слова для распознавания «вариантных»
                           подпапок (СИ, ЛП, альт., черновик, вариант,
                           alt, draft и т.п.).
                           Такие папки наследуют серию родителя вместо
                           собственного имени.

  author_series_patterns_in_files
                       — список паттернов вида "Author - Title (Series)"
                         для разбора имён файлов

  author_series_patterns_in_folders
                       — аналогичные паттерны для имён папок
"""),
]


# ---------------------------------------------------------------------------
# Вспомогательные функции для форматирования
# ---------------------------------------------------------------------------

def _section_key(item):
    return item[0]

def _subsection_key(item):
    return item[1]


# ---------------------------------------------------------------------------
# Класс окна справки
# ---------------------------------------------------------------------------

class HelpWindow:
    """Структурированная справка программы."""

    # Цветовая схема для текстового виджета
    _TAGS = {
        'h1': dict(font=('Arial', 14, 'bold'), foreground='#1a237e', spacing3=4),
        'h2': dict(font=('Arial', 11, 'bold'), foreground='#283593', spacing1=6, spacing3=2),
        'code': dict(font=('Courier New', 9), background='#f0f0f0', foreground='#333'),
        'body': dict(font=('Arial', 10), foreground='#212121', spacing1=0),
        'sep': dict(font=('Arial', 6), foreground='#bdbdbd'),
    }

    def __init__(self, parent=None, settings_manager: SettingsManager = None):
        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title("Справка — EBook Library Organizer")
        self.window.minsize(800, 500)
        if parent:
            self.window.transient(parent)

        if settings_manager:
            setup_window_persistence(self.window, 'help', settings_manager,
                                     '1100x680+100+80')
        else:
            self.window.geometry('1100x680')

        self._build_ui()
        self._populate_tree()
        # Select first real item
        first = self._tree.get_children()
        if first:
            first_child = self._tree.get_children(first[0])
            if first_child:
                self._tree.selection_set(first_child[0])
                self._tree.focus(first_child[0])
                self._on_select(None)

    # ------------------------------------------------------------------
    def _build_ui(self):
        main = ttk.Frame(self.window)
        main.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        main.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)

        # ── Левая панель: дерево разделов ──
        left = ttk.Frame(main, width=200)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 4))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        left.grid_propagate(False)

        self._tree = ttk.Treeview(left, show='tree', selectmode='browse')
        vsb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        self._tree.bind('<<TreeviewSelect>>', self._on_select)

        # ── Разделитель ──
        ttk.Separator(main, orient='vertical').grid(
            row=0, column=1, sticky='ns', padx=2)

        # ── Правая панель: текст ──
        right = ttk.Frame(main)
        right.grid(row=0, column=2, sticky='nsew')
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self._text = ScrolledText(
            right, wrap='word', state='disabled',
            font=('Arial', 10), bg='#fafafa', bd=0,
            relief='flat', padx=14, pady=10
        )
        self._text.grid(row=0, column=0, sticky='nsew')

        # Настройка тегов оформления
        for tag, opts in self._TAGS.items():
            self._text.tag_configure(tag, **opts)

        # ── Строка поиска внизу ──
        search_frame = ttk.Frame(self.window)
        search_frame.pack(fill=tk.X, padx=6, pady=(0, 4))
        ttk.Label(search_frame, text="Поиск:").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        ttk.Entry(search_frame, textvariable=self._search_var,
                  width=40).pack(side=tk.LEFT, padx=4)
        ttk.Button(search_frame, text="Найти",
                   command=self._search_next).pack(side=tk.LEFT)
        ttk.Button(search_frame, text="✕", width=3,
                   command=lambda: (self._search_var.set(''),
                                    self._text.tag_remove('found', '1.0', tk.END))
                   ).pack(side=tk.LEFT)
        self._search_pos = '1.0'

    # ------------------------------------------------------------------
    def _populate_tree(self):
        """Заполнить дерево разделов из HELP_TREE."""
        from collections import OrderedDict
        sections = OrderedDict()
        for section, sub, text in HELP_TREE:
            if section not in sections:
                sections[section] = []
            if sub is not None:
                sections[section].append((sub, text))

        for section, children in sections.items():
            parent_id = self._tree.insert('', tk.END, text=f'  {section}',
                                          tags=('section',))
            for sub, text in children:
                self._tree.insert(parent_id, tk.END, text=f'  {sub}',
                                  values=(section, sub, text))

        self._tree.tag_configure('section',
                                 font=('Arial', 9, 'bold'), foreground='#1a237e')
        # Expand all sections
        for iid in self._tree.get_children():
            self._tree.item(iid, open=True)

    # ------------------------------------------------------------------
    def _on_select(self, _event):
        sel = self._tree.selection()
        if not sel:
            return
        vals = self._tree.item(sel[0], 'values')
        if not vals:
            return  # заголовок категории
        section, sub, text = vals[0], vals[1], vals[2]
        self._show_content(section, sub, text)

    def _show_content(self, section: str, sub: str, text: str):
        self._text.configure(state='normal')
        self._text.delete('1.0', tk.END)
        self._text.insert(tk.END, section + '\n', 'h1')
        self._text.insert(tk.END, sub + '\n', 'h2')
        self._text.insert(tk.END, '─' * 72 + '\n', 'sep')
        self._text.insert(tk.END, '\n')
        # Format text: lines starting with spaces or bullets → body;
        # lines starting with code markers → code
        for line in text.split('\n'):
            stripped = line.lstrip()
            if stripped.startswith(('•', '→', '1.', '2.', '3.', '4.', '5.',
                                    '6.', '7.', '8.', '9.', '10.')):
                self._text.insert(tk.END, line + '\n', 'body')
            elif stripped.startswith(('get_', '_', 'def ', 'class ')):
                self._text.insert(tk.END, line + '\n', 'code')
            else:
                self._text.insert(tk.END, line + '\n', 'body')
        self._text.configure(state='disabled')
        self._text.yview_moveto(0)
        self._search_pos = '1.0'

    # ------------------------------------------------------------------
    def _search_next(self):
        """Highlight next occurrence of search term in current text."""
        query = self._search_var.get().strip()
        if not query:
            return
        self._text.tag_remove('found', '1.0', tk.END)
        self._text.tag_configure('found', background='#ffeb3b', foreground='#000')

        pos = self._text.search(query, self._search_pos, nocase=True,
                                stopindex=tk.END)
        if not pos:
            # Wrap around
            pos = self._text.search(query, '1.0', nocase=True, stopindex=tk.END)
            if not pos:
                return

        end = f"{pos}+{len(query)}c"
        self._text.tag_add('found', pos, end)
        self._text.see(pos)
        self._search_pos = end
