from Types import resolve
from phone_manager.manager import UserManagement


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
                    'BUTTON{"result": true} get_all_users',
                    'BUTTON{"result": true} count_users',
                    'export_users file="users_backup.json"',
                    'import_users data="[...]" mode="replace"',
                    'import_users file="users_backup.json" mode="merge"',
                    'grant_access phone="+36202002000" valid_from="2026-05-10T12:00" expires="2026-06-13T20:00"',
                    'check_access phone="+36202002000"',
                    'BUTTON{"result": true} get_inactive_users',
                    'clear_users'), widgets=widgets)
