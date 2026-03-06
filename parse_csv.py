headers = 'file_path,metadata_authors,proposed_author,author_source,metadata_series,proposed_series,series_source,file_title'
line = 'Волков Тим\\Пленники Зоны. Кровь цвета хаки.fb2,Сергей Коротков; Тим Волков,Волков Тим,folder_dataset,Пленники Зоны,,,Кровь цвета хаки'

header_cols = headers.split(',')
data_cols = line.split(',')

print(f"Total columns: {len(header_cols)}\n")

for i in range(max(len(header_cols), len(data_cols))):
    h = header_cols[i] if i < len(header_cols) else "??"
    v = data_cols[i] if i < len(data_cols) else "[missing]"
    v_display = "[EMPTY]" if v == "" else v
    print(f"[{i+1:02d}] {h}: '{v_display}'")
