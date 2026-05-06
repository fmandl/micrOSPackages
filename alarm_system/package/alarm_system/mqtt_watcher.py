"""
alarm_system/mqtt_watcher.py — MQTT topic watcher for remote zone triggers.
Subscribes to arbitrary MQTT topics and maps payload changes to zone_trigger calls.
"""

import json
from Common import console

_watches = []
_zone_trigger_cb = None
_mqtt = None


def init(zone_trigger_cb):
    """Initialize watcher with zone_trigger callback.
    :param zone_trigger_cb func: function to call on trigger (name, event)
    """
    global _zone_trigger_cb, _mqtt
    _zone_trigger_cb = zone_trigger_cb
    try:
        import LM_mqtt_client as mqtt
        _mqtt = mqtt
    except ImportError:
        _mqtt = None
        console("mqtt_watcher: async_mqtt not available, watches disabled")


def add_watch(topic, zone, trigger_value, reset_value=None, trigger_field=None):
    """Add a watch entry and subscribe to the topic.
    :param topic str: MQTT topic to subscribe to
    :param zone str: zone name to trigger
    :param trigger_value: value that means 'triggered'
    :param reset_value: value that means 'reset' (optional)
    :param trigger_field str|None: JSON field to extract (None = raw payload)
    :return str: status message
    """
    watch = {
        'topic': topic,
        'zone': zone,
        'trigger_value': trigger_value,
        'trigger_field': trigger_field,
    }
    if reset_value is not None:
        watch['reset_value'] = reset_value
    _watches.append(watch)
    _subscribe_topic(topic)
    return f"Watch added: {topic} → zone '{zone}'"


def remove_watch(topic):
    """Remove all watch entries for a topic and unsubscribe.
    :param topic str: MQTT topic
    :return str: status message
    """
    before = len(_watches)
    remaining = [w for w in _watches if w['topic'] != topic]
    removed = before - len(remaining)
    _watches.clear()
    _watches.extend(remaining)
    if removed > 0:
        _unsubscribe_topic(topic)
        return f"Removed {removed} watch(es) for topic '{topic}'"
    return f"No watches found for topic '{topic}'"


def list_watches():
    """List all watch entries.
    :return list: watch configurations
    """
    return [{'topic': w['topic'], 'zone': w['zone'], 'trigger_field': w.get('trigger_field'),
             'trigger_value': w['trigger_value'], 'reset_value': w.get('reset_value')}
            for w in _watches]


def load_watches(watches_config):
    """Load watches from config list and subscribe to all topics.
    :param watches_config list: list of watch dicts from config file
    """
    for w in watches_config:
        _watches.append(w)
    # Subscribe to unique topics
    topics = set(w['topic'] for w in _watches)
    for topic in topics:
        _subscribe_topic(topic)


def unload():
    """Unsubscribe from all topics and clear watches."""
    topics = set(w['topic'] for w in _watches)
    for topic in topics:
        _unsubscribe_topic(topic)
    _watches.clear()


def get_watches_config():
    """Return watches in config-saveable format.
    :return list: watch dicts
    """
    return [{'topic': w['topic'], 'zone': w['zone'], 'trigger_value': w['trigger_value'],
             'trigger_field': w.get('trigger_field'),
             **({'reset_value': w['reset_value']} if 'reset_value' in w else {})}
            for w in _watches]


def _on_message(topic, payload):
    """MQTT message callback. Evaluates all watches matching the topic.
    :param topic str: received MQTT topic
    :param payload str: received payload
    """
    if not _zone_trigger_cb:
        return
    for watch in _watches:
        if watch['topic'] != topic:
            continue
        event = _evaluate(watch, payload)
        if event:
            _zone_trigger_cb(watch['zone'], event)


def _evaluate(watch, payload):
    """Evaluate payload against watch entry.
    :param watch dict: watch configuration
    :param payload str: raw MQTT payload
    :return str|None: 'triggered', 'reset', or None
    """
    try:
        field = watch.get('trigger_field')
        if field:
            data = json.loads(payload)
            value = data.get(field)
        else:
            # Try to parse as JSON first (for bool/int values)
            try:
                value = json.loads(payload)
            except (ValueError, Exception):
                value = payload.strip()

        if value == watch['trigger_value']:
            return 'triggered'
        if 'reset_value' in watch and value == watch['reset_value']:
            return 'reset'
    except Exception as e:
        console(f"mqtt_watcher: evaluate error for {watch['zone']}: {e}")
    return None


def _subscribe_topic(topic):
    """Subscribe to an MQTT topic."""
    if _mqtt is None:
        return
    try:
        _mqtt.subscribe(topic, _on_message)
    except Exception as e:
        console(f"mqtt_watcher: subscribe error for '{topic}': {e}")


def _unsubscribe_topic(topic):
    """Unsubscribe from an MQTT topic."""
    if _mqtt is None:
        return
    try:
        _mqtt.unsubscribe(topic)
    except Exception as e:
        console(f"mqtt_watcher: unsubscribe error for '{topic}': {e}")
