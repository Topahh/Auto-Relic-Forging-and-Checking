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


@dataclass
class FlowContext:
    processed_relics: int = 0
    batch_size: int = 10
    choose_10_done: bool = False
    confirm_done: bool = False
    transition_started: bool = False
    skip_sent: bool = False
    recovering: bool = False
    round_active: bool = False
    last_action: Optional[Action] = None
    last_state: UIState = UIState.UNKNOWN
    empty_ticks: int = 0

    def reset_round(self) -> None:
        self.processed_relics = 0
        self.choose_10_done = False
        self.confirm_done = False
        self.transition_started = False
        self.skip_sent = False
        self.recovering = False
        self.round_active = False
        self.last_action = None
        self.empty_ticks = 0


@dataclass
class TickDecision:
    state: UIState
    action: Action
    reason: str
    updates: Dict[str, Any] = field(default_factory=dict)

# endregion
# region State machine implementation

class ForgeBotStateMachine:
    """
    Pure decision layer:
    - detects the current UI state from OCR text
    - decides the next high-level action
    - does not press keys itself
    """

    def __init__(self, relic_tokens: list[str], flatstone_tokens: list[str], min_text_len: int, batch_size: int):
        self.relic_tokens = [t.lower() for t in relic_tokens]
        self.flatstone_tokens = [t.lower() for t in flatstone_tokens]
        self.min_text_len = min_text_len
        self.batch_size = batch_size

    def _count_hits(self, text: str, tokens: list[str]) -> int:
        if not text:
            return 0
        t = text.lower()
        return sum(1 for tok in tokens if tok in t)

    def detect_state(self, recognized_text: str, ctx: FlowContext) -> TickInput:
        text = (recognized_text or "").strip().lower()

        relic_hits = self._count_hits(text, self.relic_tokens)
        flatstone_hits = self._count_hits(text, self.flatstone_tokens)

        return TickInput(
            recognized_text=text,
            min_text_len=self.min_text_len,
            relic_token_hits=relic_hits,
            flatstone_token_hits=flatstone_hits,
        )

    def classify_state(self, tick: TickInput, ctx: FlowContext) -> UIState:
        text = tick.recognized_text

        if not text or len(text) < tick.min_text_len:
            if ctx.transition_started:
                return UIState.TRANSITION
            return UIState.MAIN_MENU

        if tick.relic_token_hits >= 1:
            return UIState.RELIC_MENU

        if tick.flatstone_token_hits >= 2:
            return UIState.FLATSTONE_MENU

        if ctx.transition_started:
            return UIState.TRANSITION

        return UIState.UNKNOWN

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

        # ---- RELIC MENU ----
        if state == UIState.RELIC_MENU:
            updates["transition_started"] = False
            updates["skip_sent"] = False
            updates["round_active"] = True

            if ctx.processed_relics >= ctx.batch_size:
                return TickDecision(
                    state=state,
                    action=Action.EXIT_RELIC_MENU,
                    reason="Batch completed, exit relic menu",
                    updates=updates,
                )

            return TickDecision(
                state=state,
                action=Action.PROCESS_CURRENT_RELIC,
                reason="Relic menu detected, process current relic",
                updates=updates,
            )

        # ---- FLATSTONE MENU ----
        if state == UIState.FLATSTONE_MENU:
            updates["round_active"] = True
            updates["transition_started"] = False

            if not ctx.choose_10_done:
                updates["choose_10_done"] = True
                return TickDecision(
                    state=state,
                    action=Action.CHOOSE_BATCH_SIZE,
                    reason="Flatstone menu detected, choose batch size once",
                    updates=updates,
                )

            if not ctx.confirm_done:
                updates["confirm_done"] = True
                updates["transition_started"] = True
                return TickDecision(
                    state=state,
                    action=Action.CONFIRM_FLATSTONE,
                    reason="Batch size chosen, confirm flatstone purchase",
                    updates=updates,
                )

            updates["transition_started"] = True
            return TickDecision(
                state=state,
                action=Action.SKIP_TO_RELIC_MENU,
                reason="Still in flatstone after confirm, send skip/confirm",
                updates=updates,
            )

        # ---- TRANSITION ----
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
                reason="Transition in progress, wait for relic menu",
                updates=updates,
            )

        # ---- MAIN MENU ----
        if state == UIState.MAIN_MENU:
            if ctx.round_active and ctx.processed_relics >= ctx.batch_size:
                return TickDecision(
                    state=state,
                    action=Action.RESET_ROUND,
                    reason="Returned to main menu after completed batch",
                    updates=updates,
                )

            if not ctx.round_active:
                updates["round_active"] = True
                return TickDecision(
                    state=state,
                    action=Action.ENTER_FLATSTONE,
                    reason="Main menu detected, start cycle by entering flatstone",
                    updates=updates,
                )

            return TickDecision(
                state=state,
                action=Action.WAIT,
                reason="Main menu detected during active round, wait or external recovery",
                updates=updates,
            )

        # ---- UNKNOWN ----
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