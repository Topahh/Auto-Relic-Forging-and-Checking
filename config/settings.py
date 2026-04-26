# config.py

import os
import dataclasses
from configparser import ConfigParser
from typing import Tuple

from utils.text import fuzzy_clean_text, natural_sort_key

# ==================== 多语言支持 ====================
class Language:
    """多语言文本管理"""
    def __init__(self, config: ConfigParser, lang_code: str):
        self.lang_code = lang_code
        self.texts = {}
        
        # 加载指定语言的文本
        section = f'Language_{lang_code}'
        if config.has_section(section):
            for key, value in config.items(section):
                self.texts[key] = value
        else:
            print(f"[警告] 未找到语言配置 [{section}]，使用默认中文")
            self.lang_code = 'zh'
    
    def get(self, key: str, default: str = "") -> str:
        """获取文本"""
        return self.texts.get(key, default)


# ==================== 配置加载 ====================
def load_config_file():
    """加载hajiwo.ini配置文件"""
    config = ConfigParser()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'hajiwo.ini')
    
    if not os.path.exists(config_path):
        print("[错误] 未找到hajiwo.ini配置文件")
        print("请确保hajiwo.ini与脚本在同一目录")
        return None
    
    try:
        config.read(config_path, encoding='utf-8')
        return config
    except Exception as e:
        print(f"[错误] 读取配置文件失败: {e}")
        return None

config_file = load_config_file()

# ==================== 配置类 ====================
@dataclass
class Config:
    """脚本配置"""
    SCAN_REGION: Tuple[int, int, int, int] = (668, 608, 736, 243)
    KEYWORD_GROUPS: dict = None
    KEY_INTERACT: str = "f"
    KEY_DOWN: str = "down"
    KEY_RIGHT: str = "right"
    KEY_KEEP: str = "2"
    KEY_DISCARD: str = "3"
    KEY_INTERVAL: float = 0.10 # 按键间延时（每次按键后的通用等待时间）
    WAIT_ANIM: float = 0.20 # 界面操作延时（仅用于锻造开始和结束的界面转换）
    BATCH_SIZE: int = 10
    lang: Language = None
    
    def __post_init__(self):
        if config_file:
            # 加载语言配置
            lang_code = config_file.get('General', 'language', fallback='zh')
            self.lang = Language(config_file, lang_code)
            
            if config_file.has_section('ScreenRegion'):
                left = config_file.getint('ScreenRegion', 'left', fallback=1248)
                top = config_file.getint('ScreenRegion', 'top', fallback=1211)
                width = config_file.getint('ScreenRegion', 'width', fallback=1433)
                height = config_file.getint('ScreenRegion', 'height', fallback=451)
                self.SCAN_REGION = (left, top, width, height)
            
            if config_file.has_section('Keywords'):
                if self.KEYWORD_GROUPS is None:
                    groups = {}
                    items = config_file.items('Keywords')
                    
                    group_names = set()
                    for key, value in items:
                        if '_a' in key:
                            group_name = key.replace('_a', '')
                            group_names.add(group_name)
                    
                    for group_name in sorted(group_names, key=natural_sort_key):
                        a_key = f"{group_name}_a"
                        b_key = f"{group_name}_b"
                        min_key = f"{group_name}_min"
                        blacklist_key = f"{group_name}_blacklist"
                        
                        if config_file.has_option('Keywords', a_key):
                            a_str = config_file.get('Keywords', a_key, fallback='')
                            b_str = config_file.get('Keywords', b_key, fallback='')
                            min_val = config_file.getint('Keywords', min_key, fallback=1)
                            blacklist_str = config_file.get('Keywords', blacklist_key, fallback='')
                            
                            a_list = [fuzzy_clean_text(k.strip()) for k in a_str.split('||') if k.strip()]
                            b_list = [fuzzy_clean_text(k.strip()) for k in b_str.split('||') if k.strip()]
                            blacklist_list = [fuzzy_clean_text(k.strip()) for k in blacklist_str.split('||') if k.strip()]
                            
                            if a_list:
                                groups[group_name] = {
                                    'a': a_list,
                                    'b': b_list,
                                    'min': min_val,
                                    'blacklist': blacklist_list
                                }
                    
                    # 如果没有配置任何词组，给出警告
                    if not groups:
                        print("[警告] hajiwo.ini中未配置任何有效词组")
                        print("[提示] 请编辑hajiwo.ini，删除案例前的#符号以启用配置")
                        self.KEYWORD_GROUPS = {}
                    else:
                        self.KEYWORD_GROUPS = groups
        else:
            if self.KEYWORD_GROUPS is None:
                self.KEYWORD_GROUPS = {}