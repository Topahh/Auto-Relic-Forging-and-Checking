# engine/flow.py

# engine/flow.py

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import numpy as np

from engine.state_machine import Action, FlowContext


@dataclass
class FlowHooks:
    """
    Hooks implemented by ForgeBot and injected into ForgeFlow,
    so Flow stays modular and does not depend on the whole main class.
    """
    capture_text: Callable[[], Tuple[np.ndarray, list, str]]
    process_item: Callable[[int], Tuple[bool, str, np.ndarray]]
    ensure_relic_menu: Callable[[int, int], bool]


class ForgeFlow:
    """
    Execution layer:
    - executes actions decided by the state machine
    - updates flow context
    - delegates OCR/matching work to ForgeBot through hooks
    """

    def __init__(self, cfg, keyboard, hooks: FlowHooks):
        self.cfg = cfg
        self.keyboard = keyboard
        self.hooks = hooks

    def execute(self, action: Action, ctx: FlowContext) -> bool:
        """
        Execute one high-level action.
        Returns True when the action succeeded well enough to continue.
        Returns False when a blocking failure happened.
        """
        if action == Action.WAIT:
            time.sleep(self.cfg.POLL_INTERVAL)
            return True

        if action == Action.ENTER_FLATSTONE:
            print("[FLOW] MAIN_MENU -> press interact to enter flatstone")
            self.keyboard.press(self.cfg.KEY_INTERACT)
            return True

        if action == Action.CHOOSE_BATCH_SIZE:
            print(f"[FLOW] FLATSTONE_MENU -> choose batch size with {self.cfg.KEY_CHOSE_10_RELICS}")
            self.keyboard.press(self.cfg.KEY_CHOSE_10_RELICS)
            return True

        if action == Action.CONFIRM_FLATSTONE:
            print("[FLOW] FLATSTONE_MENU -> confirm purchase/opening")
            self.keyboard.press(self.cfg.KEY_INTERACT)
            return True

        if action == Action.SKIP_TO_RELIC_MENU:
            print("[FLOW] TRANSITION/FLATSTONE -> skip or advance with interact")
            self.keyboard.press(self.cfg.KEY_INTERACT)
            return True

        if action == Action.PROCESS_CURRENT_RELIC:
            next_index = ctx.processed_relics + 1
            print(f"[FLOW] RELIC_MENU -> process relic {next_index}/{ctx.batch_size}")

            ok, current_text, _ = self.hooks.process_item(next_index)
            if not ok:
                print(f"[FLOW] Failed to validate relic {next_index}")
                return False

            ctx.processed_relics += 1
            print(f"[FLOW] Relic processed -> total={ctx.processed_relics}/{ctx.batch_size}")
            return True

        if action == Action.EXIT_RELIC_MENU:
            print("[FLOW] RELIC_MENU -> batch complete, exit menu")
            self.keyboard.press(self.cfg.KEY_INTERACT)
            return True

        if action == Action.RECOVER_TO_RELIC_MENU:
            print("[FLOW] Unknown state during active round -> ensure relic menu")
            ok = self.hooks.ensure_relic_menu(ctx.processed_relics + 1, max_retries=3)
            return ok

        if action == Action.RESET_ROUND:
            print("[FLOW] Reset round context")
            ctx.reset_round()
            return True

        print(f"[FLOW] Unhandled action: {action}")
        return False