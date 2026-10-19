"""
Physical button adapter for Aqua irrigation (wired to the irq1 pin, GPIO 45).

Behaviour (B variant):
- Short press (released before btn_long_ms): state-dependent action
    IDLE -> start (manual), RUNNING -> pause, PAUSED -> resume
- Long press (held >= btn_long_ms): fires immediately while still held -> stop;
  the following release does NOT trigger a short action ("consumed").

Implementation: own both-edge IRQ (like alarm_system door_sensor) with ticks_ms
debounce, plus a short poll task that fires the long-press the moment the
threshold is reached (responsive, no need to wait for release).

Best-effort: if no button is wired (btn_pin None/0) or the hardware fails, the
irrigation logic is unaffected.

The edge-processing logic (`on_edge`) is pure and unit-testable: the test drives
it directly with (pressed, now_ms) without any hardware.
"""

try:
    import utime as time
except Exception:
    import time

try:
    from machine import Pin
except Exception:
    Pin = None

try:
    from Common import micro_task, manage_task
except Exception:  # pragma: no cover - test stubs provide these
    micro_task = None
    manage_task = None

from irrigation_system import monitoring


POLL_TASK_TAG = "aqua._button_poll"


def _ticks_ms():
    try:
        return time.ticks_ms()
    except Exception:
        return int(time.time() * 1000)


def _ticks_diff(a, b):
    try:
        return time.ticks_diff(a, b)
    except Exception:
        return a - b


class Button:
    """Physical button -> state machine adapter (best-effort)."""

    def __init__(self, state_machine=None, config=None):
        self.sm = state_machine
        self.config = monitoring.CONFIG if config is None else config
        self._pin = None
        self._press_ms = None       # ticks when pressed; None when released
        self._last_edge_ms = 0
        self._consumed = False      # True after a long-press fired; suppresses the release action

    def bind_state_machine(self, state_machine):
        self.sm = state_machine

    # ---- config helpers ----

    def _long_ms(self):
        try:
            return int(self.config.get("btn_long_ms") or 1500)
        except Exception:
            return 1500

    def _debounce_ms(self):
        try:
            return int(self.config.get("btn_debounce_ms") or 50)
        except Exception:
            return 50

    def _enabled(self):
        pin = self.config.get("btn_pin")
        return Pin is not None and pin is not None and str(pin) not in ("0", "None", "none")

    # ---- hardware setup (best-effort) ----

    def load(self):
        """Bind the button pin and attach the both-edge IRQ. No-op if disabled."""
        if not self._enabled():
            return False
        try:
            pin_no = int(self.config.get("btn_pin"))
            self._pin = Pin(pin_no, Pin.IN, Pin.PULL_DOWN)
            self._pin.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=self._irq)
            return True
        except Exception:
            self._pin = None
            return False

    def _pressed_now(self):
        # Active-high (PULL_DOWN): 1 = pressed.
        try:
            return bool(self._pin.value())
        except Exception:
            return False

    def _irq(self, _pin):
        now = _ticks_ms()
        if _ticks_diff(now, self._last_edge_ms) < self._debounce_ms():
            return
        self._last_edge_ms = now
        self.on_edge(self._pressed_now(), now)

    # ---- pure, testable edge logic ----

    def on_edge(self, pressed, now_ms):
        """Process a debounced edge. Returns an action label or None.

        pressed=True  -> button went down: remember press time, start poll.
        pressed=False -> button went up: fire short action unless consumed.
        """
        if pressed:
            self._press_ms = now_ms
            self._consumed = False
            self._start_poll()
            return None
        # released
        self._stop_poll()
        press_ms = self._press_ms
        self._press_ms = None
        if self._consumed:
            self._consumed = False
            return None
        if press_ms is None:
            return None
        held = _ticks_diff(now_ms, press_ms)
        if held >= self._long_ms():
            # Long press that we somehow didn't catch during poll -> stop on release.
            return self._do_long()
        return self._do_short()

    def check_long(self, now_ms):
        """Called by the poll task while held: fire long-press at the threshold."""
        if self._press_ms is None or self._consumed:
            return None
        if _ticks_diff(now_ms, self._press_ms) >= self._long_ms():
            self._consumed = True
            return self._do_long()
        return None

    # ---- actions (dispatch to state machine) ----

    def _state(self):
        try:
            return self.sm.snapshot().get("state")
        except Exception:
            return None

    def _do_short(self):
        if self.sm is None:
            return None
        st = self._state()
        try:
            if st == "IDLE":
                self.sm.transition("start")       # manual
                return "start"
            if st == "RUNNING":
                self.sm.transition("pause")
                return "pause"
            if st == "PAUSED":
                self.sm.transition("resume")
                return "resume"
        except Exception:
            pass
        return None

    def _do_long(self):
        if self.sm is None:
            return None
        try:
            self.sm.transition("stop")
            return "stop"
        except Exception:
            return None

    # ---- poll task (responsive long-press) ----

    def _start_poll(self):
        if micro_task is None:
            return
        _button_poll_task(self)

    def _stop_poll(self):
        if manage_task is not None:
            try:
                manage_task(POLL_TASK_TAG, "kill")
            except Exception:
                pass

    def is_pressed(self):
        return self._press_ms is not None and not self._consumed


def _make_poll_task():
    if micro_task is None:
        return None

    @micro_task("aqua", _wrap=True)
    async def button_poll(tag, btn):
        with micro_task(tag=tag) as my_task:
            while btn.is_pressed():
                btn.check_long(_ticks_ms())
                my_task.out = "button held"
                await my_task.feed(sleep_ms=50)
    return button_poll


_button_poll_task = _make_poll_task()
