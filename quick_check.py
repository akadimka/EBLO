import re
from pathlib import Path

fb2_file = Path(r'C:\Users\dmitriy.murov\Downloads\TriblerDownloads\Test1\Волков Тим\Пленники Зоны. Кровь цвета хаки.fb2')
print(f'Opening {fb2_file.name}...')

with open(fb2_file, 'rb') as f:
    content = f.read()
    print(f'Read {len(content)} bytes')

# Try to find title-info with character reading
if b'<title-info>' in content:
    print('Found title-info XML tag')
else:
    print('title-info tag not found')

# Check for sequence tags
if b'<sequence' in content:
    print('Found sequence tags')
    # Extract all sequence tags quickly
    matches = re.findall(rb'<sequence[^>]*name="([^"]+)"', content)
    for match in matches:
        try:
            print(f'  Series: {match.decode()}')
        except:
            print(f'  Series (decode error): {match}')
else:
    print('No sequence tags found')
