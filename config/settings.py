# config/settings.py
# Configuration loader for hajiwo — handles multi-language support, screen region,
# key bindings, timing/sync parameters, OCR language, and keyword groups.
# Reads: [General], [ScreenRegion], [Controls], [Timing], [OCR], [Keywords], [Language_XX]

import os
from dataclasses import dataclass
from configparser import ConfigParser
from typing import Tuple

from utils.text import fuzzy_clean_text, natural_sort_key

# region Language
# ==================== Multi-language support ====================

class Language:
    """
    Manages localized UI text loaded from a [Language_XX] section in the INI file.
    Falls back to 'zh' if the requested section is not found.
    """

    def __init__(self, config: ConfigParser, lang_code: str):
        self.lang_code = lang_code
        self.texts = {}

        section = f'Language_{lang_code}'
        if config.has_section(section):
            for key, value in config.items(section):
                self.texts[key] = value
        else:
            print(f"[WARN] Language section [{section}] not found — falling back to default (zh)")
            self.lang_code = 'zh'

    def get(self, key: str, default: str = "") -> str:
        """Return the localized string for the given key, or default if not found."""
        return self.texts.get(key, default)

# endregion
# region Config
# ==================== Configuration file loading ====================

def load_config_file():
    """Locate and parse hajiwo.ini from the project root directory."""
    config = ConfigParser()
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(project_root, 'hajiwo.ini')

    if not os.path.exists(config_path):
        print("[ERROR] hajiwo.ini not found")
        print("[INFO] Make sure hajiwo.ini is in the same directory as the script")
        return None

    try:
        config.read(config_path, encoding='utf-8')
        return config
    except Exception as e:
        print(f"[ERROR] Failed to read configuration file: {e}")
        return None

config_file = load_config_file()

# ==================== Configuration dataclass ====================

@dataclass
class Config:
    """
    Runtime configuration for the script.

    All values are populated from hajiwo.ini at instantiation.
    Falls back to hardcoded defaults if the INI file is missing or incomplete.

    INI sections:
    - [General]     : UI language code
    - [ScreenRegion]: screen capture area
    - [Controls]    : key bindings
    - [Timing]      : all timing and sync parameters
    - [OCR]         : PaddleOCR recognition language
    - [Keywords]    : relic keyword groups
    - [RelicMenu]   : tokens for relic selection menu

    Key bindings:
    - KEY_INTERACT          : interact / confirm
    - KEY_DOWN              : navigate down
    - KEY_RIGHT             : navigate right
    - KEY_KEEP              : keep item action
    - KEY_DISCARD           : discard item action
    - KEY_CHOSE_10_RELICS   : select batch of 10 relics (F2)

    Base timing (keyboard):
    - KEY_INTERVAL      : general delay after each keypress (s)
    - WAIT_ANIM         : UI transition delay for forge start/end screens (s)
    - WAIT_ANIM_EXTRA   : long wait after entering relic scroll mode (s)
    - FORGE_MENU_SLEEP  : mid-sequence sleep inside forge_start() navigation (s)
    - FORGE_READY_SLEEP : sleep after forge_start() completes in run_round() (s)
    - FOCUS_DELAY       : sleep after xdotool windowfocus in _focus_game() (s)
    - WARMUP_DELAY      : sleep steps in warmup_permissions() (s)

    Sync / OCR (ForgeBot):
    - SYNC_THRESHOLD : frame pixel diff mean threshold to detect screen change
    - SYNC_TIMEOUT   : max wait time for next item (s)
    - POLL_INTERVAL  : polling interval during wait_for_next_item loop (s)
    - EMPTY_READS_MAX: consecutive empty OCR reads before declaring end of list
    - MIN_TEXT_LEN   : minimum OCR text length to be considered valid
    - BATCH_SIZE     : max items processed per round

    OCR engine:
    - OCR_LANG : PaddleOCR recognition language (e.g. 'en', 'ch')
    """

    # Screen
    SCAN_REGION: Tuple[int, int, int, int] = (626, 576, 744, 318)

    # Keywords
    KEYWORD_GROUPS: dict = None
    RELIC_TOKENS: list = None

    # Controls
    KEY_INTERACT:        str = "f"
    KEY_DOWN:            str = "down"
    KEY_RIGHT:           str = "right"
    KEY_KEEP:            str = "right"
    KEY_DISCARD:         str = "3"
    KEY_CHOSE_10_RELICS: str = "f2"     # ← NEW

    # Base timing
    KEY_HOLD: float = 0.08   
    KEY_INTERVAL: float = 0.30
    WAIT_ANIM:    float = 0.20
    BATCH_SIZE:   int   = 10

    # Extended keyboard timing
    WAIT_ANIM_EXTRA:   float = 7.0    # ← NEW — long wait into relic scroll mode
    FORGE_MENU_SLEEP:  float = 0.50   # Mid-sequence inside forge_start()
    FORGE_READY_SLEEP: float = 0.50   # After forge_start() in run_round()
    FOCUS_DELAY:       float = 0.05   # After windowfocus in _focus_game()
    WARMUP_DELAY:      float = 0.20   # Steps in warmup_permissions()

    # Sync parameters (ForgeBot)
    SYNC_THRESHOLD: float = 2.5
    SYNC_TIMEOUT:   float = 3.0
    POLL_INTERVAL:  float = 0.1
    EMPTY_READS_MAX: int  = 3
    MIN_TEXT_LEN:    int  = 2

    # OCR engine
    OCR_LANG: str = "en"

    # Language (loaded last)
    lang: Language = None

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def __post_init__(self):
        if not config_file:
            if self.KEYWORD_GROUPS is None:
                self.KEYWORD_GROUPS = {}
            return

        # --------------------------------------------------------------
        # [General] — UI language
        # --------------------------------------------------------------
        lang_code = config_file.get('General', 'language', fallback='en')
        self.lang = Language(config_file, lang_code)

        # --------------------------------------------------------------
        # [ScreenRegion]
        # --------------------------------------------------------------
        if config_file.has_section('ScreenRegion'):
            left   = config_file.getint('ScreenRegion', 'left',   fallback=1248)
            top    = config_file.getint('ScreenRegion', 'top',    fallback=1211)
            width  = config_file.getint('ScreenRegion', 'width',  fallback=1433)
            height = config_file.getint('ScreenRegion', 'height', fallback=451)
            self.SCAN_REGION = (left, top, width, height)

        # --------------------------------------------------------------
        # [Controls] — key bindings
        # --------------------------------------------------------------
        if config_file.has_section('Controls'):
            self.KEY_INTERACT        = config_file.get('Controls', 'key_interact',          fallback=self.KEY_INTERACT)
            self.KEY_DOWN            = config_file.get('Controls', 'key_down',               fallback=self.KEY_DOWN)
            self.KEY_RIGHT           = config_file.get('Controls', 'key_right',              fallback=self.KEY_RIGHT)
            self.KEY_KEEP            = config_file.get('Controls', 'key_keep',               fallback=self.KEY_KEEP)
            self.KEY_DISCARD         = config_file.get('Controls', 'key_discard',            fallback=self.KEY_DISCARD)
            self.KEY_CHOSE_10_RELICS = config_file.get('Controls', 'key_chose_10_relics',    fallback=self.KEY_CHOSE_10_RELICS)
        
        # --------------------------------------------------------------
        # [Timing] — all timing and sync parameters
        # --------------------------------------------------------------
        if config_file.has_section('Timing'):
            # Base timing (keyboard):
            self.KEY_HOLD          = config_file.getfloat('Timing', 'key_hold',            fallback=self.KEY_HOLD)
            self.KEY_INTERVAL      = config_file.getfloat('Timing', 'key_interval',        fallback=self.KEY_INTERVAL)
            self.WAIT_ANIM         = config_file.getfloat('Timing', 'wait_anim',           fallback=self.WAIT_ANIM)
            self.WAIT_ANIM_EXTRA   = config_file.getfloat('Timing', 'wait_anim_extra',     fallback=self.WAIT_ANIM_EXTRA)  
            self.BATCH_SIZE        = config_file.getint  ('Timing', 'batch_size',          fallback=self.BATCH_SIZE)
            self.FORGE_MENU_SLEEP  = config_file.getfloat('Timing', 'forge_menu_sleep',    fallback=self.FORGE_MENU_SLEEP)
            self.FORGE_READY_SLEEP = config_file.getfloat('Timing', 'forge_ready_sleep',   fallback=self.FORGE_READY_SLEEP)
            self.FOCUS_DELAY       = config_file.getfloat('Timing', 'focus_delay',         fallback=self.FOCUS_DELAY)
            self.WARMUP_DELAY      = config_file.getfloat('Timing', 'warmup_delay',        fallback=self.WARMUP_DELAY)
            self.SYNC_THRESHOLD    = config_file.getfloat('Timing', 'sync_threshold',      fallback=self.SYNC_THRESHOLD)
            self.SYNC_TIMEOUT      = config_file.getfloat('Timing', 'sync_timeout',        fallback=self.SYNC_TIMEOUT)
            self.POLL_INTERVAL     = config_file.getfloat('Timing', 'poll_interval',       fallback=self.POLL_INTERVAL)
            self.EMPTY_READS_MAX   = config_file.getint  ('Timing', 'empty_reads_max',     fallback=self.EMPTY_READS_MAX)
            self.MIN_TEXT_LEN      = config_file.getint  ('Timing', 'min_text_len',        fallback=self.MIN_TEXT_LEN)

        # --------------------------------------------------------------
        # [OCR] — PaddleOCR recognition language
        # --------------------------------------------------------------
        if config_file.has_section('OCR'):
            self.OCR_LANG = config_file.get('OCR', 'lang', fallback=self.OCR_LANG)

        # --------------------------------------------------------------
        # [Keywords] — relic keyword groups
        # --------------------------------------------------------------
        if config_file.has_section('Keywords'):
            if self.KEYWORD_GROUPS is None:
                groups = {}
                items = config_file.items('Keywords')

                group_names = set()
                for key, value in items:
                    if '_a' in key:
                        group_names.add(key.replace('_a', ''))

                for group_name in sorted(group_names, key=natural_sort_key):
                    a_key         = f"{group_name}_a"
                    b_key         = f"{group_name}_b"
                    min_key       = f"{group_name}_min"
                    blacklist_key = f"{group_name}_blacklist"

                    if config_file.has_option('Keywords', a_key):
                        a_str         = config_file.get ('Keywords', a_key,         fallback='')
                        b_str         = config_file.get ('Keywords', b_key,         fallback='')
                        min_val       = config_file.getint('Keywords', min_key,     fallback=1)
                        blacklist_str = config_file.get ('Keywords', blacklist_key, fallback='')

                        a_list         = [fuzzy_clean_text(k.strip()) for k in a_str.split('||')         if k.strip()]
                        b_list         = [fuzzy_clean_text(k.strip()) for k in b_str.split('||')         if k.strip()]
                        blacklist_list = [fuzzy_clean_text(k.strip()) for k in blacklist_str.split('||') if k.strip()]

                        if a_list:
                            groups[group_name] = {
                                'a':         a_list,
                                'b':         b_list,
                                'min':       min_val,
                                'blacklist': blacklist_list
                            }

                if not groups:
                    print("[WARN] No valid keyword groups found in hajiwo.ini")
                    print("[INFO] Edit hajiwo.ini and remove the leading '#' from example entries to enable them")
                    self.KEYWORD_GROUPS = {}
                else:
                    self.KEYWORD_GROUPS = groups
        else:
            if self.KEYWORD_GROUPS is None:
                self.KEYWORD_GROUPS = {}

        # --------------------------------------------------------------
        # [RelicMenu] — tokens for relic selection menu / flatstone menu
        # --------------------------------------------------------------
        if config_file.has_section('RelicMenu'):
            raw_relic_tokens = config_file.get('RelicMenu', 'relic_tokens', fallback='')
            self.RELIC_TOKENS = [fuzzy_clean_text(t.strip()) for t in raw_relic_tokens.split(',') if t.strip()]

            raw_flatstone_tokens = config_file.get('RelicMenu', 'flatstone_tokens', fallback='')
            self.FLATSTONE_TOKENS = [fuzzy_clean_text(t.strip()) for t in raw_flatstone_tokens.split(',') if t.strip()]

            raw_main_menu_tokens = config_file.get('RelicMenu', 'main_menu_tokens', fallback='')
            self.MAIN_MENU_TOKENS = [fuzzy_clean_text(t.strip()) for t in raw_main_menu_tokens.split(',') if t.strip()]
        else:
            self.RELIC_TOKENS = []
            self.FLATSTONE_TOKENS = []
            self.MAIN_MENU_TOKENS = []
# endregion