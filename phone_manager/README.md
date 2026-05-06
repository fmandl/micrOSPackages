# micrOS Application: phone_manager

Phone number-based user management and access control for micrOS devices. Provides user CRUD operations, role-based access (admin/user), time-windowed access control (valid_from/expires), phone number normalization, JSON persistence, and **multiple named phonebook instances** for isolated access control per subsystem.

## Install

```bash
pacman install "github:BxNxM/micrOSPackages/phone_manager"
```

```bash
pacman upgrade "phone_manager"
pacman uninstall "phone_manager"
```

## Device Layout

- Package files: `/lib/phone_manager`
- Load module: `/modules/LM_users.py`
- Data files: `/data/users.json` (default), or custom per book

## Usage

### Single phonebook (backward compatible)

```commandline
users load json_file="users.json"
users add_user phone="+36202002000" name="John Doe" status="A" role="user"
users check_access phone="+36202002000"
users get_all_users
```

### Multiple phonebooks (isolated access control)

```commandline
users load json_file="garage_users.json" book="garage"
users load json_file="home_users.json" book="home"
users add_user phone="+36201111111" name="Owner" role="admin" book="garage"
users add_user phone="+36201111111" name="Owner" role="admin" book="home"
users add_user phone="+36202222222" name="Cleaner" role="user" book="home"
users check_access phone="+36202222222" book="garage"  # → not found
users check_access phone="+36202222222" book="home"    # → OK
users list_books
users unload book="garage"
```

### All commands

```commandline
users load json_file="users.json" book="default"
users add_user phone="+36202002000" name="John Doe" status="A" role="user" book="default"
users modify_user phone="+36202002000" status="B" book="default"
users delete_user phone="+36202002000" book="default"
users get_user name="John Doe" book="default"
users get_all_users book="default"
users count_users book="default"
users export_users file="users_backup.json" book="default"
users import_users file="users_backup.json" mode="merge" book="default"
users grant_access phone="+36202002000" valid_from="2026-05-10T12:00" expires="2026-06-13T20:00" book="default"
users check_access phone="+36202002000" book="default"
users get_inactive_users book="default"
users clear_users book="default"
users unload book="default"
users list_books
```

## Features

- **Multiple named phonebooks**: Isolated user databases per subsystem (garage, home, alarm)
- **Phone number normalization**: Handles Hungarian formats (06, 36, 0036, +36) automatically
- **Role-based access**: `admin` and `user` roles for different permission levels
- **Time-windowed access**: `valid_from` and `expires` fields for temporary access grants
- **Auto-deactivation**: Users outside their time window are automatically set to blocked status
- **Import/Export**: Backup and restore user lists via JSON files
- **Path traversal protection**: Filenames are validated against directory traversal attacks
- **Phone index**: O(1) lookup by phone number
- **Backward compatible**: All functions default to `book='default'` if not specified

## Multi-Phonebook Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    LM_users.py                          │
│                                                         │
│  UserManagement.INSTANCES = {                           │
│    'default': UserManagement('/data/users.json'),       │
│    'garage':  UserManagement('/data/garage_users.json'),│
│    'home':    UserManagement('/data/home_users.json'),  │
│  }                                                      │
│                                                         │
│  Each instance has its own:                             │
│    - JSON file                                          │
│    - User list                                          │
│    - Phone index                                        │
└─────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│  LM_garage.py  │  │ alarm (home) │  │ alarm (garage)│
│  book='default'│  │ book='home'  │  │ book='garage' │
└───────────────┘  └───────────────┘  └───────────────┘
```

## User Fields

| Field | Type | Description |
|-------|------|-------------|
| `phone` | str | Phone number (unique identifier, normalized to +countrycode) |
| `name` | str | Display name |
| `status` | str | `A` (active) or `B` (blocked) |
| `role` | str | `user` or `admin` |
| `info` | str | Free-text additional info |
| `valid_from` | str | Access start time `YYYY-MM-DDTHH:MM` or empty for immediate |
| `expires` | str | Access end time `YYYY-MM-DDTHH:MM` or empty for no expiry |
| `daily_from` | str | Daily access start `HH:MM` or empty for no restriction |
| `daily_to` | str | Daily access end `HH:MM` or empty for no restriction |

## Integration Example

```python
import LM_users as users

# Garage uses its own phonebook
users.load(json_file='garage_users.json', book='garage')

# Add a cleaner with daily time window (08:00-17:00 only)
users.add_user(phone='+36202222222', name='Cleaner', role='user',
               daily_from='08:00', daily_to='17:00', book='garage')

# Check access in a call handler
result = users.get_user(phone=caller, book='garage')
if result:
    user = result[0]
    if user["status"] == "A" and not users.check_access(user["phone"], book='garage'):
        print(f"Access granted for {user['name']}")
    else:
        print(f"Access denied (outside daily window or expired)")
```

## Tests

```bash
cd phone_manager
python3 -m pytest tests/test_users.py -v
```

124 tests (103 core + 9 multi-phonebook + 12 daily time window).

## Author

Flórián Mandl ([@fmandl](https://github.com/fmandl))
