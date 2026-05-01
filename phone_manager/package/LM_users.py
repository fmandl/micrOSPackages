import json
import time
from Common import data_dir
from Types import resolve


def _sanitize(value):
    """Sanitize user input for safe inclusion in output strings."""
    return str(value).replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


class UserManagement:
    INSTANCE = None
    VALID_STATUSES = ('A', 'B')
    VALID_ROLES = ('user', 'admin')

    @staticmethod
    def _parse_datetime(value):
        """Parse datetime value to unix timestamp.
        :param value str|int: 'YYYY-MM-DDTHH:MM' string, unix timestamp int, or '' for none
        :return int: unix timestamp, 0 = not set, -1 = parse error
        """
        if not value:
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        try:
            d, t = value.split('T')
            parts = d.split('-') + t.split(':')
            return int(time.mktime((int(parts[0]), int(parts[1]), int(parts[2]),
                                    int(parts[3]), int(parts[4]), 0, 0, 0, -1)))
        except Exception:
            return -1

    @staticmethod
    def _normalize_phone(phone):
        """Normalize phone number to +countrycode format.
        :param phone str: phone number in any format
        :return str: normalized phone number
        """
        phone = phone.strip().replace(' ', '').replace('-', '')
        if phone.startswith('06') and len(phone) == 11:
            phone = '+36' + phone[2:]
        elif phone.startswith('36') and not phone.startswith('+'):
            phone = '+' + phone
        elif phone.startswith('00'):
            phone = '+' + phone[2:]
        return phone

    def __init__(self, json_file):
        self.json_file = data_dir(json_file)
        self.users = self._load_users()
        self._phone_index = {u['phone']: u for u in self.users}

    def _load_users(self):
        """
        Load users from JSON file.
        :return list: list of user dicts, empty list on error
        """
        try:
            with open(self.json_file, 'r') as f:
                return json.load(f)
        except OSError:
            return []
        except Exception:
            return []

    def _save_users(self):
        """
        Persist users list to JSON file.
        :return str|None: error message on failure, None on success
        """
        try:
            with open(self.json_file, 'w') as f:
                json.dump(self.users, f)
        except Exception as e:
            return f"Save failed: {e}"
        return None

    def add_user(self, phone, name, status='A', role='user', info='', valid_from='', expires=''):
        """
        Add a new user.
        :param phone str: phone number (unique identifier)
        :param name str: display name
        :param status str: 'A' (active) or 'B' (blocked)
        :param role str: 'user' or 'admin'
        :param info str: additional info
        :param valid_from str: start datetime 'YYYY-MM-DDTHH:MM' or '' for immediate
        :param expires str: end datetime 'YYYY-MM-DDTHH:MM' or '' for no expiry
        :return str: success or error message
        """
        phone = self._normalize_phone(phone)
        if any(u['phone'] == phone for u in self.users):
            return f"User with phone {_sanitize(phone)} already exists."
        if status not in self.VALID_STATUSES:
            return f"Invalid status '{_sanitize(status)}'. Must be one of: {', '.join(self.VALID_STATUSES)}"
        if role not in self.VALID_ROLES:
            return f"Invalid role '{_sanitize(role)}'. Must be one of: {', '.join(self.VALID_ROLES)}"
        vf_ts = self._parse_datetime(valid_from)
        if vf_ts == -1:
            return f"Invalid valid_from format: '{_sanitize(valid_from)}'. Use 'YYYY-MM-DDTHH:MM'."
        exp_ts = self._parse_datetime(expires)
        if exp_ts == -1:
            return f"Invalid expires format: '{_sanitize(expires)}'. Use 'YYYY-MM-DDTHH:MM'."
        self.users.append({'phone': phone, 'name': name, 'status': status, 'role': role,
                           'info': info, 'valid_from': vf_ts, 'expires': exp_ts})
        self._phone_index[phone] = self.users[-1]
        err = self._save_users()
        return err if err else f"User {_sanitize(name)} added successfully."

    def modify_user(self, phone, **kwargs):
        """
        Modify an existing user's fields.
        :param phone str: phone number of user to modify
        :param kwargs: field=value pairs to update (must be existing fields)
        :return str: success or error message
        """
        phone = self._normalize_phone(phone)
        for user in self.users:
            if user['phone'] == phone:
                if 'new_phone' in kwargs:
                    new_phone = self._normalize_phone(kwargs.pop('new_phone'))
                    if new_phone != phone and new_phone in self._phone_index:
                        return f"User with phone {_sanitize(new_phone)} already exists."
                    kwargs['phone'] = new_phone
                unknown = [k for k in kwargs if k not in user]
                if unknown:
                    return f"Unknown field(s): {', '.join(_sanitize(k) for k in unknown)}"
                if 'status' in kwargs and kwargs['status'] not in self.VALID_STATUSES:
                    return f"Invalid status '{_sanitize(kwargs['status'])}'. Must be one of: {', '.join(self.VALID_STATUSES)}"
                if 'role' in kwargs and kwargs['role'] not in self.VALID_ROLES:
                    return f"Invalid role '{_sanitize(kwargs['role'])}'. Must be one of: {', '.join(self.VALID_ROLES)}"
                for key, value in kwargs.items():
                    user[key] = value
                if user['phone'] != phone:
                    del self._phone_index[phone]
                    self._phone_index[user['phone']] = user
                err = self._save_users()
                return err if err else f"User {phone} modified successfully."
        return f"User with phone {phone} not found."

    def delete_user(self, phone):
        """
        Delete a user by phone number.
        :param phone str: phone number of user to delete
        :return str: success or error message
        """
        phone = self._normalize_phone(phone)
        for i, user in enumerate(self.users):
            if user['phone'] == phone:
                del self.users[i]
                del self._phone_index[phone]
                err = self._save_users()
                return err if err else f"User {phone} deleted successfully."
        return f"User with phone {phone} not found."

    def get_user(self, **kwargs):
        """
        Find users matching all given field=value criteria.
        Uses phone index for O(1) lookup when only phone is given.
        :param kwargs: field=value pairs to match (all must match)
        :return list|None: list of matching user dicts, or None if no match
        """
        if not kwargs:
            return None
        if 'phone' in kwargs:
            kwargs['phone'] = self._normalize_phone(kwargs['phone'])
            if len(kwargs) == 1:
                user = self._phone_index.get(kwargs['phone'])
                return [user] if user else None
        results = [u for u in self.users if all(u.get(k) == v for k, v in kwargs.items())]
        return results if results else None

    def get_all_users(self):
        """
        Return all users.
        :return list: list of user dicts
        """
        return self.users

    def count_users(self):
        """
        Return number of users.
        :return int: user count
        """
        return len(self.users)

    @staticmethod
    def _safe_filename(file):
        """Validate filename has no path traversal."""
        if '..' in file or '/' in file or '\\' in file:
            return None
        return file

    def export_users(self, file='users_backup.json'):
        """
        Export users to a backup file in data_dir.
        :param file str: backup filename
        :return str: success or error message
        """
        if not self._safe_filename(file):
            return "Export failed: invalid filename."
        try:
            path = data_dir(file)
            with open(path, 'w') as f:
                json.dump(self.users, f)
            return f"Exported {len(self.users)} user(s) to {file}"
        except Exception as e:
            return f"Export failed: {e}"

    def import_users(self, data=None, file=None, mode='replace'):
        """
        Import users from JSON string or backup file.
        :param data str|None: JSON string (from get_all_users output)
        :param file str|None: backup filename in data_dir
        :param mode str: 'replace' (clear + load) or 'merge' (add/update)
        :return str: success or error message
        """
        if data is not None:
            try:
                users = json.loads(data) if isinstance(data, str) else data
            except Exception as e:
                return f"Import failed: invalid JSON: {e}"
        elif file is not None:
            if not self._safe_filename(file):
                return "Import failed: invalid filename."
            try:
                with open(data_dir(file), 'r') as f:
                    users = json.load(f)
            except Exception as e:
                return f"Import failed: {e}"
        else:
            return "Import failed: provide data or file parameter."
        if not isinstance(users, list):
            return "Import failed: expected a list of users."
        if mode == 'replace':
            self.users = []
            self._phone_index = {}
        count = 0
        for u in users:
            phone = self._normalize_phone(u.get('phone', ''))
            if not phone:
                continue
            if phone in self._phone_index:
                if mode == 'merge':
                    existing = self._phone_index[phone]
                    for k, v in u.items():
                        if k != 'phone':
                            existing[k] = v
                    count += 1
            else:
                entry = {'phone': phone, 'name': u.get('name', ''), 'status': u.get('status', 'A'),
                         'role': u.get('role', 'user'), 'info': u.get('info', '')}
                self.users.append(entry)
                self._phone_index[phone] = entry
                count += 1
        err = self._save_users()
        return err if err else f"Imported {count} user(s) ({mode})."

    def check_access(self, phone):
        """
        Check if a user's access is currently valid.
        If not yet active or expired, set status to B and mark info as 'inactive'.
        :param phone str: phone number to check
        :return bool: True if access denied (inactive), False if access OK
        """
        phone = self._normalize_phone(phone)
        user = self._phone_index.get(phone)
        if not user:
            return False
        now = time.time()
        vf = user.get('valid_from', 0)
        exp = user.get('expires', 0)
        if vf and now < vf:
            self._set_inactive(user)
            return True
        if exp and now >= exp:
            self._set_inactive(user)
            return True
        return False

    def _set_inactive(self, user):
        """Mark user as inactive: status B, add 'inactive' to info."""
        user['status'] = 'B'
        info = user.get('info', '')
        if 'inactive' not in info:
            user['info'] = f"inactive {info}".strip() if info else 'inactive'
        self._save_users()

    def grant_access(self, phone, valid_from='', expires=''):
        """
        Grant or extend access for an existing user.
        Sets status to A, updates valid_from/expires, removes 'inactive' from info.
        :param phone str: phone number of user
        :param valid_from str: start datetime 'YYYY-MM-DDTHH:MM' or '' for immediate
        :param expires str: end datetime 'YYYY-MM-DDTHH:MM' or '' for no expiry
        :return str: success or error message
        """
        phone = self._normalize_phone(phone)
        user = self._phone_index.get(phone)
        if not user:
            return f"User with phone {_sanitize(phone)} not found."
        vf_ts = self._parse_datetime(valid_from)
        if vf_ts == -1:
            return f"Invalid valid_from format: '{_sanitize(valid_from)}'. Use 'YYYY-MM-DDTHH:MM'."
        exp_ts = self._parse_datetime(expires)
        if exp_ts == -1:
            return f"Invalid expires format: '{_sanitize(expires)}'. Use 'YYYY-MM-DDTHH:MM'."
        user['valid_from'] = vf_ts
        user['expires'] = exp_ts
        user['status'] = 'A'
        info = user.get('info', '')
        if 'inactive' in info:
            user['info'] = info.replace('inactive', '').strip()
        err = self._save_users()
        return err if err else f"Access granted for {phone}."

    def get_inactive_users(self):
        """
        Return all users whose access is not currently valid (not yet active or expired).
        :return list: list of inactive user dicts
        """
        now = time.time()
        result = []
        for u in self.users:
            vf = u.get('valid_from', 0)
            exp = u.get('expires', 0)
            if (vf and now < vf) or (exp and now >= exp):
                result.append(u)
        return result

    def clear_users(self):
        """
        Delete all users.
        :return str: success or error message
        """
        self.users = []
        self._phone_index = {}
        err = self._save_users()
        return err if err else "All users cleared."


def load(json_file='users.json'):
    """
    Initialize the UserManagement module.
    :param json_file str: JSON filename stored in data_dir (default: users.json)
    :return str: status message
    """
    if UserManagement.INSTANCE is None:
        UserManagement.INSTANCE = UserManagement(json_file)
        return 'UserManagement started.'
    return 'UserManagement already running.'

def add_user(phone, name, status='A', role='user', info='', valid_from='', expires=''):
    """
    Add a new user.
    :param phone str: phone number (unique identifier)
    :param name str: display name
    :param status str: 'A' (active) or 'B' (blocked)
    :param role str: 'user' or 'admin'
    :param info str: additional info
    :param valid_from str: start datetime 'YYYY-MM-DDTHH:MM' or '' for immediate
    :param expires str: end datetime 'YYYY-MM-DDTHH:MM' or '' for no expiry
    :return str: success or error message
    """
    return UserManagement.INSTANCE.add_user(phone, name, status, role, info, valid_from, expires)

def modify_user(phone, **kwargs):
    """
    Modify an existing user's fields.
    :param phone str: phone number of user to modify
    :param kwargs: field=value pairs to update
    :return str: success or error message
    """
    return UserManagement.INSTANCE.modify_user(phone, **kwargs)

def delete_user(phone):
    """
    Delete a user by phone number.
    :param phone str: phone number of user to delete
    :return str: success or error message
    """
    return UserManagement.INSTANCE.delete_user(phone)

def get_user(**kwargs):
    """
    Find users matching all given field=value criteria.
    :param kwargs: field=value pairs to match
    :return list|None: list of matching user dicts, or None
    """
    return UserManagement.INSTANCE.get_user(**kwargs)

def get_all_users():
    """
    Return all users.
    :return list: list of user dicts
    """
    return UserManagement.INSTANCE.get_all_users()

def count_users():
    """
    Return number of users.
    :return int: user count
    """
    return UserManagement.INSTANCE.count_users()

def export_users(file='users_backup.json'):
    """
    Export users to a backup file.
    :param file str: backup filename
    :return str: success or error message
    """
    return UserManagement.INSTANCE.export_users(file)

def import_users(data=None, file=None, mode='replace'):
    """
    Import users from JSON string or backup file.
    :param data str|None: JSON string (from get_all_users output)
    :param file str|None: backup filename
    :param mode str: 'replace' or 'merge'
    :return str: success or error message
    """
    return UserManagement.INSTANCE.import_users(data, file, mode)

def check_access(phone):
    """
    Check if a user's access is currently valid.
    :param phone str: phone number to check
    :return bool: True if access denied (inactive)
    """
    return UserManagement.INSTANCE.check_access(phone)

def grant_access(phone, valid_from='', expires=''):
    """
    Grant or extend access for an existing user.
    :param phone str: phone number
    :param valid_from str: start datetime 'YYYY-MM-DDTHH:MM' or '' for immediate
    :param expires str: end datetime 'YYYY-MM-DDTHH:MM' or '' for no expiry
    :return str: success or error message
    """
    return UserManagement.INSTANCE.grant_access(phone, valid_from, expires)

def get_inactive_users():
    """
    Return all users whose access is not currently valid.
    :return list: list of inactive user dicts
    """
    return UserManagement.INSTANCE.get_inactive_users()

def clear_users():
    """
    Delete all users.
    :return str: success or error message
    """
    return UserManagement.INSTANCE.clear_users()


#######################
# LM helper functions #
#######################

def help(widgets=False):
    """
    [i] micrOS LM naming convention - built-in help message
    :return tuple:
        (widgets=False) list of functions implemented by this application
        (widgets=True) list of widget json for UI generation
    """
    return resolve(('load json_file=users.json',
                    'add_user phone="+36202002000" name="John Doe" status="A" role="user" info="apartment 21"',
                    'modify_user phone="+36202002000" status="B"',
                    'modify_user phone="+36202002000" new_phone="+36203003000"',
                    'delete_user phone="+36202002000"',
                    'get_user name="John Doe"',
                    'get_all_users',
                    'count_users',
                    'export_users file="users_backup.json"',
                    'import_users data="[...]" mode="replace"',
                    'import_users file="users_backup.json" mode="merge"',
                    'grant_access phone="+36202002000" valid_from="2026-05-10T12:00" expires="2026-06-13T20:00"',
                    'check_access phone="+36202002000"',
                    'get_inactive_users',
                    'clear_users'), widgets=widgets)
