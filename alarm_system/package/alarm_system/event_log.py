"""
alarm_system/event_log.py — Circular event log with JSON persistence.

Records alarm system events (arm, disarm, zone_trigger, alarm, etc.)
with timestamps. Stored as a JSON array in /data/alarm_log.json.
"""

import json
import time

_log = []
_max_entries = 100
_log_file = None


def init(log_file, max_entries=100):
    """Initialize event log: set file path, load existing entries.
    :param log_file str: absolute path to log JSON file
    :param max_entries int: max entries to keep (circular buffer)
    """
    global _log, _max_entries, _log_file
    _log_file = log_file
    _max_entries = max_entries
    _log = _load()


def log(event, data=None):
    """Append an event to the log.
    :param event str: event type (arm, disarm, zone_trigger, alarm, etc.)
    :param data dict|None: optional event data
    """
    entry = {'ts': int(time.time()), 'event': event}
    if data:
        entry['data'] = data
    _log.append(entry)
    # Circular trim
    while len(_log) > _max_entries:
        _log.pop(0)
    _save()


def get(count=20):
    """Return last N log entries (newest last).
    :param count int: number of entries to return
    :return list: log entries
    """
    return _log[-count:]


def clear():
    """Clear all log entries."""
    global _log
    _log = []
    _save()


def _save():
    """Persist log to file."""
    if _log_file is None:
        return
    try:
        with open(_log_file, 'w') as f:
            json.dump(_log, f)
    except Exception:
        pass


def _load():
    """Load log from file. Returns list or empty."""
    if _log_file is None:
        return []
    try:
        with open(_log_file, 'r') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data[-_max_entries:]
        return []
    except (OSError, ValueError, Exception):
        return []
