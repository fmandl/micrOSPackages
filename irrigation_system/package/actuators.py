"""
Pump actuator and watering-task helpers for Aqua.
"""

try:
    import utime as time
except Exception:
    import time

try:
    from machine import Pin
except Exception:
    Pin = None

from Common import manage_task, micro_task
from microIO import bind_pin, pinmap_search
from irrigation_system import monitoring


RUNTIME = {
    "pump_on": False,
    "last_action": "boot",
    "last_run": None,
    "watering": None,
}

PUMP_TAG = "aqua_pump"
TASK_TAG = "aqua._watering_task"
_PUMP_OUT = None


def now():
    try:
        return int(time.time())
    except Exception:
        return 0


def ticks_ms():
    try:
        return time.ticks_ms()
    except Exception:
        return int(time.time() * 1000)


def ticks_diff(current, start):
    try:
        return time.ticks_diff(current, start)
    except Exception:
        return current - start


def _pump_off():
    try:
        _PUMP_OUT.value(0)
    except Exception:
        pass


def _set_pump_runtime(pin, error=None):
    RUNTIME["pump_pin"] = pin
    RUNTIME["pump_hw"] = error is None
    RUNTIME["pump_on"] = False
    RUNTIME["pump_level"] = 0
    if error is None:
        if "pump_error" in RUNTIME:
            del RUNTIME["pump_error"]
    else:
        RUNTIME["pump_error"] = str(error)


def set_last_action(action):
    RUNTIME["last_action"] = action


def bind_pump(config=None, pump_pin=None):
    global _PUMP_OUT
    config = monitoring.CONFIG if config is None else config
    pin = pump_pin
    _pump_off()
    try:
        pin = bind_pin(PUMP_TAG, pin)
        if Pin is None:
            raise Exception("pump_hardware_unavailable")
        _PUMP_OUT = Pin(pin, Pin.OUT)
        _PUMP_OUT.value(0)
        config["pump_pin"] = pin
        _set_pump_runtime(pin)
    except Exception as e:
        _PUMP_OUT = None
        _set_pump_runtime(pin, error=e)
        raise
    return pin


def set_pump_power(enabled, config=None):
    global _PUMP_OUT
    level = 1 if enabled else 0
    if enabled and _PUMP_OUT is None:
        bind_pump(config=config)
    if _PUMP_OUT is not None:
        try:
            _PUMP_OUT.value(level)
        except Exception as e:
            _PUMP_OUT = None
            _set_pump_runtime(RUNTIME.get("pump_pin"), error=e)
            if enabled:
                raise
    RUNTIME["pump_on"] = bool(enabled and _PUMP_OUT is not None)
    RUNTIME["pump_level"] = level if RUNTIME["pump_on"] else 0
    return level


def pinmap(config=None):
    config = monitoring.CONFIG if config is None else config
    pins = pinmap_search(PUMP_TAG)
    if pins.get(PUMP_TAG) is None:
        pins[PUMP_TAG] = config.get("pump_pin")
    return pins


def load(config=None, pump_pin=None):
    """Bind the pump pin. Kills any active run watcher first; bind_pump powers the pump off."""
    manage_task(SM_TASK_TAG, "kill")
    _WATCH["started_ms"] = None
    try:
        bind_pump(config=config, pump_pin=pump_pin)
    except Exception:
        RUNTIME["last_action"] = "load_failed"
        raise
    RUNTIME["last_action"] = "load"
    return RUNTIME["pump_pin"]


def task_status():
    """Status of the run watcher task."""
    task = micro_task(SM_TASK_TAG)
    if task is None:
        return {"id": SM_TASK_TAG, "active": False, "out": RUNTIME.get("task_out")}
    try:
        active = not task.done.is_set()
    except Exception:
        active = RUNTIME.get("pump_on")
    return {"id": SM_TASK_TAG, "active": bool(active), "out": getattr(task, "out", RUNTIME.get("task_out"))}


def status():
    """Low-level pump + watcher task status (run lifecycle lives in the state machine)."""
    return {
        "pump_on": RUNTIME.get("pump_on"),
        "runtime": RUNTIME,
        "task": task_status(),
    }


# ---------------------------------------------------------------------------
# State-machine driven controller (new architecture)
#
# PumpController is the adapter the AquaStateMachine talks to. It owns the pump
# pin (reusing the low-level helpers above) and a single watcher task that:
#   - tracks elapsed_s (continuing from base_elapsed_s on resume),
#   - runs check_level(strict=True) every cycle -> low_water event,
#   - fires timer_expired when a timed run (or manual hard cap) is up,
#   - writes periodic checkpoints (timed + checkpoint_interval_s > 0 only).
# The watcher never switches the pump directly; it dispatches events to the
# state machine, whose transitions call pump_off(). (Single-threaded async =>
# no reentrancy issues.)
# ---------------------------------------------------------------------------

SM_TASK_TAG = "aqua._run_watcher_task"

_WATCH = {
    "started_ms": None,
    "base_elapsed_s": 0.0,
    "elapsed_s": 0.0,
    "mode": None,
    "remaining_s": None,
    "max_runtime_s": 0,
    "last_checkpoint_ms": None,
}


def _watch_elapsed():
    """Worked seconds of the current run: base (from resume) + since start."""
    started = _WATCH.get("started_ms")
    base = _WATCH.get("base_elapsed_s", 0.0) or 0.0
    if started is None:
        return base
    return base + max(0.0, ticks_diff(ticks_ms(), started) / 1000.0)


@micro_task("aqua", _wrap=True)
async def run_watcher_task(tag, controller):
    """Watcher loop driving the state machine via controller.on_event."""
    with micro_task(tag=tag) as my_task:
        try:
            while True:
                _WATCH["elapsed_s"] = _watch_elapsed()

                # 1) safety: live level check every cycle
                required_l = None
                if _WATCH.get("mode") == "timed":
                    required_l = controller.remaining_volume_l()
                level = monitoring.check_level(required_l=required_l, strict=True)
                if not level.get("ok"):
                    my_task.out = "low water -> auto pause"
                    controller.on_event("low_water")
                    break

                # 2) completion: timed duration or manual hard cap
                remaining = controller.remaining_s()
                if remaining is not None and remaining <= 0:
                    my_task.out = "run complete"
                    controller.on_event("timer_expired")
                    break

                # 3) periodic checkpoint (timed + interval > 0 only)
                controller.maybe_checkpoint()

                my_task.out = controller.task_message()
                # wake at most every 1s, at least 100ms; if remaining known, don't oversleep
                if remaining is None:
                    sleep_ms = 1000
                else:
                    sleep_ms = int(min(1000, max(100, remaining * 1000)))
                await my_task.feed(sleep_ms=sleep_ms)
        except Exception:
            # On unexpected error, fail safe: stop the run via the state machine.
            try:
                controller.on_event("stop")
            except Exception:
                pass


class PumpController:
    """Adapter between AquaStateMachine and the low-level pump + watcher task."""

    def __init__(self, config=None, state_machine=None):
        self.config = monitoring.CONFIG if config is None else config
        self.sm = state_machine  # set after construction (circular wiring)

    def bind_state_machine(self, state_machine):
        self.sm = state_machine

    # ---- interface used by the state machine ----

    def now(self):
        return now()

    def elapsed_s(self):
        return _watch_elapsed()

    def check_level(self, required_l=None):
        return monitoring.check_level(required_l=required_l, strict=False)

    def plan(self, volume_l=None, per_head_l=None):
        return monitoring.plan(volume_l=volume_l, per_head_l=per_head_l)

    def pump_on(self, mode, remaining_s, max_runtime_s, elapsed_s):
        """Turn pump ON and (re)start the watcher task for this run segment."""
        manage_task(SM_TASK_TAG, "kill")
        set_pump_power(True, self.config)
        _WATCH.update({
            "started_ms": ticks_ms(),
            "base_elapsed_s": float(elapsed_s or 0.0),
            "elapsed_s": float(elapsed_s or 0.0),
            "mode": mode,
            "remaining_s": remaining_s,
            "max_runtime_s": max_runtime_s or 0,
            "last_checkpoint_ms": ticks_ms(),
        })
        RUNTIME["last_action"] = "run"
        run_watcher_task(self)

    def pump_off(self):
        """Kill watcher task and turn pump OFF."""
        manage_task(SM_TASK_TAG, "kill")
        set_pump_power(False)
        _WATCH["started_ms"] = None

    # ---- helpers used by the watcher task ----

    def _since_segment_start_s(self):
        """Seconds elapsed since the current pump_on() segment began."""
        started = _WATCH.get("started_ms")
        if started is None:
            return 0.0
        return max(0.0, ticks_diff(ticks_ms(), started) / 1000.0)

    def remaining_s(self):
        """Seconds left; None = infinite (manual, no cap)."""
        mode = _WATCH.get("mode")
        since = self._since_segment_start_s()
        if mode == "timed":
            # remaining_s stored at pump_on is the segment's starting remaining.
            seg_remaining = _WATCH.get("remaining_s")
            seg_remaining = 0.0 if seg_remaining is None else seg_remaining
            return max(0.0, seg_remaining - since)
        cap = _WATCH.get("max_runtime_s", 0) or 0
        if cap > 0:
            # cap counts total worked time (base + since)
            return max(0.0, cap - (_WATCH.get("base_elapsed_s", 0.0) + since))
        return None

    def remaining_volume_l(self):
        """For timed runs: litres still to dispense (for the level pre-check)."""
        run = self.sm.run if self.sm is not None else None
        if not isinstance(run, dict) or run.get("mode") != "timed":
            return None
        duration = run.get("duration_s") or 0
        if duration <= 0:
            return None
        remaining = self.remaining_s() or 0
        total_l = run.get("volume_l") or 0
        return round(total_l * (remaining / duration), 3) if duration > 0 else 0

    def maybe_checkpoint(self):
        """Write a periodic checkpoint only for timed runs with interval > 0."""
        if _WATCH.get("mode") != "timed":
            return
        interval = monitoring.as_float(self.config.get("checkpoint_interval_s"), 0, minimum=0) or 0
        if interval <= 0:
            return
        last = _WATCH.get("last_checkpoint_ms")
        if last is not None and ticks_diff(ticks_ms(), last) / 1000.0 < interval:
            return
        _WATCH["last_checkpoint_ms"] = ticks_ms()
        if self.sm is not None:
            self.sm.checkpoint(self.elapsed_s())

    def on_event(self, event):
        if self.sm is not None:
            return self.sm.transition(event)
        return None

    def task_message(self):
        mode = _WATCH.get("mode")
        remaining = self.remaining_s()
        if remaining is None:
            return "watering (manual), elapsed {}s".format(round(self.elapsed_s(), 1))
        return "watering ({}): {}s left".format(mode, round(remaining, 1))
