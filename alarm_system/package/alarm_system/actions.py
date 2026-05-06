"""
alarm_system/actions.py — Action dispatcher hooks.

Sends MQTT notifications to remote devices on state transitions.
"""

import json
from Notify import Notify


def on_arming():
    """Exit delay started. Notify remote devices: buzzer slow beep."""
    Notify.notify(json.dumps({"action": "buzzer_slow"}), topic="alarm/action")


def on_armed():
    """System armed. Notify remote devices: buzzer stop, LED red."""
    Notify.notify(json.dumps({"action": "buzzer_stop"}), topic="alarm/action")
    Notify.notify(json.dumps({"action": "led_red"}), topic="alarm/action")


def on_entry_delay():
    """Entry delay started. Notify remote devices: buzzer fast beep."""
    Notify.notify(json.dumps({"action": "buzzer_fast"}), topic="alarm/action")


def on_alarm(alarm_memory):
    """Alarm triggered. Notify remote devices: siren on. Send SMS to admins.
    :param alarm_memory list: zones that caused the alarm
    """
    Notify.notify(json.dumps({"action": "siren_on"}), topic="alarm/action")
    _notify_admins_sms(alarm_memory)


def on_disarmed():
    """System disarmed. Notify remote devices: all stop, LED green."""
    Notify.notify(json.dumps({"action": "all_stop"}), topic="alarm/action")
    Notify.notify(json.dumps({"action": "led_green"}), topic="alarm/action")


def on_silent_alert(zone_name):
    """24h zone triggered while disarmed. Notify only, no siren."""
    Notify.notify(json.dumps({"alert": zone_name, "type": "silent"}), topic="alarm/action")


def _notify_admins_sms(alarm_memory):
    """Send alarm SMS to all admin users in the phonebook."""
    try:
        import LM_users as users
        import LM_sim800 as sim
        all_users = users.get_all_users(book='alarm')
    except Exception:
        return
    zones = ', '.join(alarm_memory) if alarm_memory else 'unknown'
    msg = f"ALARM! Zones: {zones}"
    for u in all_users:
        if u.get('role') == 'admin' and u.get('status') == 'A':
            try:
                sim.send_sms(u['phone'], msg)
            except Exception:
                pass
