# main.py
import os
import time
import datetime
import cv2
import numpy as np
from typing import Tuple, Optional

from config.settings import Config
from engine.ocr import OCREngine
from engine.keyboard import KeyboardController
from engine.capture import ScreenCapture
from engine.matcher import ItemMatcher
from engine.flow import ForgeFlow, FlowHooks
from engine.state_machine import ForgeBotStateMachine, FlowContext, TickInput, UIState
# from engine.locker import CurrencyLocker
from utils.text import fuzzy_clean_text, natural_sort_key
from utils.stats import Statistics
from utils.signal import StopSignal


# region ForgeBot
class ForgeBot:
    """Forge Bot — OCR synchronized, fully INI-configured."""

    def __init__(self):
        self.cfg = Config()
        self.ocr = OCREngine(self.cfg)
        self.keyboard = KeyboardController(self.cfg)
        self.matcher = ItemMatcher(self.cfg)
        self.capture = ScreenCapture(self.cfg.SCAN_REGION)
        self.debug_screenshot()
        self.stats = Statistics(self.cfg.lang)
        self.stop_signal = StopSignal(self.cfg.lang)
        self.stop_signal.clear()
        self.locker = None
        self.first_round = True
        self.flow_context = FlowContext(batch_size=self.cfg.BATCH_SIZE)
        self.state_machine = ForgeBotStateMachine(
            relic_tokens=self.cfg.RELIC_TOKENS,
            flatstone_tokens=self.cfg.FLATSTONE_TOKENS,
            main_menu_tokens=self.cfg.MAIN_MENU_TOKENS,
            reset_menu_tokens=self.cfg.RESET_MENU_TOKENS,
            min_text_len=self.cfg.MIN_TEXT_LEN,  # Seuil global state machine
            batch_size=self.cfg.BATCH_SIZE,
        )
        self.flow = ForgeFlow(
            cfg=self.cfg,
            keyboard=self.keyboard,
            hooks=FlowHooks(
                capture_text=self.capture_text,
                process_item=self.process_item,
                ensure_relic_menu=self.ensure_relic_menu,
            ),
        )

# endregion
# region 
    # ==================== SYNCHRONIZATION ====================

    def ensure_relic_menu(self, index: int, max_retries: int = 5) -> bool:
        for attempt in range(1, max_retries + 1):
            _, texts, recognized = self.capture_text()
            print(f" [{index:2d}] [ENSURE] attempt {attempt}/{max_retries} -> '{recognized}'")

            if self.is_relic_menu(recognized):
                return True

            if self.is_flatstone_menu(recognized):
                print(f" [{index:2d}] [ENSURE] flatstone -> enter relic menu")
                self.keyboard.press(self.cfg.KEY_INTERACT)
                time.sleep(self.cfg.WAIT_ANIM_EXTRA)
                continue

            if self.is_main_menu(recognized):
                print(f" [{index:2d}] [ENSURE] main menu -> open flatstone path")
                self.keyboard.press(self.cfg.KEY_INTERACT)
                time.sleep(self.cfg.WAIT_ANIM_EXTRA)
                continue

            if self.is_partial_relic_overlay(recognized):
                print(f" [{index:2d}] [ENSURE] partial overlay -> press F to dismiss")
                self.keyboard.press(self.cfg.KEY_INTERACT)
                time.sleep(max(self.cfg.WAIT_ANIM, self.cfg.POLL_INTERVAL))
                continue

            print(f" [{index:2d}] [ENSURE] unknown/empty UI -> press F to recover")
            self.keyboard.press(self.cfg.KEY_INTERACT)
            time.sleep(max(self.cfg.WAIT_ANIM, self.cfg.POLL_INTERVAL))

        return False
    
    def is_main_menu(self, text: str) -> bool:
        tick = self.state_machine.detect_state(text, self.flow_context)
        state = self.state_machine.classify_state(tick, self.flow_context)
        return state == UIState.MAIN_MENU

    def is_flatstone_menu(self, text: str) -> bool:
        tick = self.state_machine.detect_state(text, self.flow_context)
        state = self.state_machine.classify_state(tick, self.flow_context)
        return state == UIState.FLATSTONE_MENU
    
    def is_relic_menu(self, text: str) -> bool:
        tick = self.state_machine.detect_state(text, self.flow_context)
        state = self.state_machine.classify_state(tick, self.flow_context)
        return state == UIState.RELIC_MENU
    
    def is_reset_menu(self, text: str) -> bool:
        tick = self.state_machine.detect_state(text, self.flow_context)
        state = self.state_machine.classify_state(tick, self.flow_context)
        return state == UIState.RESET_MENU

    def is_partial_relic_overlay(self, text: str) -> bool:
        t = text.lower()
        return (
            "close" in t
            and "reset" in t
            and "addremovefavorites" not in t
            and "sellnow" not in t
        )

    def looks_like_action_menu(self, text: str) -> bool:
        t = (text or "").lower()
        
        # NOUVEAU : ignore si fin de batch
        if self.flow_context.processed_relics >= self.cfg.BATCH_SIZE - 2:
            return False
        
        # NOUVEAU : ignore si contient "reset" ET "favorites/sell"
        if "reset" in t and ("favorites" in t or "sellnow" in t):
            return False
        
        # Tes règles existantes...
        has_overlay_tokens = ("close" in t and "reset" in t)
        has_relic_tokens = any(tok in t for tok in self.cfg.RELIC_TOKENS)
        return has_overlay_tokens and not has_relic_tokens and len(t) < 40

    def capture_text(self) -> Tuple[np.ndarray, list, str]:
        image = self.capture.capture()
        texts = self.ocr.recognize(image)
        cleaned = [fuzzy_clean_text(t) for t in texts]
        recognized = "".join(cleaned)
        return image, texts, recognized

    def frame_has_changed(
        self,
        prev_frame: np.ndarray,
        new_frame: np.ndarray,
        threshold: float = None
    ) -> bool:
        """Visual validation: has the screen changed?"""
        if prev_frame is None or new_frame is None:
            return True
        threshold = threshold if threshold is not None else self.cfg.SYNC_THRESHOLD
        if len(prev_frame.shape) == 3:
            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            new_gray = cv2.cvtColor(new_frame, cv2.COLOR_BGR2GRAY)
        else:
            prev_gray, new_gray = prev_frame, new_frame
        diff = cv2.absdiff(prev_gray, new_gray)
        mean_diff = np.mean(diff)
        changed = mean_diff > threshold
        print(f"  [SYNC] frame_diff={mean_diff:.1f}>{threshold}={changed}")
        return changed

    def is_valid_ocr_text(
        self,
        text: str,
        prev_text: str = None,
        min_len: int = None,
        allow_unchanged: bool = False
    ) -> bool:
        """Textual validation: does the OCR text look valid enough to consider a real menu change?"""
        min_len = min_len if min_len is not None else self.cfg.MIN_TEXT_LEN
        if not text or len(text) < min_len:
            return False
        if not allow_unchanged and prev_text and text == prev_text:
            return False
        if len(set(text)) / len(text) < 0.3:
            return False
        return True
    
    def wait_for_next_item(
        self,
        prev_frame: np.ndarray,
        prev_text: str,
        allow_unchanged_text: bool = False
    ) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """Wait for the next valid item frame."""
        timeout = self.cfg.SYNC_TIMEOUT
        poll_interval = self.cfg.POLL_INTERVAL
        empty_reads_max = self.cfg.EMPTY_READS_MAX
        start_time = time.time()
        empty_reads = 0

        print(f"  [SYNC] Waiting next valid item (timeout={timeout}s)...")
        while time.time() - start_time < timeout:
            if self.stop_signal.should_stop():
                return None, None

            new_frame = self.capture.capture()
            new_texts = self.ocr.recognize(new_frame)
            new_text = "".join([fuzzy_clean_text(t) for t in new_texts])
            if not self.frame_has_changed(prev_frame, new_frame):
                if len(new_text) >= self.cfg.RELIC_MIN_LEN:
                    if allow_unchanged_text:
                        return new_frame, new_text
                    elif new_text != prev_text:
                        return new_frame, new_text
                time.sleep(poll_interval)
                continue

            print("  [SYNC] frame changed → OCR...")
            new_texts = self.ocr.recognize(new_frame)
            new_text = "".join([fuzzy_clean_text(t) for t in new_texts])

            if self.looks_like_action_menu(new_text):
                print(f"  [SYNC] Overlay/action popup detected: '{new_text}' -> skip")
                time.sleep(poll_interval)
                continue

            if (
                len(new_text) >= self.cfg.RELIC_MIN_LEN
                and new_text != prev_text    # Changement de texte
                and not self.looks_like_action_menu(new_text)  # Pas overlay
            ):
                print(f"  [SYNC] ✓ FALLBACK ✓ len={len(new_text)} != prev: '{new_text[:60]}...'")
                return new_frame, new_text

            if self.is_relic_menu(new_text) and self.is_valid_ocr_text(new_text, prev_text):
                print(f"  [SYNC] ✓ Next relic menu detected: '{new_text}'")
                return new_frame, new_text

            if self.is_main_menu(new_text):
                print(f"  [SYNC] main menu detected during sync: '{new_text}'")
                return new_frame, new_text

            if not self.is_valid_ocr_text(
                new_text,
                prev_text,
                self.cfg.RELIC_MIN_LEN,
                allow_unchanged=allow_unchanged_text
            ):
                print(f"  [SYNC] Invalid OCR: '{new_text}' (len={len(new_text)})")
                empty_reads += 1
                if empty_reads >= empty_reads_max:
                    print(f"  [SYNC] {empty_reads} empty reads → end of list")
                    return None, None
                continue

            print(f"  [SYNC] ✓ Valid item: '{new_text}'")
            return new_frame, new_text

        print("  [SYNC] timeout → end of list")
        return None, None

# endregion
# region processing items
    # ==================== PROCESS_ITEM ====================

    def process_item(self, index: int) -> Tuple[bool, str, np.ndarray]:
        """
        Ensure relic menu, OCR current relic, decide keep/discard,
        then wait for a real transition to the next relic before returning success.

        Returns:
            (success, recognized_text, image)
        """
        if not self.ensure_relic_menu(index):
            print(f" [{index:2d}] [ERROR] UI not recovered -> skip item")
            return False, "", None

        image, texts, recognized = self.capture_text()

        print(f" [{index:2d}] OCR: '{recognized}' (len={len(recognized)})")

        keep, info, matched_kw, blacklist_kw, has_partial, group_name = self.matcher.match(texts)
        self.stats.scanned += 1

        if keep:
            self.stats.kept += 1
            self.stats.add_kept_item(texts, matched_kw, group_name)
            print(f" [{index:2d}] ★ KEEP - {info} [KEY={self.cfg.KEY_KEEP}]")
            self.keyboard.keep_item()
        else:
            print(f" [{index:2d}] ✗ DISCARD - {info} [KEY={self.cfg.KEY_DISCARD}]")

            if has_partial and blacklist_kw:
                self.stats.add_qualified_blacklisted(texts, matched_kw, blacklist_kw)
            elif has_partial and not blacklist_kw:
                self.stats.add_partial_match(texts, matched_kw, info, group_name)

            self.keyboard.discard_item()

        # For the last relic of the batch, do not wait for a "next item"
        if index >= self.cfg.BATCH_SIZE:
            print(f" [{index:2d}] [SYNC] last relic in batch -> no next-item wait needed")
            return True, recognized, image

        print(f" [{index:2d}] [SYNC] waiting for next relic...")
        next_frame, next_text = self.wait_for_next_item(image, recognized, allow_unchanged_text=False)

        if next_frame is None or not next_text:
            print(f" [{index:2d}] [SYNC] next relic not observed -> action not validated")
            self.flow_context.max_failed_syncs += 1
            # if self.flow_context.max_failed_syncs >= 3 and index >= 8:
            if index >= self.cfg.BATCH_SIZE - 2:
                print(f"[END] {self.flow_context.max_failed_syncs} failed syncs → end of batch")
                self.flow_context.round_active = False
                self.flow_context.pending_new_round = True
                return True, recognized, image
            return False, recognized, image

        print(f" [{index:2d}] [SYNC] next relic detected: '{next_text}'")
        return True, recognized, image

# region flow and state machine
    # ==================== GAME ACTIONS ====================

    def run_round(self) -> bool:
        raise NotImplementedError("run_round is deprecated; use tick() and the state machine flow")

    # ==================== RUN ====================

    def start_currency_locker(self) -> bool:
        print("[STEP 1] Linux mode: Skipping currency lock\n")
        return True

    def show_config_keywords(self):
        print("\n" + "-" * 50)
        print("Keyword Groups")
        print("-" * 50)
        if not self.cfg.KEYWORD_GROUPS:
            print("No keyword groups")
        else:
            for group_name in sorted(self.cfg.KEYWORD_GROUPS.keys(), key=natural_sort_key):
                group_config = self.cfg.KEYWORD_GROUPS[group_name]
                print(f"\n【{group_name}】")
                if group_config["a"]:
                    print(f"  Required (≥{group_config['min']}): {chr(32).join(group_config['a'])}")
                if group_config["b"]:
                    print(f"  Optional : {chr(32).join(group_config['b'])}")
                if group_config["blacklist"]:
                    print(f"  Blacklist: {chr(32).join(group_config['blacklist'])}")
        print("=" * 50)

    def wait_user_ready(self) -> bool:
        print("\n[STEP 2] Prepare...")
        print("=" * 50)
        print("Steps:")
        print("  1. Enter shop")
        print("  2. Select relic batch (10)")
        print("  3. Press Enter")
        print("\nPress ESC to stop anytime")
        print("=" * 50)
        print("\nPress Enter to continue...")
        input()
        return True

    def tick(self) -> bool:
        _, _, recognized = self.capture_text()
        print(
            f"[OCR] len={len(recognized)} grace={self.flow_context.main_menu_grace_ticks} "
            f"transition={self.flow_context.transition_ticks} pending={self.flow_context.pending_new_round} "
            f"text='{recognized[:120]}'"
        )
        decision = self.state_machine.decide(recognized, self.flow_context)
        print(f"[STATE] state={decision.state} action={decision.action} reason={decision.reason}")
        self.state_machine.apply_updates(self.flow_context, decision)
        return self.flow.execute(decision.action, self.flow_context)

    def run(self):
        """Main loop."""
        print("=" * 50)
        print("Relic Auto-Forging — OCR SYNC")
        print("=" * 50)

        if not self.cfg.KEYWORD_GROUPS:
            print("[ERROR] No keywords configured")
            self.wait_for_exit()
            return

        if not self.start_currency_locker():
            print("[ERROR] Currency lock failed")
            self.wait_for_exit()
            return

        print("[INIT] Warmup input permissions...")
        self.keyboard.warmup_permissions()
        print("[INIT] Warmup done")

        self.show_config_keywords()
        if not self.wait_user_ready():
            self.wait_for_exit()
            return

        print("\nSwitch to game...")
        for i in range(5, 0, -1):
            print(f"{i}...")
            time.sleep(1)

        try:
            while not self.stop_signal.should_stop():
                if not self.tick():
                    print("[WARNING] Tick failed, retrying...")
                    time.sleep(1)
        except KeyboardInterrupt:
            print("\n[INTERRUPTED]")
        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.stop_signal.event.set()
            time.sleep(0.2)
            if self.locker:
                self.locker.stop()
            self.stats.print_report()
            try:
                self.capture.close()
            except Exception:
                pass
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            log_filename = f"hajiwo_log_{timestamp}.txt"
            script_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_captures")
            log_path = os.path.join(script_dir, log_filename)
            self.stats.save_log(log_path)

    def debug_screenshot(self):
        img = self.capture.capture()
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "debug_captures",
            f"debug_{datetime.datetime.now().strftime('%H%M%S')}.png",
        )
        cv2.imwrite(path, img)
        print(f"[DEBUG] Saved: {path}")
        h, w = img.shape[:2]
        print(f"[DEBUG] captured size = {w}x{h}")
        texts = self.ocr.recognize(img)
        print(f"[DEBUG] OCR: {texts}")

    def wait_for_exit(self):
        input("\nPress Enter to exit...")

# endregion
# region main

if __name__ == "__main__":
    bot = None
    try:
        bot = ForgeBot()
        bot.run()
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n" + "=" * 50)
        if bot and bot.cfg and bot.cfg.lang:
            print(bot.cfg.lang.get("program_done"))
        else:
            print("Program completed")
        print("=" * 50)
        input("Press Enter to exit...")


# endregion