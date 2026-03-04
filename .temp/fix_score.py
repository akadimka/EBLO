import re

with open('passes/pass2_series_filename.py', 'r', encoding='utf-8') as f:
    content = f.read()

match = re.search(
    r'(        if not extracted_series:\n            return -1\n).*?(        return max\(0, score\)  # REPLACED_MARKER\n)',
    content,
    re.DOTALL
)

if not match:
    print("NOT FOUND")
    exit(1)

print(f"Found at {match.start()}-{match.end()}, length={match.end()-match.start()}")

new_body = r"""        if not extracted_series:
            return -1

        # ── HARD DISQUALIFIERS ──────────────────────────────────────────────────
        # Если паттерн требует структурный элемент, которого нет в имени файла,
        # этот паттерн не может подойти → сразу возвращаем -1.

        # Паттерн требует ' - ' (разделитель-тире), но в имени файла его нет
        if ' - ' in pattern and ' - ' not in filename:
            return -1

        # Паттерн требует запятую (соавторы), но в имени файла её нет
        if ',' in pattern and ',' not in filename:
            return -1

        # Паттерн требует скобки '(', но в имени файла их нет
        if '(' in pattern and '(' not in filename:
            return -1

        # ── POSITIVE SCORING ────────────────────────────────────────────────────
        # Начисляем очки за каждый структурный элемент, который паттерн
        # правильно предсказывает. Также начисляем очки, когда паттерн
        # правильно предсказывает ОТСУТСТВИЕ элемента (двунаправленное).

        score = 0
        max_score = 0

        # Тире ' - '
        max_score += 3
        if ' - ' in pattern:
            if ' - ' in filename:
                score += 3
        else:
            # Паттерн без тире — награждаем, если и в файле нет тире
            if ' - ' not in filename:
                score += 3

        # Запятая (соавторы)
        max_score += 2
        if ',' in pattern:
            if ',' in filename:
                score += 2
        else:
            if ',' not in filename:
                score += 2

        # Скобки '('
        max_score += 2
        if '(' in pattern:
            if '(' in filename:
                score += 2
        else:
            if '(' not in filename:
                score += 2

        # service_words в паттерне
        max_score += 1
        if 'service_words' in pattern:
            score += 1

        # Длина извлечённой серии: больше слов = надёжнее
        word_count = len(extracted_series.split())
        max_score += 6
        if word_count >= 2:
            score += min(6, word_count * 2)
        elif word_count == 0:
            return -1

        if max_score == 0:
            return 0

        return max(0, score)
"""

new_content = content[:match.start()] + new_body + content[match.end():]

with open('passes/pass2_series_filename.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Done! Replaced successfully.")
