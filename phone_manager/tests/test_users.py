"""
LM_users.py unit tests — runs on host CPython without hardware.

Run:
  cd /home/ealfnmo/smarthome/garage
  python3 -m pytest tests/test_users.py -v
"""

import unittest
import sys
from unittest import mock
import os
import time
import tempfile
import importlib.util
from pathlib import Path

GARAGE_DIR = Path(__file__).resolve().parent.parent / "package"


def _load_users_module():
    import types as _t
    if "Types" not in sys.modules:
        stub = _t.ModuleType("Types")
        stub.resolve = lambda t, **kw: t
        sys.modules["Types"] = stub
    if "Common" not in sys.modules:
        stub = _t.ModuleType("Common")
        sys.modules["Common"] = stub
    sys.modules["Common"].data_dir = lambda f_name=None: f_name if f_name else '.'
    spec = importlib.util.spec_from_file_location("LM_users_real", str(GARAGE_DIR / "LM_users.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


um_mod = _load_users_module()


class TestUserManagement(unittest.TestCase):
    """Test UserManagement CRUD operations with a temp file."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.json_path = os.path.join(self.tmpdir, "users.json")
        self._orig_cwd = os.getcwd()
        os.chdir(self.tmpdir)
        self.um = um_mod.UserManagement(os.path.basename(self.json_path))

    def tearDown(self):
        os.chdir(self._orig_cwd)
        if os.path.exists(self.json_path):
            os.remove(self.json_path)
        os.rmdir(self.tmpdir)

    def test_add_and_get_user(self):
        self.um.add_user("+36201111111", "Test User", "A", "admin", "test")
        result = self.um.get_user(phone="+36201111111")
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["name"], "Test User")
        self.assertEqual(result[0]["role"], "admin")

    def test_add_duplicate_user(self):
        self.um.add_user("+36201111111", "User1")
        result = self.um.add_user("+36201111111", "User2")
        self.assertIn("already exists", result)

    def test_modify_user(self):
        self.um.add_user("+36201111111", "User1", "A")
        self.um.modify_user("+36201111111", status="B")
        result = self.um.get_user(phone="+36201111111")
        self.assertEqual(result[0]["status"], "B")

    def test_delete_user(self):
        self.um.add_user("+36201111111", "User1")
        self.um.delete_user("+36201111111")
        result = self.um.get_user(phone="+36201111111")
        self.assertIsNone(result)

    def test_get_user_by_name(self):
        self.um.add_user("+36201111111", "Alice")
        self.um.add_user("+36202222222", "Bob")
        result = self.um.get_user(name="Bob")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["phone"], "+36202222222")

    def test_get_nonexistent_user(self):
        result = self.um.get_user(phone="+00000000000")
        self.assertIsNone(result)

    def test_clear_users(self):
        self.um.add_user("+36201111111", "User1")
        self.um.add_user("+36202222222", "User2")
        self.um.clear_users()
        self.assertEqual(self.um.get_all_users(), [])

    def test_persistence(self):
        """Verify users survive re-instantiation (file persistence)."""
        self.um.add_user("+36201111111", "Persistent")
        um2 = um_mod.UserManagement(os.path.basename(self.json_path))
        result = um2.get_user(phone="+36201111111")
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["name"], "Persistent")

    # --- modify_user unknown field rejection ---

    def test_modify_unknown_field_rejected(self):
        self.um.add_user("+36201111111", "User1", "A")
        result = self.um.modify_user("+36201111111", staus="B")
        self.assertIn("Unknown field", result)
        self.assertEqual(self.um.get_user(phone="+36201111111")[0]["status"], "A")

    def test_modify_multiple_unknown_fields(self):
        self.um.add_user("+36201111111", "User1")
        result = self.um.modify_user("+36201111111", foo="x", bar="y")
        self.assertIn("foo", result)
        self.assertIn("bar", result)

    def test_modify_mixed_known_unknown_rejected(self):
        self.um.add_user("+36201111111", "User1", "A")
        result = self.um.modify_user("+36201111111", status="B", foo="x")
        self.assertIn("Unknown field", result)
        self.assertEqual(self.um.get_user(phone="+36201111111")[0]["status"], "A")

    def test_modify_nonexistent_user(self):
        result = self.um.modify_user("+00000000000", status="B")
        self.assertIn("not found", result)

    # --- _save_users error propagation ---

    def test_save_error_propagated_on_add(self):
        self.um.json_file = "/nonexistent_dir/users.json"
        result = self.um.add_user("+36201111111", "User1")
        self.assertIn("Save failed", result)

    def test_save_error_propagated_on_modify(self):
        self.um.add_user("+36201111111", "User1")
        self.um.json_file = "/nonexistent_dir/users.json"
        result = self.um.modify_user("+36201111111", status="B")
        self.assertIn("Save failed", result)

    def test_save_error_propagated_on_delete(self):
        self.um.add_user("+36201111111", "User1")
        self.um.json_file = "/nonexistent_dir/users.json"
        result = self.um.delete_user("+36201111111")
        self.assertIn("Save failed", result)

    def test_save_error_propagated_on_clear(self):
        self.um.add_user("+36201111111", "User1")
        self.um.json_file = "/nonexistent_dir/users.json"
        result = self.um.clear_users()
        self.assertIn("Save failed", result)

    # --- get_user edge cases ---

    def test_get_user_no_kwargs_returns_none(self):
        self.assertIsNone(self.um.get_user())

    def test_get_user_by_role(self):
        self.um.add_user("+36201111111", "Admin", role="admin")
        self.um.add_user("+36202222222", "User", role="user")
        result = self.um.get_user(role="admin")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Admin")

    def test_get_user_multiple_matches(self):
        self.um.add_user("+36201111111", "User1", status="A")
        self.um.add_user("+36202222222", "User2", status="A")
        result = self.um.get_user(status="A")
        self.assertEqual(len(result), 2)

    def test_get_user_multi_kwargs_filter(self):
        self.um.add_user("+36201111111", "Admin1", role="admin", status="A")
        self.um.add_user("+36202222222", "Admin2", role="admin", status="B")
        self.um.add_user("+36203333333", "User1", role="user", status="A")
        result = self.um.get_user(role="admin", status="A")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Admin1")

    def test_get_user_multi_kwargs_no_match(self):
        self.um.add_user("+36201111111", "User1", role="user", status="A")
        result = self.um.get_user(role="admin", status="B")
        self.assertIsNone(result)

    def test_get_user_by_nonexistent_field(self):
        self.um.add_user("+36201111111", "User1")
        result = self.um.get_user(nonexistent="value")
        self.assertIsNone(result)

    # --- get_all_users ---

    def test_get_all_users_empty(self):
        self.assertEqual(self.um.get_all_users(), [])

    def test_get_all_users_count(self):
        self.um.add_user("+36201111111", "User1")
        self.um.add_user("+36202222222", "User2")
        self.um.add_user("+36203333333", "User3")
        self.assertEqual(len(self.um.get_all_users()), 3)

    # --- delete edge cases ---

    def test_delete_nonexistent_user(self):
        result = self.um.delete_user("+00000000000")
        self.assertIn("not found", result)

    # --- _load_users edge cases ---

    def test_load_corrupt_json(self):
        with open(self.json_path, 'w') as f:
            f.write("not valid json{{{")
        um2 = um_mod.UserManagement(os.path.basename(self.json_path))
        self.assertEqual(um2.get_all_users(), [])

    def test_load_nonexistent_file(self):
        um2 = um_mod.UserManagement("nonexistent_file.json")
        self.assertEqual(um2.get_all_users(), [])

    # --- module-level functions ---

    def test_module_load(self):
        um_mod.UserManagement.INSTANCES = {}
        result = um_mod.load(os.path.basename(self.json_path))
        self.assertIn("started", result)
        um_mod.UserManagement.INSTANCES = {}

    def test_module_load_already_running(self):
        um_mod.UserManagement.INSTANCES["default"] = self.um
        result = um_mod.load()
        self.assertIn("already running", result)
        um_mod.UserManagement.INSTANCES = {}

    # --- phone normalization ---

    def test_normalize_06_prefix(self):
        self.um.add_user("06201234567", "User1")
        result = self.um.get_user(phone="+36201234567")
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["phone"], "+36201234567")

    def test_normalize_36_without_plus(self):
        self.um.add_user("36201234567", "User1")
        result = self.um.get_user(phone="+36201234567")
        self.assertIsNotNone(result)

    def test_normalize_00_prefix(self):
        self.um.add_user("0036201234567", "User1")
        result = self.um.get_user(phone="+36201234567")
        self.assertIsNotNone(result)

    def test_normalize_with_spaces_and_dashes(self):
        self.um.add_user("+36 20-123 4567", "User1")
        result = self.um.get_user(phone="+36201234567")
        self.assertIsNotNone(result)

    def test_normalize_prevents_duplicate(self):
        self.um.add_user("+36201234567", "User1")
        result = self.um.add_user("06201234567", "User2")
        self.assertIn("already exists", result)

    def test_normalize_modify_finds_user(self):
        self.um.add_user("+36201234567", "User1", "A")
        self.um.modify_user("06201234567", status="B")
        result = self.um.get_user(phone="+36201234567")
        self.assertEqual(result[0]["status"], "B")

    def test_normalize_delete_finds_user(self):
        self.um.add_user("+36201234567", "User1")
        self.um.delete_user("06201234567")
        self.assertIsNone(self.um.get_user(phone="+36201234567"))

    def test_normalize_international_unchanged(self):
        self.um.add_user("+44201234567", "UK User")
        result = self.um.get_user(phone="+44201234567")
        self.assertIsNotNone(result)

    # --- count_users ---

    def test_count_users_empty(self):
        self.assertEqual(self.um.count_users(), 0)

    def test_count_users(self):
        self.um.add_user("+36201111111", "User1")
        self.um.add_user("+36202222222", "User2")
        self.assertEqual(self.um.count_users(), 2)

    def test_count_users_after_delete(self):
        self.um.add_user("+36201111111", "User1")
        self.um.add_user("+36202222222", "User2")
        self.um.delete_user("+36201111111")
        self.assertEqual(self.um.count_users(), 1)

    def test_module_count_users(self):
        um_mod.UserManagement.INSTANCES["default"] = self.um
        self.um.add_user("+36201111111", "User1")
        self.assertEqual(um_mod.count_users(), 1)
        um_mod.UserManagement.INSTANCES = {}

    # --- phone index ---

    def test_phone_index_fast_lookup(self):
        self.um.add_user("+36201111111", "User1")
        self.um.add_user("+36202222222", "User2")
        result = self.um.get_user(phone="+36201111111")
        self.assertEqual(result[0]["name"], "User1")

    def test_phone_index_after_delete(self):
        self.um.add_user("+36201111111", "User1")
        self.um.delete_user("+36201111111")
        self.assertIsNone(self.um.get_user(phone="+36201111111"))

    def test_phone_index_after_clear(self):
        self.um.add_user("+36201111111", "User1")
        self.um.clear_users()
        self.assertIsNone(self.um.get_user(phone="+36201111111"))

    def test_phone_index_survives_persistence(self):
        self.um.add_user("+36201111111", "User1")
        um2 = um_mod.UserManagement(os.path.basename(self.json_path))
        result = um2.get_user(phone="+36201111111")
        self.assertIsNotNone(result)

    def test_phone_index_multi_kwargs_still_works(self):
        self.um.add_user("+36201111111", "Admin1", role="admin", status="A")
        self.um.add_user("+36202222222", "Admin2", role="admin", status="B")
        result = self.um.get_user(phone="+36201111111", role="admin")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Admin1")

    def test_phone_index_multi_kwargs_no_match(self):
        self.um.add_user("+36201111111", "User1", role="user")
        result = self.um.get_user(phone="+36201111111", role="admin")
        self.assertIsNone(result)

    # --- export/import ---

    def test_export_creates_file(self):
        self.um.add_user("+36201111111", "User1")
        result = self.um.export_users('test_backup.json')
        self.assertIn('Exported 1', result)
        self.assertTrue(os.path.exists('test_backup.json'))
        os.remove('test_backup.json')

    def test_export_import_replace_roundtrip(self):
        self.um.add_user("+36201111111", "User1")
        self.um.add_user("+36202222222", "User2")
        self.um.export_users('test_backup.json')
        self.um.clear_users()
        self.assertEqual(self.um.count_users(), 0)
        result = self.um.import_users(file='test_backup.json', mode='replace')
        self.assertIn('Imported 2', result)
        self.assertEqual(self.um.count_users(), 2)
        os.remove('test_backup.json')

    def test_import_from_data_string(self):
        data = '[{"phone":"+36201111111","name":"User1","status":"A","role":"user","info":""}]'
        result = self.um.import_users(data=data)
        self.assertIn('Imported 1', result)
        self.assertEqual(self.um.count_users(), 1)
        self.assertEqual(self.um.get_user(phone="+36201111111")[0]["name"], "User1")

    def test_import_replace_clears_existing(self):
        self.um.add_user("+36201111111", "Old")
        data = '[{"phone":"+36202222222","name":"New","status":"A","role":"user","info":""}]'
        self.um.import_users(data=data, mode='replace')
        self.assertEqual(self.um.count_users(), 1)
        self.assertIsNone(self.um.get_user(phone="+36201111111"))
        self.assertIsNotNone(self.um.get_user(phone="+36202222222"))

    def test_import_merge_keeps_existing(self):
        self.um.add_user("+36201111111", "Existing")
        data = '[{"phone":"+36202222222","name":"New","status":"A","role":"user","info":""}]'
        self.um.import_users(data=data, mode='merge')
        self.assertEqual(self.um.count_users(), 2)
        self.assertIsNotNone(self.um.get_user(phone="+36201111111"))
        self.assertIsNotNone(self.um.get_user(phone="+36202222222"))

    def test_import_merge_updates_existing(self):
        self.um.add_user("+36201111111", "Old Name", status="A")
        data = '[{"phone":"+36201111111","name":"New Name","status":"B"}]'
        self.um.import_users(data=data, mode='merge')
        self.assertEqual(self.um.count_users(), 1)
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertEqual(user["name"], "New Name")
        self.assertEqual(user["status"], "B")

    def test_import_normalizes_phones(self):
        data = '[{"phone":"06201234567","name":"User1","status":"A","role":"user","info":""}]'
        self.um.import_users(data=data)
        self.assertIsNotNone(self.um.get_user(phone="+36201234567"))

    def test_import_invalid_json(self):
        result = self.um.import_users(data='not json{{')
        self.assertIn('invalid JSON', result)

    def test_import_not_a_list(self):
        result = self.um.import_users(data='{"phone":"+36201111111"}')
        self.assertIn('expected a list', result)

    def test_import_no_params(self):
        result = self.um.import_users()
        self.assertIn('provide data or file', result)

    def test_import_nonexistent_file(self):
        result = self.um.import_users(file='nonexistent.json')
        self.assertIn('Import failed', result)

    def test_export_error_bad_path(self):
        result = self.um.export_users('/nonexistent_dir/backup.json')
        self.assertIn('Export failed', result)

    # --- field validation ---

    def test_add_invalid_status(self):
        result = self.um.add_user("+36201111111", "User1", status="X")
        self.assertIn("Invalid status", result)
        self.assertEqual(self.um.count_users(), 0)

    def test_add_invalid_role(self):
        result = self.um.add_user("+36201111111", "User1", role="superadmin")
        self.assertIn("Invalid role", result)
        self.assertEqual(self.um.count_users(), 0)

    def test_add_valid_status_B(self):
        result = self.um.add_user("+36201111111", "User1", status="B")
        self.assertIn("successfully", result)

    def test_modify_invalid_status(self):
        self.um.add_user("+36201111111", "User1", status="A")
        result = self.um.modify_user("+36201111111", status="X")
        self.assertIn("Invalid status", result)
        self.assertEqual(self.um.get_user(phone="+36201111111")[0]["status"], "A")

    def test_modify_invalid_role(self):
        self.um.add_user("+36201111111", "User1", role="user")
        result = self.um.modify_user("+36201111111", role="root")
        self.assertIn("Invalid role", result)
        self.assertEqual(self.um.get_user(phone="+36201111111")[0]["role"], "user")

    def test_modify_valid_role_to_admin(self):
        self.um.add_user("+36201111111", "User1", role="user")
        result = self.um.modify_user("+36201111111", role="admin")
        self.assertIn("successfully", result)
        self.assertEqual(self.um.get_user(phone="+36201111111")[0]["role"], "admin")

    # --- access control (valid_from + expires) ---

    def test_add_user_with_expires(self):
        result = self.um.add_user("+36201111111", "Temp", expires="2099-12-31T23:59")
        self.assertIn("successfully", result)
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertGreater(user['expires'], 0)
        self.assertEqual(user['valid_from'], 0)

    def test_add_user_with_valid_from(self):
        result = self.um.add_user("+36201111111", "Future", valid_from="2099-01-01T00:00")
        self.assertIn("successfully", result)
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertGreater(user['valid_from'], 0)
        self.assertEqual(user['expires'], 0)

    def test_add_user_with_time_window(self):
        result = self.um.add_user("+36201111111", "Window", valid_from="2020-01-01T00:00", expires="2099-12-31T23:59")
        self.assertIn("successfully", result)
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertGreater(user['valid_from'], 0)
        self.assertGreater(user['expires'], 0)

    def test_add_user_no_time_constraints(self):
        self.um.add_user("+36201111111", "Perm")
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertEqual(user['expires'], 0)
        self.assertEqual(user['valid_from'], 0)

    def test_add_user_invalid_expires(self):
        result = self.um.add_user("+36201111111", "Bad", expires="not-a-date")
        self.assertIn("Invalid expires", result)
        self.assertEqual(self.um.count_users(), 0)

    def test_add_user_invalid_valid_from(self):
        result = self.um.add_user("+36201111111", "Bad", valid_from="not-a-date")
        self.assertIn("Invalid valid_from", result)
        self.assertEqual(self.um.count_users(), 0)

    # --- check_access: expires ---

    def test_check_access_not_expired(self):
        self.um.add_user("+36201111111", "Future", expires="2099-12-31T23:59")
        self.assertFalse(self.um.check_access("+36201111111"))
        self.assertEqual(self.um.get_user(phone="+36201111111")[0]['status'], 'A')

    def test_check_access_expired(self):
        self.um.add_user("+36201111111", "Past", expires="2020-01-01T00:00")
        self.assertTrue(self.um.check_access("+36201111111"))
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertEqual(user['status'], 'B')
        self.assertIn('inactive', user['info'])

    def test_check_access_boundary_just_expired(self):
        self.um.add_user("+36201111111", "JustPast")
        self.um._phone_index["+36201111111"]['expires'] = int(time.time()) - 1
        self.assertTrue(self.um.check_access("+36201111111"))

    def test_check_access_boundary_just_future(self):
        self.um.add_user("+36201111111", "JustFuture")
        self.um._phone_index["+36201111111"]['expires'] = int(time.time()) + 10
        self.assertFalse(self.um.check_access("+36201111111"))
        self.assertEqual(self.um.get_user(phone="+36201111111")[0]['status'], 'A')

    def test_check_access_boundary_exactly_now(self):
        self.um.add_user("+36201111111", "ExactNow")
        self.um._phone_index["+36201111111"]['expires'] = int(time.time())
        self.assertTrue(self.um.check_access("+36201111111"))

    # --- check_access: valid_from ---

    def test_check_access_not_yet_active(self):
        self.um.add_user("+36201111111", "Future", valid_from="2099-01-01T00:00")
        self.assertTrue(self.um.check_access("+36201111111"))
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertEqual(user['status'], 'B')
        self.assertIn('inactive', user['info'])

    def test_check_access_already_active(self):
        self.um.add_user("+36201111111", "Past", valid_from="2020-01-01T00:00")
        self.assertFalse(self.um.check_access("+36201111111"))
        self.assertEqual(self.um.get_user(phone="+36201111111")[0]['status'], 'A')

    def test_check_access_valid_from_boundary_just_past(self):
        self.um.add_user("+36201111111", "JustPast")
        self.um._phone_index["+36201111111"]['valid_from'] = int(time.time()) - 1
        self.assertFalse(self.um.check_access("+36201111111"))

    def test_check_access_valid_from_boundary_just_future(self):
        self.um.add_user("+36201111111", "JustFuture")
        self.um._phone_index["+36201111111"]['valid_from'] = int(time.time()) + 10
        self.assertTrue(self.um.check_access("+36201111111"))

    # --- check_access: time window ---

    def test_check_access_inside_window(self):
        self.um.add_user("+36201111111", "InWindow", valid_from="2020-01-01T00:00", expires="2099-12-31T23:59")
        self.assertFalse(self.um.check_access("+36201111111"))

    def test_check_access_before_window(self):
        self.um.add_user("+36201111111", "BeforeWindow", valid_from="2099-01-01T00:00", expires="2099-12-31T23:59")
        self.assertTrue(self.um.check_access("+36201111111"))

    def test_check_access_after_window(self):
        self.um.add_user("+36201111111", "AfterWindow", valid_from="2020-01-01T00:00", expires="2020-12-31T23:59")
        self.assertTrue(self.um.check_access("+36201111111"))

    # --- check_access: edge cases ---

    def test_check_access_no_constraints(self):
        self.um.add_user("+36201111111", "Perm")
        self.assertFalse(self.um.check_access("+36201111111"))

    def test_check_access_unknown_phone(self):
        self.assertFalse(self.um.check_access("+36200000000"))

    def test_check_access_preserves_existing_info(self):
        self.um.add_user("+36201111111", "Past", info="APG20", expires="2020-01-01T00:00")
        self.um.check_access("+36201111111")
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertIn('inactive', user['info'])
        self.assertIn('APG20', user['info'])

    def test_check_access_no_double_inactive_tag(self):
        self.um.add_user("+36201111111", "Past", expires="2020-01-01T00:00")
        self.um.check_access("+36201111111")
        self.um.check_access("+36201111111")
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertEqual(user['info'].count('inactive'), 1)

    # --- grant_access ---

    def test_grant_access_with_window(self):
        self.um.add_user("+36201111111", "User1", status="B", info="inactive")
        result = self.um.grant_access("+36201111111", valid_from="2020-01-01T00:00", expires="2099-12-31T23:59")
        self.assertIn("Access granted", result)
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertEqual(user['status'], 'A')
        self.assertGreater(user['valid_from'], 0)
        self.assertGreater(user['expires'], 0)
        self.assertNotIn('inactive', user['info'])

    def test_grant_access_only_expires(self):
        self.um.add_user("+36201111111", "User1", status="B", info="inactive", expires="2020-01-01T00:00")
        result = self.um.grant_access("+36201111111", expires="2099-12-31T23:59")
        self.assertIn("Access granted", result)
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertEqual(user['valid_from'], 0)
        self.assertGreater(user['expires'], 0)

    def test_grant_access_only_valid_from(self):
        self.um.add_user("+36201111111", "User1", status="B", info="inactive")
        result = self.um.grant_access("+36201111111", valid_from="2020-01-01T00:00")
        self.assertIn("Access granted", result)
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertGreater(user['valid_from'], 0)
        self.assertEqual(user['expires'], 0)

    def test_grant_access_permanent(self):
        self.um.add_user("+36201111111", "User1", expires="2020-01-01T00:00")
        self.um.grant_access("+36201111111")
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertEqual(user['expires'], 0)
        self.assertEqual(user['valid_from'], 0)
        self.assertEqual(user['status'], 'A')

    def test_grant_access_not_found(self):
        result = self.um.grant_access("+36200000000", expires="2099-12-31T23:59")
        self.assertIn("not found", result)

    def test_grant_access_invalid_expires(self):
        self.um.add_user("+36201111111", "User1")
        result = self.um.grant_access("+36201111111", expires="bad-format")
        self.assertIn("Invalid expires", result)

    def test_grant_access_invalid_valid_from(self):
        self.um.add_user("+36201111111", "User1")
        result = self.um.grant_access("+36201111111", valid_from="bad-format")
        self.assertIn("Invalid valid_from", result)

    def test_grant_access_cleans_inactive_from_info(self):
        self.um.add_user("+36201111111", "User1", info="inactive APG20", expires="2020-01-01T00:00")
        self.um.grant_access("+36201111111", expires="2099-12-31T23:59")
        user = self.um.get_user(phone="+36201111111")[0]
        self.assertEqual(user['info'], 'APG20')

    # --- get_inactive_users ---

    def test_get_inactive_users_empty(self):
        self.um.add_user("+36201111111", "Perm")
        self.assertEqual(self.um.get_inactive_users(), [])

    def test_get_inactive_users_finds_expired(self):
        self.um.add_user("+36201111111", "Past", expires="2020-01-01T00:00")
        self.um.add_user("+36202222222", "Future", expires="2099-12-31T23:59")
        self.um.add_user("+36203333333", "Perm")
        result = self.um.get_inactive_users()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['phone'], '+36201111111')

    def test_get_inactive_users_finds_not_yet_active(self):
        self.um.add_user("+36201111111", "FutureStart", valid_from="2099-01-01T00:00")
        self.um.add_user("+36202222222", "Perm")
        result = self.um.get_inactive_users()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['phone'], '+36201111111')

    def test_get_inactive_users_finds_both(self):
        self.um.add_user("+36201111111", "Expired", expires="2020-01-01T00:00")
        self.um.add_user("+36202222222", "NotYet", valid_from="2099-01-01T00:00")
        self.um.add_user("+36203333333", "Active", valid_from="2020-01-01T00:00", expires="2099-12-31T23:59")
        result = self.um.get_inactive_users()
        self.assertEqual(len(result), 2)
        phones = [u['phone'] for u in result]
        self.assertIn('+36201111111', phones)
        self.assertIn('+36202222222', phones)

    def test_modify_phone_duplicate_rejected(self):
        self.um.add_user("+36201111111", "User1")
        self.um.add_user("+36202222222", "User2")
        result = self.um.modify_user("+36201111111", new_phone="+36202222222")
        self.assertIn("already exists", result)
        self.assertEqual(self.um.get_user(phone="+36201111111")[0]["name"], "User1")

    def test_modify_phone_duplicate_normalized(self):
        self.um.add_user("+36201111111", "User1")
        self.um.add_user("+36202222222", "User2")
        result = self.um.modify_user("+36201111111", new_phone="06202222222")
        self.assertIn("already exists", result)

    def test_modify_phone_to_new_number_ok(self):
        self.um.add_user("+36201111111", "User1")
        result = self.um.modify_user("+36201111111", new_phone="+36209999999")
        self.assertIn("successfully", result)
        self.assertIsNone(self.um.get_user(phone="+36201111111"))
        self.assertEqual(self.um.get_user(phone="+36209999999")[0]["name"], "User1")

    def test_modify_phone_same_number_ok(self):
        self.um.add_user("+36201111111", "User1")
        result = self.um.modify_user("+36201111111", new_phone="+36201111111")
        self.assertIn("successfully", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestMultiPhonebook(unittest.TestCase):
    """Test multiple phonebook instances."""

    def setUp(self):
        um_mod.UserManagement.INSTANCES = {}
        self.tmpdir = tempfile.mkdtemp()
        # Patch data_dir at module level (from Common import data_dir binds early)
        um_mod.data_dir = lambda f: os.path.join(self.tmpdir, f)

    def tearDown(self):
        um_mod.UserManagement.INSTANCES = {}
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_creates_named_instance(self):
        result = um_mod.load('home.json', book='home')
        self.assertIn('home', um_mod.UserManagement.INSTANCES)
        self.assertIn('started', result)

    def test_load_two_books(self):
        um_mod.load('home.json', book='home')
        um_mod.load('garage.json', book='garage')
        self.assertEqual(len(um_mod.UserManagement.INSTANCES), 2)

    def test_books_are_isolated(self):
        um_mod.load('home.json', book='home')
        um_mod.load('garage.json', book='garage')
        um_mod.add_user('+36201111111', 'Home User', book='home')
        um_mod.add_user('+36202222222', 'Garage User', book='garage')
        self.assertEqual(um_mod.count_users(book='home'), 1)
        self.assertEqual(um_mod.count_users(book='garage'), 1)
        self.assertIsNone(um_mod.get_user(phone='+36201111111', book='garage'))
        self.assertIsNone(um_mod.get_user(phone='+36202222222', book='home'))

    def test_default_book_backward_compatible(self):
        um_mod.load('users.json')
        um_mod.add_user('+36201111111', 'Default User')
        self.assertEqual(um_mod.count_users(), 1)

    def test_unload_book(self):
        um_mod.load('home.json', book='home')
        result = um_mod.unload(book='home')
        self.assertNotIn('home', um_mod.UserManagement.INSTANCES)
        self.assertIn('stopped', result)

    def test_unload_nonexistent(self):
        result = um_mod.unload(book='bogus')
        self.assertIn('not loaded', result)

    def test_list_books(self):
        um_mod.load('home.json', book='home')
        um_mod.load('garage.json', book='garage')
        books = um_mod.list_books()
        self.assertIn('home', books)
        self.assertIn('garage', books)

    def test_access_unloaded_book_raises(self):
        with self.assertRaises(RuntimeError):
            um_mod.get_all_users(book='nonexistent')

    def test_check_access_per_book(self):
        um_mod.load('home2.json', book='home')
        um_mod.load('garage2.json', book='garage')
        um_mod.add_user('+36201111111', 'Owner', role='admin', book='home')
        um_mod.add_user('+36201111111', 'Owner', role='admin', book='garage')
        um_mod.add_user('+36202222222', 'Cleaner', role='user', book='home')
        # Cleaner is in home but not in garage
        home_users = um_mod.get_user(phone='+36202222222', book='home')
        garage_users = um_mod.get_user(phone='+36202222222', book='garage')
        self.assertIsNotNone(home_users)
        self.assertIsNone(garage_users)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestDailyTimeWindow(unittest.TestCase):
    """Test daily_from/daily_to time window access control."""

    def setUp(self):
        um_mod.UserManagement.INSTANCES = {}
        self.tmpdir = tempfile.mkdtemp()
        um_mod.data_dir = lambda f: os.path.join(self.tmpdir, f)
        um_mod.load('daily_test.json', book='daily')

    def tearDown(self):
        um_mod.UserManagement.INSTANCES = {}
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_user_with_daily_window(self):
        result = um_mod.add_user('+36201111111', 'Worker', daily_from='08:00', daily_to='17:00', book='daily')
        self.assertIn('added', result)
        user = um_mod.get_user(phone='+36201111111', book='daily')[0]
        self.assertEqual(user['daily_from'], '08:00')
        self.assertEqual(user['daily_to'], '17:00')

    def test_add_user_invalid_daily_from(self):
        result = um_mod.add_user('+36201111111', 'Worker', daily_from='25:00', book='daily')
        self.assertIn('Invalid daily_from', result)

    def test_add_user_invalid_daily_to(self):
        result = um_mod.add_user('+36201111111', 'Worker', daily_to='abc', book='daily')
        self.assertIn('Invalid daily_to', result)

    @mock.patch('time.localtime')
    def test_access_within_window(self, mock_lt):
        # 10:30 — within 08:00-17:00
        mock_lt.return_value = (2025, 1, 15, 10, 30, 0, 0, 0, -1)
        um_mod.add_user('+36201111111', 'Worker', daily_from='08:00', daily_to='17:00', book='daily')
        denied = um_mod.check_access('+36201111111', book='daily')
        self.assertFalse(denied)

    @mock.patch('time.localtime')
    def test_access_before_window(self, mock_lt):
        # 07:00 — before 08:00
        mock_lt.return_value = (2025, 1, 15, 7, 0, 0, 0, 0, -1)
        um_mod.add_user('+36201111111', 'Worker', daily_from='08:00', daily_to='17:00', book='daily')
        denied = um_mod.check_access('+36201111111', book='daily')
        self.assertTrue(denied)

    @mock.patch('time.localtime')
    def test_access_after_window(self, mock_lt):
        # 18:00 — after 17:00
        mock_lt.return_value = (2025, 1, 15, 18, 0, 0, 0, 0, -1)
        um_mod.add_user('+36201111111', 'Worker', daily_from='08:00', daily_to='17:00', book='daily')
        denied = um_mod.check_access('+36201111111', book='daily')
        self.assertTrue(denied)

    @mock.patch('time.localtime')
    def test_access_at_exact_start(self, mock_lt):
        # 08:00 — exactly at start
        mock_lt.return_value = (2025, 1, 15, 8, 0, 0, 0, 0, -1)
        um_mod.add_user('+36201111111', 'Worker', daily_from='08:00', daily_to='17:00', book='daily')
        denied = um_mod.check_access('+36201111111', book='daily')
        self.assertFalse(denied)

    @mock.patch('time.localtime')
    def test_access_at_exact_end(self, mock_lt):
        # 17:00 — at end (exclusive)
        mock_lt.return_value = (2025, 1, 15, 17, 0, 0, 0, 0, -1)
        um_mod.add_user('+36201111111', 'Worker', daily_from='08:00', daily_to='17:00', book='daily')
        denied = um_mod.check_access('+36201111111', book='daily')
        self.assertTrue(denied)

    @mock.patch('time.localtime')
    def test_no_daily_restriction_always_ok(self, mock_lt):
        # No daily_from/daily_to — always accessible
        mock_lt.return_value = (2025, 1, 15, 3, 0, 0, 0, 0, -1)
        um_mod.add_user('+36201111111', 'Owner', book='daily')
        denied = um_mod.check_access('+36201111111', book='daily')
        self.assertFalse(denied)

    @mock.patch('time.localtime')
    def test_only_daily_from(self, mock_lt):
        # daily_from='08:00', no daily_to — accessible from 08:00 onwards
        mock_lt.return_value = (2025, 1, 15, 7, 59, 0, 0, 0, -1)
        um_mod.add_user('+36201111111', 'Worker', daily_from='08:00', book='daily')
        denied = um_mod.check_access('+36201111111', book='daily')
        self.assertTrue(denied)
        mock_lt.return_value = (2025, 1, 15, 22, 0, 0, 0, 0, -1)
        denied = um_mod.check_access('+36201111111', book='daily')
        self.assertFalse(denied)

    @mock.patch('time.localtime')
    def test_only_daily_to(self, mock_lt):
        # no daily_from, daily_to='17:00' — accessible until 17:00
        mock_lt.return_value = (2025, 1, 15, 5, 0, 0, 0, 0, -1)
        um_mod.add_user('+36201111111', 'Worker', daily_to='17:00', book='daily')
        denied = um_mod.check_access('+36201111111', book='daily')
        self.assertFalse(denied)
        mock_lt.return_value = (2025, 1, 15, 17, 0, 0, 0, 0, -1)
        denied = um_mod.check_access('+36201111111', book='daily')
        self.assertTrue(denied)

    def test_daily_window_persisted(self):
        um_mod.add_user('+36201111111', 'Worker', daily_from='09:00', daily_to='18:00', book='daily')
        # Reload
        um_mod.unload(book='daily')
        um_mod.load('daily_test.json', book='daily')
        user = um_mod.get_user(phone='+36201111111', book='daily')[0]
        self.assertEqual(user['daily_from'], '09:00')
        self.assertEqual(user['daily_to'], '18:00')
