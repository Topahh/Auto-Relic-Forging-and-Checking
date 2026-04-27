# utils/stats.py
# Session statistics tracker.
# Records kept items, blacklist-vetoed items, and scan counters across forging rounds.
# Outputs a formatted report to stdout and optionally writes it to a log file.


from typing import List


from config.settings import Language
from utils.text import fuzzy_clean_text


class Statistics:
    """
    Tracks and reports item scanning statistics for a forging session.

    Counters:
    - rounds     : number of forging batches processed
    - scanned    : total items scanned
    - kept       : total items accepted

    Lists:
    - kept_items                 : items that passed all match conditions
    - qualified_but_blacklisted  : items that matched primary keywords but were vetoed by the blacklist
    """

    def __init__(self, lang: Language):
        self.lang                       = lang
        self.rounds                     = 0
        self.scanned                    = 0
        self.kept                       = 0
        self.kept_items                 = []
        self.qualified_but_blacklisted  = []

    # ------------------------------------------------------------------
    # Data recording
    # ------------------------------------------------------------------

    def add_kept_item(self, texts: List[str], keywords: List[str], group_name: str):
        """Record an item that was accepted by the matcher."""
        self.kept_items.append((texts, keywords, group_name))

    def add_qualified_blacklisted(self, texts: List[str], matched_keywords: List[str], blacklist_keywords: List[str]):
        """Record an item that matched primary keywords but was rejected by the blacklist."""
        self.qualified_but_blacklisted.append((texts, matched_keywords, blacklist_keywords))

    # ------------------------------------------------------------------
    # Report rendering (shared logic)
    # ------------------------------------------------------------------

    def _build_report_lines(self) -> List[str]:
        """
        Build the report as a list of strings shared by print_report() and save_log().

        Matched keywords are highlighted with [[ ]] and blacklisted keywords with (( )).
        Empty text blocks are shown as '(none)'.
        """
        lang  = self.lang
        lines = []

        lines.append("=" * 40)
        lines.append(lang.get('stats_title'))
        lines.append("=" * 40)
        lines.append(f"{lang.get('total_rounds')}: {self.rounds}")
        lines.append(f"{lang.get('total_scanned')}: {self.scanned}")
        lines.append(f"{lang.get('total_kept')}: {self.kept}")

        if self.scanned > 0:
            rate = (self.kept / self.scanned) * 100
            lines.append(f"{lang.get('keep_rate')}: {rate:.2f}%")

        if self.kept_items:
            lines.append(f"\n{lang.get('kept_items')}:")
            for idx, (texts, keywords, group_name) in enumerate(self.kept_items, 1):
                cleaned_texts = [fuzzy_clean_text(t) for t in texts]
                joined_texts  = "".join(cleaned_texts) if cleaned_texts else "(none)"
                for keyword in keywords:
                    joined_texts = joined_texts.replace(keyword, f"[[{keyword}]]")
                lines.append(f"  {idx}. [{group_name}] {joined_texts}")

        if self.qualified_but_blacklisted:
            lines.append(
                f"\n{lang.get('blacklist_items')}: "
                f"{len(self.qualified_but_blacklisted)}{lang.get('件')}"
            )
            for idx, (texts, matched_kw, blacklist_kw) in enumerate(self.qualified_but_blacklisted, 1):
                cleaned_texts = [fuzzy_clean_text(t) for t in texts]
                joined_texts  = "".join(cleaned_texts) if cleaned_texts else "(none)"
                for keyword in matched_kw:
                    joined_texts = joined_texts.replace(keyword, f"[[{keyword}]]")
                for keyword in blacklist_kw:
                    joined_texts = joined_texts.replace(keyword, f"(({keyword}))")
                lines.append(f"  {idx}. {joined_texts}")

        lines.append("=" * 40)
        return lines

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def print_report(self):
        """Print the session statistics report to stdout."""
        print("\n" + "\n".join(self._build_report_lines()))

    def save_log(self, filepath: str):
        """
        Write the session statistics report to a UTF-8 text file.

        Prints a confirmation message on success, or an error message on failure.
        """
        lang = self.lang
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("\n".join(self._build_report_lines()) + "\n")
            print(f"\n[OK] {lang.get('log_saved')}: {filepath}")
        except Exception as e:
            print(f"\n[ERROR] Failed to save log: {e}")