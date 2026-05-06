"""
alarm_system/sms_handler.py — SMS command handler.

Parses incoming SMS, checks authorization via phone_manager,
and dispatches alarm commands.
"""

import json
from Common import console

_BOOK = 'alarm'
_alarm_ref = None  # Reference to alarm module functions, set by init()


def init(alarm_module):
    """Initialize SMS handler with reference to alarm module.
    :param alarm_module: the LM_alarm_system module
    """
    global _alarm_ref
    _alarm_ref = alarm_module


def handle_sms(sms):
    """Handle incoming SMS: check authorization, execute command.
    :param sms dict: parsed SMS from SIM800 (sender, text)
    """
    if _alarm_ref is None:
        return
    sender = sms.get('sender', '')
    text = sms.get('text', '').strip().lower()
    if not sender or not text:
        return
    try:
        import LM_users as users
        result = users.get_user(phone=sender, book=_BOOK)
    except Exception:
        console("alarm_system: SMS auth failed (no phonebook)")
        return
    if not result:
        console(f"alarm_system: SMS from unknown: {sender}")
        return
    user = result[0]
    if user['status'] != 'A':
        console(f"alarm_system: SMS from blocked: {user['name']}")
        return
    try:
        if users.check_access(user['phone'], book=_BOOK):
            console(f"alarm_system: SMS from inactive: {user['name']}")
            return
    except Exception:
        pass

    from alarm_system.event_log import log as _elog
    role = user.get('role', 'user')

    # Parse command
    if text == 'disarm':
        _elog('sms_cmd', {'cmd': 'disarm', 'phone': sender, 'name': user['name']})
        _alarm_ref.disarm()
    elif text in ('arm full', 'arm'):
        _elog('sms_cmd', {'cmd': 'arm full', 'phone': sender, 'name': user['name']})
        _alarm_ref.arm(mode='full')
    elif text == 'arm night':
        _elog('sms_cmd', {'cmd': 'arm night', 'phone': sender, 'name': user['name']})
        _alarm_ref.arm(mode='night')
    elif text == 'status':
        _notify_status_sms(sender)
    elif text.startswith('bypass ') and role == 'admin':
        zone_name = text[7:].strip()
        _elog('sms_cmd', {'cmd': 'bypass', 'zone': zone_name, 'phone': sender, 'name': user['name']})
        _alarm_ref.bypass(zone_name)
    elif text.startswith('unbypass ') and role == 'admin':
        zone_name = text[9:].strip()
        _elog('sms_cmd', {'cmd': 'unbypass', 'zone': zone_name, 'phone': sender, 'name': user['name']})
        _alarm_ref.unbypass(zone_name)
    elif text.startswith('auto_arm ') and role == 'admin':
        parts = text.split()
        delay = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        mode = parts[2] if len(parts) > 2 else 'full'
        _elog('sms_cmd', {'cmd': 'auto_arm', 'delay': delay, 'mode': mode, 'phone': sender, 'name': user['name']})
        _alarm_ref.auto_arm(delay=delay, mode=mode)
    else:
        console(f"alarm_system: unknown SMS cmd '{text}' from {user['name']}")


def _notify_status_sms(phone):
    """Send status SMS to a specific phone number."""
    if _alarm_ref is None:
        return
    try:
        import LM_sim800 as sim
    except Exception:
        return
    state = _alarm_ref._state
    arm_mode = _alarm_ref._arm_mode
    zones = _alarm_ref._zones
    msg = f"State:{state} Mode:{arm_mode} Zones:{len(zones)} Open:{','.join(n for n,z in zones.items() if z.get('last_event')=='triggered') or 'none'}"
    try:
        sim.send_sms(phone, msg)
    except Exception:
        pass
