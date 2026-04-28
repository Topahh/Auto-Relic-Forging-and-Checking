# engine/matcher.py
# Item matching module.
# Compares OCR-extracted text blocks against configured keyword groups,
# including required keywords, optional secondary keywords, and blacklists.
#
# v2 — richer diagnostics:
#   - _match_group() returns a MatchResult dataclass with full per-group detail
#   - match() returns has_partial=True as soon as ANY primary keyword is found,
#     even if the group threshold is not met (old has_a was True only when threshold met)
#   - per-group debug line printed to console: [MATCH] [R1] A:1/2 B:0/0 BL:0 -> reason
#   - best_partial tracking lets main.py/stats.py log items with partial hits

from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional

from config.settings import Config
from utils.text import fuzzy_clean_text, natural_sort_key


# ---------------------------------------------------------------------------
# MatchResult — result of evaluating one group against OCR text
# ---------------------------------------------------------------------------

@dataclass
class MatchResult:
    """Detailed result from evaluating a single keyword group."""
    group_name:  str
    a_matched:   List[str]   # primary keywords found
    a_min:       int         # minimum required
    b_matched:   List[str]   # optional keywords found
    b_required:  bool        # True if group has a non-empty b list
    blacklist_hit: List[str] # blacklist keywords found
    keep:        bool        # True only when all conditions are satisfied
    reason:      str         # human-readable explanation

    # ---- convenience properties ----------------------------------------

    @property
    def has_any_primary(self) -> bool:
        """True if at least one primary keyword was found (regardless of threshold)."""
        return len(self.a_matched) > 0

    @property
    def primary_threshold_met(self) -> bool:
        return len(self.a_matched) >= self.a_min

    @property
    def is_partial(self) -> bool:
        """Primary keywords found but the group was not fully validated."""
        return self.has_any_primary and not self.keep

    def debug_str(self) -> str:
        b_label = f"B:{len(self.b_matched)}/{'1+' if self.b_required else '0'}"
        return (
            f"[{self.group_name}] "
            f"A:{len(self.a_matched)}/{self.a_min} "
            f"{b_label} "
            f"BL:{len(self.blacklist_hit)} "
            f"-> {self.reason}"
        )


# ---------------------------------------------------------------------------
# ItemMatcher
# ---------------------------------------------------------------------------

class ItemMatcher:
    """
    Matches item text against configured keyword groups.

    Each group may contain:
    - a         : required primary keywords
    - b         : optional secondary keywords (at least one must match if defined)
    - min       : minimum number of primary keyword matches required
    - blacklist : forbidden keywords that veto an otherwise valid match

    match() return signature (backward-compatible 6-tuple):
        matched       : bool   — True if any group fully validates
        reason        : str    — human-readable result (includes best partial info on failure)
        matched_terms : list   — matched keywords (a + b)
        blacklist_hit : list   — blacklist keywords that fired
        has_partial   : bool   — True if at least 1 primary keyword found in ANY group
                                 (replaces old has_a which was True only when threshold met)
        group_name    : str    — matched group, or best partial group on failure
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _clean(text: str) -> str:
        return fuzzy_clean_text(text)

    def _match_group(self,
                     group_name: str,
                     group_config: Dict[str, Any],
                     merged_text: str) -> MatchResult:
        """Evaluate one keyword group against the pre-merged OCR text."""
        a_list    = group_config['a']
        b_list    = group_config['b']
        blacklist = group_config['blacklist']
        a_min     = group_config['min']

        # --- primary keywords ---
        a_matched = [kw for kw in a_list if kw in merged_text]

        if len(a_matched) < a_min:
            return MatchResult(
                group_name    = group_name,
                a_matched     = a_matched,
                a_min         = a_min,
                b_matched     = [],
                b_required    = bool(b_list),
                blacklist_hit = [],
                keep          = False,
                reason        = f"A {len(a_matched)}/{a_min} (need {a_min - len(a_matched)} more)"
            )

        # --- optional secondary keywords (b) ---
        b_matched = []
        if b_list:
            b_matched = [kw for kw in b_list if kw in merged_text]
            if not b_matched:
                return MatchResult(
                    group_name    = group_name,
                    a_matched     = a_matched,
                    a_min         = a_min,
                    b_matched     = [],
                    b_required    = True,
                    blacklist_hit = [],
                    keep          = False,
                    reason        = "B missing (0 optional keywords matched)"
                )

        # --- blacklist ---
        blacklist_hit = [kw for kw in blacklist if kw in merged_text]
        if blacklist_hit:
            return MatchResult(
                group_name    = group_name,
                a_matched     = a_matched,
                a_min         = a_min,
                b_matched     = b_matched,
                b_required    = bool(b_list),
                blacklist_hit = blacklist_hit,
                keep          = False,
                reason        = f"Blacklisted: {', '.join(blacklist_hit)}"
            )

        # --- all conditions met ---
        b_info = f" B:{len(b_matched)}" if b_list else ""
        return MatchResult(
            group_name    = group_name,
            a_matched     = a_matched,
            a_min         = a_min,
            b_matched     = b_matched,
            b_required    = bool(b_list),
            blacklist_hit = [],
            keep          = True,
            reason        = f"KEEP A:{len(a_matched)}/{a_min}{b_info}"
        )

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def match(self, texts: List[str]) -> Tuple[bool, str, List[str], List[str], bool, str]:
        """
        Match OCR text blocks against all configured keyword groups.

        Returns:
            (matched, reason, matched_terms, blacklist_hit, has_partial, group_name)
        """
        if not texts:
            return False, "No content", [], [], False, ""

        merged_text = "".join([self._clean(t) for t in texts])

        # Best partial result: group with the highest a_matched count (for diagnostics)
        best_partial: Optional[MatchResult] = None

        for group_name in sorted(self.cfg.KEYWORD_GROUPS.keys(), key=natural_sort_key):
            group_config = self.cfg.KEYWORD_GROUPS[group_name]
            result = self._match_group(group_name, group_config, merged_text)

            # Always print the per-group debug line
            print(f"   [MATCH] {result.debug_str()}")

            if result.keep:
                all_matched = result.a_matched + result.b_matched
                return (
                    True,
                    f"{group_name}: {', '.join(all_matched)}",
                    all_matched,
                    [],
                    True,
                    group_name,
                )

            # Track best partial for the final diagnostic return
            if result.has_any_primary:
                if (best_partial is None or
                        len(result.a_matched) > len(best_partial.a_matched)):
                    best_partial = result

        # ---- no group fully matched ----
        if best_partial:
            reason = f"No match — best partial: {best_partial.debug_str()}"
            return (
                False,
                reason,
                best_partial.a_matched,
                best_partial.blacklist_hit,
                True,          # has_partial: at least 1 primary keyword was found
                best_partial.group_name,
            )

        return False, "No match", [], [], False, ""
