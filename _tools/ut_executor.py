#!/usr/bin/env python3

import os
import subprocess
import sys

try:
    from .create_package import REPO_ROOT
    from .validate import resolve_packages
except ImportError:
    from create_package import REPO_ROOT
    from validate import resolve_packages


def _pytest_command(tests_path, verbose=True):
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(tests_path),
        "-o",
        "cache_dir=/tmp/pytest-cache",
    ]
    cmd.append("-v" if verbose else "-q")
    return cmd


def _pytest_summary(output):
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return "no pytest summary available"
    summary = lines[-1]
    if summary.startswith("=") and summary.endswith("="):
        summary = summary.strip("= ").strip()
    return summary


def _resolve_tests_path(package_name, announce_skip=True):
    package_path = REPO_ROOT / package_name
    if not package_path.is_dir():
        print(f"❌ Package not found: {package_name}")
        return False, None

    tests_path = package_path / "tests"
    if not tests_path.is_dir():
        if announce_skip:
            print(f"ℹ️ No tests directory found for {package_name}: {tests_path}")
        return True, None

    test_files = sorted(
        path for path in tests_path.iterdir()
        if path.is_file() and path.name.startswith("test")
    )
    if not test_files:
        if announce_skip:
            print(f"ℹ️ No test files found in: {tests_path}")
        return True, None

    return True, tests_path


def _execute_pytest(package_name, tests_path, quiet=False, show_command=True):
    cmd = _pytest_command(tests_path, verbose=not quiet)
    if quiet:
        result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
        summary = _pytest_summary(f"{result.stdout}\n{result.stderr}")
        print(f"unit-test {package_name}: {summary}", flush=True)
        return result.returncode == 0

    print(f"Running unit tests for {package_name}: {tests_path}", flush=True)
    if show_command:
        print(f"Command: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    return result.returncode == 0


def run_unit_tests(package_name, quiet=False, announce_skip=True, show_command=True):
    ok, tests_path = _resolve_tests_path(package_name, announce_skip=announce_skip)
    if not ok or tests_path is None:
        return ok
    return _execute_pytest(package_name, tests_path, quiet=quiet, show_command=show_command)


def run_all_unit_tests(quiet=False, show_command=True):
    packages = resolve_packages()
    if not packages:
        print("⚠️ No packages found (no subfolders containing package.json).")
        return False

    tests_found = False
    all_ok = True

    for pkg in packages:
        package_name = os.path.basename(pkg)
        ok, tests_path = _resolve_tests_path(package_name, announce_skip=False)
        if not ok:
            all_ok = False
            continue
        if tests_path is None:
            continue
        tests_found = True
        if not _execute_pytest(package_name, tests_path, quiet=quiet, show_command=show_command):
            all_ok = False

    if not tests_found:
        print("ℹ️ No package tests found.")
    return all_ok
