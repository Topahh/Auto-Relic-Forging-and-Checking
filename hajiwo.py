"""
锻造自动化脚本
功能：钱币锁定 + OCR识别 + 自动锻造
依赖：pip install pymem paddleocr opencv-python pyautogui pydirectinput keyboard
PaddlePaddle安装：https://www.paddlepaddle.org.cn/install/quick
"""

# — Standard library —
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from turtle import delay
import unicodedata
from configparser import ConfigParser
from dataclasses import dataclass
import datetime
from threading import Thread, Event
from typing import List, Tuple, Optional

from pynput import keyboard # Ajoute cet import

# — Third-party —
import cv2
import numpy as np
from paddleocr import PaddleOCR
from PIL import Image

# ==================== 工具函数 ====================
def natural_sort_key(s: str):
    """自然排序key函数，使g1 < g2 < ... < g9 < g10"""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]


# ==================== 钱币锁定器 ====================
class CurrencyLocker:
    def __init__(self):
        self.pm = None
        self.base_address = None
        self.anhen_address = None
        self.wangzheng_address = None
        self.anhen_value = None
        self.wangzheng_value = None
        self.is_running = True
        
    def get_process(self):
        """获取游戏进程"""
        try:
            self.pm = pymem.Pymem("nightreign.exe")
            module = pymem.process.module_from_name(self.pm.process_handle, "nightreign.exe")
            self.base_address = module.lpBaseOfDll
            print(f"[成功] 已连接到进程，基址: 0x{self.base_address:X}")
            return True
        except Exception as e:
            print(f"[错误] 无法找到游戏进程: {e}")
            return False
    
    def read_pointer_chain(self, offsets):
        """读取偏移链最终地址"""
        try:
            base_ptr_address = self.base_address + 0x03C078D0
            address = self.pm.read_ulonglong(base_ptr_address)
            
            for offset in reversed(offsets[1:]):
                address = self.pm.read_ulonglong(address + offset)
            
            final_address = address + offsets[0]
            return final_address
        except Exception as e:
            print(f"[错误] 读取偏移链失败: {e}")
            return None
    
    def initialize_addresses(self):
        """初始化两种钱币的内存地址"""
        anhen_offsets = [0x530]
        self.anhen_address = self.read_pointer_chain(anhen_offsets)
        
        wangzheng_offsets = [0x4BC]
        self.wangzheng_address = self.read_pointer_chain(wangzheng_offsets)
        
        if self.anhen_address and self.wangzheng_address:
            print(f"[成功] 暗痕地址: 0x{self.anhen_address:X}")
            print(f"[成功] 王证地址: 0x{self.wangzheng_address:X}")
            return True
        else:
            print("[错误] 地址初始化失败")
            return False
    
    def read_and_set_values(self):
        """读取并设置锁定值"""
        try:
            self.anhen_value = self.pm.read_int(self.anhen_address)
            print(f"[读取] 暗痕当前值: {self.anhen_value}")
            
            current_wangzheng = self.pm.read_int(self.wangzheng_address)
            print(f"[读取] 王证当前值: {current_wangzheng}")
            
            if current_wangzheng < 100:
                self.wangzheng_value = 100
                self.pm.write_int(self.wangzheng_address, 100)
                print(f"[修改] 王证已修改为: 100")
            else:
                self.wangzheng_value = current_wangzheng
                print(f"[锁定] 王证锁定当前值: {current_wangzheng}")
            
            return True
        except Exception as e:
            print(f"[错误] 读取或设置数值失败: {e}")
            return False
    
    def lock_loop(self):
        """持续锁定循环"""
        print("[启动] 锁定线程已启动")
        while self.is_running:
            try:
                self.pm.write_int(self.anhen_address, self.anhen_value)
                self.pm.write_int(self.wangzheng_address, self.wangzheng_value)
                time.sleep(0.05)
            except Exception as e:
                print(f"[警告] 锁定写入异常: {e}")
                time.sleep(0.1)
    
    def start(self):
        """启动锁定器"""
        print("=" * 50)
        print("货币锁定 Currency Locking")
        print("=" * 50)
        
        if not self.get_process():
            return False
        
        if not self.initialize_addresses():
            return False
        
        if not self.read_and_set_values():
            return False
        
        lock_thread = threading.Thread(target=self.lock_loop, daemon=True)
        lock_thread.start()
        
        print("=" * 50)
        print("[成功] 已激活")
        print("=" * 50)
        return True
    
    def stop(self):
        """停止锁定器"""
        self.is_running = False
        print("[停止] 已停止")


# ==================== 文本清洗工具 ====================
def fuzzy_clean_text(text: str) -> str:
    """清洗文本：仅保留中文、英文、数字"""
    # Unicode规范化：统一全角/半角
    normalized = unicodedata.normalize('NFKC', text)
    
    # 删除所有符号：仅保留中文、英文、数字
    cleaned = re.sub(r'[^\u4e00-\u9fffa-zA-Z0-9]', '', normalized)
    
    # 统一小写
    return cleaned.lower()


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

# ==================== OCR引擎 ====================
class OCREngine:
    """OCR识别引擎"""
    
    def __init__(self):
        print("[初始化] 正在加载OCR引擎...")
        
        try:
            import paddle
            has_gpu = paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0
            
            if has_gpu:
                print("  ✓ 检测到GPU支持，将自动使用GPU加速")
            else:
                print("  ✓ 未检测到GPU，使用CPU模式")
        except Exception:
            print("  ✓ 使用默认设备")
        
        self.engine = PaddleOCR(
            lang='en',                          # 语言：中文
            use_textline_orientation=False      # 禁用文本行方向检测
        )
        
        print("[完成] OCR引擎就绪\n")
    
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


# Remplacer KeyboardController entièrement
class KeyboardController:
    _KEY_MAP = {
        'down': 'Down', 'up': 'Up', 'right': 'Right', 'left': 'Left',
        'enter': 'Return', 'return': 'Return', 'escape': 'Escape',
        'esc': 'Escape', 'space': 'space', 'tab': 'Tab', 'f': 'f',
        '2': '2', '3': '3',
    }

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._env = {**os.environ, 'DISPLAY': ':0'}
        self._window_id = None
        self._verify_and_find_window()

    def _verify_and_find_window(self):
        r = subprocess.run(['which', 'xdotool'], capture_output=True)
        if r.returncode != 0:
            print("[ERREUR] xdotool introuvable : sudo dnf install xdotool")
            return
        print("[OK] xdotool détecté")

        # Cherche la fenêtre du jeu
        r = subprocess.run(
            ['xdotool', 'search', '--name', 'ELDEN RING NIGHTREIGN'],
            capture_output=True, text=True, env=self._env
        )
        if r.returncode == 0 and r.stdout.strip():
            self._window_id = r.stdout.strip().split('\n')[0]
            print(f"[OK] Fenêtre jeu trouvée : ID {self._window_id}")
        else:
            print("[WARN] Fenêtre jeu non trouvée — les inputs peuvent échouer")

    def warmup_permissions(self):
        """Déclenche tôt la première interaction clavier/focus."""
        self._focus_game()
        time.sleep(0.2)

        # touche inoffensive pour déclencher l'autorisation / initialisation
        subprocess.run(
            ['xdotool', 'key', '--clearmodifiers', 'Shift_L'],
            env=self._env, capture_output=True
        )
        time.sleep(0.2)

    def _focus_game(self):
        """Focus la fenêtre du jeu avant d'envoyer des inputs"""
        if self._window_id:
            subprocess.run(
                ['xdotool', 'windowfocus', '--sync', self._window_id],
                capture_output=True, env=self._env
            )
            time.sleep(0.05)

    def press(self, key: str, delay: float = None):
        xkey = self._KEY_MAP.get(key.lower(), key)
        subprocess.run(
            ['xdotool', 'key', '--clearmodifiers', xkey],
            env=self._env, capture_output=True
        )
        time.sleep(delay or self.cfg.KEY_INTERVAL)

    def keep_item(self):
        self.press(self.cfg.KEY_KEEP)
        self.press(self.cfg.KEY_RIGHT)

    def discard_item(self):
        self.press(self.cfg.KEY_DISCARD)

    def forge_start(self):
        self._focus_game()           # ← focus AVANT les inputs
        self.press(self.cfg.KEY_INTERACT)
        self.press(self.cfg.KEY_DOWN)
        self.press(self.cfg.KEY_INTERACT)
        time.sleep(0.5)              # ← augmenté de 0.2 à 0.5
        self.press(self.cfg.KEY_INTERACT)
        time.sleep(self.cfg.WAIT_ANIM)

    def forge_end(self):
        self._focus_game()
        self.press(self.cfg.KEY_INTERACT)
        time.sleep(self.cfg.WAIT_ANIM)

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

class StopSignal:
    def __init__(self, lang: Language):
        self.lang = lang
        self.event = Event()
        self.stop_file = "/tmp/hajiwo_stop"

    def should_stop(self) -> bool:
        if self.event.is_set():
            return True
        if os.path.exists(self.stop_file):
            self.event.set()
            return True
        return False

    def clear(self):
        self.event.clear()
        try:
            if os.path.exists(self.stop_file):
                os.unlink(self.stop_file)
        except Exception:
            pass

# ===================== 主逻辑 ==================

class ForgeBot:
    """Forge Bot - OCR SYNCHRONIZED VERSION (FIXED)"""
    
    def __init__(self):
        self.cfg = Config()
        self.ocr = OCREngine()
        self.keyboard = KeyboardController(self.cfg)
        self.matcher = ItemMatcher(self.cfg)
        self.capture = ScreenCapture(self.cfg.SCAN_REGION)
        self.debug_save_capture_series("before_round")
        self.stats = Statistics(self.cfg.lang)
        self.stop_signal = StopSignal(self.cfg.lang)
        self.stop_signal.clear()    
        self.locker = None
        
        # FIXED Sync state - seuil adapté à tes logs (2.0-2.5)
        self._sync_threshold = 2.5        # ← CORRIGÉ (était 15.0)
        self._min_text_len = 2            # ← BAISSÉ (pour 'ie', 're')
        self._sync_timeout = 3.0
        self._poll_interval = 0.1
        self._empty_reads_max = 3
    
    # ==================== SYNCHRONIZATION (FIXED) ====================
    def looks_like_action_menu(self, text: str) -> bool:
        """Détecte les menus 'favorites/sell' au lieu de reliques"""
        bad_tokens = ["add", "remove", "favorites", "sellnow", "3sell"]
        return sum(1 for tok in bad_tokens if tok in text.lower()) >= 1
    
    def frame_has_changed(self, prev_frame: np.ndarray, new_frame: np.ndarray, 
                         threshold: float = None) -> bool:
        """VISUAL validation: has screen changed? (seuil 2.5)"""
        if prev_frame is None or new_frame is None:
            return True
        threshold = threshold or self._sync_threshold
        if len(prev_frame.shape) == 3:
            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            new_gray = cv2.cvtColor(new_frame, cv2.COLOR_BGR2GRAY)
        else:
            prev_gray, new_gray = prev_frame, new_frame
        diff = cv2.absdiff(prev_gray, new_gray)
        mean_diff = np.mean(diff)
        changed = mean_diff > threshold
        print(f"  [SYNC] frame_diff={mean_diff:.1f}>{threshold}={changed}")
        return changed
    
    def is_valid_ocr_text(self, text: str, prev_text: str = None, min_len: int = None) -> bool:
        """TEXTUAL validation (min_len=2)"""
        min_len = min_len or self._min_text_len
        if not text or len(text) < min_len:
            return False
        if prev_text and text == prev_text:
            return False
        if len(set(text)) / len(text) < 0.3:
            return False
        return True
    
    def wait_for_next_item(self, prev_frame: np.ndarray, prev_text: str) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """FIXED: wait for VALID next item (seuil 2.5)"""
        timeout = self._sync_timeout
        poll_interval = self._poll_interval
        empty_reads_max = self._empty_reads_max
        start_time = time.time()
        empty_reads = 0
        
        print(f"  [SYNC] Waiting next valid item (timeout={timeout}s)...")
        while time.time() - start_time < timeout:
            if self.stop_signal.should_stop():
                return None, None
                
            new_frame = self.capture.capture()
            if not self.frame_has_changed(prev_frame, new_frame):
                time.sleep(poll_interval)
                continue
                
            print("  [SYNC] frame changed → OCR...")
            new_texts = self.ocr.recognize(new_frame)
            new_text = "".join([fuzzy_clean_text(t) for t in new_texts])
            
            # FIXED: rejet menu actions
            if self.looks_like_action_menu(new_text):
                print(f"  [SYNC] Action menu detected: '{new_text}' → skip")
                time.sleep(poll_interval)
                continue
            
            if not self.is_valid_ocr_text(new_text, prev_text):
                print(f"  [SYNC] Invalid OCR: '{new_text}' (len={len(new_text)})")
                empty_reads += 1
                if empty_reads >= empty_reads_max:
                    print(f"  [SYNC] {empty_reads} empty → end of list")
                    return None, None
                continue
                
            print(f"  [SYNC] ✓ Valid item: '{new_text}'")
            return new_frame, new_text
            
        print(f"  [SYNC] timeout → end of list")
        return None, None
    
    # ==================== FIXED PROCESS_ITEM ====================
    def process_item(self, index: int, image: np.ndarray = None) -> Tuple[bool, str, np.ndarray]:
        """FIXED: accepte image injectée OU capture nouvelle"""
        lang = self.cfg.lang
        
        # FIXED: utilise frame déjà validée si fournie
        if image is None:
            image = self.capture.capture()
            
        # FIXED: rejet menu actions AVANT OCR
        dummy_text = "".join([fuzzy_clean_text(t) for t in self.ocr.recognize(image)])
        if self.looks_like_action_menu(dummy_text):
            print(f"  [{index:2d}] [WRONG UI] Action menu detected")
            return False, "", image  # Pas d'action !
        
        texts = self.ocr.recognize(image)
        cleaned_texts = [fuzzy_clean_text(t) for t in texts]
        recognized = "".join(cleaned_texts)
        print(f"  [{index:2d}] OCR: '{recognized}' (len={len(recognized)})")
        
        keep, info, matched_kw, blacklist_kw, has_a, group_name = self.matcher.match(texts)
        self.stats.scanned += 1
        
        if keep:
            self.stats.kept += 1
            self.stats.add_kept_item(texts, matched_kw, group_name)
            print(f"  [{index:2d}] ★ KEEP - {info}")
            self.keyboard.keep_item()
        else:
            print(f"  [{index:2d}] ✗ DISCARD - {info}")
            if has_a and blacklist_kw:
                self.stats.add_qualified_blacklisted(texts, matched_kw, blacklist_kw)
            self.keyboard.discard_item()
            
        return keep, recognized, image
        
    def debug_save_capture_series(self, prefix="series", count=5, delay=0.5):
        """Save several consecutive captures to verify helper output."""
        prev = None

        base_dir = os.path.dirname(os.path.abspath(__file__))
        debug_dir = os.path.join(base_dir, "debug_captures")
        os.makedirs(debug_dir, exist_ok=True)

        print(f"[DEBUG] Saving {count} captures to: {debug_dir}")

        for i in range(count):
            img = self.capture.capture()

            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = os.path.join(debug_dir, f"{prefix}_{i:02d}_{ts}.png")

            ok = cv2.imwrite(path, img)
            print(f"[DEBUG] #{i} saved={ok} path={path}")

            if prev is not None:
                diff = np.mean(cv2.absdiff(prev, img))
                print(f"[DEBUG] #{i} diff_vs_prev={diff:.3f}")

            try:
                texts = self.ocr.recognize(img)
                merged = "".join([fuzzy_clean_text(t) for t in texts])
                print(f"[DEBUG] #{i} OCR='{merged}' raw={texts}")
            except Exception as e:
                print(f"[DEBUG] #{i} OCR error: {e}")

            prev = img
            time.sleep(delay)

    
    # ==================== FIXED RUN_ROUND ====================
    def run_round(self) -> bool:
        """FULL SYNCHRONIZED + FIXED LOGIC"""
        lang = self.cfg.lang
        self.stats.rounds += 1
        print(f"\n🔥 [ROUND {self.stats.rounds}]")
        
        self.keyboard.forge_start()
        time.sleep(0.5)  # FIXED: stabilise UI après forge_start
        
        actual_count = 0
        prev_frame = None
        prev_text = None
        
        print("  [SYNC] Capture first item...")
        
        # FIXED: Premier item - capture + validation
        keep, current_text, current_frame = self.process_item(1)
        
        # FIXED: Si premier item déjà invalide → round échoué
        if not self.is_valid_ocr_text(current_text) or self.looks_like_action_menu(current_text):
            print(f"  [ERROR] First item invalid → round failed")
            self.keyboard.forge_end()
            return False
            
        actual_count = 1
        prev_frame = current_frame
        prev_text = current_text
        
        print(f"  [OK] Item 1 processed ✓")
        
        # Boucle sur items suivants
        while actual_count < self.cfg.BATCH_SIZE:
            if self.stop_signal.should_stop():
                return False
                
            item_idx = actual_count + 1
            print(f"\n  [SYNC] Item {actual_count} → wait {item_idx}...")
            
            new_frame, new_text = self.wait_for_next_item(prev_frame, prev_text)
            if new_frame is None or new_text is None:
                print(f"  [END] List exhausted after {actual_count}")
                break
                
            # FIXED: utilise frame déjà validée !
            keep, current_text, current_frame = self.process_item(item_idx, new_frame)
            if not self.is_valid_ocr_text(current_text):
                print(f"  [ERROR] Item {item_idx} invalid after sync")
                break
                
            actual_count += 1
            prev_frame = current_frame
            prev_text = current_text
            
        print(f"  🎯 FINAL Batch: {actual_count} relics processed")
        self.keyboard.forge_end()
        return actual_count > 0  # FIXED: ne relance PAS si 0
    
    # Autres méthodes (identiques)
    def start_currency_locker(self) -> bool:
        print("[STEP 1] Linux mode: Skipping currency lock\n")
        return True
    
    def show_config_keywords(self):
        lang = self.cfg.lang
        print("\n" + "-"*50)
        print("Keyword Groups")
        print("-"*50)
        if not self.cfg.KEYWORD_GROUPS:
            print("No keyword groups")
        else:
            for group_name in sorted(self.cfg.KEYWORD_GROUPS.keys(), key=natural_sort_key):
                group_config = self.cfg.KEYWORD_GROUPS[group_name]
                print(f"\n【{group_name}】")
                if group_config['a']:
                    print(f"  Required (≥{group_config['min']}): {' || '.join(group_config['a'])}")
                if group_config['b']:
                    print(f"  Optional: {' || '.join(group_config['b'])}")
                if group_config['blacklist']:
                    print(f"  Blacklist: {' || '.join(group_config['blacklist'])}")
        print("="*50)
    
    def wait_user_ready(self) -> bool:
        print("\n[STEP 2] Prepare...")
        print("="*50)
        print("LOCK SUCCESS")
        print("="*50)
        print("Steps:")
        print("  1. Enter shop")
        print("  2. Select relic batch (10)")
        print("  3. Press Enter")
        print("\nPress ESC to stop anytime")
        print("="*50)
        print("\nPress Enter to continue...")
        input()
        return True
    
    def run(self):
        """Main loop - FIXED"""
        print("="*50)
        print("Relic Auto-Forging - OCR SYNC FIXED")
        print("="*50)
        
        if not self.cfg.KEYWORD_GROUPS:
            print("[ERROR] No keywords")
            self.wait_for_exit()
            return
            
        if not self.start_currency_locker():
            print("[ERROR] Currency lock failed")
            self.wait_for_exit()
            return
        
        print("[INIT] Warmup input permissions...")
        self.keyboard.warmup_permissions()
        print("[INIT] Warmup done")
            
        self.show_config_keywords()
        if not self.wait_user_ready():
            self.wait_for_exit()
            return
            
        print("\nSwitch to game...")
        for i in range(5, 0, -1):
            print(f"{i}...")
            time.sleep(1)
            
        consecutive_fails = 0
        try:
            while not self.stop_signal.should_stop():
                if not self.run_round():
                    consecutive_fails += 1
                    print(f"[WARNING] Round failed ({consecutive_fails}/3)")
                    if consecutive_fails >= 3:
                        print("[STOP] Too many failed rounds")
                        break
                    time.sleep(1)
                else:
                    consecutive_fails = 0  # Reset sur succès
        except KeyboardInterrupt:
            print("\n[INTERRUPTED]")
        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.stop_signal.event.set()
            time.sleep(0.2)
            if self.locker:
                self.locker.stop()
            self.stats.print_report()
            try:
                self.capture.close()
            except:
                pass
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            log_filename = f"hajiwo_log_{timestamp}.txt"
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_captures")
            log_path = os.path.join(log_dir, log_filename)
            self.stats.save_log(log_path)
    
    def debug_screenshot(self):
        img = self.capture.capture()
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                           f"debug_{datetime.datetime.now().strftime('%H%M%S')}.png")
        cv2.imwrite(path, img)
        print(f"[DEBUG] Saved: {path}")
        h, w = img.shape[:2]
        print(f"[DEBUG] captured size = {w}x{h}")   
        texts = self.ocr.recognize(img)
        print(f"[DEBUG] OCR: {texts}")
    
    def wait_for_exit(self):
        input("\nPress Enter to exit...")

# ==================== 入口 ====================
if __name__ == "__main__":
    bot = None
    try:
        bot = ForgeBot()
        bot.run()
    except Exception as e:
        print(f"致命错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 最外层兜底，使用Windows pause命令
        print("\n" + "="*50)
        if bot and bot.cfg and bot.cfg.lang:
            print(bot.cfg.lang.get('program_done'))
        else:
            print("程序执行完毕")
        print("="*50)
        input("程序执行完毕 / Program completed. Press Enter to exit...")
