# engine/state_machine.py

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any

# region Context and decision data structures
class UIState(str, Enum):
    MAIN_MENU = "MAIN_MENU"
    FLATSTONE_MENU = "FLATSTONE_MENU"
    RELIC_MENU = "RELIC_MENU"
    RESET_MENU = "RESET_MENU"
    TRANSITION = "TRANSITION"
    UNKNOWN = "UNKNOWN"


class Action(str, Enum):
    WAIT = "WAIT"
    ENTER_FLATSTONE = "ENTER_FLATSTONE"
    CHOOSE_BATCH_SIZE = "CHOOSE_BATCH_SIZE"
    CONFIRM_FLATSTONE = "CONFIRM_FLATSTONE"
    SKIP_TO_RELIC_MENU = "SKIP_TO_RELIC_MENU"
    PROCESS_CURRENT_RELIC = "PROCESS_CURRENT_RELIC"
    EXIT_RELIC_MENU = "EXIT_RELIC_MENU"
    RECOVER_TO_RELIC_MENU = "RECOVER_TO_RELIC_MENU"
    RESET_ROUND = "RESET_ROUND"


@dataclass
class TickInput:
    recognized_text: str
    min_text_len: int
    relic_token_hits: int = 0
    flatstone_token_hits: int = 0
    main_menu_token_hits: int = 0
    reset_token_hits: int = 0


@dataclass
class FlowContext:
    processed_relics: int = 0
    batch_size: int = 10
    max_failed_syncs: int = 0
    batch_select_requested: bool = False
    choose_10_done: bool = False
    confirm_done: bool = False
    batch_exit_sent: bool = False
    transition_started: bool = False
    skip_sent: bool = False
    recovering: bool = False
    round_active: bool = False
    pending_new_round: bool = False
    last_action: Optional[Action] = None
    last_state: Optional[UIState] = None
    empty_ticks: int = 0

    def reset_round(self) -> None:
        self.processed_relics = 0
        self.max_failed_syncs = 0
        self.batch_select_requested = False
        self.choose_10_done = False
        self.confirm_done = False
        self.batch_exit_sent = False
        self.transition_started = False
        self.skip_sent = False
        self.recovering = False
        self.round_active = False
        self.pending_new_round = False
        self.last_action = None
        self.empty_ticks = 0


@dataclass
class TickDecision:
    state: UIState
    action: Action
    reason: str
    updates: Dict[str, Any] = field(default_factory=dict)

# endregion
# region definition and helper methods of the state machine

class ForgeBotStateMachine:
    """
    Pure decision layer:
    - detects the current UI state from OCR text
    - decides the next high-level action
    - does not press keys itself
    """

    def __init__(
        self,
        relic_tokens: list[str],
        flatstone_tokens: list[str],
        main_menu_tokens: list[str],
        reset_menu_tokens: list[str],
        min_text_len: int,
        batch_size: int,
    ):
        self.relic_tokens = [t.lower() for t in relic_tokens]
        self.flatstone_tokens = [t.lower() for t in flatstone_tokens]
        self.main_menu_tokens = [t.lower() for t in main_menu_tokens]
        self.reset_menu_tokens = [t.lower() for t in reset_menu_tokens]
        self.min_text_len = min_text_len
        self.batch_size = batch_size


    def _menu_score(self, text: str, tokens: list[str]) -> int:
        if not text:
            return 0
        t = text.lower()
        return sum(1 for tok in tokens if tok and tok in t)

    def _is_relic_menu(self, tick: TickInput) -> bool:
        return tick.relic_token_hits >= 2

    def _is_flatstone_menu(self, tick: TickInput) -> bool:
        return tick.flatstone_token_hits >= 2

    def _is_main_menu(self, tick: TickInput) -> bool:
        return tick.main_menu_token_hits >= 2
    
    def _is_reset_menu(self, tick: TickInput) -> bool:
        return tick.reset_token_hits >= 1

    def is_relic_menu(self, text: str) -> bool:
        tick = self.detect_state(text, FlowContext())
        return self._is_relic_menu(tick)

    def is_flatstone_menu(self, text: str) -> bool:
        tick = self.detect_state(text, FlowContext())
        return self._is_flatstone_menu(tick)

    def is_main_menu(self, text: str) -> bool:
        tick = self.detect_state(text, FlowContext())
        return self._is_main_menu(tick)
    
    def is_reset_menu(self, text: str) -> bool:
        tick = self.detect_state(text, FlowContext())
        return self._is_reset_menu(tick)
    
    def is_batch_selected(self, text: str) -> bool:
        # "10/10" devient "1010" après fuzzy_clean_text
        # "1/10" devient "110"
        return "1010" in text

    def _count_hits(self, text: str, tokens: list[str]) -> int:
        if not text:
            return 0
        t = text.lower()
        return sum(1 for tok in tokens if tok in t)

#endregion
# region menu classification rules

    def detect_state(self, recognized_text: str, ctx: FlowContext) -> TickInput:
        text = (recognized_text or "").strip().lower()

        relic_hits = self._count_hits(text, self.relic_tokens)
        flatstone_hits = self._count_hits(text, self.flatstone_tokens)
        main_menu_hits = self._count_hits(text, self.main_menu_tokens)
        reset_menu_hits = self._count_hits(text, self.reset_menu_tokens)

        return TickInput(
            recognized_text=text,
            min_text_len=self.min_text_len,
            relic_token_hits=relic_hits,
            flatstone_token_hits=flatstone_hits,
            main_menu_token_hits=main_menu_hits,
            reset_token_hits=reset_menu_hits,
        )

    def classify_state(self, tick: TickInput, ctx: FlowContext) -> UIState:
        text = tick.recognized_text

        relic_hits = tick.relic_token_hits
        flatstone_hits = tick.flatstone_token_hits
        main_hits = tick.main_menu_token_hits

        if not text or len(text) < tick.min_text_len:
            if ctx.transition_started:
                return UIState.TRANSITION
            if tick.reset_token_hits >= 1:
                return UIState.RESET_MENU
            return UIState.UNKNOWN

        if relic_hits >= 2 and relic_hits > flatstone_hits and relic_hits > main_hits:
            return UIState.RELIC_MENU

        if flatstone_hits >= 2 and flatstone_hits > relic_hits and flatstone_hits > main_hits:
            return UIState.FLATSTONE_MENU

        if ctx.processed_relics >= ctx.batch_size:
            # Si batch complet, et on ne voit pas de reliques/flatstone, même un main_hits faible suffit
            if main_hits >= 1 and relic_hits < 2 and flatstone_hits < 2:
                return UIState.MAIN_MENU
            # Si aucun token relique/flatstone, et même pas de main, on favorise MAIN_MENU après sortie
            if relic_hits < 2 and flatstone_hits < 2:
                return UIState.MAIN_MENU
        else:
            # Avant fin de batch, on reste strict
            if main_hits >= 2 and relic_hits < 2 and flatstone_hits < 2:
                return UIState.MAIN_MENU

        if ctx.transition_started:
            return UIState.TRANSITION

        if tick.reset_token_hits >= 1:
            return UIState.RESET_MENU

        return UIState.UNKNOWN

# endregion
#region Decision logic

    def decide(self, recognized_text: str, ctx: FlowContext) -> TickDecision:
        tick = self.detect_state(recognized_text, ctx)
        state = self.classify_state(tick, ctx)

        updates: Dict[str, Any] = {
            "last_state": state,
        }

        # Track empty OCR while in transition/main-like states
        if not tick.recognized_text or len(tick.recognized_text) < tick.min_text_len:
            updates["empty_ticks"] = ctx.empty_ticks + 1
        else:
            updates["empty_ticks"] = 0

        # ==========================================================
        # PRIORITÉ 1 : batch terminé
        # ==========================================================
        # ==========================================================
        # PRIORITÉ 1 : batch terminé
        # ==========================================================
        if ctx.processed_relics >= ctx.batch_size:
            # Si on est revenu au menu principal, on peut reset le round
            if state == UIState.MAIN_MENU:
                updates["batch_exit_sent"] = False
                updates["pending_new_round"] = True
                updates["round_active"] = False
                updates["transition_started"] = False
                updates["skip_sent"] = False
                return TickDecision(
                    state=state,
                    action=Action.RESET_ROUND,
                    reason="Main menu reached after completed batch, reset before next round",
                    updates=updates,
                )

            # Si un menu reset/confirmation apparaît, on sort avec interact
            if state == UIState.RESET_MENU:
                return TickDecision(
                    state=state,
                    action=Action.EXIT_RELIC_MENU,
                    reason="Reset menu detected after batch complete, exit with interact",
                    updates=updates,
                )

            # If exit not yet sent, send it once
            if not ctx.batch_exit_sent:
                updates["batch_exit_sent"] = True
                updates["transition_started"] = True
                return TickDecision(
                    state=state,
                    action=Action.EXIT_RELIC_MENU,
                    reason="Batch complete, send exit only once",
                    updates=updates,
                )

            # Ici : on ajoute un timeout sur TRANSITION
            if state == UIState.TRANSITION:
                # Si longtemps en TRANSITION après batch, tenter de forcer MAIN_MENU
                if ctx.empty_ticks > 3:
                    updates["transition_started"] = False
                    return TickDecision(
                        state=UIState.TRANSITION,
                        action=Action.WAIT,
                        reason="Long TRANSITION after batch, waiting for OCR change",
                        updates=updates,
                    )
                # Après 6 ticks en TRANSITION, on force l’hypothèse MAIN_MENU même si OCR faible
                if ctx.empty_ticks > 6:
                    updates["transition_started"] = False
                    updates["empty_ticks"] = 0
                    # Retourne un état MAIN_MENU factice pour déclencher le reset
                    return TickDecision(
                        state=UIState.MAIN_MENU,
                        action=Action.RESET_ROUND,
                        reason="Forced main menu after long batch transition",
                        updates=updates,
                    )
            # Sinon on attend que l'UI revienne à un état stable
            return TickDecision(
                state=state,
                action=Action.WAIT,
                reason="Batch complete, waiting for main menu or reset menu",
                updates=updates,
            )

        # ==========================================================
        # RELIC MENU
        # ==========================================================
        if state == UIState.RELIC_MENU:
            updates["transition_started"] = False
            updates["skip_sent"] = False
            updates["round_active"] = True

            return TickDecision(
                state=state,
                action=Action.PROCESS_CURRENT_RELIC,
                reason="Relic menu detected, process current relic",
                updates=updates,
            )

        # ==========================================================
        # FLATSTONE MENU
        # ==========================================================
        if state == UIState.FLATSTONE_MENU:
            updates["round_active"] = True
            updates["transition_started"] = False

            text = tick.recognized_text or ""
            batch_10_visible = "1010" in text  # "10/10" après fuzzy_clean_text

            # 1) Envoyer F2 une seule fois
            if not ctx.batch_select_requested:
                updates["batch_select_requested"] = True
                return TickDecision(
                    state=state,
                    action=Action.CHOOSE_BATCH_SIZE,
                    reason="Flatstone menu detected, send F2 once to request batch 10",
                    updates=updates,
                )

            # 2) Attendre confirmation visuelle du 10/10
            if not ctx.choose_10_done:
                if batch_10_visible:
                    updates["choose_10_done"] = True
                    return TickDecision(
                        state=state,
                        action=Action.WAIT,
                        reason="Batch 10 visually confirmed (10/10 detected)",
                        updates=updates,
                    )

                return TickDecision(
                    state=state,
                    action=Action.WAIT,
                    reason="Waiting for visual confirmation of batch 10 after F2",
                    updates=updates,
                )

            # 3) Confirmer l'achat
            if not ctx.confirm_done:
                updates["confirm_done"] = True
                updates["transition_started"] = True
                return TickDecision(
                    state=state,
                    action=Action.CONFIRM_FLATSTONE,
                    reason="Batch 10 confirmed visually, confirm flatstone purchase",
                    updates=updates,
                )

            # 4) Si on est toujours là, avancer
            updates["transition_started"] = True
            return TickDecision(
                state=state,
                action=Action.SKIP_TO_RELIC_MENU,
                reason="Still in flatstone after confirm, send skip/confirm",
                updates=updates,
            )

        # ==========================================================
        # TRANSITION
        # ==========================================================
        if state == UIState.TRANSITION:
            updates["round_active"] = True

            if not ctx.skip_sent:
                updates["skip_sent"] = True
                return TickDecision(
                    state=state,
                    action=Action.SKIP_TO_RELIC_MENU,
                    reason="Transition detected, send one skip input",
                    updates=updates,
                )

            return TickDecision(
                state=state,
                action=Action.WAIT,
                reason="Transition in progress, wait for next stable menu",
                updates=updates,
            )

        # ==========================================================
        # RESET MENU
        # ==========================================================
        if state == UIState.RESET_MENU:
            return TickDecision(
                state=state,
                action=Action.EXIT_RELIC_MENU,
                reason="Reset menu detected, exit with interact",
                updates=updates,
            )

        # ==========================================================
        # MAIN MENU
        # ==========================================================
        if state == UIState.MAIN_MENU:
            updates["recovering"] = False
            updates["transition_started"] = False
            updates["skip_sent"] = False

            if ctx.pending_new_round:
                updates["pending_new_round"] = False
                updates["round_active"] = True
                return TickDecision(
                    state=state,
                    action=Action.ENTER_FLATSTONE,
                    reason="Confirmed main menu after reset, start next round",
                    updates=updates,
                )

            if not ctx.round_active:
                updates["round_active"] = True
                return TickDecision(
                    state=state,
                    action=Action.ENTER_FLATSTONE,
                    reason="Confirmed main menu, start first cycle",
                    updates=updates,
                )

            return TickDecision(
                state=state,
                action=Action.WAIT,
                reason="Confirmed main menu during active round, wait",
                updates=updates,
            )

        # ==========================================================
        # UNKNOWN
        # ==========================================================
        if ctx.round_active and ctx.processed_relics < ctx.batch_size:
            updates["recovering"] = True
            return TickDecision(
                state=state,
                action=Action.RECOVER_TO_RELIC_MENU,
                reason="Unknown state during active round, try recovering to relic menu",
                updates=updates,
            )

        return TickDecision(
            state=state,
            action=Action.WAIT,
            reason="Unknown idle state, wait",
            updates=updates,
        )

    @staticmethod
    def apply_updates(ctx: FlowContext, decision: TickDecision) -> None:
        for key, value in decision.updates.items():
            setattr(ctx, key, value)
        ctx.last_action = decision.action

# endregion