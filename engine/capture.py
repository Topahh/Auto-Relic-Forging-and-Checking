import os
import cv2
import datetime
import subprocess
import tempfile
import numpy as np
from PIL import Image

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
        self.region       = region
        self.debug_mode   = debug_mode
        self.helper       = None
        self.helper_path  = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "wayland_capture_helper.py"
        )
        self.debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_captures")
        os.makedirs(self.debug_dir, exist_ok=True)
        self._calibration = None          # ← ICI, avant le if
        if region is not None:
            if len(region) == 4:
                self.set_calibration(*region)
            else:
                raise ValueError(f"[ERROR] Invalid region format: {region}")


    # ------------------------------------------------------------------
    # Helper process management
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


    # ------------------------------------------------------------------
    # Raw full-screen capture  (BGR numpy array — Wayland-safe)
    # ------------------------------------------------------------------

    def capture_full(self) -> np.ndarray:
        """
        Request a full-screen capture from the helper and return it as a
        BGR numpy array.  The region is NEVER passed to the helper — this
        is intentional: Wayland region captures are unreliable across
        compositors.  Cropping is always done in Python (see grab/capture).

        The helper writes a PNG to a temporary file; this method reads it
        with OpenCV and deletes the temporary file before returning.
        """
        self._ensure_helper()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            self.helper.stdin.write(f"CAPTURE {tmp_path}\n")
            self.helper.stdin.flush()

            reply = _readline_with_timeout(self.helper.stdout, timeout=20).strip()
            if not reply.startswith("OK "):
                raise RuntimeError(f"[ERROR] Capture helper failed: {reply}")

            img = cv2.imread(tmp_path, cv2.IMREAD_COLOR)
            if img is None:
                raise RuntimeError(f"[ERROR] Could not read PNG produced by helper: {tmp_path}")

            return img
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


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

    def capture(self) -> np.ndarray:
        """
        Full-screen capture then optional crop.  Returns a BGR numpy array.

        Debug files (full_*.png / crop_*.png) are written to debug_dir ONLY
        when debug_mode=True, so normal OCR polling never hits the disk.

        Raises RuntimeError if the calibration rectangle is out of bounds.
        """
        img = self.capture_full()

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

    def grab(self) -> Image.Image:
        """
        Main method for OCR consumption.

        Captures the full screen via Wayland, crops to the calibrated popup
        region (if set), then converts BGR → RGB → PIL Image.

        No files are written.  Safe to call in tight polling loops.
        """
        img_bgr = self.capture_full()

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

    def grab_full(self) -> Image.Image:
        """
        Full-screen capture without any cropping, returned as a PIL Image.

        Use this for calibration debug: save the result, open it in a viewer,
        find the popup coordinates, then call set_calibration().

            cap.grab_full().save("/tmp/hajiwo_fullscreen.png")
        """
        img_bgr = self.capture_full()
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        return Image.fromarray(img_rgb)


    # ------------------------------------------------------------------
    # On-demand debug snapshot  (call explicitly, not automatically)
    # ------------------------------------------------------------------

    def save_debug_snapshot(self, label: str = "debug"):
        """
        Manually save a full+crop PNG pair to debug_dir.

        Call this from run_round() or process_item() when you want a one-off
        snapshot without enabling debug_mode globally.

            self.capture.save_debug_snapshot("after_forge_start")
            self.capture.save_debug_snapshot(f"before_item_{item_idx}")
        """
        img_bgr = self.capture_full()
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
        Gracefully shut down the helper process.

        Sends a QUIT command and waits for acknowledgment before terminating.
        Silently ignores errors — the process is forcefully terminated if needed.
        """
        if self.helper is None:
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