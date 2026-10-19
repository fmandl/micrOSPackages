"""
NeoPixel status LED for Aqua irrigation.

A single on-board NeoPixel (or short strip) reflects the state machine state:
steady colour for normal states, blinking for warnings (low water / errors).

Design notes:
- Direct NeoPixel control (not via the core `neopixel` LM).
- Best-effort: if the LED hardware is missing or any call fails, irrigation
  logic must NOT be affected -- failures are swallowed.
- The state machine calls `on_state_change(state, fault)` after every
  transition; steady colours are a single write, warnings run a blink task.

EDIT COLOURS HERE: the STATE_COLORS / WARNING_COLOR maps are meant to be tweaked
freely. Colours are (R, G, B), 0-255 (pre-brightness scaling).
"""

try:
    from machine import Pin
except Exception:
    Pin = None

try:
    from neopixel import NeoPixel
except Exception:
    NeoPixel = None

try:
    from Common import micro_task, manage_task
except Exception:  # pragma: no cover - provided by test stubs on CPython
    micro_task = None
    manage_task = None

from irrigation_system import monitoring


# --- Easily editable colour map (R, G, B) ------------------------------------
# Keyed by a logical status label derived from (state, mode).
STATE_COLORS = {
    "idle":          (0, 0, 8),      # faint blue standby
    "running_timed": (0, 40, 0),     # green
    "running_manual": (0, 25, 25),   # teal (distinct from timed)
    "paused":        (40, 25, 0),    # amber (intentional pause)
}
# Warning / error states blink in this colour.
WARNING_COLOR = (50, 0, 0)           # red
OFF = (0, 0, 0)
# -----------------------------------------------------------------------------

BLINK_TASK_TAG = "aqua._status_led_blink"


def _status_label(state, run):
    """Map (state, run) to a STATE_COLORS key for steady (non-warning) states."""
    if state == "RUNNING":
        mode = (run or {}).get("mode") if isinstance(run, dict) else None
        return "running_manual" if mode == "manual" else "running_timed"
    if state == "PAUSED":
        return "paused"
    return "idle"


class StatusLed:
    """Best-effort NeoPixel status indicator driven by the state machine."""

    def __init__(self, config=None):
        self.config = monitoring.CONFIG if config is None else config
        self._np = None
        self._n = 0
        self._blinking = False

    # ---- hardware (all best-effort) ----

    def _enabled(self):
        pin = self.config.get("led_pin")
        count = int(self.config.get("led_count") or 0)
        return Pin is not None and NeoPixel is not None and pin is not None and count > 0

    def _init(self):
        if self._np is not None:
            return True
        if not self._enabled():
            return False
        try:
            pin = int(self.config.get("led_pin"))
            self._n = int(self.config.get("led_count") or 1)
            self._np = NeoPixel(Pin(pin), self._n)
            return True
        except Exception:
            self._np = None
            return False

    def _scaled(self, rgb):
        br = self.config.get("led_brightness")
        try:
            br = 100 if br is None else max(0, min(100, float(br)))
        except Exception:
            br = 100
        factor = br / 100.0
        return tuple(int(max(0, min(255, c)) * factor) for c in rgb)

    def _write(self, rgb):
        if not self._init():
            return False
        try:
            scaled = self._scaled(rgb)
            for i in range(self._n):
                self._np[i] = scaled
            self._np.write()
            return True
        except Exception:
            return False

    # ---- state machine hook ----

    def on_state_change(self, state, fault=None, error=None):
        """Called after every transition. Steady colour, or blink on warning."""
        try:
            warning = bool(fault) or bool(error)
            if warning:
                self._start_blink()
            else:
                self._stop_blink()
                self._write(STATE_COLORS.get(_status_label(state, self._run_hint)))
        except Exception:
            # Never let LED issues break the state machine.
            pass

    # The state machine passes the run dict via set_run_hint before the hook,
    # so we can distinguish running_timed / running_manual.
    _run_hint = None

    def set_run_hint(self, run):
        self._run_hint = run

    # ---- blink task ----

    def _blink_ms(self):
        try:
            return int(self.config.get("led_blink_ms") or 400)
        except Exception:
            return 400

    def _start_blink(self):
        if micro_task is None:
            # No async runtime (e.g. bare test) -> just show a steady warning colour.
            self._write(WARNING_COLOR)
            return
        if self._blinking:
            return
        self._blinking = True
        _blink_task(self)

    def _stop_blink(self):
        self._blinking = False
        if manage_task is not None:
            try:
                manage_task(BLINK_TASK_TAG, "kill")
            except Exception:
                pass

    def blink_step(self, on):
        """One blink half-cycle (called by the task): warning colour or off."""
        self._write(WARNING_COLOR if on else OFF)


def _make_blink_task():
    if micro_task is None:
        return None

    @micro_task("aqua", _wrap=True)
    async def status_led_blink(tag, led):
        on = True
        with micro_task(tag=tag) as my_task:
            while led._blinking:
                led.blink_step(on)
                on = not on
                my_task.out = "status led: warning blink"
                await my_task.feed(sleep_ms=led._blink_ms())
            led.blink_step(False)
    return status_led_blink


_blink_task = _make_blink_task()
