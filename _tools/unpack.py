#!/usr/bin/env python3
import os.path
import json
from pathlib import Path
import shutil
REPO_ROOT  = Path(__file__).resolve().parent.parent
CACHE_DIR_PATH  = Path(__file__).resolve().parent / "cache"
DEFAULT_UNPACKED_DIR = REPO_ROOT / "unpacked"

try:
    from .validate import find_all_packages, GITHUB_BASE
except ImportError:
    print("Import error: validate")
    from validate import find_all_packages, GITHUB_BASE
try:
    from .mip import install as mip_install
except ImportError:
    print("Import error: mip")
    from mip import install as mip_install


def parse_package_json(package_json_path:Path):
    """
    "urls": [
    [
        "async_oledui/uiframes.py",
        "github:BxNxM/micrOSPackages/async_oledui/package/uiframes.py"
    ], ...]
    Return version, urls and deps
    """
    print(f"[Unpack] package.json {package_json_path}")
    content = {"version": "n/a", "urls": [], "deps": []}
    with open(package_json_path, 'r') as f:
        content = json.load(f)
    return content.get("version", "0.0.0"), content.get("urls", []), content.get("deps", [])


def resolve_urls_with_local_path(files_list:list, target_dir_lib:Path) -> list:
    """
    Replace GitHub URLs with local paths
    """
    copy_struct = []
    for file in files_list:
        target = file[0]
        source = file[1]
        mod_source = source.replace(GITHUB_BASE.rstrip("/"), str(REPO_ROOT))
        mod_target = str(target_dir_lib / target)
        copy_struct.append([mod_target, mod_source])
    return copy_struct


def copy_package_resources(local_packages):

    for package_source in local_packages:
        source_path = package_source[1]
        target_path = package_source[0]
        print(f"COPY {source_path} to {target_path}")
        try:
            shutil.copy(source_path, target_path)
        except Exception as e:
            print(f"Error copying {source_path} to {target_path}: {e}")


def post_install(lib_path:Path, package_name:str) -> tuple[list, list]:
    """
    MICROS ON-DEVICE SIDE - post install simulation + load module name collection (ext package mapping)
    returns: overwritten_files, load_modules_list
    """
    pacman_json_path = lib_path / package_name / "pacman.json"
    overwrites = []
    ext_load_modules = []
    if pacman_json_path.is_file():
        # NEW pacman.json['layout'] based package management (unpack, etc...)
        print("[Unpack] micrOS on device LM unpack from pacman.json")
        package_layout = {}
        with open(pacman_json_path, 'r') as f:
            package_layout = json.load(f).get("layout", {})

        for target, sources in package_layout.items():
            for s in sources:
                source_abs_path = lib_path / s
                target_abs_path = lib_path.parent / target.lstrip("/") / Path(s).name
                print(f"[Unpack] Move {source_abs_path} -> {target_abs_path}")
                if not target_abs_path.parent.is_dir():
                    print(f"[Unpack] Create subdir: {str(target_abs_path.parent)}")
                    target_abs_path.parent.mkdir()
                if target_abs_path.is_file():
                    overwrites.append(str(target_abs_path).replace(str(lib_path.parent), ""))
                shutil.move(source_abs_path, target_abs_path)
                if s.startswith("LM_"):
                    ext_load_modules.append(s)
    return overwrites, ext_load_modules


# --- the caching decorator (one main folder per ref@version) ---
def cache_dep(func):

    def _copy_delta(delta_paths: set[Path], src_root: Path, cache_pkg: Path) -> None:
        """
        Copy new/changed items listed in delta_paths into cache_pkg, preserving
        paths relative to src_root. Creates missing dirs as needed.

        delta_paths: absolute Paths (files/dirs) under src_root
        src_root: the root to compute relative paths from (e.g. .../unpacked/lib)
        cache_pkg: destination root
        """
        src_root = Path(src_root).resolve()
        cache_pkg = Path(cache_pkg).resolve()

        # Work only with items that still exist and are under src_root
        items = []
        for p in delta_paths:
            p = Path(p)
            if not p.exists():
                continue
            try:
                p.relative_to(src_root)
            except ValueError:
                continue
            items.append(p)

        # Ensure directories are created before files (important)
        items.sort(key=lambda p: (p.is_file(), str(p)))

        for src in items:
            rel = src.relative_to(src_root)
            dst = cache_pkg / rel

            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    def wrapper(ref:str, version:str, target_path:Path):
        target_str = str(target_path)
        cache_root = CACHE_DIR_PATH / "deps"
        cache_pkg = cache_root / f"{ref}@{version}"

        print(f"🗄️ [CACHE] Deps path: {str(cache_pkg)}")
        if cache_pkg.is_dir():
            print("[CACHE] RESTORE ... skip mip install")
            try:
                _copy_delta({p.resolve() for p in cache_pkg.rglob("*")}, cache_pkg, target_path)
                return None
            except Exception as e:
                print(f"\t❌ Restore failed: {e}")

        # Install and cache 3PP from the internet
        print(f"\tCreate cache dir: {'/'.join(str(cache_pkg).split('/')[-2:])}")
        os.makedirs(cache_pkg, exist_ok=True)
        before_snapshot = {p.resolve() for p in target_path.rglob("*")}
        # Run decorated function
        result = func(ref, version, target_str)
        after_snapshot = {p.resolve() for p in target_path.rglob("*")}
        new_contents = after_snapshot - before_snapshot
        print("[CACHE] BACKUP ... cache mip install content")
        try:
            _copy_delta(new_contents, target_path, cache_pkg)
        except Exception as e:
            print(f"\t❌ Backup failed: {e}")
        return result

    return wrapper

def clean_cache():
    if DEFAULT_UNPACKED_DIR.exists():
        print(f"🗑️  Clean default unpacked dir: {str(DEFAULT_UNPACKED_DIR)}")
        shutil.rmtree(DEFAULT_UNPACKED_DIR)
    if CACHE_DIR_PATH.exists():
        print(f"🗑️  Clean cache dir: {str(CACHE_DIR_PATH)}")
        shutil.rmtree(CACHE_DIR_PATH)
        return
    print(f"Cache dir not exists: {str(CACHE_DIR_PATH)}")

# --- the decorated single-dependency installer ---
@cache_dep
def _install_dep(ref:str, version:str, target_path:Path):
    if isinstance(target_path, Path):
        # Make sure target_path is mip compatible (str)
        target_path = str(target_path)
    print(f"[DEP] Install: {ref} @{version} ({target_path})")
    mip_install(ref, target=target_path)


def download_deps(deps:list, target_path:Path):
    """
    micrOS.Simulator -> mip.py copy usage - download 3pps (with 3PP caching)
    """
    print(f"INSTALL 3PPs FROM DEPS: {deps}\n\tTARGET: {str(target_path)}")
    for dep in deps:
        if not isinstance(dep, list):
            raise Exception(f"Invalid deps structure: {dep} must be list, structure must be [[],[],...]")
        ref = dep[0]
        version = dep[1] if len(dep) > 1 else "latest"

        # Only this part is now "decorated logic":
        _install_dep(ref, version, target_path)


def unpack_package(package_path:Path, target_path:Path) -> tuple[list, list]:
    """
    1. Create target_path folder
    2. Parse package.json from package_path/package.json
    3. Copy files from package_path/package/* to target_path based on package.json urls
    """
    print(f"📦 [UNPACK] {package_path.name}")
    source_package_json_path = package_path / "package.json"

    # Build target dir structure - ensure prerequisites
    target_dir_root = target_path
    target_dir_lib = target_dir_root / "lib"
    target_dir_lib_package = target_dir_lib / package_path.name
    target_dir_web = target_dir_root / "web"
    target_dir_data = target_dir_root / "data"
    target_dir_modules = target_dir_root / "modules"
    if not target_dir_root.is_dir():
        print(f"[Unpack] Create dir: {target_dir_root}")
        target_dir_root.mkdir(exist_ok=True)
    if not target_dir_lib.is_dir():
        print(f"[Unpack] Create dir: {target_dir_lib}")
        target_dir_lib.mkdir(exist_ok=True)
    if not target_dir_modules.is_dir():
        print(f"[Unpack] Create dir: {target_dir_modules}")
        target_dir_modules.mkdir(exist_ok=True)
    if not target_dir_web.is_dir():
        print(f"[Unpack] Create dir: {target_dir_web}")
        target_dir_web.mkdir(exist_ok=True)
    if not target_dir_data.is_dir():
        print(f"[Unpack] Create dir: {target_dir_data}")
        target_dir_data.mkdir(exist_ok=True)
    if not target_dir_lib_package.is_dir():
        print(f"[Unpack] Create dir: {target_dir_lib_package}")
        target_dir_lib_package.mkdir(exist_ok=True)

    # PACKAGE.JSON
    version, files, deps = parse_package_json(source_package_json_path)
    local_package_source = resolve_urls_with_local_path(files, target_dir_lib)
    copy_package_resources(local_package_source)
    # Download deps - 3pps
    try:
        download_deps(deps, target_dir_lib)
    except Exception as e:
        print(f"❌ 3PP DEP install failed: {e}")
    # PACMAN.JSON
    overwrites, load_modules = post_install(target_dir_lib, package_path.name)
    return overwrites, load_modules


def unpack_all(target:Path=None):
    """
    Find and unpack all packages to target folder
    :param target: target directory
    """
    if target is None:
        target = DEFAULT_UNPACKED_DIR
    print(f"UNPACK ALL PACKAGES FROM {REPO_ROOT}")
    all_overwrites = []
    all_lm_names = []
    for pkg in find_all_packages(REPO_ROOT):
        overwrites, load_modules = unpack_package(Path(pkg), target)
        all_overwrites += overwrites
        all_lm_names += load_modules
    print(f"[UNPACK] Overwritten from packages: {all_overwrites}")
    print(f"[UNPACK] Available Load Modules: {all_lm_names}")
    return all_overwrites, all_lm_names


if __name__ == "__main__":
    unpack_all()
