# engine/locker.py
# Optional module: locks in-game currency values in memory to prevent them from changing
# Reads the current values of two currencies (dark_mark and royal_seal), then
# re-writes them in a tight loop (every 50ms) to prevent the game from draining them
# Only works on Windows (requires pymem + nightreign.exe)

import time
import threading

import pymem
import pymem.process


class CurrencyLocker:
    """
    Attaches to the nightreign.exe process and locks two in-game currency values
    by continuously re-writing their memory addresses.

    Currencies:
    - dark_mark  : locked at its current value
    - royal_seal : locked at current value, forced to 100 if below
    """

    # Base pointer offset from the module base address
    BASE_PTR_OFFSET = 0x03C078D0

    # Pointer chain offsets for each currency
    DARK_MARK_OFFSET   = 0x530
    ROYAL_SEAL_OFFSET  = 0x4BC 

    # Minimum enforced value for royal_seal
    ROYAL_SEAL_MIN = 100

    # Lock loop interval in seconds
    LOCK_INTERVAL = 0.05

    def __init__(self):
        self.process        = None
        self.base_address   = None

        self.dark_mark_address   = None
        self.royal_seal_address  = None

        self.dark_mark_value   = None
        self.royal_seal_value  = None

        self.is_running = True

    # ------------------------------------------------------------------
    # Process attachment
    # ------------------------------------------------------------------

    def attach_process(self) -> bool:
        """Attach to the game process and retrieve the module base address."""
        try:
            self.process = pymem.Pymem("nightreign.exe")
            module = pymem.process.module_from_name(
                self.process.process_handle, "nightreign.exe"
            )
            self.base_address = module.lpBaseOfDll
            print(f"[OK] Attached to process. Base address: 0x{self.base_address:X}")
            return True
        except Exception as e:
            print(f"[ERROR] Could not attach to game process: {e}")
            return False

    # ------------------------------------------------------------------
    # Memory resolution
    # ------------------------------------------------------------------

    def resolve_pointer_chain(self, final_offset: int):
        """
        Resolve the final memory address for a currency from the base pointer.

        The base pointer is located at: module_base + BASE_PTR_OFFSET
        Then we add the currency-specific offset to get the target address.
        """
        try:
            base_ptr_address = self.base_address + self.BASE_PTR_OFFSET
            resolved = self.process.read_ulonglong(base_ptr_address)
            final_address = resolved + final_offset
            return final_address
        except Exception as e:
            print(f"[ERROR] Pointer chain resolution failed: {e}")
            return None

    def initialize_addresses(self) -> bool:
        """Resolve and store the memory addresses of both currencies."""
        self.dark_mark_address  = self.resolve_pointer_chain(self.DARK_MARK_OFFSET)
        self.royal_seal_address = self.resolve_pointer_chain(self.ROYAL_SEAL_OFFSET)

        if self.dark_mark_address and self.royal_seal_address:
            print(f"[OK] Dark mark address:  0x{self.dark_mark_address:X}")
            print(f"[OK] Royal seal address: 0x{self.royal_seal_address:X}")
            return True

        print("[ERROR] Address initialization failed.")
        return False

    # ------------------------------------------------------------------
    # Value snapshot
    # ------------------------------------------------------------------

    def snapshot_and_set_values(self) -> bool:
        """
        Read current in-game currency values and determine the lock targets.

        - dark_mark  : locked at whatever its current value is.
        - royal_seal : locked at current value, or forced to ROYAL_SEAL_MIN if below.
        """
        try:
            self.dark_mark_value = self.process.read_int(self.dark_mark_address)
            print(f"[READ] Dark mark current value:  {self.dark_mark_value}")

            current_royal_seal = self.process.read_int(self.royal_seal_address)
            print(f"[READ] Royal seal current value: {current_royal_seal}")

            if current_royal_seal < self.ROYAL_SEAL_MIN:
                self.royal_seal_value = self.ROYAL_SEAL_MIN
                self.process.write_int(self.royal_seal_address, self.ROYAL_SEAL_MIN)
                print(f"[SET] Royal seal forced to minimum: {self.ROYAL_SEAL_MIN}")
            else:
                self.royal_seal_value = current_royal_seal
                print(f"[LOCK] Royal seal locked at: {current_royal_seal}")

            return True
        except Exception as e:
            print(f"[ERROR] Failed to read or set currency values: {e}")
            return False

    # ------------------------------------------------------------------
    # Lock loop
    # ------------------------------------------------------------------

    def _lock_loop(self):
        """
        Background thread: continuously re-writes the locked values to prevent
        the game from modifying them.
        """
        print("[THREAD] Lock loop started.")
        while self.is_running:
            try:
                self.process.write_int(self.dark_mark_address,  self.dark_mark_value)
                self.process.write_int(self.royal_seal_address, self.royal_seal_value)
                time.sleep(self.LOCK_INTERVAL)
            except Exception as e:
                print(f"[WARN] Lock write failed: {e}")
                time.sleep(self.LOCK_INTERVAL * 2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """
        Full startup sequence:
        1. Attach to process
        2. Resolve memory addresses
        3. Snapshot current values
        4. Start background lock thread
        """
        print("=" * 50)
        print("Currency Locker — Starting")
        print("=" * 50)

        if not self.attach_process():
            return False
        if not self.initialize_addresses():
            return False
        if not self.snapshot_and_set_values():
            return False

        lock_thread = threading.Thread(target=self._lock_loop, daemon=True)
        lock_thread.start()

        print("=" * 50)
        print("[OK] Currency locker active.")
        print("=" * 50)
        return True

    def stop(self):
        """Stop the lock loop (the daemon thread will exit naturally)."""
        self.is_running = False
        print("[STOP] Currency locker stopped.")