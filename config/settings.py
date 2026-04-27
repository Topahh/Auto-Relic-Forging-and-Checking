# config.py
# Configuration loader for hajiwo — handles multi-language support, screen region,
# and keyword group definitions from hajiwo.ini
# Reads structured INI sections: [General], [ScreenRegion], [Keywords], [Language_XX]


import os
from dataclasses import dataclass
from configparser import ConfigParser
from typing import Tuple


from utils.text import fuzzy_clean_text, natural_sort_key

# region Language class for localized UI text
# ==================== Multi-language support ====================

class Language:
    """
    Manages localized UI text loaded from a [Language_XX] section in the INI file.

    The section name is built from the language code (e.g. [Language_en], [Language_zh]).
    Falls back to 'zh' if the requested section is not found.
    """

    def __init__(self, config: ConfigParser, lang_code: str):
        self.lang_code = lang_code
        self.texts = {}

        # Load all key/value pairs for the requested language section
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
        print("[INFO]  Make sure hajiwo.ini is in the same directory as the script")
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

    Key bindings:
    - KEY_INTERACT : interact / confirm
    - KEY_DOWN     : navigate down
    - KEY_RIGHT    : navigate right
    - KEY_KEEP     : keep item action
    - KEY_DISCARD  : discard item action

    Timing:
    - KEY_INTERVAL : general delay after each keypress (seconds)
    - WAIT_ANIM    : UI transition delay for forge start/end screens (seconds)
    """

    SCAN_REGION:    Tuple[int, int, int, int] = (668, 608, 736, 243)
    KEYWORD_GROUPS: dict  = None
    KEY_INTERACT:   str   = "f"
    KEY_DOWN:       str   = "down"
    KEY_RIGHT:      str   = "right"
    KEY_KEEP:       str   = "2"
    KEY_DISCARD:    str   = "3"
    KEY_INTERVAL:   float = 0.10  # General delay after each keypress
    WAIT_ANIM:      float = 0.20  # UI transition delay (forge start / end screens only)
    BATCH_SIZE:     int   = 10
    lang:           Language = None

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def __post_init__(self):
        if config_file:
            # Load language configuration
            lang_code  = config_file.get('General', 'language', fallback='zh')
            self.lang  = Language(config_file, lang_code)

            # ----------------------------------------------------------
            # Screen region
            # ----------------------------------------------------------

            if config_file.has_section('ScreenRegion'):
                left   = config_file.getint('ScreenRegion', 'left',   fallback=1248)
                top    = config_file.getint('ScreenRegion', 'top',    fallback=1211)
                width  = config_file.getint('ScreenRegion', 'width',  fallback=1433)
                height = config_file.getint('ScreenRegion', 'height', fallback=451)
                self.SCAN_REGION = (left, top, width, height)

            # ----------------------------------------------------------
            # Keyword groups
            # ----------------------------------------------------------

            if config_file.has_section('Keywords'):
                if self.KEYWORD_GROUPS is None:
                    groups = {}
                    items  = config_file.items('Keywords')

                    # Discover group names by scanning for keys ending in '_a'
                    group_names = set()
                    for key, value in items:
                        if '_a' in key:
                            group_name = key.replace('_a', '')
                            group_names.add(group_name)

                    for group_name in sorted(group_names, key=natural_sort_key):
                        a_key         = f"{group_name}_a"
                        b_key         = f"{group_name}_b"
                        min_key       = f"{group_name}_min"
                        blacklist_key = f"{group_name}_blacklist"

                        if config_file.has_option('Keywords', a_key):
                            a_str         = config_file.get('Keywords', a_key,         fallback='')
                            b_str         = config_file.get('Keywords', b_key,         fallback='')
                            min_val       = config_file.getint('Keywords', min_key,    fallback=1)
                            blacklist_str = config_file.get('Keywords', blacklist_key, fallback='')

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

                    # Warn if the INI file contains no valid keyword groups
                    if not groups:
                        print("[WARN] No valid keyword groups found in hajiwo.ini")
                        print("[INFO] Edit hajiwo.ini and remove the leading '#' from example entries to enable them")
                        self.KEYWORD_GROUPS = {}
                    else:
                        self.KEYWORD_GROUPS = groups
        else:
            if self.KEYWORD_GROUPS is None:
                self.KEYWORD_GROUPS = {}

# endregion