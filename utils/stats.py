# utils/stats.py
# Session statistics tracker.
# Records kept items, blacklist-vetoed items, partial matches and scan counters
# across forging rounds.
# Outputs a formatted report to stdout and optionally writes it to a log file.

from typing import List, Optional

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
    - kept_items
    - qualified_but_blacklisted
    - partial_matches

    These detailed lists can be periodically flushed to disk and cleared
    to keep memory usage bounded during very long sessions.
    """

    def __init__(self, lang: Language, max_in_memory_details: int = 300):
        self.lang = lang
        self.rounds = 0
        self.scanned = 0
        self.kept = 0

        self.kept_items = []
        self.qualified_but_blacklisted = []
        self.partial_matches = []

        self.max_in_memory_details = max_in_memory_details
        self.flush_count = 0

    # ------------------------------------------------------------------
    # Internal memory helpers
    # ------------------------------------------------------------------

    def _trim_list(self, items: list):
        """
        Keep only the newest max_in_memory_details entries.
        Prevents unbounded RAM growth during long runs.
        """
        overflow = len(items) - self.max_in_memory_details
        if overflow > 0:
            del items[:overflow]

    def _trim_all(self):
        self._trim_list(self.kept_items)
        self._trim_list(self.qualified_but_blacklisted)
        self._trim_list(self.partial_matches)

    def clear_detailed_lists(self):
        """
        Clear heavy OCR-derived detail lists while preserving counters.
        """
        self.kept_items.clear()
        self.qualified_but_blacklisted.clear()
        self.partial_matches.clear()

    # ------------------------------------------------------------------
    # Data recording
    # ------------------------------------------------------------------

    def add_kept_item(self, texts: List[str], keywords: List[str], group_name: str):
        """Record an item that was fully accepted by the matcher."""
        self.kept_items.append((texts, keywords, group_name))
        self._trim_list(self.kept_items)

    def add_qualified_blacklisted(
        self,
        texts: List[str],
        matched_keywords: List[str],
        blacklist_keywords: List[str]
    ):
        """Record an item that met primary + optional conditions but was vetoed by the blacklist."""
        self.qualified_but_blacklisted.append(
            (texts, matched_keywords, blacklist_keywords)
        )
        self._trim_list(self.qualified_but_blacklisted)

    def add_partial_match(
        self,
        texts: List[str],
        matched_keywords: List[str],
        reason: str,
        group_name: str
    ):
        """Record an item where at least one primary keyword was found but the group was not fully validated."""
        self.partial_matches.append((texts, matched_keywords, reason, group_name))
        self._trim_list(self.partial_matches)

    # ------------------------------------------------------------------
    # Report rendering (shared logic)
    # ------------------------------------------------------------------

    def _build_report_lines(
        self,
        include_details: bool = True,
        header_suffix: Optional[str] = None
    ) -> List[str]:
        """
        Build the report as a list of strings shared by print_report(), save_log()
        and append_log_snapshot().

        - Matched keywords highlighted with [[ ]]
        - Blacklisted keywords highlighted with (( ))
        - Partial match reason shown inline
        """
        lang = self.lang
        lines = []

        lines.append("=" * 40)
        title = lang.get('stats_title')
        if header_suffix:
            title = f"{title} - {header_suffix}"
        lines.append(title)
        lines.append("=" * 40)
        lines.append(f"{lang.get('total_rounds')}: {self.rounds}")
        lines.append(f"{lang.get('total_scanned')}: {self.scanned}")
        lines.append(f"{lang.get('total_kept')}: {self.kept}")

        if self.scanned > 0:
            rate = (self.kept / self.scanned) * 100
            lines.append(f"{lang.get('keep_rate')}: {rate:.2f}%")

        if not include_details:
            lines.append("=" * 40)
            return lines

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
        """Write the full current statistics report to a UTF-8 text file."""
        lang = self.lang
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("\n".join(self._build_report_lines()) + "\n")
            print(f"\n[OK] {lang.get('log_saved')}: {filepath}")
        except Exception as e:
            print(f"\n[ERROR] Failed to save log: {e}")

    def append_log_snapshot(
        self,
        filepath: str,
        header_suffix: Optional[str] = None,
        include_details: bool = True,
        clear_after_write: bool = False
    ):
        """
        Append a snapshot of current statistics to an existing log file.

        Useful for long-running sessions:
        - write incremental state to disk,
        - then optionally free RAM by clearing detailed OCR lists.
        """
        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write("\n".join(
                    self._build_report_lines(
                        include_details=include_details,
                        header_suffix=header_suffix
                    )
                ) + "\n\n")
            self.flush_count += 1
            print(f"[STATS] Snapshot appended to: {filepath}")

            if clear_after_write:
                self.clear_detailed_lists()
                print("[STATS] Detailed lists cleared from memory after flush")

        except Exception as e:
            print(f"\n[ERROR] Failed to append snapshot: {e}")