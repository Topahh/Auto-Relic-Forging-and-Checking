# utils/stats.py
# Session statistics tracker.
# Records kept items, blacklist-vetoed items, partial matches and scan counters
# across forging rounds.
# Outputs a formatted report to stdout and optionally writes it to a log file.

from typing import List

from config.settings import Language
from utils.text import fuzzy_clean_text


class Statistics:
    """
    Tracks and reports item scanning statistics for a forging session.

    Counters:
    - rounds  : number of forging batches processed
    - scanned : total items scanned
    - kept    : total items accepted

    Lists:
    - kept_items                 : items that passed all match conditions
    - qualified_but_blacklisted  : items that matched primary keywords but were vetoed
    - partial_matches            : items where at least one primary keyword was found
                                   but the group was not fully validated
                                   (threshold not met, or B condition missing)
    """

    def __init__(self, lang: Language):
        self.lang    = lang
        self.rounds  = 0
        self.scanned = 0
        self.kept    = 0

        self.kept_items               = []
        self.qualified_but_blacklisted = []
        self.partial_matches          = []

    # ------------------------------------------------------------------
    # Data recording
    # ------------------------------------------------------------------

    def add_kept_item(self, texts: List[str], keywords: List[str], group_name: str):
        """Record an item that was fully accepted by the matcher."""
        self.kept_items.append((texts, keywords, group_name))

    def add_qualified_blacklisted(self,
                                  texts: List[str],
                                  matched_keywords: List[str],
                                  blacklist_keywords: List[str]):
        """Record an item that met primary + optional conditions but was
        vetoed by the blacklist."""
        self.qualified_but_blacklisted.append(
            (texts, matched_keywords, blacklist_keywords)
        )

    def add_partial_match(self,
                          texts: List[str],
                          matched_keywords: List[str],
                          reason: str,
                          group_name: str):
        """Record an item where at least one primary keyword was found but
        the group was not fully validated (threshold not met or B missing).

        These are the most useful items for tuning keyword groups and min values.
        """
        self.partial_matches.append((texts, matched_keywords, reason, group_name))

    # ------------------------------------------------------------------
    # Report rendering (shared logic)
    # ------------------------------------------------------------------

    def _build_report_lines(self) -> List[str]:
        """
        Build the report as a list of strings shared by print_report() and save_log().

        - Matched keywords highlighted with [[ ]]
        - Blacklisted keywords highlighted with (( ))
        - Partial match reason shown inline
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

        # ---- kept items ----
        if self.kept_items:
            lines.append(f"\n{lang.get('kept_items')}:")
            for idx, (texts, keywords, group_name) in enumerate(self.kept_items, 1):
                cleaned_texts = [fuzzy_clean_text(t) for t in texts]
                joined = "".join(cleaned_texts) if cleaned_texts else "(none)"
                for kw in keywords:
                    joined = joined.replace(kw, f"[[{kw}]]")
                lines.append(f"  {idx}. [{group_name}] {joined}")

        # ---- partial matches ----
        if self.partial_matches:
            lines.append(
                f"\n[PARTIAL MATCHES — {len(self.partial_matches)} item(s) "
                f"with at least one primary keyword found but group not validated]"
            )
            for idx, (texts, matched_kw, reason, group_name) in enumerate(self.partial_matches, 1):
                cleaned_texts = [fuzzy_clean_text(t) for t in texts]
                joined = "".join(cleaned_texts) if cleaned_texts else "(none)"
                for kw in matched_kw:
                    joined = joined.replace(kw, f"[[{kw}]]")
                # Truncate long OCR strings for readability
                preview = joined[:150] + ("..." if len(joined) > 150 else "")
                lines.append(f"  {idx}. [{group_name}] {reason}")
                lines.append(f"       {preview}")

        # ---- blacklisted items ----
        if self.qualified_but_blacklisted:
            lines.append(
                f"\n{lang.get('blacklist_items')}: "
                f"{len(self.qualified_but_blacklisted)}{lang.get('件')}"
            )
            for idx, (texts, matched_kw, blacklist_kw) in enumerate(
                self.qualified_but_blacklisted, 1
            ):
                cleaned_texts = [fuzzy_clean_text(t) for t in texts]
                joined = "".join(cleaned_texts) if cleaned_texts else "(none)"
                for kw in matched_kw:
                    joined = joined.replace(kw, f"[[{kw}]]")
                for kw in blacklist_kw:
                    joined = joined.replace(kw, f"(({kw}))")
                lines.append(f"  {idx}. {joined}")

        lines.append("=" * 40)
        return lines

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def print_report(self):
        """Print the session statistics report to stdout."""
        print("\n" + "\n".join(self._build_report_lines()))

    def save_log(self, filepath: str):
        """Write the session statistics report to a UTF-8 text file."""
        lang = self.lang
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("\n".join(self._build_report_lines()) + "\n")
            print(f"\n[OK] {lang.get('log_saved')}: {filepath}")
        except Exception as e:
            print(f"\n[ERROR] Failed to save log: {e}")