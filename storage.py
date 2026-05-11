# -*- coding: utf-8 -*-
import os
import shutil


MUTABLE_DIR_ENV_MAP = {
    "UPLOAD_FOLDER": "uploads",
    "TASK_FOLDER": "task_files",
    "LIB_FOLDER": "library_files",
    "BACKUP_FOLDER": "backups",
    "REPORT_TEMPLATE_FOLDER": "report_templates",
    "REPORT_EXPORT_FOLDER": "report_exports",
    "LOG_DIR": "logs",
    "TMP_FOLDER": "tmp",
}

_PLACEHOLDER_FILES = {".gitkeep", ".DS_Store"}


def _absolute_path(base_dir, value):
    if not value:
        return base_dir
    if os.path.isabs(value):
        return os.path.abspath(value)
    return os.path.abspath(os.path.join(base_dir, value))


def _running_under_passenger():
    return os.environ.get("PC06_PASSENGER") == "1" or any(
        os.environ.get(key)
        for key in ("PASSENGER_APP_ENV", "PASSENGER_BASE_URI", "PASSENGER_SPAWN_METHOD")
    )


def _resolve_data_root(base_dir):
    explicit_root = (os.environ.get("PC06_DATA_DIR") or os.environ.get("APP_DATA_DIR") or "").strip()
    if explicit_root:
        return _absolute_path(base_dir, explicit_root)
    if _running_under_passenger():
        home_dir = os.path.expanduser("~") or base_dir
        return os.path.join(home_dir, "pc06_data")
    return base_dir


def _resolve_mutable_path(base_dir, data_root, env_name, default_dirname):
    raw_value = (os.environ.get(env_name) or "").strip()
    if raw_value:
        if os.path.isabs(raw_value):
            return os.path.abspath(raw_value)
        return os.path.abspath(os.path.join(data_root, raw_value))
    return os.path.abspath(os.path.join(data_root, default_dirname))


def _resolve_database_uri(base_dir, data_root):
    raw_uri = (os.environ.get("DATABASE_URL") or "").strip()
    if not raw_uri:
        return "sqlite:///" + os.path.abspath(os.path.join(data_root, "pc06_system.db"))

    if raw_uri.startswith("sqlite:///"):
        sqlite_path = raw_uri[len("sqlite:///") :]
        if sqlite_path.startswith("/"):
            resolved_path = sqlite_path
        else:
            resolved_path = os.path.join(data_root, sqlite_path)
        return "sqlite:///" + os.path.abspath(resolved_path)

    return raw_uri


def build_storage_layout(base_dir):
    data_root = os.path.abspath(_resolve_data_root(base_dir))
    layout = {
        "data_root": data_root,
    }
    for env_name, default_dirname in MUTABLE_DIR_ENV_MAP.items():
        layout[env_name] = _resolve_mutable_path(base_dir, data_root, env_name, default_dirname)

    database_uri = _resolve_database_uri(base_dir, data_root)
    layout["DATABASE_URI"] = database_uri
    layout["SQLITE_DB_PATH"] = ""
    if database_uri.startswith("sqlite:///"):
        layout["SQLITE_DB_PATH"] = os.path.abspath(database_uri[len("sqlite:///") :])
    return layout


def _directory_has_real_content(directory):
    if not os.path.isdir(directory):
        return False
    for root, _, files in os.walk(directory):
        for filename in files:
            if filename not in _PLACEHOLDER_FILES:
                return True
        for dirname in os.listdir(root):
            if dirname.startswith("."):
                continue
            full_path = os.path.join(root, dirname)
            if os.path.isdir(full_path):
                return True
    return False


def _copy_missing_tree(source_dir, target_dir):
    for root, dirs, files in os.walk(source_dir):
        rel_path = os.path.relpath(root, source_dir)
        target_root = target_dir if rel_path == "." else os.path.join(target_dir, rel_path)
        os.makedirs(target_root, exist_ok=True)
        for dirname in dirs:
            os.makedirs(os.path.join(target_root, dirname), exist_ok=True)
        for filename in files:
            if filename in _PLACEHOLDER_FILES:
                continue
            source_file = os.path.join(root, filename)
            target_file = os.path.join(target_root, filename)
            if not os.path.exists(target_file):
                shutil.copy2(source_file, target_file)


def bootstrap_storage(layout, legacy_root):
    data_root = layout["data_root"]
    os.makedirs(data_root, exist_ok=True)

    for env_name in MUTABLE_DIR_ENV_MAP:
        os.makedirs(layout[env_name], exist_ok=True)

    target_db_path = layout.get("SQLITE_DB_PATH") or ""
    legacy_db_path = os.path.abspath(os.path.join(legacy_root, "pc06_system.db"))
    if (
        target_db_path
        and os.path.abspath(target_db_path) != legacy_db_path
        and not os.path.exists(target_db_path)
        and os.path.exists(legacy_db_path)
    ):
        os.makedirs(os.path.dirname(target_db_path), exist_ok=True)
        shutil.copy2(legacy_db_path, target_db_path)

    for env_name, dirname in MUTABLE_DIR_ENV_MAP.items():
        source_dir = os.path.abspath(os.path.join(legacy_root, dirname))
        target_dir = layout[env_name]
        if source_dir == target_dir:
            continue
        if not _directory_has_real_content(source_dir):
            continue
        if _directory_has_real_content(target_dir):
            continue
        _copy_missing_tree(source_dir, target_dir)
