from block_level_pattern_matcher import BlockLevelPatternMatcher
from settings_manager import SettingsManager

settings = SettingsManager('config.json')
patterns = settings.get_author_series_patterns_in_files()
service_words = settings.get_service_words()

print(f"Service words: {service_words[:5]}")
print(f"Total patterns: {len(patterns)}")
print()

matcher = BlockLevelPatternMatcher(service_words=service_words)

filename = "Янковский Дмитрий - Охотник (Тетралогия)"
print(f"Testing: {filename}")
print("=" * 80)

# Test tokenization
blocks = matcher.tokenize_filename(filename)
print(f"Filename blocks: {len(blocks)}")
for b in blocks:
    print(f"  {b}")

# Test all patterns
print(f"\nScoring patterns...")
scores = []
for pattern_obj in patterns[:5]:  # First 5
    pattern = pattern_obj.get('pattern', '')
    score, matched_pattern, author, series = matcher.score_pattern_match(filename, pattern)
    scores.append((score, pattern, author, series))
    print(f"  Pattern: {pattern:45} → score={score:.2f}, author={author}, series={series}")

# Find best
best_score, best_pattern, best_author, best_series = matcher.find_best_pattern_match(filename, patterns)
print(f"\nBest match:")
print(f"  Score: {best_score:.2f}")
print(f"  Pattern: {best_pattern}")
print(f"  Author: {best_author}")
print(f"  Series: {best_series}")
