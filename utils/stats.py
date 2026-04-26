# utils/stats.py

from typing import List

from config.settings import Language
from utils.text import fuzzy_clean_text


class Statistics:
    """统计数据"""
    
    def __init__(self, lang: Language):
        self.lang = lang
        self.rounds = 0
        self.scanned = 0
        self.kept = 0
        self.kept_items = []
        self.qualified_but_blacklisted = []
    
    def add_kept_item(self, texts: List[str], keywords: List[str], group_name: str):
        """记录保留的道具"""
        self.kept_items.append((texts, keywords, group_name))
    
    def add_qualified_blacklisted(self, texts: List[str], matched_keywords: List[str], blacklist_keywords: List[str]):
        """记录被黑名单否决的道具"""
        self.qualified_but_blacklisted.append((texts, matched_keywords, blacklist_keywords))
    
    def print_report(self):
        """输出报表"""
        lang = self.lang
        print("\n" + "="*40)
        print(lang.get('stats_title'))
        print("="*40)
        print(f"{lang.get('total_rounds')}: {self.rounds}")
        print(f"{lang.get('total_scanned')}: {self.scanned}")
        print(f"{lang.get('total_kept')}: {self.kept}")
        if self.scanned > 0:
            rate = (self.kept / self.scanned) * 100
            print(f"{lang.get('keep_rate')}: {rate:.2f}%")
        
        if self.kept_items:
            print(f"\n{lang.get('kept_items')}:")
            for idx, (texts, keywords, group_name) in enumerate(self.kept_items, 1):
                cleaned_texts = [fuzzy_clean_text(t) for t in texts]
                joined_texts = "".join(cleaned_texts) if cleaned_texts else "(无)"
                for keyword in keywords:
                    joined_texts = joined_texts.replace(keyword, f"[[{keyword}]]")
                print(f"  {idx}. [{group_name}] {joined_texts}")
        
        if self.qualified_but_blacklisted:
            print(f"\n{lang.get('blacklist_items')}: {len(self.qualified_but_blacklisted)}{lang.get('件')}")
            for idx, (texts, matched_kw, blacklist_kw) in enumerate(self.qualified_but_blacklisted, 1):
                cleaned_texts = [fuzzy_clean_text(t) for t in texts]
                joined_texts = "".join(cleaned_texts) if cleaned_texts else "(无)"
                for keyword in matched_kw:
                    joined_texts = joined_texts.replace(keyword, f"[[{keyword}]]")
                for keyword in blacklist_kw:
                    joined_texts = joined_texts.replace(keyword, f"(({keyword}))")
                print(f"  {idx}. {joined_texts}")
        
        print("="*40)
    
    def save_log(self, filepath: str):
        """保存统计报表"""
        lang = self.lang
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("="*40 + "\n")
                f.write(f"{lang.get('stats_title')}\n")
                f.write("="*40 + "\n")
                f.write(f"{lang.get('total_rounds')}: {self.rounds}\n")
                f.write(f"{lang.get('total_scanned')}: {self.scanned}\n")
                f.write(f"{lang.get('total_kept')}: {self.kept}\n")
                if self.scanned > 0:
                    rate = (self.kept / self.scanned) * 100
                    f.write(f"{lang.get('keep_rate')}: {rate:.2f}%\n")
                
                if self.kept_items:
                    f.write(f"\n{lang.get('kept_items')}:\n")
                    for idx, (texts, keywords, group_name) in enumerate(self.kept_items, 1):
                        cleaned_texts = [fuzzy_clean_text(t) for t in texts]
                        joined_texts = "".join(cleaned_texts) if cleaned_texts else "(无)"
                        for keyword in keywords:
                            joined_texts = joined_texts.replace(keyword, f"[[{keyword}]]")
                        f.write(f"  {idx}. [{group_name}] {joined_texts}\n")
                
                if self.qualified_but_blacklisted:
                    f.write(f"\n{lang.get('blacklist_items')}: {len(self.qualified_but_blacklisted)}{lang.get('件')}\n")
                    for idx, (texts, matched_kw, blacklist_kw) in enumerate(self.qualified_but_blacklisted, 1):
                        cleaned_texts = [fuzzy_clean_text(t) for t in texts]
                        joined_texts = "".join(cleaned_texts) if cleaned_texts else "(无)"
                        for keyword in matched_kw:
                            joined_texts = joined_texts.replace(keyword, f"[[{keyword}]]")
                        for keyword in blacklist_kw:
                            joined_texts = joined_texts.replace(keyword, f"(({keyword}))")
                        f.write(f"  {idx}. {joined_texts}\n")
                
                f.write("="*40 + "\n")
            
            print(f"\n[日志] {lang.get('log_saved')}: {filepath}")
        except Exception as e:
            print(f"\n[错误] 保存日志失败: {e}")