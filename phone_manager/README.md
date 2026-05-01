# micrOS Application: phone_manager

Phone number-based user management and access control for micrOS devices. Provides user CRUD operations, role-based access (admin/user), time-windowed access control (valid_from/expires), phone number normalization, and JSON persistence.

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
- Data file: `/data/users.json`

## Usage

```commandline
users load json_file=users.json
users add_user phone="+36202002000" name="John Doe" status="A" role="user" info="main user"
users add_user phone="+36203003000" name="Jane" status="A" role="admin" valid_from="2026-05-10T12:00" expires="2026-06-13T20:00"
users modify_user phone="+36202002000" status="B"
users modify_user phone="+36202002000" new_phone="+36203003000"
users delete_user phone="+36202002000"
users get_user name="John Doe"
users get_all_users
users count_users
users export_users file="users_backup.json"
users import_users data="[...]" mode="replace"
users import_users file="users_backup.json" mode="merge"
users grant_access phone="+36202002000" valid_from="2026-05-10T12:00" expires="2026-06-13T20:00"
users check_access phone="+36202002000"
users get_inactive_users
users clear_users
```

## Features

- **Phone number normalization**: Handles Hungarian formats (06, 36, 0036, +36) automatically
- **Role-based access**: `admin` and `user` roles for different permission levels
- **Time-windowed access**: `valid_from` and `expires` fields for temporary access grants
- **Auto-deactivation**: Users outside their time window are automatically set to blocked status
- **Import/Export**: Backup and restore user lists via JSON files
- **Path traversal protection**: Filenames are validated against directory traversal attacks
- **Phone index**: O(1) lookup by phone number

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

## Integration Example

```python
import LM_users as users

users.load()

# Add a user
users.add_user(phone="+36201234567", name="Alice", role="user")

# Check access in a call handler
result = users.get_user(phone="+36201234567")
if result:
    user = result[0]
    if user["status"] == "A" and not users.check_access(user["phone"]):
        print(f"Access granted for {user['name']}")
```

## Tests

```bash
cd phone_manager
python3 -m pytest tests/test_users.py -v
```

## Author

Flórián Mandl ([@fmandl](https://github.com/fmandl))
