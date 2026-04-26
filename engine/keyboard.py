 # engine/keyboard.py

import os
import time
import subprocess


# region 
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
        self._focus_game()           # focus AVANT les inputs
        self.press(self.cfg.KEY_INTERACT)
        self.press(self.cfg.KEY_DOWN)
        self.press(self.cfg.KEY_INTERACT)
        time.sleep(0.5)              # augmenté de 0.2 à 0.5
        self.press(self.cfg.KEY_INTERACT)
        time.sleep(self.cfg.WAIT_ANIM)

    def forge_end(self):
        self._focus_game()
        self.press(self.cfg.KEY_INTERACT)
        time.sleep(self.cfg.WAIT_ANIM)


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

# endregion