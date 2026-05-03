"""
SMS Notify subscriber — integrates SIM800 SMS into micrOS Notify system.
Only sends when explicitly requested (channels="SMS" or sms_to=...).
"""

from Notify import Notify
from Debug import syslog
from Common import data_dir


class SMS(Notify):
    INSTANCE = None
    _NUMBERS = []
    _FILE_CACHE = data_dir('notify_sms.cache')

    def __init__(self, numbers):
        super().add_subscriber(self)
        SMS._NUMBERS = numbers
        SMS.INSTANCE = self

    @staticmethod
    def send_msg(text, *args, **kwargs):
        channels = kwargs.get("channels", ())
        if isinstance(channels, str):
            channels = (channels,)
        # Only send if explicitly requested
        if len(channels) > 0 and "SMS" not in channels:
            return
        if len(channels) == 0 and not kwargs.get("sms_to"):
            return
        from sim800.modem import Sim800
        if Sim800.INSTANCE is None:
            syslog("[WARN] notify_sms: sim800 not loaded")
            return
        msg = f"{SMS._DEVFID}: {text}"
        if len(msg) > 160:
            msg = msg[:157] + "..."
        targets = kwargs.get("sms_to", None)
        if targets is None:
            targets = SMS._NUMBERS
        elif isinstance(targets, str):
            targets = [targets]
        for number in targets:
            try:
                Sim800.INSTANCE.queue_sms(number, msg)
            except Exception as e:
                syslog(f"[ERR] notify_sms to {number}: {e}")

    @staticmethod
    def _save_cache():
        with open(SMS._FILE_CACHE, 'w') as f:
            f.write(','.join(SMS._NUMBERS))

    @staticmethod
    def _load_cache():
        try:
            with open(SMS._FILE_CACHE, 'r') as f:
                return [n.strip() for n in f.read().strip().split(',') if n.strip()]
        except:
            return []
