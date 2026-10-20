"""
Tank, level-sensor, flow, and soil monitoring helpers for Aqua.
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


CONFIG = {
    "tank_width_cm": 40.0,
    "tank_depth_cm": 25.0,
    "tank_height_cm": 20.0,
    "water_distance_cm": 7.0,
    "min_level_cm": 2.0,
    "pump_l_hour": 300.0,
    "head_count": 4,
    "head_flow_l_hour": 4.0,
    "soil_sensor_count": 4,
    "pump_pin": 3,
    "level_module": "manual",
    "checkpoint_interval_s": 0.0,
    "max_runtime_s": 0.0,
    "led_pin": 6,
    "led_count": 1,
    "led_brightness": 100.0,
    "led_blink_ms": 400.0,
    "btn_pin": 45,
    "btn_long_ms": 1500.0,
    "btn_debounce_ms": 50.0,
}

CONFIG_FILE = "aqua_cfg.cache"


def _config_path():
    return data_dir(CONFIG_FILE)


def save_config():
    """Persist CONFIG to /data so configure/GUI changes survive reboot."""
    try:
        with open(_config_path(), "w") as f:
            f.write(json.dumps(CONFIG))
        return True
    except Exception:
        return False


def load_config():
    """Load persisted CONFIG from /data (merge onto defaults). Best-effort."""
    try:
        with open(_config_path(), "r") as f:
            data = json.loads(f.read())
        if isinstance(data, dict):
            for key in CONFIG:            # only known keys, keep defaults for the rest
                if key in data and data[key] is not None:
                    CONFIG[key] = data[key]
        return True
    except Exception:
        return False


RUNTIME = {
    "last_level": None,
}

_LEVEL_MANUAL = (
    "manual", "none", "no_sensor", "no-sensor", "nosensor",
    "disabled", "disable", "off", "false", "0"
)


def as_float(value, default=None, minimum=None, maximum=None):
    if value in (None, "", "None", "none", "null", "n/a"):
        return default
    try:
        value = float(value)
    except Exception:
        return default
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def as_int(value, default=None, minimum=None, maximum=None):
    value = as_float(value, default, minimum=minimum, maximum=maximum)
    return None if value is None else int(value)


def optional_str(value):
    if value in (None, "", "None", "none", "null", "n/a"):
        return None
    return str(value)


def as_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).lower() in ("1", "true", "yes", "on")


def update_config(data):
    if not isinstance(data, dict):
        return
    if "level_module" in data and data.get("level_module") is not None:
        CONFIG["level_module"] = optional_str(data.get("level_module"))
    # led_pin: integer pin number, or an explicit disable ("none"/"off"/0 -> None)
    if "led_pin" in data and data.get("led_pin") is not None:
        raw = data.get("led_pin")
        if str(raw).lower() in ("none", "off", "disable", "disabled", "false"):
            CONFIG["led_pin"] = None
        else:
            pin = as_int(raw, None, minimum=0)
            CONFIG["led_pin"] = None if (pin is None or pin == 0) else pin
    # btn_pin: same convention (0/"none" -> disabled)
    if "btn_pin" in data and data.get("btn_pin") is not None:
        raw = data.get("btn_pin")
        if str(raw).lower() in ("none", "off", "disable", "disabled", "false"):
            CONFIG["btn_pin"] = None
        else:
            pin = as_int(raw, None, minimum=0)
            CONFIG["btn_pin"] = None if (pin is None or pin == 0) else pin
    fields = {
        "tank_width_cm": ("float", 0.1, None),
        "tank_depth_cm": ("float", 0.1, None),
        "tank_height_cm": ("float", 0.1, None),
        "min_level_cm": ("float", 0, None),
        "pump_l_hour": ("float", 0.1, None),
        "head_count": ("int", 1, 100),
        "head_flow_l_hour": ("float", 0.01, None),
        "soil_sensor_count": ("int", 0, 100),
        "pump_pin": ("int", 0, None),
        "checkpoint_interval_s": ("float", 0, None),
        "max_runtime_s": ("float", 0, None),
        "led_count": ("int", 0, 256),
        "led_brightness": ("float", 0, 100),
        "led_blink_ms": ("float", 50, None),
        "btn_long_ms": ("float", 100, None),
        "btn_debounce_ms": ("float", 0, None),
    }
    for key, (kind, minimum, maximum) in fields.items():
        if key not in data or data.get(key) is None:
            continue
        if kind == "int":
            CONFIG[key] = as_int(data.get(key), CONFIG.get(key), minimum, maximum)
        else:
            CONFIG[key] = as_float(data.get(key), CONFIG.get(key), minimum, maximum)
    if is_manual_level_module() and "water_distance_cm" in data and data.get("water_distance_cm") is not None:
        CONFIG["water_distance_cm"] = as_float(data.get("water_distance_cm"), CONFIG.get("water_distance_cm"), 0, None)
    save_config()   # persist every configure/GUI change to /data


def tank():
    width = as_float(CONFIG.get("tank_width_cm"), 0, minimum=0)
    depth = as_float(CONFIG.get("tank_depth_cm"), 0, minimum=0)
    height = as_float(CONFIG.get("tank_height_cm"), 0, minimum=0)
    distance = as_float(CONFIG.get("water_distance_cm"), None, minimum=0)
    reserve_cm = as_float(CONFIG.get("min_level_cm"), 0, minimum=0)
    capacity = round(width * depth * height / 1000.0, 2)
    water_height = None
    level = None
    volume_l = None
    if distance is not None and height > 0:
        water_height = round(max(0, min(height, height - distance)), 2)
        level = round(water_height * 100.0 / height, 1)
        volume_l = round(width * depth * water_height / 1000.0, 2)
    reserve_l = round(width * depth * reserve_cm / 1000.0, 2)
    usable_l = None if volume_l is None else round(max(0, volume_l - reserve_l), 2)
    return {
        "width_cm": width,
        "depth_cm": depth,
        "height_cm": height,
        "water_distance_cm": distance,
        "water_height_cm": water_height,
        "level_percent": level,
        "capacity_l": capacity,
        "volume_l": volume_l,
        "reserve_cm": reserve_cm,
        "reserve_l": reserve_l,
        "usable_l": usable_l,
        "source": "dummy",
    }


def level_module_name(module=None):
    module = optional_str(module) or optional_str(CONFIG.get("level_module")) or "manual"
    key = module.lower()
    if key in _LEVEL_MANUAL:
        return "manual"
    aliases = {
        "hcsr04": "LM_hcsr04",
        "hc-sr04": "LM_hcsr04",
        "lm_hcsr04": "LM_hcsr04",
        "rcwl1670": "LM_rcwl1670",
        "rcwl-1670": "LM_rcwl1670",
        "lm_rcwl1670": "LM_rcwl1670",
    }
    if key in aliases:
        return aliases[key]
    return module if module.startswith("LM_") else None


def is_manual_level_module(module=None):
    return level_module_name(module) == "manual"


def manual_level(source="manual"):
    return {
        "state": False,
        "source": source,
        "module": "manual",
        "enabled": False,
        "distance_cm": CONFIG.get("water_distance_cm"),
    }


def sensor_distance(module=None):
    module_name = level_module_name(module)
    if module_name == "manual":
        return manual_level("manual")
    if module_name is None:
        return {
            "state": False,
            "error": "unsupported_level_module",
            "module": optional_str(module) or optional_str(CONFIG.get("level_module")),
            "enabled": False,
        }
    try:
        sensor = __import__(module_name)
        measurement = sensor.measure_cm()
        distance = measurement.get("cm") if isinstance(measurement, dict) else measurement
        distance = as_float(distance, None, minimum=0)
        if distance is None:
            return {"state": False, "error": "invalid_sensor_distance", "module": module_name}
        return {
            "state": True,
            "module": module_name,
            "distance_cm": round(distance, 2),
            "raw": measurement,
        }
    except Exception as e:
        return {"state": False, "error": "sensor_unavailable", "module": module_name, "detail": str(e)}


def apply_sensor_distance(module=None):
    measurement = sensor_distance(module=module)
    RUNTIME["last_level"] = measurement
    if measurement.get("state"):
        CONFIG["water_distance_cm"] = measurement["distance_cm"]
    return measurement


def configure_level(was_manual, water_distance_cm=None):
    if is_manual_level_module():
        if water_distance_cm is not None or not was_manual or RUNTIME.get("last_level") is None:
            RUNTIME["last_level"] = manual_level("manual_config" if water_distance_cm is not None else "manual")
    else:
        apply_sensor_distance()


def flow():
    pump_l_hour = as_float(CONFIG.get("pump_l_hour"), 0, minimum=0)
    heads = as_int(CONFIG.get("head_count"), 1, minimum=1, maximum=100)
    head_l_hour = as_float(CONFIG.get("head_flow_l_hour"), 0, minimum=0)
    total_flow = heads_total_flow()   # heads' combined flow drives the water use
    tank_data = tank()
    minutes_to_reserve = None
    if total_flow > 0 and tank_data.get("usable_l") is not None:
        minutes_to_reserve = round(tank_data["usable_l"] * 60.0 / total_flow, 1)
    return {
        "pump_l_hour": round(pump_l_hour, 1),
        "head_count": heads,
        "head_l_hour": round(head_l_hour, 1),
        "heads_total_l_hour": total_flow,
        "pump_overload": pump_overload(),
        "minutes_to_reserve": minutes_to_reserve,
    }


def soil():
    sensor_count = as_int(CONFIG.get("soil_sensor_count"), 0, minimum=0, maximum=100)
    sensors = []
    for index in range(sensor_count):
        moisture = 42 + ((index * 17) % 29)
        if index % 3 == 0:
            moisture -= 8
        moisture = max(0, min(100, moisture))
        sensors.append({
            "id": index + 1,
            "moisture_percent": round(moisture, 1),
            "source": "dummy",
        })
    average = None
    if sensors:
        total = sum(sensor["moisture_percent"] for sensor in sensors)
        average = round(total / len(sensors), 1)
    return {
        "count": sensor_count,
        "average_percent": average,
        "sensors": sensors,
        "source": "dummy",
    }


def heads_total_flow():
    """Combined nominal flow of all irrigation heads (L/h).

    v1 (C model): uniform per-head flow x head_count. Mixed per-head flows
    (a list) are a future extension.
    """
    head_flow = as_float(CONFIG.get("head_flow_l_hour"), 0, minimum=0)
    heads = as_int(CONFIG.get("head_count"), 1, minimum=1, maximum=100)
    return round(head_flow * heads, 3)


def pump_overload():
    """True if the heads' combined flow exceeds the pump's max output.

    In that case the pump cannot supply all heads at full flow; starting is
    blocked (SPEC: planning-time overload -> reject start, GUI warning).
    """
    pump = as_float(CONFIG.get("pump_l_hour"), 0, minimum=0)
    total = heads_total_flow()
    return pump > 0 and total > pump


def plan(volume_l=None, per_head_l=None):
    # Watering duration is driven by the HEADS' combined flow, not the pump.
    # The pump is only an upper bound (see pump_overload()).
    total_flow = heads_total_flow()
    heads = as_int(CONFIG.get("head_count"), 1, minimum=1, maximum=100)
    volume_l = as_float(volume_l, None, minimum=0)
    per_head_l = as_float(per_head_l, None, minimum=0)
    if volume_l is not None and volume_l > 0:
        duration_s = 0 if total_flow <= 0 else volume_l * 3600.0 / total_flow
    elif per_head_l is not None and per_head_l > 0:
        volume_l = per_head_l * heads
        duration_s = 0 if total_flow <= 0 else volume_l * 3600.0 / total_flow
    else:
        duration_s = 0
        volume_l = 0
    return {
        "duration_s": round(duration_s, 1),
        "volume_l": round(volume_l, 3),
        "per_head_l": round(volume_l / heads, 3),
        "head_count": heads,
        "heads_total_l_hour": total_flow,
        "pump_overload": pump_overload(),
    }


def ready(required_l=None):
    tank_data = tank()
    water_height = tank_data.get("water_height_cm")
    reserve_cm = as_float(CONFIG.get("min_level_cm"), 0, minimum=0)
    problems = []
    warnings = []
    if water_height is None:
        warnings.append("tank_level_unknown")
    elif water_height < reserve_cm:
        problems.append("tank_level_low")
    required_l = as_float(required_l, None, minimum=0)
    if required_l and tank_data.get("usable_l") is not None:
        if required_l > tank_data["usable_l"]:
            problems.append("not_enough_usable_water")
    return {
        "ok": len(problems) == 0,
        "problems": problems,
        "warnings": warnings,
        "tank": tank_data,
    }


def check_level(required_l=None, strict=False, measure=True):
    """
    Shared water-level safety check used by every start path (start/resume) and
    by the watcher task during a run.

    Thin wrapper over ready():
    - strict=False (start/resume): unknown level is only a warning, not blocking.
    - strict=True (watcher during run): unknown level also blocks (never pump blind).
    - measure=True: refresh from the sensor first when a real level module is set,
      so the check reflects the live tank level, not a stale value.

    Returns the ready() dict (ok/problems/warnings/tank).
    """
    if measure and not is_manual_level_module():
        apply_sensor_distance()
    result = ready(required_l=required_l)
    if strict and "tank_level_unknown" in result.get("warnings", []):
        result = dict(result)
        result["ok"] = False
        result["problems"] = list(result.get("problems", [])) + ["tank_level_unknown"]
    return result


def set_level(distance_cm=None, distance_mm=None, measure=False, module=None, clear=False):
    if clear:
        CONFIG["water_distance_cm"] = 7.0
        RUNTIME["last_level"] = {"source": "default", "distance_cm": CONFIG["water_distance_cm"]}
    elif as_bool(measure):
        measurement = apply_sensor_distance(module=module)
        if not measurement.get("state") and measurement.get("source") != "manual":
            return measurement
    elif distance_cm is not None:
        CONFIG["water_distance_cm"] = as_float(distance_cm, CONFIG["water_distance_cm"], 0, None)
        RUNTIME["last_level"] = {"source": "manual", "distance_cm": CONFIG["water_distance_cm"]}
    elif distance_mm is not None:
        distance = as_float(distance_mm, None, minimum=0)
        if distance is not None:
            CONFIG["water_distance_cm"] = round(distance / 10.0, 2)
            RUNTIME["last_level"] = {"source": "manual_mm", "distance_cm": CONFIG["water_distance_cm"]}
    return tank()


def status(measure=False):
    if as_bool(measure) and not is_manual_level_module():
        apply_sensor_distance()
    elif is_manual_level_module() and RUNTIME.get("last_level") is None:
        RUNTIME["last_level"] = manual_level()
    return {
        "config": CONFIG,
        "tank": tank(),
        "flow": flow(),
        "soil": soil(),
        "ready": ready(),
        "level_sensor": RUNTIME.get("last_level"),
    }
