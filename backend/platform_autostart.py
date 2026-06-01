import os
import plistlib
import subprocess
import sys
from pathlib import Path

from fastapi import HTTPException


AUTOSTART_VALUE_NAME = "SchoolManager"
AUTOSTART_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_STARTUP_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
MACOS_LAUNCH_AGENT_ID = "com.schoolmanager.app"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def autostart_supported() -> bool:
    return sys.platform in {"win32", "darwin"}


def _windows_command(start_arg: str) -> str:
    if _is_frozen():
        args = [sys.executable, start_arg]
    else:
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        desktop_script = os.path.join(app_root, "desktop_app.py")
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        python_exe = pythonw if os.path.exists(pythonw) else sys.executable
        args = [python_exe, desktop_script, start_arg]
    return subprocess.list2cmdline(args)


def _delete_windows_run_value():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _write_windows_run_value(start_arg: str):
    import winreg

    command = _windows_command(start_arg)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, AUTOSTART_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, command)

    # If Windows Startup Apps disabled this entry earlier, this flips it back on.
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, AUTOSTART_STARTUP_APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(
                key,
                AUTOSTART_VALUE_NAME,
                0,
                winreg.REG_BINARY,
                bytes([0x02, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            )
    except OSError:
        pass


def _macos_program_arguments(start_arg: str) -> list[str]:
    if _is_frozen():
        return [sys.executable, start_arg]

    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    desktop_script = os.path.join(app_root, "desktop_app.py")
    return [sys.executable, desktop_script, start_arg]


def _validate_macos_autostart_location():
    if not _is_frozen():
        return

    executable = os.path.abspath(sys.executable)
    unstable_locations = (
        executable.startswith("/Volumes/"),
        "/AppTranslocation/" in executable,
    )
    if any(unstable_locations):
        raise HTTPException(
            status_code=400,
            detail=(
                "Для автозапуску на macOS перенесіть SchoolManager.app у папку Applications, "
                "відкрийте програму звідти і увімкніть автозапуск ще раз."
            ),
        )


def _macos_launch_agent_path() -> str:
    return os.path.join(
        os.path.expanduser("~"),
        "Library",
        "LaunchAgents",
        f"{MACOS_LAUNCH_AGENT_ID}.plist",
    )


def expected_autostart_command(start_arg: str) -> str:
    if sys.platform == "win32":
        return _windows_command(start_arg)
    if sys.platform == "darwin":
        return " ".join(_macos_program_arguments(start_arg))
    return ""


def _read_windows_autostart_value() -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _value_type = winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
            return value
    except FileNotFoundError:
        return None
    except OSError:
        return None


def _delete_windows_startup_approved_value():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_STARTUP_APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _read_windows_startup_approved_enabled() -> bool | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_STARTUP_APPROVED_KEY, 0, winreg.KEY_READ) as key:
            value, _value_type = winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
        if isinstance(value, bytes) and value:
            return value[0] == 0x02
    except FileNotFoundError:
        return None
    except OSError:
        return None
    return None


def _write_windows_autostart_value(enabled: bool, start_arg: str):
    try:
        if enabled:
            _write_windows_run_value(start_arg)
        else:
            _delete_windows_run_value()
            _delete_windows_startup_approved_value()
    except PermissionError as error:
        raise HTTPException(status_code=500, detail=f"Немає доступу до автозапуску Windows: {error}") from error
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Не вдалося змінити автозапуск: {error}") from error


def _read_macos_autostart_value() -> str | None:
    plist_path = _macos_launch_agent_path()
    if not os.path.isfile(plist_path):
        return None

    try:
        with open(plist_path, "rb") as plist_file:
            payload = plistlib.load(plist_file)
        args = payload.get("ProgramArguments") or []
        if not isinstance(args, list):
            return None
        return " ".join(str(arg) for arg in args)
    except Exception:
        return None


def _write_macos_autostart_value(enabled: bool, start_arg: str):
    plist_path = _macos_launch_agent_path()

    try:
        if enabled:
            _validate_macos_autostart_location()
            Path(os.path.dirname(plist_path)).mkdir(parents=True, exist_ok=True)
            logs_dir = os.path.join(os.path.expanduser("~"), "Library", "Logs")
            Path(logs_dir).mkdir(parents=True, exist_ok=True)
            payload = {
                "Label": MACOS_LAUNCH_AGENT_ID,
                "ProgramArguments": _macos_program_arguments(start_arg),
                "RunAtLoad": True,
                "KeepAlive": False,
                "LimitLoadToSessionType": "Aqua",
                "ProcessType": "Interactive",
                "WorkingDirectory": os.path.dirname(sys.executable if _is_frozen() else os.path.dirname(os.path.abspath(__file__))),
                "StandardOutPath": os.path.join(logs_dir, "SchoolManager.launchd.log"),
                "StandardErrorPath": os.path.join(logs_dir, "SchoolManager.launchd.err.log"),
            }
            with open(plist_path, "wb") as plist_file:
                plistlib.dump(payload, plist_file)
        else:
            try:
                os.remove(plist_path)
            except FileNotFoundError:
                pass
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Не вдалося змінити автозапуск macOS: {error}") from error


def read_autostart_value() -> str | None:
    if sys.platform == "win32":
        return _read_windows_autostart_value()
    if sys.platform == "darwin":
        return _read_macos_autostart_value()
    return None


def write_autostart_value(enabled: bool, start_arg: str):
    if not autostart_supported():
        raise HTTPException(status_code=400, detail="Автозапуск підтримується тільки у Windows та macOS")

    if sys.platform == "win32":
        _write_windows_autostart_value(enabled, start_arg)
        return

    if sys.platform == "darwin":
        _write_macos_autostart_value(enabled, start_arg)
        return


def autostart_status(start_arg: str) -> dict:
    supported = autostart_supported()
    current_value = read_autostart_value() if supported else None
    expected_command = expected_autostart_command(start_arg) if supported else ""
    startup_approved_enabled = _read_windows_startup_approved_enabled() if sys.platform == "win32" and supported else None
    enabled = bool(current_value) and startup_approved_enabled is not False

    return {
        "supported": supported,
        "platform": sys.platform,
        "enabled": enabled,
        "starts_in_tray": enabled and start_arg in (current_value or ""),
        "command": current_value or expected_command,
        "expected_command": expected_command,
        "is_current": enabled and current_value == expected_command,
        "startup_approved_enabled": startup_approved_enabled,
    }
