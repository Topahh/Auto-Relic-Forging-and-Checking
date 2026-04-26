# utils/signal.py

import os
from threading import Event

from config.settings import Language

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