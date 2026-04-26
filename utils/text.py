# utils/text.py

import re
import unicodedata

# ==================== 工具函数 ====================
def natural_sort_key(s: str):
    """自然排序key函数，使g1 < g2 < ... < g9 < g10"""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

# ==================== 文本清洗工具 ====================
def fuzzy_clean_text(text: str) -> str:
    """清洗文本：仅保留中文、英文、数字"""
    # Unicode规范化：统一全角/半角
    normalized = unicodedata.normalize('NFKC', text)
    
    # 删除所有符号：仅保留中文、英文、数字
    cleaned = re.sub(r'[^\u4e00-\u9fffa-zA-Z0-9]', '', normalized)
    
    # 统一小写
    return cleaned.lower()
