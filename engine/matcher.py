# engine/matcher.py

from utils.text import fuzzy_clean_text, natural_sort_key

class ItemMatcher:
    """道具匹配器"""
    
    def __init__(self, cfg: Config):
        self.cfg = cfg
    
    def _fuzzy_clean(self, text: str) -> str:
        """模糊匹配：仅保留中文、英文、数字"""
        return fuzzy_clean_text(text)
    
    def match(self, texts: List[str]) -> Tuple[bool, str, List[str], List[str], bool, str]:
        """匹配道具"""
        if not texts:
            return False, "无内容", [], [], False, ""
        
        # 合并所有文本块为一个完整字符串
        merged_text = "".join([self._fuzzy_clean(text) for text in texts])
        
        for group_name in sorted(self.cfg.KEYWORD_GROUPS.keys(), key=natural_sort_key):
            group_config = self.cfg.KEYWORD_GROUPS[group_name]
            
            # 在合并后的文本中匹配关键词
            a_matched = [kw for kw in group_config['a'] if kw in merged_text]
            
            if len(a_matched) >= group_config['min']:
                has_a = True
                
                b_ok = True
                if group_config['b']:
                    b_ok = any(kw in merged_text for kw in group_config['b'])
                    if b_ok:
                        b_matched = [kw for kw in group_config['b'] if kw in merged_text]
                        a_matched.extend(b_matched)
                
                if b_ok:
                    blacklist_hit = [kw for kw in group_config['blacklist'] if kw in merged_text]
                    
                    if not blacklist_hit:
                        matched_str = ", ".join(a_matched)
                        return True, f"{group_name}: {matched_str}", a_matched, [], True, group_name
                    else:
                        return False, "黑名单否决", a_matched, blacklist_hit, True, group_name
        
        return False, "无匹配", [], [], False, ""