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
# from engine.locker import CurrencyLocker
from utils.text import fuzzy_clean_text, natural_sort_key
from utils.stats import Statistics
from utils.signal import StopSignal

# region ForgeBot
class ForgeBot:
    """Forge Bot — OCR synchronized, fully INI-configured."""

    def __init__(self):
        self.cfg      = Config()
        self.ocr      = OCREngine(self.cfg)          # OCR_LANG read from [OCR] in hajiwo.ini
        self.keyboard = KeyboardController(self.cfg)
        self.matcher  = ItemMatcher(self.cfg)
        self.capture  = ScreenCapture(self.cfg.SCAN_REGION)
        self.debug_save_capture_series("before_round")
        self.stats       = Statistics(self.cfg.lang)
        self.stop_signal = StopSignal(self.cfg.lang)
        self.stop_signal.clear()
        self.locker = None
        # All sync / timing parameters come from self.cfg (hajiwo.ini [Timing])
        # No hardcoded _sync_* attributes here.

    # ==================== SYNCHRONIZATION ====================

    def is_relic_menu(self, text: str) -> bool:
        """
        Returns true if the given text contains any of the 
        relic menu tokens configured in self.cfg.RELIC_TOKENS.
        """
        if not self.cfg.RELIC_TOKENS:
            return True
        t = text.lower()
        return any(tok in t for tok in self.cfg.RELIC_TOKENS)

    def frame_has_changed(self, prev_frame: np.ndarray, new_frame: np.ndarray,
                          threshold: float = None) -> bool:
        """Visual validation: has the screen changed?
        Threshold defaults to cfg.SYNC_THRESHOLD ([Timing] sync_threshold)."""
        if prev_frame is None or new_frame is None:
            return True
        threshold = threshold if threshold is not None else self.cfg.SYNC_THRESHOLD
        if len(prev_frame.shape) == 3:
            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            new_gray  = cv2.cvtColor(new_frame,  cv2.COLOR_BGR2GRAY)
        else:
            prev_gray, new_gray = prev_frame, new_frame
        diff      = cv2.absdiff(prev_gray, new_gray)
        mean_diff = np.mean(diff)
        changed   = mean_diff > threshold
        print(f"  [SYNC] frame_diff={mean_diff:.1f}>{threshold}={changed}")
        return changed

    def is_valid_ocr_text(self, text: str, prev_text: str = None, min_len: int = None) -> bool:
        """Textual validation.
        min_len defaults to cfg.MIN_TEXT_LEN ([Timing] min_text_len)."""
        min_len = min_len if min_len is not None else self.cfg.MIN_TEXT_LEN
        if not text or len(text) < min_len:
            return False
        if prev_text and text == prev_text:
            return False
        if len(set(text)) / len(text) < 0.3:
            return False
        return True

    def wait_for_next_item(self, prev_frame: np.ndarray, prev_text: str
                           ) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """Wait for the next valid item frame.
        All timeouts/intervals come from cfg ([Timing] section)."""
        timeout        = self.cfg.SYNC_TIMEOUT
        poll_interval  = self.cfg.POLL_INTERVAL
        empty_reads_max = self.cfg.EMPTY_READS_MAX
        start_time     = time.time()
        empty_reads    = 0

        print(f"  [SYNC] Waiting next valid item (timeout={timeout}s)...")
        while time.time() - start_time < timeout:
            if self.stop_signal.should_stop():
                return None, None

            new_frame = self.capture.capture()
            if not self.frame_has_changed(prev_frame, new_frame):
                time.sleep(poll_interval)
                continue

            print("  [SYNC] frame changed → OCR...")
            new_texts = self.ocr.recognize(new_frame)
            new_text  = "".join([fuzzy_clean_text(t) for t in new_texts])

            if self.looks_like_action_menu(new_text):
                print(f"  [SYNC] Action menu detected: '{new_text}' → skip")
                time.sleep(poll_interval)
                continue

            if not self.is_valid_ocr_text(new_text, prev_text):
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

    # ==================== PROCESS_ITEM ====================

    def process_item(self, index: int, image: np.ndarray = None) -> Tuple[bool, str, np.ndarray]:
        """Process one item: OCR → match → keep/discard.
        Accepts an already-validated frame or captures a new one."""
        if image is None:
            image = self.capture.capture()

        dummy_text = "".join([fuzzy_clean_text(t) for t in self.ocr.recognize(image)])
        if not self.is_relic_menu(dummy_text):
            print(f" [{index:2d}] [WRONG UI] Relic menu not detected")
            return False, "", image

        texts         = self.ocr.recognize(image)
        cleaned_texts = [fuzzy_clean_text(t) for t in texts]
        recognized    = "".join(cleaned_texts)
        print(f"  [{index:2d}] OCR: '{recognized}' (len={len(recognized)})")

        keep, info, matched_kw, blacklist_kw, has_a, group_name = self.matcher.match(texts)
        self.stats.scanned += 1

        if keep:
            self.stats.kept += 1
            self.stats.add_kept_item(texts, matched_kw, group_name)
            print(f"  [{index:2d}] ★ KEEP - {info}")
            self.keyboard.keep_item()
        else:
            print(f"  [{index:2d}] ✗ DISCARD - {info}")
            if has_a and blacklist_kw:
                self.stats.add_qualified_blacklisted(texts, matched_kw, blacklist_kw)
            self.keyboard.discard_item()

        return keep, recognized, image

    def debug_save_capture_series(self, prefix="series", count=5, delay=0.5):
        """Save several consecutive captures to verify helper output."""
        prev = None
        base_dir  = os.path.dirname(os.path.abspath(__file__))
        debug_dir = os.path.join(base_dir, "debug_captures")
        os.makedirs(debug_dir, exist_ok=True)

        print(f"[DEBUG] Saving {count} captures to: {debug_dir}")

        for i in range(count):
            img = self.capture.capture()
            ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = os.path.join(debug_dir, f"{prefix}_{i:02d}_{ts}.png")
            ok   = cv2.imwrite(path, img)
            print(f"[DEBUG] #{i} saved={ok} path={path}")

            if prev is not None:
                diff = np.mean(cv2.absdiff(prev, img))
                print(f"[DEBUG] #{i} diff_vs_prev={diff:.3f}")

            try:
                texts  = self.ocr.recognize(img)
                merged = "".join([fuzzy_clean_text(t) for t in texts])
                print(f"[DEBUG] #{i} OCR='{merged}' raw={texts}")
            except Exception as e:
                print(f"[DEBUG] #{i} OCR error: {e}")

            prev = img
            time.sleep(delay)

    # ==================== RUN_ROUND ====================

    def run_round(self) -> bool:
        """Execute one fixed forge round:
        F -> F2 -> F -> long wait -> process exactly BATCH_SIZE relics -> F
        """
        self.stats.rounds += 1
        print(f"\n🔥 [ROUND {self.stats.rounds}]")

        if self.stop_signal.should_stop():
            return False

        # 1) Open forge flow (F -> F2 -> F -> 4s wait)
        print("  [FLOW] Open forge cycle")
        self.keyboard.forge_cycle_start()

        # 2) Process exactly BATCH_SIZE relics
        processed_count = 0

        for item_idx in range(1, self.cfg.BATCH_SIZE + 1):
            if self.stop_signal.should_stop():
                return False

            print(f"\n  [FLOW] Processing relic {item_idx}/{self.cfg.BATCH_SIZE}")

            keep, current_text, _ = self.process_item(item_idx)

            if not self.is_valid_ocr_text(current_text):
                print(f"  [ERROR] Item {item_idx} OCR invalid -> stop round")
                break

            processed_count += 1

            if item_idx < self.cfg.BATCH_SIZE:
                time.sleep(self.cfg.KEY_INTERVAL)

        # 3) Close cycle
        print(f"\n  🎯 FINAL Batch: {processed_count}/{self.cfg.BATCH_SIZE} relics processed")

        if self.stop_signal.should_stop():
            return False

        print("  [FLOW] Close forge cycle")
        self.keyboard.forge_cycle_end()

        return processed_count == self.cfg.BATCH_SIZE

    # ==================== RUN ====================

    def start_currency_locker(self) -> bool:
        print("[STEP 1] Linux mode: Skipping currency lock\n")
        return True

    def show_config_keywords(self):
        print("\n" + "-"*50)
        print("Keyword Groups")
        print("-"*50)
        if not self.cfg.KEYWORD_GROUPS:
            print("No keyword groups")
        else:
            for group_name in sorted(self.cfg.KEYWORD_GROUPS.keys(), key=natural_sort_key):
                group_config = self.cfg.KEYWORD_GROUPS[group_name]
                print(f"\n【{group_name}】")
                if group_config['a']:
                    print(f"  Required (≥{group_config['min']}): {chr(32).join(group_config['a'])}")
                if group_config['b']:
                    print(f"  Optional : {chr(32).join(group_config['b'])}")
                if group_config['blacklist']:
                    print(f"  Blacklist: {chr(32).join(group_config['blacklist'])}")
        print("="*50)

    def wait_user_ready(self) -> bool:
        print("\n[STEP 2] Prepare...")
        print("="*50)
        print("Steps:")
        print("  1. Enter shop")
        print("  2. Select relic batch (10)")
        print("  3. Press Enter")
        print("\nPress ESC to stop anytime")
        print("="*50)
        print("\nPress Enter to continue...")
        input()
        return True

    def run(self):
        """Main loop."""
        print("="*50)
        print("Relic Auto-Forging — OCR SYNC")
        print("="*50)

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

        consecutive_fails = 0
        try:
            while not self.stop_signal.should_stop():
                if not self.run_round():
                    consecutive_fails += 1
                    print(f"[WARNING] Round failed ({consecutive_fails}/3)")
                    if consecutive_fails >= 3:
                        print("[STOP] Too many failed rounds")
                        break
                    time.sleep(1)
                else:
                    consecutive_fails = 0
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
            timestamp    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            log_filename = f"hajiwo_log_{timestamp}.txt"
            script_dir   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_captures")
            log_path     = os.path.join(script_dir, log_filename)
            self.stats.save_log(log_path)

    def debug_screenshot(self):
        img  = self.capture.capture()
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"debug_{datetime.datetime.now().strftime('%H%M%S')}.png"
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
        print("\n" + "="*50)
        if bot and bot.cfg and bot.cfg.lang:
            print(bot.cfg.lang.get('program_done'))
        else:
            print("Program completed")
        print("="*50)
        input("Press Enter to exit...")

# endregion