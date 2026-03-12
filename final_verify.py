import csv

with open('regen.csv', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# Check metadata vs filename extraction
print(f"Total: {len(rows)} records")
print(f"From filename: {sum(1 for r in rows if r.get('author_source') == 'filename')}")
print(f"From metadata: {sum(1 for r in rows if r.get('author_source') == 'metadata')}")

print("\n11 records still from METADATA:")
for i, r in enumerate([r for r in rows if r.get('author_source') == 'metadata']):
    print(f"  {i+1}. {r.get('proposed_author')} | {r.get('file_path')[:60]}...")

print("\nSample FILENAME extractions:")
for i, r in enumerate([r for r in rows if r.get('author_source') == 'filename'][:5]):
    print(f"  {r.get('proposed_author')} | {r.get('file_path')[:60]}...")
