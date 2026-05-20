# engine/capture.py
# Cross-platform screen capture for hajiwo.
#
# Backend selection happens ONCE at __init__ via method binding:
#   Linux Wayland  →  ScreenCast DBus helper (wayland_capture_helper.py)
#   Windows / X11  →  pyautogui.screenshot()
#
# After __init__, self.capture_full points directly to the right
# implementation — no per-call branching.

import os
import cv2
import time
import datetime
import subprocess
import tempfile
import numpy as np
from PIL import Image
from typing import Optional

from engine.platform_detect import is_wayland


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _readline_with_timeout(stream, timeout: float = 20.0) -> str:
    """Read one line from *stream* with a wall-clock timeout."""
    import select
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        raise RuntimeError(f"[ERROR] Helper did not respond within {timeout}s")
    return stream.readline()


class ScreenCapture:
    def __init__(self, region=None, debug_mode: bool = False):
        """
        Parameters
        ----------
        region      : kept for backward compatibility (unused internally —
                      use set_calibration() or set_region_xywh() instead).
        debug_mode  : when True, capture() saves full+crop PNGs to debug_dir.
                      Off by default — avoids disk I/O during normal OCR polling.
        """
        self.region     = region
        self.debug_mode = debug_mode
        self.debug_dir  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_captures")
        os.makedirs(self.debug_dir, exist_ok=True)
        self._calibration = None

        # Dispatch ONCE — no branching at call time
        if is_wayland():
            self._init_wayland()
        else:
            self._init_pyautogui()

        if region is not None:
            if len(region) == 4:
                self.set_calibration(*region)
            else:
                raise ValueError(f"[ERROR] Invalid region format: {region}")


    # ------------------------------------------------------------------
    # Backend initializers
    # ------------------------------------------------------------------

    def _init_wayland(self):
        """Set up the Wayland ScreenCast helper and bind capture_full."""
        self.helper      = None
        self.helper_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "wayland_capture_helper.py"
        )
        self._pipewire_fail_count     = 0
        self._pipewire_fail_threshold = 5
        # Bind
        self.capture_full = self._capture_full_wayland

    def _init_pyautogui(self):
        """Set up the pyautogui backend and bind capture_full."""
        try:
            import pyautogui  # verify at init time
        except ImportError:
            raise RuntimeError(
                "[ERROR] pyautogui is not installed. "
                "Install it with: pip install pyautogui"
            )
        # Bind
        self.capture_full = self._capture_full_pyautogui


    # ------------------------------------------------------------------
    # Wayland — helper process management
    # ------------------------------------------------------------------

    def _ensure_helper(self):
        """
        Spawn the Wayland capture helper process if it is not already running.
        Waits for the helper to emit 'READY' on stdout before returning.
        Raises RuntimeError if the helper is missing or fails to initialize.
        """
        if self.helper is not None and self.helper.poll() is None:
            return

        if not os.path.exists(self.helper_path):
            raise RuntimeError(f"[ERROR] Helper not found: {self.helper_path}")

        self.helper = subprocess.Popen(
            ["/usr/bin/python3", self.helper_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        line = _readline_with_timeout(self.helper.stdout, timeout=60).strip()
        if line != "READY":
            stderr = ""
            try:
                stderr = self.helper.stderr.read().strip()
            except Exception:
                pass
            raise RuntimeError(
                f"[ERROR] ScreenCast helper failed to initialize. "
                f"Response: {line!r}. stderr: {stderr}"
            )
        # Reset fail counter on successful (re)spawn
        self._pipewire_fail_count = 0

    def _force_restart_helper(self):
        """Forcefully terminate and respawn the helper process."""
        print("[CAPTURE] Forcing helper restart due to repeated PipeWire failures...")
        try:
            if self.helper is not None and self.helper.poll() is None:
                self.helper.terminate()
                self.helper.wait(timeout=3)
        except Exception:
            pass
        self.helper = None
        self._pipewire_fail_count = 0
        self._ensure_helper()


    # ------------------------------------------------------------------
    # Wayland — raw full-screen capture
    # ------------------------------------------------------------------

    def _capture_full_wayland(self, retries: int = 3, retry_delay: float = 0.15) -> Optional[np.ndarray]:
        """
        Request a full-screen capture from the ScreenCast helper and return it
        as a BGR numpy array, or None on transient PipeWire failure.

        Retries up to `retries` times on "ERR No sample" before giving up.
        Returns None instead of raising so callers can decide how to react.
        Fatal errors (helper crash, PNG unreadable) still raise RuntimeError.
        """
        for attempt in range(1, retries + 1):
            self._ensure_helper()

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                self.helper.stdin.write(f"CAPTURE {tmp_path}\n")
                self.helper.stdin.flush()

                reply = _readline_with_timeout(self.helper.stdout, timeout=20).strip()

                if reply.startswith("OK "):
                    img = cv2.imread(tmp_path, cv2.IMREAD_COLOR)
                    if img is None:
                        raise RuntimeError(
                            f"[ERROR] Could not read PNG produced by helper: {tmp_path}"
                        )
                    self._pipewire_fail_count = 0
                    return img

                # ---- Transient PipeWire error ----
                if "No sample received" in reply or reply.startswith("ERR"):
                    self._pipewire_fail_count += 1
                    print(
                        f"[CAPTURE] PipeWire transient error (attempt {attempt}/{retries},"
                        f" total_fails={self._pipewire_fail_count}): {reply}"
                    )

                    if self._pipewire_fail_count >= self._pipewire_fail_threshold:
                        try:
                            self._force_restart_helper()
                        except Exception as e:
                            print(f"[CAPTURE] Helper restart failed: {e}")
                            return None

                    if attempt < retries:
                        time.sleep(retry_delay)
                        continue

                    print(f"[CAPTURE] Max retries exhausted, returning None")
                    return None

                # ---- Unknown error format ----
                print(f"[CAPTURE] Unexpected helper reply: {reply!r}")
                return None

            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        return None


    # ------------------------------------------------------------------
    # Windows / X11 — raw full-screen capture
    # ------------------------------------------------------------------

    def _capture_full_pyautogui(self, retries: int = 3, retry_delay: float = 0.15) -> Optional[np.ndarray]:
        """Full-screen capture via pyautogui (Windows / X11)."""
        try:
            import pyautogui
            screenshot = pyautogui.screenshot()
            return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        except Exception as e:
            print(f"[CAPTURE] pyautogui capture failed: {e}")
            return None


    # ------------------------------------------------------------------
    # Public stub — replaced by method binding at __init__ time.
    # Defined here only so IDEs / type checkers see the signature.
    # ------------------------------------------------------------------

    def capture_full(self, retries: int = 3, retry_delay: float = 0.15) -> Optional[np.ndarray]:
        raise NotImplementedError("Backend not initialized")


    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def set_calibration(self, left: int, top: int, width: int, height: int):
        """Store the popup crop region as (left, top, width, height)."""
        self._calibration = (left, top, width, height)

    def set_region_xywh(self, x: int, y: int, w: int, h: int):
        """Alias of set_calibration() — preferred for readability."""
        self._calibration = (x, y, w, h)

    def clear_calibration(self):
        """Remove the crop region — grab() will return the full frame."""
        self._calibration = None


    # ------------------------------------------------------------------
    # Cropped numpy capture  (internal / legacy)
    # ------------------------------------------------------------------

    def capture(self) -> Optional[np.ndarray]:
        """
        Full-screen capture then optional crop.  Returns a BGR numpy array,
        or None if the capture failed transiently.

        Debug files (full_*.png / crop_*.png) are written to debug_dir ONLY
        when debug_mode=True.

        Raises RuntimeError only if the calibration rectangle is out of bounds.
        """
        img = self.capture_full()
        if img is None:
            return None

        if self._calibration is None:
            if self.debug_mode:
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                cv2.imwrite(os.path.join(self.debug_dir, f"full_{ts}.png"), img)
            return img

        left, top, width, height = self._calibration
        h, w = img.shape[:2]

        x1 = max(0, left)
        y1 = max(0, top)
        x2 = min(w, left + width)
        y2 = min(h, top + height)

        if x1 >= x2 or y1 >= y2:
            raise RuntimeError(
                f"[ERROR] Calibration region out of image bounds: "
                f"{self._calibration} for {w}x{h} image"
            )

        crop = img[y1:y2, x1:x2]

        if self.debug_mode:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            cv2.imwrite(os.path.join(self.debug_dir, f"full_{ts}.png"), img)
            cv2.imwrite(os.path.join(self.debug_dir, f"crop_{ts}.png"), crop)

        return crop


    # ------------------------------------------------------------------
    # PIL helpers  (used by OCREngine and the guard loop)
    # ------------------------------------------------------------------

    def grab(self) -> Optional[Image.Image]:
        """
        Main method for OCR consumption.

        Captures the full screen, crops to the calibrated popup region (if set),
        then converts BGR → RGB → PIL Image.
        Returns None on transient capture failure.
        """
        img_bgr = self.capture_full()
        if img_bgr is None:
            return None

        if self._calibration is not None:
            left, top, width, height = self._calibration
            h, w = img_bgr.shape[:2]
            x1 = max(0, left)
            y1 = max(0, top)
            x2 = min(w, left + width)
            y2 = min(h, top + height)
            if x1 < x2 and y1 < y2:
                img_bgr = img_bgr[y1:y2, x1:x2]

        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        return Image.fromarray(img_rgb)

    def grab_full(self) -> Optional[Image.Image]:
        """
        Full-screen capture without any cropping, returned as a PIL Image.
        Returns None on transient failure.

        Use this for calibration debug: save the result, open it in a viewer,
        find the popup coordinates, then call set_calibration().

            cap.grab_full().save("/tmp/hajiwo_fullscreen.png")
        """
        img_bgr = self.capture_full()
        if img_bgr is None:
            return None
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        return Image.fromarray(img_rgb)


    # ------------------------------------------------------------------
    # On-demand debug snapshot  (call explicitly, not automatically)
    # ------------------------------------------------------------------

    def save_debug_snapshot(self, label: str = "debug") -> Optional[str]:
        """
        Manually save a full+crop PNG pair to debug_dir.
        Returns the full image path, or None if capture failed.
        """
        img_bgr = self.capture_full()
        if img_bgr is None:
            print(f"[CAPTURE] save_debug_snapshot({label!r}): capture returned None, skipping")
            return None

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        full_path = os.path.join(self.debug_dir, f"full_{label}_{ts}.png")
        cv2.imwrite(full_path, img_bgr)

        if self._calibration is not None:
            left, top, width, height = self._calibration
            h, w = img_bgr.shape[:2]
            x1, y1 = max(0, left), max(0, top)
            x2, y2 = min(w, left + width), min(h, top + height)
            if x1 < x2 and y1 < y2:
                crop = img_bgr[y1:y2, x1:x2]
                crop_path = os.path.join(self.debug_dir, f"crop_{label}_{ts}.png")
                cv2.imwrite(crop_path, crop)

        return full_path


    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self):
        """
        Gracefully shut down the helper process (Wayland only).
        Sends a QUIT command and waits for acknowledgment before terminating.
        Silently ignores errors — the process is forcefully terminated if needed.
        No-op on Windows / X11 (no helper process).
        """
        if not hasattr(self, 'helper') or self.helper is None:
            return

        try:
            if self.helper.poll() is None:
                self.helper.stdin.write("QUIT\n")
                self.helper.stdin.flush()
                _readline_with_timeout(self.helper.stdout, timeout=5)
        except Exception:
            pass
        finally:
            try:
                if self.helper.poll() is None:
                    self.helper.terminate()
            except Exception:
                pass
            self.helper = None