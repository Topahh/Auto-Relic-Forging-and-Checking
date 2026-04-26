# engine/capture.py

import os
import cv2
import datetime
import tempfile
import subprocess
import numpy as np


def _readline_with_timeout(pipe, timeout=45):
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
        raise TimeoutError("Timeout while waiting helper response")

    if result["error"] is not None:
        raise result["error"]

    return result["line"]

class ScreenCapture:
    def __init__(self, region=None):
        self.region = region
        self.helper = None
        self.helper_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wayland_capture_helper.py")
        self.debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_captures")
        os.makedirs(self.debug_dir, exist_ok=True)
        self._calibration = None

    def _ensure_helper(self):
        if self.helper is not None and self.helper.poll() is None:
            return
        if not os.path.exists(self.helper_path):
            raise RuntimeError(f"Helper introuvable: {self.helper_path}")
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
            raise RuntimeError(f"Échec init helper ScreenCast. Réponse: {line!r}. stderr: {stderr}")

    def capture_full(self) -> np.ndarray:
        self._ensure_helper()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            self.helper.stdin.write(f"CAPTURE {tmp_path}\n")
            self.helper.stdin.flush()
            reply = _readline_with_timeout(self.helper.stdout, timeout=20).strip()
            if not reply.startswith("OK "):
                raise RuntimeError(f"Capture helper échouée: {reply}")
            img = cv2.imread(tmp_path, cv2.IMREAD_COLOR)
            if img is None:
                raise RuntimeError(f"Impossible de lire le PNG produit: {tmp_path}")
            return img
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def set_calibration(self, left: int, top: int, width: int, height: int):
        self._calibration = (left, top, width, height)

    def capture(self) -> np.ndarray:
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
            raise RuntimeError(f"Calibration hors image: {self._calibration} pour image {w}x{h}")
        crop = img[y1:y2, x1:x2]
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        cv2.imwrite(os.path.join(self.debug_dir, f"full_{ts}.png"), img)
        cv2.imwrite(os.path.join(self.debug_dir, f"crop_{ts}.png"), crop)
        return crop

    def close(self):
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