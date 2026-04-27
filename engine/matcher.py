# engine/matcher.py
# Item matching module.
# Compares OCR-extracted text blocks against configured keyword groups,
# including required keywords, optional secondary keywords, and blacklists.


from typing import List, Tuple


from config.settings import Config
from utils.text import fuzzy_clean_text, natural_sort_key


class ItemMatcher:
    """
    Matches item text against configured keyword groups.

    Each group may contain:
    - a         : required primary keywords
    - b         : optional secondary keywords (at least one must match if defined)
    - min       : minimum number of primary keyword matches required
    - blacklist : forbidden keywords that veto an otherwise valid match
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _fuzzy_clean(self, text: str) -> str:
        """Normalize text for fuzzy matching by keeping only useful characters."""
        return fuzzy_clean_text(text)

    def match(self, texts: List[str]) -> Tuple[bool, str, List[str], List[str], bool, str]:
        """
        Match OCR text blocks against all configured keyword groups.

        Returns:
        - matched       : True if the item is accepted
        - reason        : Human-readable match result
        - matched_terms : List of matched keywords
        - blacklist_hit : List of matched blacklist keywords
        - has_primary   : True if the primary keyword condition was met
        - group_name    : Name of the matched group, or empty string if none
        """
        if not texts:
            return False, "No content", [], [], False, ""

        # Merge all OCR text blocks into one normalized string
        merged_text = "".join([self._fuzzy_clean(text) for text in texts])

        for group_name in sorted(self.cfg.KEYWORD_GROUPS.keys(), key=natural_sort_key):
            group_config = self.cfg.KEYWORD_GROUPS[group_name]

            # Match primary keywords inside the merged text
            a_matched = [kw for kw in group_config['a'] if kw in merged_text]

            if len(a_matched) >= group_config['min']:
                has_a = True

                b_ok = True
                if group_config['b']:
                    b_ok = any(kw in merged_text for kw in group_config['b'])
                    if b_ok:
                        b_matched = [kw for kw in group_config['b'] if kw in merged_text]
                        a_matched.extend(b_matched)

                if b_ok:
                    blacklist_hit = [kw for kw in group_config['blacklist'] if kw in merged_text]

                    if not blacklist_hit:
                        matched_str = ", ".join(a_matched)
                        return True, f"{group_name}: {matched_str}", a_matched, [], True, group_name
                    else:
                        return False, "Rejected by blacklist", a_matched, blacklist_hit, True, group_name

        return False, "No match", [], [], False, ""