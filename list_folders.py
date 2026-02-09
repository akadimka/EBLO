import json
from pathlib import Path

cfg = json.load(open('config.json'))
work_dir = Path(cfg['last_scan_path'])
series_dir = work_dir / 'Серия - «Военная фантастика»'

print("Папки внутри 'Серия - «Военная фантастика»':")
for folder in sorted(series_dir.iterdir()):
    if folder.is_dir():
        print(f"  {repr(folder.name)}")
