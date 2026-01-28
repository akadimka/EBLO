import csv

with open('regen.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print(f'Total: {len(rows)}\n')

print('Files with metadata source (should be folder_dataset):')
for i, row in enumerate(rows):
    if row['author_source'] == 'metadata':
        path = row['file_path'].replace('C:\\Users\\dmitriy.murov\\Downloads\\TriblerDownloads\\Test1\\', '')
        author = row['proposed_author']
        print(f"  {path}")
        print(f"    author: '{author}'")
        print()
