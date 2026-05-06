"""
Door/tamper sensor module with debounced GPIO inputs.
Reports state changes via Notify (always) and via callback to alarm_system.
"""

from machine import Pin
from Common import console
from Notify import Notify
from microIO import bind_pin
import time
import json

DEBOUNCE_MS = 30
CONFIRM_MS = 80
RESCUE_MS = 1000


class DebouncedInput:
    """Debounced GPIO input with IRQ-driven detection and rescue polling.
    Uses active-low logic: 0 = triggered (closed contact), 1 = reset (open contact).
    """

    def __init__(self, pin_number, name, callback=None):
        """Initialize debounced input.
        :param pin_number int: GPIO pin number
        :param name str: sensor name (used in notifications)
        :param callback func|None: called with (name, event) on state change
        """
        self.pin = Pin(bind_pin(f"alarm_{name}", pin_number), Pin.IN, Pin.PULL_UP)
        self.name = name
        self.callback = callback
        self.last_irq_time = 0

        self.last_reported_state = self.pin.value()
        self.tentative_state = self.last_reported_state
        self.tentative_time = 0
        self.event = False

        self.pin.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=self._irq_handler)

    def _irq_handler(self, pin):
        """IRQ handler — debounces and stores tentative state change."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_irq_time) < DEBOUNCE_MS:
            return
        self.last_irq_time = now
        self.tentative_state = pin.value()
        self.tentative_time = now
        self.event = True

    def _report_state(self, current):
        """Send confirmed state change via Notify and invoke callback.
        :param current int: confirmed pin value (0=triggered, 1=reset)
        """
        self.last_reported_state = current
        self.last_irq_time = time.ticks_ms()
        event = "triggered" if current == 0 else "reset"
        console(f"{self.name} {event}")
        Notify.notify(json.dumps({self.name: event}), topic="alarm/sensor")
        if self.callback:
            self.callback(self.name, event)

    def process_if_needed(self):
        """Process pending IRQ event if confirmation time has elapsed.
        Discards event if pin bounced back during confirm window.
        """
        if not self.event:
            return

        now = time.ticks_ms()
        age = time.ticks_diff(now, self.tentative_time)

        if age < CONFIRM_MS:
            return

        current = self.pin.value()
        if current != self.tentative_state:
            self.event = False
            self.tentative_state = None
            return

        if current != self.last_reported_state:
            self._report_state(current)

        self.event = False
        self.tentative_state = None

    def poll(self):
        """Rescue polling: detect state changes if IRQ missed or stuck.
        Forces report after RESCUE_MS without IRQ activity.
        """
        now = time.ticks_ms()
        current = self.pin.value()

        if current == self.last_reported_state:
            self.tentative_state = None
            self.event = False
            return

        if self.event:
            age = time.ticks_diff(now, self.tentative_time)
            if age >= CONFIRM_MS and current == self.tentative_state:
                self._report_state(current)
                self.event = False
                self.tentative_state = None
            return

        if time.ticks_diff(now, self.last_irq_time) > RESCUE_MS:
            self._report_state(current)
            self.last_irq_time = now
            self.tentative_state = None
            self.event = False
            return

        self.tentative_state = current
        self.tentative_time = now
        self.event = True
