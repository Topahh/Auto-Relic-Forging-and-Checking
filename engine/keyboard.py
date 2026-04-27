# engine/keyboard.py
# Keyboard input controller for X11 / Wayland (XWayland) environments.
# Uses xdotool to send keystrokes to the game window identified by its title.
# Requires xdotool to be installed: sudo dnf install xdotool

import os
import time
import subprocess

from config.settings import Config

# ------------------------------------------------------------------
# Keyboard controller
# ------------------------------------------------------------------

class KeyboardController:
    """
    Sends keystrokes to the game window using xdotool.

    On startup, verifies that xdotool is available and resolves the game
    window ID by title.  All key presses are routed to that window to avoid
    focus side-effects on other applications.

    Key names are normalized through _KEY_MAP before being passed to xdotool.
    All timing values are read from cfg — no hardcoded sleeps.
    """

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

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _verify_and_find_window(self):
        """
        Check that xdotool is installed, then locate the game window by title.

        Stores the window ID in self._window_id for use by _focus_game().
        Prints a warning if the window cannot be found — inputs may still work
        if the game window happens to have focus.
        """
        r = subprocess.run(['which', 'xdotool'], capture_output=True)
        if r.returncode != 0:
            print("[ERROR] xdotool not found — install it with: sudo dnf install xdotool")
            return
        print("[OK] xdotool detected")

        r = subprocess.run(
            ['xdotool', 'search', '--name', 'ELDEN RING NIGHTREIGN'],
            capture_output=True, text=True, env=self._env
        )

        if r.returncode == 0 and r.stdout.strip():
            self._window_id = r.stdout.strip().split('\n')[0]
            print(f"[OK] Game window found — ID {self._window_id}")
        else:
            print("[WARN] Game window not found — inputs may fail")

    # ------------------------------------------------------------------
    # Focus & warmup
    # ------------------------------------------------------------------

    def warmup_permissions(self):
        """
        Trigger an early focus + harmless keypress to initialize input permissions.
        Delay steps use cfg.WARMUP_DELAY (from [Timing] warmup_delay).
        """
        self._focus_game()
        time.sleep(self.cfg.WARMUP_DELAY)

        subprocess.run(
            ['xdotool', 'key', '--clearmodifiers', 'Shift_L'],
            env=self._env, capture_output=True
        )

        time.sleep(self.cfg.WARMUP_DELAY)

    def _focus_game(self):
        """Focus the game window before sending any input.
        Delay uses cfg.FOCUS_DELAY (from [Timing] focus_delay)."""
        if self._window_id:
            subprocess.run(
                ['xdotool', 'windowfocus', '--sync', self._window_id],
                capture_output=True, env=self._env
            )
            time.sleep(self.cfg.FOCUS_DELAY)

    # ------------------------------------------------------------------
    # Key press primitives
    # ------------------------------------------------------------------

    def press(self, key: str, delay: float = None):
        """
        Send a single keystroke to the game via xdotool.

        The key name is normalized through _KEY_MAP.  If no explicit delay is
        provided, falls back to cfg.KEY_INTERVAL.
        """
        xkey = self._KEY_MAP.get(key.lower(), key)
        subprocess.run(
            ['xdotool', 'key', '--clearmodifiers', xkey],
            env=self._env, capture_output=True
        )
        time.sleep(delay if delay is not None else self.cfg.KEY_INTERVAL)

    # ------------------------------------------------------------------
    # Game actions
    # ------------------------------------------------------------------

    def keep_item(self):
        """Press the keep key then navigate right to confirm."""
        self.press(self.cfg.KEY_KEEP)
        self.press(self.cfg.KEY_RIGHT)

    def discard_item(self):
        """Press the discard key."""
        self.press(self.cfg.KEY_DISCARD)

    def forge_start(self):
        """
        Execute the key sequence to open the forge menu and start a forging session.

        The mid-sequence pause (between the 2nd and 3rd KEY_INTERACT) uses
        cfg.FORGE_MENU_SLEEP (from [Timing] forge_menu_sleep).
        The final wait uses cfg.WAIT_ANIM (from [Timing] wait_anim).
        """
        self._focus_game()
        self.press(self.cfg.KEY_INTERACT)
        self.press(self.cfg.KEY_DOWN)
        self.press(self.cfg.KEY_INTERACT)
        time.sleep(self.cfg.FORGE_MENU_SLEEP)   # UI transition between submenu pages
        self.press(self.cfg.KEY_INTERACT)
        time.sleep(self.cfg.WAIT_ANIM)

    def forge_end(self):
        """Confirm the end of a forging session and wait for the UI transition."""
        self._focus_game()
        self.press(self.cfg.KEY_INTERACT)
        time.sleep(self.cfg.WAIT_ANIM)


# ------------------------------------------------------------------
# Helper I/O (shared utility)
# ------------------------------------------------------------------

def _readline_with_timeout(pipe, timeout=45):
    """
    Read one line from a pipe with a hard timeout.

    Runs the blocking readline() in a daemon thread.
    Raises TimeoutError if no response arrives within `timeout` seconds.
    """
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
        raise TimeoutError("Timed out waiting for helper response")

    if result["error"] is not None:
        raise result["error"]

    return result["line"]