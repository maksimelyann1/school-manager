import os
import shutil
import sys


APP_DIR_NAME = "SchoolManager"
DATA_DIR_NAMES = ("template_files", "auto_message_files", "import_cache", "sticker_cache")


def get_app_data_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return os.path.join(base, APP_DIR_NAME)
    if sys.platform == "darwin":
        return os.path.join(
            os.path.expanduser("~"),
            "Library",
            "Application Support",
            APP_DIR_NAME,
        )
    return os.path.join(os.path.expanduser("~"), ".school_manager")


def get_runtime_data_dir() -> str:
    if getattr(sys, "frozen", False):
        return get_app_data_dir()
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_legacy_install_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_runtime_data_dir() -> str:
    data_dir = get_runtime_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def _copy_missing_tree(source_dir: str, target_dir: str):
    for root, dirs, files in os.walk(source_dir):
        rel_root = os.path.relpath(root, source_dir)
        target_root = target_dir if rel_root == "." else os.path.join(target_dir, rel_root)
        os.makedirs(target_root, exist_ok=True)

        for directory in dirs:
            os.makedirs(os.path.join(target_root, directory), exist_ok=True)

        for filename in files:
            source = os.path.join(root, filename)
            target = os.path.join(target_root, filename)
            if not os.path.exists(target):
                shutil.copy2(source, target)


def migrate_legacy_runtime_data():
    if not getattr(sys, "frozen", False):
        return

    target_dir = ensure_runtime_data_dir()
    legacy_dir = get_legacy_install_dir()
    if os.path.abspath(target_dir) == os.path.abspath(legacy_dir):
        return

    try:
        for suffix in ("", "-wal", "-shm"):
            source = os.path.join(legacy_dir, f"school_manager.db{suffix}")
            target = os.path.join(target_dir, f"school_manager.db{suffix}")
            if os.path.exists(source) and not os.path.exists(target):
                shutil.copy2(source, target)

        for dirname in DATA_DIR_NAMES:
            source_dir = os.path.join(legacy_dir, dirname)
            target_subdir = os.path.join(target_dir, dirname)
            if os.path.isdir(source_dir):
                _copy_missing_tree(source_dir, target_subdir)
    except Exception:
        pass
