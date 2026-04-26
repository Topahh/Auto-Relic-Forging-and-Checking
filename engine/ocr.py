# engine/ocr.py

import numpy as np
from typing import List
from paddleocr import PaddleOCR
import paddle

# ==================== OCR引擎 ====================
class OCREngine:
    """OCR识别引擎"""
    
    def __init__(self):
        print("[Initialization] Loading OCR engine...")
        
        try:
            import paddle
            has_gpu = paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0
            
            if has_gpu:
                print("  ✓ GPU support detected, will automatically use GPU acceleration")
            else:
                print("  X GPU not detected, using CPU mode")
        except Exception as e:
            print(f"  X Error occurred while checking GPU: {e}")
        
        self.engine = PaddleOCR(
            lang='en',                          # Language: English
            use_textline_orientation=False      # Disable text line orientation detection
        )
        
        print("[完成] OCR引擎就绪\n") # 
    
    def recognize(self, image: np.ndarray) -> List[str]:
        """识别图像中的文本"""
        try:
            results = self.engine.predict(image)
            texts = []
            
            for result in results:
                if isinstance(result, dict) and 'rec_texts' in result:
                    texts.extend(result['rec_texts'])
                elif isinstance(result, list):
                    for line in result:
                        try:
                            texts.append(line[1][0])
                        except:
                            pass
            
            return texts
        except Exception as e:
            print(f"[警告] OCR识别异常: {e}")
            return []
                    