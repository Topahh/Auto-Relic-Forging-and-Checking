# utils/text.py
# Text utility functions for normalization and sorting.
# Used across the project wherever OCR output or keyword strings need to be cleaned
# before comparison, or group names need to be sorted in human-readable order.


import re
import unicodedata

# ==================== Sorting ====================

def natural_sort_key(s: str):
    """
    Sort key that orders strings containing numbers naturally.

    Ensures g1 < g2 < ... < g9 < g10 instead of the lexicographic g1 < g10 < g2.
    Splits the string on digit runs and converts each numeric segment to int.
    """
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

# ==================== Text cleaning ====================

def fuzzy_clean_text(text: str) -> str:
    """
    Normalize and strip a text string for fuzzy keyword matching.

    Steps:
    1. NFKC Unicode normalization — converts full-width / half-width variants
       to their canonical forms (e.g. '１' → '1', 'Ａ' → 'A').
    2. Strip all characters except CJK ideographs (U+4E00–U+9FFF),
       ASCII letters, and ASCII digits.
    3. Lowercase the result for case-insensitive matching.
    """
    # Step 1 — Normalize full-width / half-width variants
    normalized = unicodedata.normalize('NFKC', text)

    # Step 2 — Keep only CJK characters, ASCII letters, and digits
    cleaned = re.sub(r'[^\u4e00-\u9fffa-zA-Z0-9]', '', normalized)

    # Step 3 — Lowercase for case-insensitive matching
    return cleaned.lower()