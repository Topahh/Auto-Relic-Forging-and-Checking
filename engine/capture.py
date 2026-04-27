# engine/capture.py
# Screen capture module for Wayland environments.
# Spawns a persistent wayland_capture_helper.py subprocess and communicates
# with it over stdin/stdout to request full-screen PNG snapshots.
# Supports optional calibration cropping and saves debug images to disk.


import os
import cv2
import datetime
import tempfile
import subprocess
import numpy as np


# ------------------------------------------------------------------
# Helper I/O
# ------------------------------------------------------------------


def _readline_with_timeout(pipe, timeout=45):
    """
    Read one line from a pipe with a hard timeout.

    Runs the blocking readline() in a daemon thread.
    Raises TimeoutError if no response arrives within `timeout` seconds.
    """
    import threading

    result = {"line": None, "error": None}

    def _target():
        try:
            result["line"] = pipe.readline()
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout)

    if t.is_alive():
        raise TimeoutError("Timed out waiting for helper response")

    if result["error"] is not None:
        raise result["error"]

    return result["line"]


# ------------------------------------------------------------------
# Screen capture
# ------------------------------------------------------------------


class ScreenCapture:
    def __init__(self, region=None):
        self.region       = region
        self.helper       = None
        self.helper_path  = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "wayland_capture_helper.py"
        )
        self.debug_dir    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_captures")
        os.makedirs(self.debug_dir, exist_ok=True)
        self._calibration = None

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
    # Capture
    # ------------------------------------------------------------------

    def capture_full(self) -> np.ndarray:
        """
        Request a full-screen capture from the helper and return it as a BGR numpy array.

        The helper writes a PNG to a temporary file; this method reads it with OpenCV
        and deletes the temporary file before returning.
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
        """Store the crop region used by capture()."""
        self._calibration = (left, top, width, height)

    def capture(self) -> np.ndarray:
        """
        Return a cropped screen region based on the stored calibration.

        If no calibration is set, returns the full-screen image.
        Both the full frame and the cropped region are saved to debug_dir
        with a timestamp-based filename for inspection.

        Raises RuntimeError if the calibration rectangle falls outside the image.
        """
        img = self.capture_full()

        if self._calibration is None:
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

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        cv2.imwrite(os.path.join(self.debug_dir, f"full_{ts}.png"), img)
        cv2.imwrite(os.path.join(self.debug_dir, f"crop_{ts}.png"), crop)

        return crop

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
