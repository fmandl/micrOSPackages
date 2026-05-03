#!/usr/bin/env python3
import os
import json
import sys
from pathlib import Path

ROOT = os.path.abspath(os.path.dirname(__file__))

try:
    from .create_package import GITHUB_BASE
except ImportError:
    from create_package import GITHUB_BASE

VERBOSE = True

def verbose_print(text):
    if VERBOSE:
        print(text)


def _check_package_json(path):
    """Check if a package"""
    pkg_file = os.path.join(path, "package.json")
    if os.path.isfile(pkg_file):
        return True
    return False


def find_all_packages(source_path):
    """Find subdirectories containing a package.json."""
    packages = []

    current_dir_name = os.path.basename(ROOT)

    # List directories in the parent dir, excluding the current dir
    root_folders = [
        f for f in os.listdir(source_path)
        if f != current_dir_name and os.path.isdir(os.path.join(source_path, f))
    ]

    for entry in root_folders:
        full = os.path.join(source_path, entry)  # use parent, not root
        if _check_package_json(full):
            packages.append(full)

    return sorted(packages)


def resolve_packages(pack_name: str = None):
    """Resolve one package or all packages to absolute package directories."""
    source_path = os.path.dirname(ROOT)
    if pack_name is None:
        return find_all_packages(source_path)

    package = os.path.join(source_path, pack_name)
    if _check_package_json(package):
        return [package]
    return []
def is_http_remote(src: str) -> bool:
    if not isinstance(src, str):
        return False
    return src.startswith("http://") or src.startswith("https://")


def resolve_repo_local_github_path(src: str, pkg_name: str, pkg_path: str):
    """
    Try to resolve a github:BxNxM/micrOSPackages/... path to a local file.

    Examples:
      src = github:BxNxM/micrOSPackages/blinky_example/package/__init__.py

    We try:
      1) ROOT / (rest after GITHUB_BASE)
         -> ROOT/blinky_example/package/__init__.py
      2) If that doesn't exist and first path segment == pkg_name:
         pkg_path / (rest after '<pkg_name>/')
         -> <pkg_path>/package/__init__.py
    """
    if not isinstance(src, str) or not src.startswith(GITHUB_BASE):
        return None

    rel = src[len(GITHUB_BASE)+1:]  # blinky_example/package/__init__.py
    # First attempt: relative to repo root
    candidate_root = os.path.join(ROOT, rel)
    if os.path.exists(candidate_root):
        return candidate_root

    # Second attempt: strip leading "<pkg_name>/" and resolve inside pkg_path
    parts = rel.split("/", 1)
    if len(parts) == 2 and parts[0] == pkg_name:
        candidate_pkg = os.path.join(pkg_path, parts[1])
        if os.path.exists(candidate_pkg):
            return candidate_pkg

    # If neither exists, still return the ROOT-based candidate for debug
    return candidate_root


def validate_dest_path(dest: str) -> bool:
    """Basic sanity check for destination path (no '..')."""
    if not isinstance(dest, str):
        return False
    if ".." in dest.split("/"):
        return False
    return True


def validate_package_json(pkg_path):
    """
    Validate package.json and file references
    """
    pkg_json = os.path.join(pkg_path, "package.json")
    pkg_name = os.path.basename(pkg_path)

    print(f"{'\n' if VERBOSE else ''}📦 {pkg_name}")

    try:
        with open(pkg_json, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ❌ Error reading package.json: {e}")
        return False

    urls = data.get("urls")
    if not isinstance(urls, list):
        print("  ❌ 'urls' missing or invalid")
        return False

    all_ok = True

    package_lm_exists = False
    package_pacman_json_exists = False
    for entry in urls:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            print(f"  ❌ Invalid urls entry (expected [dest, src]): {entry}")
            all_ok = False
            continue

        dest, src = entry
        # Optional resource check
        if dest.endswith("pacman.json"):
            package_pacman_json_exists = True
        if dest.split("/")[-1].startswith("LM_"):
            package_lm_exists = True

        if not validate_dest_path(dest):
            print(f"  ❌ {src}  ➜  {dest}   (invalid dest path: contains '..')")
            all_ok = False
            continue

        # 1) Our own repo's github: paths
        repo_local_path = resolve_repo_local_github_path(src, pkg_name, pkg_path)
        if isinstance(src, str) and src.startswith(GITHUB_BASE):
            exists = os.path.exists(repo_local_path)
            status = "✅" if exists else "❌"
            if not exists:
                all_ok = False
            rel_local = os.path.relpath(repo_local_path, ROOT).replace("../", "./")
            verbose_print(f"  {status} {src}  ➜  {dest}   (local: {rel_local})")
            continue

        # 2) Plain local paths (relative to package folder)
        if not is_http_remote(src) and not (isinstance(src, str) and src.startswith("github:")):
            src_path = os.path.join(pkg_path, src)
            exists = os.path.exists(src_path)
            status = "✅" if exists else "❌"
            if not exists:
                all_ok = False
            verbose_print(f"  {status} {src}  ➜  {dest}")
            continue

        # 3) Other remotes: different GitHub repo or http(s)
        verbose_print(f"  🌐 {src}  ➜  {dest}   (remote, not checked)")

    verbose_print(f"{'✅ Load Module exists' if package_lm_exists else '⚠️ Load Module missing'}")
    verbose_print(f"{'✅ Packaging metadata exists (pacman.json)' if package_pacman_json_exists else '⚠️  Packaging metadata missing (pacman.json)'}")
    return all_ok


def validate_package(pkg_path):
    """
    Validate /package folder content against package.json
    - Ensure all files present
    - TODO: check files by name
    """
    if not isinstance(pkg_path, Path):
        pkg_path = Path(pkg_path)

    pkg_json = pkg_path / "package.json"
    pkg_content_path = pkg_path / "package"
    package_folder_files = [p for p in pkg_content_path.iterdir() if p.is_file()]
    folder_files_len = len(package_folder_files)

    try:
        with  open(pkg_json, 'r') as f:
            pkg_json_urls = json.load(f).get("urls", [])
        pkg_json_urls_len = len(pkg_json_urls)
    except Exception as e:
        print(f"❌ Cannot load {str(pkg_json)}: {e}")
        pkg_json_urls_len = 0

    # Check package.json and packages are matching
    if folder_files_len == pkg_json_urls_len:
        return True
    print(f"❌ File missmatch in {pkg_path.name}/package.json vs. {pkg_path.name}/package")
    return False


def main(pack_name:str=None, verbose:bool=True):
    global VERBOSE
    VERBOSE = verbose

    packages = resolve_packages(pack_name)

    if not packages:
        print("⚠️ No packages found (no subfolders containing package.json).")
        return False

    verbose_print(f"🔍 Found {len(packages)} package(s).")

    validation_ok = True
    for pkg in packages:
        package_ok = True
        if not validate_package_json(pkg):
            package_ok = False
        if not validate_package(pkg):
            package_ok = False
        validation_ok &= package_ok
        if package_ok:
            verbose_print("  ✔️ VALID\n")
        else:
            print("  ✖️ INVALID\n")

    if validation_ok:
        print("🎉 All packages are valid!")
    else:
        print("❗ Some packages failed validation.\n\tFix: ./tools.py --update <package-name>")
        if not VERBOSE:
            print("\tFor more details, run: ./tools.py --validate")
    return validation_ok


if __name__ == "__main__":
    sys.exit(main())
