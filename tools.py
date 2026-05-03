#!/usr/bin/env python3

import argparse
import sys
import subprocess
from _tools import validate, serve_packages, create_package, unpack, ut_executor


def check_githooks():
    try:
        r = subprocess.run(
            ["git", "config", "--local", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return  # git not available, silently ignore
    if r.stdout.strip() != ".githooks":
        print("⚠️  Git hooks are not enabled for this repo.")
        print("👉 Hint: git config core.hooksPath .githooks")


def build_parser():
    parser = argparse.ArgumentParser(
        description="CLI tool supporting validate, serve, and create options."
    )

    # VALIDATE: optional package name
    parser.add_argument(
        "-v", "--validate",
        nargs="?",
        const="__ALL__",   # Special marker meaning user passed -v without a value
        help="✅ Validate a package by name. If no name is provided, validate all packages."
    )

    # SERVE: simple flag
    parser.add_argument(
        "-s", "--serve",
        action="store_true",
        help="🌐 Start a local mip package registry (server)"
    )

    # CREATE: enabling creation mode
    parser.add_argument(
        "-c", "--create",
        action="store_true",
        help="📦 Create micrOS application package"
    )
    # Additional params for CREATE
    parser.add_argument("--package", help="[Package] Name of the package/application")
    parser.add_argument("--module", help="[LM] Public command name")

    # UPDATE: package.json urls
    parser.add_argument(
        "-u", "--update",
        help="✅ Update application package.json and pacman.json by package name"
    )

    parser.add_argument(
        "-ut", "--unit-test",
        nargs="?",
        const="__ALL__",
        help="🧪 Run unit tests for one package, or all package tests if no name is provided"
    )

    # SERVE: simple flag
    parser.add_argument(
        "--unpack",
        action="store_true",
        help="🌐 Unpack all packages for testing"
    )

    # Clean cache
    parser.add_argument(
        "-cl", "--clean",
        action="store_true",
        help="🗄️ Clean package cache (3PPs) and default unpacked folder if exists"
    )

    # Clean cache
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="🤐 Minimize printouts when possible (validation, unit tests)"
    )

    return parser


if __name__ == "__main__":
    check_githooks()

    parser = build_parser()
    args = parser.parse_args()
    quiet = args.quiet

    # --- SERVE LOGIC ---
    if args.serve:
        print("Starting server...")
        serve_packages.main()

    # --- UPDATE LOGIC ---
    if args.update is not None:
        package_name = args.update
        package_path = create_package.REPO_ROOT / package_name / "package"
        print(f"Updating package.json for {package_name}")
        create_package.update_package_json(package_path, package_name)
        create_package.update_pacman_json(package_path, package_name)

    # --- UNIT TEST LOGIC ---
    if args.unit_test is not None:
        if args.unit_test == "__ALL__":
            print("Running unit tests for ALL packages...")
            is_ok = ut_executor.run_all_unit_tests(quiet=quiet)
        else:
            is_ok = ut_executor.run_unit_tests(args.unit_test, quiet=quiet)
        if not is_ok:
            sys.exit(1)

    # --- CREATE LOGIC ---
    if args.create:
        print("Creating micrOS Application Package...")
        if args.package is None:
            args.package = input("Package name: ")
        if args.module is None:
            args.module = input("Command (load module) name: ")
        print(f"  package name: {args.package}")
        print(f"  command: {args.module}")
        create_package.create_package(package=args.package, module=args.module)
        print(f"Shell example: pacman install ...")
        print(f"Shell example, execution:\n\t{args.module} load\n\t{args.module} do")

    # --- UNPACK LOGIC (testing) ---
    if args.unpack:
        unpack.unpack_all()

    # --- CACHE CLEAN LOGIC ---
    if args.clean:
        unpack.clean_cache()

    # --- VALIDATE LOGIC - LAST BECAUSE SYS EXIT CODE ---
    if args.validate is not None:
        if args.validate == "__ALL__":
            print("Validating ALL packages...")
            is_valid = validate.main(verbose=not quiet)
        else:
            print(f"Validating package: {args.validate}")
            is_valid = validate.main(pack_name=args.validate, verbose=not quiet)
        if not is_valid:
            sys.exit(1)
