"""
Irrigation scheduling built on the micrOS built-in Scheduler (`crontasks`).

A crontasks string is a list of blocks separated by ';;'. Each block is
    WD:H:M:S!<LM command>[;<LM command>...]
where WD is the weekday field (0=Mon..6=Sun, '*' = every day, or a continuous
range like '0-4'), H:M:S is the time ('*' = every), and the command(s) after '!'
run when due (see source/Scheduler.py).

This module manages ONLY the irrigation blocks (command `aqua start volume_l=N`)
and leaves every other crontask block untouched. The built-in Scheduler.py runs
the schedule; we only read/compose the `crontasks` config value here.

Currently only timed runs are supported (a Total L volume). Future work: allow
sun-tag timestamps (sunrise/sunset +/- minutes) and manual/time-capped runs.
"""

# The LM command we own. A block is "ours" iff its command starts with this.
_AQUA_CMD_PREFIX = "aqua start"
_SEP = ";;"


def _cfg():
    # Lazy import so CPython tests can monkeypatch get_crontasks/set_crontasks.
    from Config import cfgget, cfgput
    return cfgget, cfgput


# ---- raw crontasks access (overridable in tests) ----

def get_crontasks():
    cfgget, _ = _cfg()
    return cfgget("crontasks")


def set_crontasks(value):
    _, cfgput = _cfg()
    return cfgput("crontasks", value)


# ---- pure parse/serialize helpers (no I/O) ----

def split_blocks(crontasks):
    """Split a crontasks string into trimmed, non-empty block strings."""
    if not crontasks or not isinstance(crontasks, str):
        return []
    raw = crontasks.strip()
    if raw == "" or raw == "n/a":
        return []
    sep = _SEP if _SEP in raw else ";"
    return [b.strip() for b in raw.split(sep) if b.strip()]


def is_aqua_block(block):
    """True if a block's command targets our irrigation run."""
    parts = block.split("!", 1)
    if len(parts) != 2:
        return False
    return parts[1].strip().startswith(_AQUA_CMD_PREFIX)


def parse_volume(cmd):
    """Extract volume_l=<float> from an aqua start command, or None."""
    for token in cmd.replace("!", " ").split():
        if token.startswith("volume_l="):
            try:
                return round(float(token.split("=", 1)[1]), 3)
            except Exception:
                return None
    return None


def parse_block(block):
    """
    Parse one aqua block into {timestamp, days, hour, minute, volume_l, raw}.
    Returns None for non-aqua or malformed blocks.
    """
    if not is_aqua_block(block):
        return None
    ts, cmd = block.split("!", 1)
    fields = ts.split(":")
    if len(fields) != 4:
        return None
    days = fields[0]
    hour = None if fields[1] == "*" else _to_int(fields[1])
    minute = None if fields[2] == "*" else _to_int(fields[2])
    return {
        "timestamp": ts,
        "days": days,
        "hour": hour,
        "minute": minute,
        "volume_l": parse_volume(cmd),
        "raw": block,
    }


def compose_block(days="*", hour=6, minute=0, volume_l=1.0):
    """Build a crontasks block: WD:H:M:0!aqua start volume_l=N (timed only)."""
    d = _norm_days(days)
    h = _clamp_int(hour, 0, 23)
    m = _clamp_int(minute, 0, 59)
    v = max(0.0, _to_float(volume_l, 0.0))
    v_txt = ("%g" % round(v, 3))
    return "{}:{}:{}:0!{} volume_l={}".format(d, h, m, _AQUA_CMD_PREFIX, v_txt)


def join_blocks(blocks):
    """Serialize blocks back to a crontasks string ('n/a' when empty)."""
    clean = [b.strip() for b in blocks if b and b.strip()]
    return _SEP.join(clean) if clean else "n/a"


# ---- high-level list/add/remove (operate on the whole crontasks) ----

def list_schedules(crontasks=None):
    """Return the parsed irrigation schedules (index = aqua-block order)."""
    if crontasks is None:
        crontasks = get_crontasks()
    out = []
    idx = 0
    for block in split_blocks(crontasks):
        parsed = parse_block(block)
        if parsed is not None:
            parsed["id"] = idx
            out.append(parsed)
            idx += 1
    return out


def add_schedule(days="*", hour=6, minute=0, volume_l=1.0, crontasks=None):
    """Append a new irrigation block; returns the new crontasks string."""
    if crontasks is None:
        crontasks = get_crontasks()
    blocks = split_blocks(crontasks)
    blocks.append(compose_block(days=days, hour=hour, minute=minute, volume_l=volume_l))
    return join_blocks(blocks)


def remove_schedule(index, crontasks=None):
    """
    Remove the Nth irrigation (aqua) block (0-based over aqua blocks only).
    Non-aqua blocks keep their place. Returns the new crontasks string.
    """
    if crontasks is None:
        crontasks = get_crontasks()
    kept = []
    aqua_idx = 0
    for block in split_blocks(crontasks):
        if is_aqua_block(block):
            if aqua_idx != index:
                kept.append(block)
            aqua_idx += 1
        else:
            kept.append(block)   # leave other crontasks untouched
    return join_blocks(kept)


# ---- small numeric helpers (MicroPython-safe) ----

def _to_int(v):
    try:
        return int(v)
    except Exception:
        return None


def _to_float(v, default):
    try:
        return float(v)
    except Exception:
        return default


def _clamp_int(v, lo, hi):
    i = _to_int(v)
    if i is None:
        i = lo
    return max(lo, min(hi, i))


def _norm_days(days):
    """
    Normalize a weekday field to micrOS form: '*' or a single 0..6 or a
    continuous range 'a-b'. Anything invalid falls back to '*'.
    """
    s = str(days).strip()
    if s == "*" or s == "":
        return "*"
    if "-" in s:
        a, _, b = s.partition("-")
        ai, bi = _to_int(a), _to_int(b)
        if ai is not None and bi is not None and 0 <= ai <= 6 and 0 <= bi <= 6:
            return "{}-{}".format(ai, bi)
        return "*"
    i = _to_int(s)
    if i is not None and 0 <= i <= 6:
        return str(i)
    return "*"
