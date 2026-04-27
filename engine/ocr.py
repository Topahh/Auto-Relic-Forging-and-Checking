# engine/ocr.py
# OCR engine wrapper around PaddleOCR.
# Detects GPU availability at startup and falls back to CPU automatically.
# Exposes a single recognize() method that returns extracted text lines
# from a numpy image array.


import numpy as np
from typing import List
from paddleocr import PaddleOCR
import paddle


# ==================== OCR engine ====================


class OCREngine:
    """
    Wrapper around PaddleOCR for in-game text recognition.

    Initializes the PaddleOCR engine at construction time.
    GPU acceleration is used automatically if CUDA is available;
    otherwise falls back to CPU mode.
    """

    def __init__(self):
        print("[INIT] Loading OCR engine...")

        try:
            import paddle
            has_gpu = (
                paddle.device.is_compiled_with_cuda()
                and paddle.device.cuda.device_count() > 0
            )

            if has_gpu:
                print("[OK]   GPU support detected — GPU acceleration enabled")
            else:
                print("[INFO] No GPU detected — running in CPU mode")
        except Exception as e:
            print(f"[WARN] Could not check GPU availability: {e}")

        self.engine = PaddleOCR(
            lang='en',                          # Recognition language: English
            use_textline_orientation=False      # Disable text line orientation detection
        )

        print("[OK] OCR engine ready\n")

    # ------------------------------------------------------------------
    # Recognition
    # ------------------------------------------------------------------

    def recognize(self, image: np.ndarray) -> List[str]:
        """
        Run OCR on a BGR numpy image and return a list of recognized text strings.

        Supports both the dict-based output format (PaddleOCR v3+, 'rec_texts' key)
        and the legacy list-based format. Returns an empty list on failure.
        """
        try:
            results = self.engine.predict(image)
            texts = []

            for result in results:
                if isinstance(result, dict) and 'rec_texts' in result:
                    # PaddleOCR v3+ output format
                    texts.extend(result['rec_texts'])
                elif isinstance(result, list):
                    # Legacy output format: [[bbox, [text, confidence]], ...]
                    for line in result:
                        try:
                            texts.append(line[1][0])
                        except Exception:
                            pass

            return texts
        except Exception as e:
            print(f"[WARN] OCR recognition error: {e}")
            return []
