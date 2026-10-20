"""
Aqua irrigation finite state machine.

States: IDLE, RUNNING, PAUSED
Events: start, pause, resume, stop, timer_expired, low_water

The machine owns the high-level run lifecycle and persistence
(/data/aqua_run.cache). Low-level pump switching and the watcher task are
delegated to an injected `controller` object (see actuators.PumpController),
so the state machine stays unit-testable without hardware.

Persisted run record (see SPEC_statemachine.md §5):
    {
        "mode": "timed" | "manual",
        "elapsed_s": float,          # worked runtime so far
        "duration_s": float | None,  # timed: total planned seconds; manual: None
        "max_runtime_s": float,      # hard cap (0 = infinite), valid in both modes
        "volume_l": float,
        "per_head_l": float,
        "reason": "pause" | "low_water" | "checkpoint",
        "saved_at": int
    }
"""

try:
    import ujson as json
except Exception:
    import json

try:
    from Common import data_dir
except Exception:  # pragma: no cover - test env provides a stub Common
    def data_dir(f_name=None):
        return f_name if f_name else "."


# --- States ---
IDLE = "IDLE"
RUNNING = "RUNNING"
PAUSED = "PAUSED"

# --- Events ---
START = "start"
PAUSE = "pause"
RESUME = "resume"
STOP = "stop"
TIMER_EXPIRED = "timer_expired"
LOW_WATER = "low_water"

RUN_FILE = "aqua_run.cache"

# Which events are valid in which state (for invalid-transition rejection).
_VALID = {
    IDLE: (START,),
    RUNNING: (PAUSE, STOP, TIMER_EXPIRED, LOW_WATER),
    PAUSED: (RESUME, STOP),
}


def _run_path():
    return data_dir(RUN_FILE)


def load_run_file():
    """Read the persisted run record, or None if missing/invalid."""
    try:
        with open(_run_path(), "r") as f:
            data = json.loads(f.read())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_run_file(record):
    """Persist the run record. Returns True on success."""
    try:
        with open(_run_path(), "w") as f:
            f.write(json.dumps(record))
        return True
    except Exception:
        return False


def clear_run_file():
    """Delete the persisted run record if present."""
    try:
        import os
        try:
            os.remove(_run_path())
        except AttributeError:
            os.unlink(_run_path())
        return True
    except Exception:
        return False


class AquaStateMachine:
    """
    High-level irrigation state machine.

    The injected `controller` must provide:
        pump_on(mode, remaining_s, max_runtime_s, elapsed_s) -> None   # pump ON + start watcher task
        pump_off() -> None                                             # pump OFF + kill watcher task
        now() -> int                                                   # epoch seconds (for saved_at)
        check_level(required_l=None) -> dict                           # {"ok": bool, "problems": [...], ...}
        plan(volume_l, per_head_l) -> dict                             # {"duration_s", "volume_l", "per_head_l", ...}
        elapsed_s() -> float                                           # worked runtime of the active run
    """

    def __init__(self, controller, led=None):
        self.c = controller
        self.led = led         # optional StatusLed (best-effort); None disables LED
        self.state = IDLE
        self.run = None        # active/last run plan dict
        self.fault = None      # {"reason": "low_water", "at": ts} when auto-paused on low water
        # On construction, restore a persisted run as PAUSED (reboot safety).
        self._restore()
        self._notify_led()

    # ---- public API ----

    def transition(self, event, **params):
        """Dispatch an event. Returns a result dict (always includes 'state')."""
        if event not in _VALID.get(self.state, ()):  # reject invalid transitions
            result = self._result(False, error="invalid_transition")
            self._notify_led()
            return result

        handler = {
            START: self._on_start,
            PAUSE: self._on_pause,
            RESUME: self._on_resume,
            STOP: self._on_stop,
            TIMER_EXPIRED: self._on_timer_expired,
            LOW_WATER: self._on_low_water,
        }[event]
        result = handler(**params)
        self._notify_led()
        return result

    def _notify_led(self):
        """Best-effort LED update after a transition (never raises).

        The LED reflects the *persistent* state only:
          - IDLE/RUNNING/PAUSED steady colour,
          - blinking only when self.fault is set (PAUSED after low_water).
        A rejected command (start/resume blocked, invalid transition) does NOT
        blink: it did not change the state, so the LED stays on the steady colour.
        That feedback belongs to the GUI message line / level badge instead.
        """
        if self.led is None:
            return
        try:
            if hasattr(self.led, "set_run_hint"):
                self.led.set_run_hint(self.run)
            self.led.on_state_change(self.state, fault=self.fault)
        except Exception:
            pass

    def snapshot(self):
        """Current machine state for status reporting."""
        return {
            "state": self.state,
            "run": self.run,
            "fault": self.fault,
        }

    def checkpoint(self, elapsed_s):
        """Persist a periodic RUNNING checkpoint (called by the watcher task).

        Only meaningful while RUNNING; updates elapsed_s and writes reason=checkpoint.
        The per-mode policy (timed only, interval gating) is enforced by the caller
        (PumpController.maybe_checkpoint).
        """
        if self.state != RUNNING or not isinstance(self.run, dict):
            return False
        self.run["elapsed_s"] = _as_float(elapsed_s, self.run.get("elapsed_s", 0.0))
        self._persist("checkpoint")
        return True

    # ---- transition handlers ----

    def _on_start(self, volume_l=None, per_head_l=None, max_runtime_s=0, **_):
        plan = self.c.plan(volume_l=volume_l, per_head_l=per_head_l)
        duration_s = plan.get("duration_s") or 0
        mode = "timed" if duration_s > 0 else "manual"
        required_l = plan.get("volume_l") if mode == "timed" else None

        level = self.c.check_level(required_l=required_l)
        if not level.get("ok"):
            return self._result(False, error="low_water", ready=level)

        max_runtime_s = _as_float(max_runtime_s, 0)
        self.run = {
            "mode": mode,
            "elapsed_s": 0.0,
            "duration_s": duration_s if mode == "timed" else None,
            "max_runtime_s": max_runtime_s,
            "volume_l": plan.get("volume_l", 0),
            "per_head_l": plan.get("per_head_l", 0),
        }
        self.fault = None
        self._go_running()
        return self._result(True, ready=level)

    def _on_resume(self, **_):
        if not isinstance(self.run, dict):
            return self._result(False, error="no_saved_run")
        required_l = self.run.get("volume_l") if self.run.get("mode") == "timed" else None
        level = self.c.check_level(required_l=required_l)
        if not level.get("ok"):
            return self._result(False, error="low_water", ready=level)
        self.fault = None
        self._go_running()
        clear_run_file()  # resume consumes the saved record
        return self._result(True, ready=level)

    def _on_pause(self, **_):
        elapsed = self._sync_elapsed()
        self.c.pump_off()
        self.state = PAUSED
        self._persist("pause")
        return self._result(True, elapsed_s=elapsed)

    def _on_stop(self, **_):
        self.c.pump_off()
        self.state = IDLE
        self.run = None
        self.fault = None
        clear_run_file()
        return self._result(True)

    def _on_timer_expired(self, **_):
        # Watcher reports the planned time (or hard cap) is up -> behaves like stop.
        self.c.pump_off()
        self.state = IDLE
        self.run = None
        self.fault = None
        clear_run_file()
        return self._result(True, done=True)

    def _on_low_water(self, **_):
        # Safety auto-pause: stop pump, keep remaining, mark fault.
        elapsed = self._sync_elapsed()
        self.c.pump_off()
        self.state = PAUSED
        self.fault = {"reason": "low_water", "at": self.c.now()}
        self._persist("low_water")
        return self._result(True, error="low_water", elapsed_s=elapsed)

    # ---- helpers ----

    def _go_running(self):
        run = self.run
        self.state = RUNNING
        self.c.pump_on(
            mode=run["mode"],
            remaining_s=self._remaining_s(),
            max_runtime_s=run.get("max_runtime_s", 0),
            elapsed_s=run.get("elapsed_s", 0.0),
        )

    def _remaining_s(self):
        """Seconds left for the active run, or None for infinite manual."""
        run = self.run
        if run is None:
            return 0
        if run.get("mode") == "timed":
            return max(0.0, (run.get("duration_s") or 0) - run.get("elapsed_s", 0.0))
        # manual
        cap = run.get("max_runtime_s", 0) or 0
        if cap > 0:
            return max(0.0, cap - run.get("elapsed_s", 0.0))
        return None  # infinite

    def _sync_elapsed(self):
        """Pull worked runtime from the controller into run['elapsed_s']."""
        if isinstance(self.run, dict):
            try:
                self.run["elapsed_s"] = float(self.c.elapsed_s())
            except Exception:
                pass
            return self.run.get("elapsed_s", 0.0)
        return 0.0

    def _persist(self, reason):
        if not isinstance(self.run, dict):
            return
        record = dict(self.run)
        record["reason"] = reason
        record["saved_at"] = self.c.now()
        save_run_file(record)

    def _restore(self):
        record = load_run_file()
        if record is None:
            return
        # Manual mode never resumes after reboot: nothing meaningful to continue
        # (no target time). Drop the file and stay IDLE.
        if record.get("mode") != "timed":
            clear_run_file()
            return
        # Timed mode: reboot safety -> come back PAUSED, never auto-start.
        self.run = {
            "mode": "timed",
            "elapsed_s": _as_float(record.get("elapsed_s"), 0.0),
            "duration_s": record.get("duration_s"),
            "max_runtime_s": _as_float(record.get("max_runtime_s"), 0.0),
            "volume_l": record.get("volume_l", 0),
            "per_head_l": record.get("per_head_l", 0),
        }
        self.state = PAUSED
        if record.get("reason") == "low_water":
            self.fault = {"reason": "low_water", "at": record.get("saved_at")}

    def _result(self, ok, **extra):
        out = {"state": ok, "fsm_state": self.state}
        out.update(extra)
        return out


def _as_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default
