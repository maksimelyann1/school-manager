from __future__ import annotations

import asyncio
import base64
import ctypes
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

import webview
from PIL import Image

try:
    import pystray
except Exception:
    pystray = None


if sys.platform == "win32":
    class _NullStream:
        def write(self, text="", *_args, **_kwargs):
            return len(text)

        def flush(self):
            pass

        def isatty(self):
            return False

    if getattr(sys, "frozen", False):
        sys.stdout = _NullStream()
        sys.stderr = _NullStream()


if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
    INSTALL_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    INSTALL_DIR = BASE_DIR

BACKEND_DIR = os.path.join(BASE_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _user_data_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return os.path.join(base, "SchoolManager")
    if sys.platform == "darwin":
        return os.path.join(
            os.path.expanduser("~"),
            "Library",
            "Application Support",
            "SchoolManager",
        )
    return os.path.join(os.path.expanduser("~"), ".school_manager")


APP_DATA_DIR = _user_data_dir() if getattr(sys, "frozen", False) else BASE_DIR
os.makedirs(APP_DATA_DIR, exist_ok=True)

LAUNCHER_LOG = os.path.join(APP_DATA_DIR, "launcher.log")
ERROR_LOG = os.path.join(APP_DATA_DIR, "error_backend.log")
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")

CANDIDATE_URLS = ["http://127.0.0.1:8001"]
if not getattr(sys, "frozen", False):
    CANDIDATE_URLS.insert(0, "http://127.0.0.1:3000")

START_IN_TRAY_ARGS = {"--start-in-tray", "--tray", "--minimized"}
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAIN_WINDOW_WIDTH = 1280
MAIN_WINDOW_HEIGHT = 960
MIN_WINDOW_WIDTH = 900
MIN_WINDOW_HEIGHT = 700
TITLE_BAR_COLOR = "#1E293B"
TITLE_BAR_BORDER_COLOR = "#334155"
TITLE_BAR_TEXT_COLOR = "#F8FAFC"
CLIPBOARD_IMPORT_MAX_BYTES = 256 * 1024 * 1024

_window: webview.Window | None = None
_splash_window: webview.Window | None = None
_tray: pystray.Icon | None = None
_app_url: str | None = None
_server_started = threading.Event()
_backend_stopped = threading.Event()
_shutdown_requested = threading.Event()
_tray_ready = threading.Event()
_exit_worker_started = threading.Event()
_main_window_maximized = False
_allow_window_close = False
_backend_server = None
_backend_loop: asyncio.AbstractEventLoop | None = None


def log_launcher(message: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LAUNCHER_LOG, "a", encoding="utf-8") as log_file:
            log_file.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def _safe_filename(filename: str | None, fallback: str = "file") -> str:
    name = os.path.basename(filename or fallback).strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or fallback


def _unique_import_name(filename: str) -> str:
    base = _safe_filename(filename, "file")
    stem, ext = os.path.splitext(base)
    stem = stem[:80] or "file"
    ext = ext[:20]
    return f"{int(time.time())}_{uuid.uuid4().hex[:12]}_{stem}{ext}"


def _read_windows_clipboard_file_paths() -> list[str]:
    if sys.platform != "win32":
        return []

    CF_HDROP = 15
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool
    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
    shell32.DragQueryFileW.restype = ctypes.c_uint

    if not user32.OpenClipboard(None):
        return []

    try:
        if not user32.IsClipboardFormatAvailable(CF_HDROP):
            return []

        handle = user32.GetClipboardData(CF_HDROP)
        if not handle:
            return []

        count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
        paths: list[str] = []
        for index in range(count):
            length = shell32.DragQueryFileW(handle, index, None, 0)
            if length <= 0:
                continue
            buffer = ctypes.create_unicode_buffer(length + 1)
            shell32.DragQueryFileW(handle, index, buffer, length + 1)
            if buffer.value:
                paths.append(buffer.value)
        return paths
    finally:
        user32.CloseClipboard()


def _import_clipboard_files_to_cache() -> dict:
    paths = _read_windows_clipboard_file_paths()
    if not paths:
        return {"files": [], "skipped": []}

    import_dir = os.path.join(APP_DATA_DIR, "import_cache")
    os.makedirs(import_dir, exist_ok=True)

    files = []
    skipped = []
    total_size = 0

    for source_path in paths:
        try:
            if not os.path.isfile(source_path):
                skipped.append({"path": source_path, "reason": "not_file"})
                continue

            size = os.path.getsize(source_path)
            if size <= 0:
                skipped.append({"path": source_path, "reason": "empty"})
                continue
            if total_size + size > CLIPBOARD_IMPORT_MAX_BYTES:
                skipped.append({"path": source_path, "reason": "too_large"})
                continue

            filename = _safe_filename(os.path.basename(source_path), "clipboard_file")
            stored_filename = _unique_import_name(filename)
            target_path = os.path.abspath(os.path.join(import_dir, stored_filename))
            if os.path.commonpath([os.path.abspath(import_dir), target_path]) != os.path.abspath(import_dir):
                skipped.append({"path": source_path, "reason": "unsafe_name"})
                continue

            shutil.copy2(source_path, target_path)
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            copied_size = os.path.getsize(target_path)
            total_size += copied_size
            files.append({
                "source": "server",
                "storage": "import",
                "stored_filename": stored_filename,
                "filename": filename,
                "name": filename,
                "type": content_type,
                "size": copied_size,
            })
        except Exception as error:
            skipped.append({"path": source_path, "reason": str(error)})

    return {"files": files, "skipped": skipped}


def _run_hidden(command: list[str], **kwargs):
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.run(command, **kwargs)


def _check_output_hidden(command: list[str], **kwargs) -> str:
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.check_output(command, **kwargs)


def _asset_data_uri(path: str) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return ""


def _loading_html(error_message: str | None = None) -> str:
    logo_uri = _asset_data_uri(LOGO_PATH)
    logo_markup = (
        f'<img class="logo" src="{logo_uri}" alt="">'
        if logo_uri
        else '<div class="logo fallback">SM</div>'
    )
    error_block = ""
    if error_message:
        error_block = f'<div class="error">{html.escape(error_message)}</div>'

    return f"""<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{
    color-scheme: dark;
    --bg: #101827;
    --panel: #172033;
    --text: #f8fafc;
    --muted: #99f6e4;
    --accent: #f59e0b;
    --accent-2: #14b8a6;
  }}
  * {{ box-sizing: border-box; }}
  button {{ font: inherit; }}
  html, body {{ margin: 0; width: 100%; height: 100%; }}
  body {{
    min-height: 100vh;
    overflow: hidden;
    background: transparent;
    color: var(--text);
    font-family: Inter, Segoe UI, Arial, sans-serif;
    user-select: none;
  }}
  .shell {{
    position: relative;
    width: 100vw;
    height: 100vh;
    padding: 42px 38px 36px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    border: 1px solid rgba(148, 163, 184, 0.24);
    border-radius: 18px;
    background:
      radial-gradient(circle at 50% 28%, rgba(20, 184, 166, 0.18), transparent 32%),
      linear-gradient(145deg, rgba(17, 24, 39, 0.98) 0%, rgba(22, 48, 54, 0.96) 52%, rgba(21, 25, 38, 0.98) 100%);
    box-shadow: 0 24px 70px rgba(0, 0, 0, 0.42);
    backdrop-filter: blur(18px);
  }}
  .close {{
    position: absolute;
    top: 16px;
    right: 16px;
    width: 34px;
    height: 34px;
    display: block;
    border: 0;
    border-radius: 50%;
    background: rgba(148, 163, 184, 0.14);
    color: #e5e7eb;
    cursor: pointer;
    font-size: 0;
    line-height: 0;
    transition: background 0.16s ease, color 0.16s ease, transform 0.12s ease, box-shadow 0.16s ease;
  }}
  .close::before,
  .close::after {{
    content: "";
    position: absolute;
    left: 50%;
    top: 50%;
    width: 14px;
    height: 2px;
    border-radius: 999px;
    background: currentColor;
    transform-origin: center;
  }}
  .close::before {{ transform: translate(-50%, -50%) rotate(45deg); }}
  .close::after {{ transform: translate(-50%, -50%) rotate(-45deg); }}
  .close:hover {{
    background: rgba(248, 113, 113, 0.28);
    color: #fff;
    box-shadow: 0 10px 24px rgba(248, 113, 113, 0.18);
  }}
  .close:active {{
    transform: scale(0.94);
    background: rgba(239, 68, 68, 0.36);
  }}
  .close:focus-visible {{
    outline: 2px solid rgba(153, 246, 228, 0.72);
    outline-offset: 2px;
  }}
  .logo {{
    width: 112px;
    height: 112px;
    display: block;
    align-self: center;
    object-fit: contain;
    margin: 0 auto 18px;
    filter: drop-shadow(0 18px 32px rgba(20, 184, 166, 0.28));
  }}
  .fallback {{
    display: inline-grid;
    place-items: center;
    border-radius: 24px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    font-size: 32px;
    font-weight: 800;
  }}
  h1 {{
    margin: 0 0 10px;
    font-size: 30px;
    line-height: 1.15;
    letter-spacing: 0;
  }}
  .status {{
    margin: 0 auto 26px;
    max-width: 420px;
    color: #cbd5e1;
    font-size: 15px;
    line-height: 1.55;
  }}
  .bar {{
    position: relative;
    width: min(100%, 486px);
    margin: 0 auto;
    height: 8px;
    overflow: hidden;
    border-radius: 999px;
    background: rgba(148, 163, 184, 0.2);
  }}
  .bar::before {{
    content: "";
    position: absolute;
    inset: 0 auto 0 0;
    width: 44%;
    border-radius: inherit;
    background: linear-gradient(90deg, var(--accent), var(--accent-2));
    animation: loading 1.25s ease-in-out infinite;
  }}
  .hint {{
    margin-top: 18px;
    color: var(--muted);
    font-size: 13px;
  }}
  .error {{
    margin-top: 20px;
    padding: 12px 14px;
    border: 1px solid rgba(248, 113, 113, 0.45);
    border-radius: 12px;
    color: #fecaca;
    background: rgba(127, 29, 29, 0.28);
    font-size: 13px;
    line-height: 1.45;
  }}
  @keyframes loading {{
    0% {{ transform: translateX(-120%); }}
    55% {{ transform: translateX(90%); }}
    100% {{ transform: translateX(250%); }}
  }}
</style>
<script>
  window.setStatus = function(text) {{
    var element = document.getElementById("status");
    if (element) element.textContent = text;
  }};
  window.closeApp = function(event) {{
    if (event) event.stopPropagation();
    if (window.pywebview && window.pywebview.api && window.pywebview.api.close_app) {{
      window.pywebview.api.close_app();
    }}
  }};
</script>
</head>
<body>
  <main class="shell">
    <button class="close" type="button" title="Закрити" aria-label="Закрити" onmousedown="event.stopPropagation()" onclick="closeApp(event)"></button>
    {logo_markup}
    <h1>School Manager</h1>
    <p id="status" class="status">Запускаємо програму та готуємо локальний сервер...</p>
    <div class="bar" aria-hidden="true"></div>
    <div class="hint">Перший запуск на різних ПК може тривати від 5 до 30 секунд.</div>
    {error_block}
  </main>
</body>
</html>"""


def _loading_target() -> webview.Window | None:
    return _splash_window or _window


def _set_loading_status(message: str):
    target = _loading_target()
    if not target:
        return
    try:
        target.evaluate_js(f"window.setStatus && window.setStatus({json.dumps(message)});")
    except Exception:
        pass


def _destroy_window_safely(window: webview.Window | None):
    if not window:
        return
    try:
        window.destroy()
    except Exception:
        pass


def _get_main_window_size() -> tuple[int, int]:
    if sys.platform != "win32":
        return MAIN_WINDOW_WIDTH, MAIN_WINDOW_HEIGHT

    try:
        screens = getattr(webview, "screens", [])
        screen_width = int(screens[0].width) if screens else MAIN_WINDOW_WIDTH
        screen_height = int(screens[0].height) if screens else MAIN_WINDOW_HEIGHT
        width = min(MAIN_WINDOW_WIDTH, max(MIN_WINDOW_WIDTH, screen_width - 80))
        height = min(MAIN_WINDOW_HEIGHT, max(MIN_WINDOW_HEIGHT, screen_height - 80))
        return width, height
    except Exception as error:
        log_launcher(f"Main window size fallback: {error}")

    return MAIN_WINDOW_WIDTH, MAIN_WINDOW_HEIGHT


def _get_window_hwnd(window: webview.Window | None) -> int | None:
    if sys.platform != "win32" or not window:
        return None

    try:
        from webview.platforms.winforms import BrowserView

        view = BrowserView.instances.get(window.uid)
        if not view:
            return None

        handle = getattr(view, "Handle", None)
        if handle is None:
            return None
        if hasattr(handle, "ToInt64"):
            return int(handle.ToInt64())
        if hasattr(handle, "ToInt32"):
            return int(handle.ToInt32())
        return int(handle)
    except Exception as error:
        log_launcher(f"HWND lookup failed: {error}")
        return None


def _rgb_to_colorref(hex_color: str) -> int:
    value = hex_color.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


def _apply_native_title_bar_colors(hwnd: int):
    try:
        dwmapi = ctypes.windll.dwmapi

        dark_mode = ctypes.c_int(1)
        for attr in (20, 19):
            dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))

        caption_color = ctypes.c_uint(_rgb_to_colorref(TITLE_BAR_COLOR))
        border_color = ctypes.c_uint(_rgb_to_colorref(TITLE_BAR_BORDER_COLOR))
        text_color = ctypes.c_uint(_rgb_to_colorref(TITLE_BAR_TEXT_COLOR))
        dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption_color), ctypes.sizeof(caption_color))
        dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border_color), ctypes.sizeof(border_color))
        dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text_color), ctypes.sizeof(text_color))
    except Exception as error:
        log_launcher(f"Native title bar styling skipped: {error}")


def _style_native_title_bar(window: webview.Window):
    if sys.platform != "win32":
        return

    for _attempt in range(60):
        hwnd = _get_window_hwnd(window)
        if hwnd:
            _apply_native_title_bar_colors(hwnd)
            return
        time.sleep(0.1)

    log_launcher("Native title bar styling skipped: HWND was not found")


def _style_native_title_bar_async(window: webview.Window):
    if sys.platform == "win32":
        threading.Thread(target=_style_native_title_bar, args=(window,), daemon=True).start()


def _bring_window_to_foreground(window: webview.Window):
    if sys.platform != "win32":
        return

    try:
        hwnd = _get_window_hwnd(window)
        if not hwnd:
            return

        user32 = ctypes.windll.user32
        SW_SHOW = 5
        SW_RESTORE = 9
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040

        show_command = SW_RESTORE if user32.IsIconic(hwnd) else SW_SHOW
        user32.ShowWindow(hwnd, show_command)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    except Exception as error:
        log_launcher(f"Bring window to foreground skipped: {error}")


def _bring_window_to_foreground_async(window: webview.Window):
    if sys.platform == "win32":
        threading.Thread(target=_bring_window_to_foreground, args=(window,), daemon=True).start()


def _request_backend_shutdown():
    _shutdown_requested.set()
    server = _backend_server
    loop = _backend_loop
    if server is not None:
        try:
            server.should_exit = True
        except Exception as error:
            log_launcher(f"Backend shutdown flag failed: {error}")
    if loop is not None:
        try:
            loop.call_soon_threadsafe(lambda: None)
        except Exception:
            pass


def _exit_after_backend_shutdown(timeout: float = 8.0):
    stopped = _backend_stopped.wait(timeout=timeout)
    log_launcher("Backend stopped cleanly" if stopped else "Backend shutdown timeout; forcing process exit")
    os._exit(0)


def _start_exit_worker():
    if _exit_worker_started.is_set():
        return
    _exit_worker_started.set()
    threading.Thread(target=_exit_after_backend_shutdown, daemon=False).start()


def _quit_application(icon: pystray.Icon | None = None):
    global _window, _splash_window, _allow_window_close

    log_launcher("Launcher quit requested")
    _allow_window_close = True
    _request_backend_shutdown()

    tray_icon = icon or _tray
    if tray_icon:
        try:
            tray_icon.stop()
        except Exception:
            pass

    target = _window or _splash_window
    if target:
        _destroy_window_safely(target)

    _start_exit_worker()


class SplashApi:
    def close_app(self):
        _quit_application()


class DesktopApi:
    def get_window_state(self):
        if not _window:
            return {"maximized": False, "x": 0, "y": 0, "width": MAIN_WINDOW_WIDTH, "height": MAIN_WINDOW_HEIGHT}

        try:
            return {
                "maximized": _main_window_maximized,
                "x": _window.x,
                "y": _window.y,
                "width": _window.width,
                "height": _window.height,
            }
        except Exception:
            return {
                "maximized": _main_window_maximized,
                "x": 0,
                "y": 0,
                "width": MAIN_WINDOW_WIDTH,
                "height": MAIN_WINDOW_HEIGHT,
            }

    def minimize_window(self):
        if _window:
            threading.Thread(target=_window.minimize, daemon=True).start()
        return True

    def toggle_maximize_window(self):
        global _main_window_maximized

        if not _window:
            return False

        try:
            if _main_window_maximized:
                _window.restore()
                _main_window_maximized = False
            else:
                _window.maximize()
                _main_window_maximized = True
        except Exception as error:
            log_launcher(f"Window maximize toggle failed: {error}")

        return _main_window_maximized

    def hide_window(self):
        if _window:
            threading.Thread(target=_window.hide, daemon=True).start()
        return True

    def save_file_dialog(self, filename, base64_data):
        if not _window:
            return {"saved": False, "cancelled": True}

        try:
            safe_name = os.path.basename(str(filename or "school_manager_schedule.xlsx"))
            if not safe_name.lower().endswith(".xlsx"):
                safe_name = f"{safe_name}.xlsx"

            documents_dir = os.path.join(os.path.expanduser("~"), "Documents")
            initial_dir = documents_dir if os.path.isdir(documents_dir) else ""
            target_path = _window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=initial_dir,
                save_filename=safe_name,
                file_types=("Excel workbook (*.xlsx)",),
            )

            if not target_path:
                return {"saved": False, "cancelled": True}
            if not str(target_path).lower().endswith(".xlsx"):
                target_path = f"{target_path}.xlsx"

            payload = base64.b64decode(str(base64_data or ""))
            with open(target_path, "wb") as output_file:
                output_file.write(payload)

            return {"saved": True, "path": target_path}
        except Exception as error:
            log_launcher(f"Save file dialog failed: {error}")
            return {"saved": False, "cancelled": False, "error": str(error)}

    def save_log_file_dialog(self, filename, base64_data):
        if not _window:
            return {"saved": False, "cancelled": True}

        try:
            safe_name = os.path.basename(str(filename or "school_manager_log.txt"))
            if not safe_name.lower().endswith(".txt"):
                safe_name = f"{safe_name}.txt"

            documents_dir = os.path.join(os.path.expanduser("~"), "Documents")
            initial_dir = documents_dir if os.path.isdir(documents_dir) else ""
            target_path = _window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=initial_dir,
                save_filename=safe_name,
                file_types=("Text log file (*.txt)",),
            )

            if not target_path:
                return {"saved": False, "cancelled": True}
            if not str(target_path).lower().endswith(".txt"):
                target_path = f"{target_path}.txt"

            payload = base64.b64decode(str(base64_data or ""))
            with open(target_path, "wb") as output_file:
                output_file.write(payload)

            return {"saved": True, "path": target_path}
        except Exception as error:
            log_launcher(f"Save log file dialog failed: {error}")
            return {"saved": False, "cancelled": False, "error": str(error)}

    def import_clipboard_files(self):
        try:
            return _import_clipboard_files_to_cache()
        except Exception as error:
            log_launcher(f"Clipboard file import failed: {error}")
            return {"files": [], "skipped": [], "error": str(error)}

    def open_external_url(self, url):
        try:
            target = str(url or "").strip()
            allowed_prefixes = (
                "https://aistudio.google.com/",
                "https://ai.google.dev/",
            )
            if not any(target.startswith(prefix) for prefix in allowed_prefixes):
                return {"opened": False, "error": "Непідтримуване посилання"}

            if sys.platform == "win32":
                os.startfile(target)  # noqa: S606 - fixed allowlisted URL opens in the default browser.
            else:
                import webbrowser

                webbrowser.open(target)
            return {"opened": True}
        except Exception as error:
            log_launcher(f"Open external URL failed: {error}")
            return {"opened": False, "error": str(error)}

    def resize_window(self, x, y, width, height):
        global _main_window_maximized

        if not _window:
            return self.get_window_state()

        try:
            width = max(MIN_WINDOW_WIDTH, int(width))
            height = max(MIN_WINDOW_HEIGHT, int(height))
            x = int(x)
            y = int(y)

            if _main_window_maximized:
                _window.restore()
                _main_window_maximized = False

            _window.move(x, y)
            _window.resize(width, height)
        except Exception as error:
            log_launcher(f"Window resize failed: {error}")

        return self.get_window_state()

def kill_process_on_port(port: int):
    if sys.platform != "win32":
        return

    try:
        output = _check_output_hidden(
            ["netstat", "-ano", "-p", "tcp"],
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        pids = set()
        for line in output.strip().splitlines():
            parts = line.split()
            if len(parts) > 4 and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
                pids.add(parts[-1])

        for pid in pids:
            if pid != "0":
                log_launcher(f"Stopping old server process on port {port}: PID {pid}")
                _run_hidden(
                    ["taskkill", "/F", "/PID", pid],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        time.sleep(1)
    except Exception as error:
        log_launcher(f"Port cleanup skipped: {error}")


def check_url(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=1)
        return True
    except Exception:
        return False


def find_active_url() -> str | None:
    for url in CANDIDATE_URLS:
        if check_url(url):
            return url
    return None


def run_backend():
    global _backend_server, _backend_loop

    log_launcher("Backend thread starting")
    kill_process_on_port(8001)
    log_launcher(f"Using backend dir: {BACKEND_DIR}")

    loop = None
    try:
        os.chdir(BACKEND_DIR)
        loop = asyncio.new_event_loop()
        _backend_loop = loop
        asyncio.set_event_loop(loop)

        import uvicorn
        from main import app  # noqa

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=8001,
            log_level="info",
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        _backend_server = server
        if _shutdown_requested.is_set():
            server.should_exit = True
        _server_started.set()
        log_launcher("Uvicorn server starting on 127.0.0.1:8001")
        loop.run_until_complete(server.serve())
    except Exception as error:
        import traceback

        error_msg = f"[Launcher] Backend error: {error}\n{traceback.format_exc()}"
        log_launcher(error_msg)
        try:
            with open(ERROR_LOG, "w", encoding="utf-8") as error_file:
                error_file.write(error_msg)
        except Exception:
            pass
        _server_started.set()
    finally:
        _backend_server = None
        _backend_loop = None
        if loop is not None:
            try:
                loop.close()
            except Exception:
                pass
        _backend_stopped.set()
        log_launcher("Backend thread stopped")


def _make_icon():
    if os.path.exists(LOGO_PATH):
        return Image.open(LOGO_PATH).convert("RGBA").resize((64, 64))
    return Image.new("RGBA", (64, 64), (99, 102, 241, 255))


def _on_show(_icon, _item):
    if _window:
        _window.show()
        _style_native_title_bar_async(_window)
        _bring_window_to_foreground_async(_window)
    elif _splash_window:
        _splash_window.show()
        _bring_window_to_foreground_async(_splash_window)


def _on_quit(icon, _item):
    _quit_application(icon)


def _create_tray_icon():
    global _tray
    if pystray is None:
        log_launcher("Tray unavailable: pystray import failed")
        return None

    try:
        menu = pystray.Menu(
            pystray.MenuItem("Відкрити", _on_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Закрити програму", _on_quit),
        )
        _tray = pystray.Icon("SchoolManager", _make_icon(), "School Manager", menu)
        return _tray
    except Exception as error:
        log_launcher(f"Tray unavailable: {error}")
        return None


def _tray_setup(icon):
    try:
        icon.visible = True
        _tray_ready.set()
        log_launcher("Tray icon ready")
    except Exception as error:
        log_launcher(f"Tray icon setup failed: {error}")


def _show_window_if_tray_unavailable():
    if should_start_in_tray() and not _tray_ready.is_set():
        log_launcher("Start-in-tray fallback: showing window because tray is unavailable")
        if _window:
            try:
                _window.show()
            except Exception:
                pass


def run_tray():
    tray_icon = _create_tray_icon()
    if tray_icon is None:
        threading.Timer(2.0, _show_window_if_tray_unavailable).start()
        return

    try:
        tray_icon.run(setup=_tray_setup)
    except Exception as error:
        log_launcher(f"Tray unavailable: {error}")
        _tray_ready.clear()
        threading.Timer(2.0, _show_window_if_tray_unavailable).start()


def start_macos_tray_detached():
    tray_icon = _create_tray_icon()
    if tray_icon is None:
        threading.Timer(2.0, _show_window_if_tray_unavailable).start()
        return

    try:
        tray_icon.run_detached(setup=_tray_setup)
    except Exception as error:
        log_launcher(f"macOS tray unavailable: {error}")
        _tray_ready.clear()
        threading.Timer(2.0, _show_window_if_tray_unavailable).start()


def on_closing():
    if _allow_window_close or not _tray_ready.is_set():
        _request_backend_shutdown()
        _start_exit_worker()
        return True

    if _window:
        threading.Thread(target=_window.hide, daemon=True).start()
    return False


def _on_window_closed():
    if not _shutdown_requested.is_set():
        log_launcher("Main window closed without tray; shutting down")
        _request_backend_shutdown()
    _start_exit_worker()
    tray_icon = _tray
    if tray_icon:
        try:
            tray_icon.stop()
        except Exception:
            pass


def _on_window_maximized():
    global _main_window_maximized
    _main_window_maximized = True


def _on_window_restored():
    global _main_window_maximized
    _main_window_maximized = False


def _attach_main_window_events(window: webview.Window):
    window.events.closing += on_closing
    window.events.closed += _on_window_closed
    window.events.maximized += _on_window_maximized
    window.events.restored += _on_window_restored
    window.events.shown += lambda: _style_native_title_bar_async(window)


def should_start_in_tray() -> bool:
    return any(arg.lower() in START_IN_TRAY_ARGS for arg in sys.argv[1:])


def _create_main_window(url: str, start_in_tray: bool):
    global _window, _splash_window

    if _window:
        _window.load_url(url)
        if start_in_tray:
            _window.hide()
        else:
            _window.show()
        _style_native_title_bar_async(_window)
    else:
        main_width, main_height = _get_main_window_size()
        _window = webview.create_window(
            "School Manager",
            url=url,
            width=main_width,
            height=main_height,
            min_size=(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT),
            hidden=start_in_tray,
            js_api=DesktopApi(),
            background_color="#111827",
        )
        _attach_main_window_events(_window)
        _style_native_title_bar_async(_window)

    if _splash_window:
        _destroy_window_safely(_splash_window)
        _splash_window = None


def _show_startup_error(message: str):
    target = _loading_target()
    if target:
        target.load_html(_loading_html(message))


def _startup_flow(start_in_tray: bool):
    global _app_url

    _set_loading_status("Запускаємо локальний сервер програми...")
    backend_thread = threading.Thread(target=run_backend, daemon=True)
    backend_thread.start()
    _server_started.wait(timeout=3)

    for attempt in range(35):
        _app_url = find_active_url()
        if _app_url:
            log_launcher(f"Window URL: {_app_url}")
            _set_loading_status("Готово. Відкриваємо програму...")
            time.sleep(0.25)
            _create_main_window(_app_url, start_in_tray)
            return

        if attempt in {4, 12, 22}:
            _set_loading_status("Ще трохи: сервер стартує, перевіряємо готовність...")
        time.sleep(1)

    log_launcher("Backend did not become ready in time")
    _show_startup_error(
        "Не вдалося швидко запустити програму. "
        f"Перевірте файл журналу: {ERROR_LOG}"
    )
    if start_in_tray and _window:
        try:
            _window.show()
            _style_native_title_bar_async(_window)
            _bring_window_to_foreground_async(_window)
        except Exception as error:
            log_launcher(f"Startup error window show skipped: {error}")


def _create_initial_window(start_in_tray: bool):
    global _window, _splash_window

    if start_in_tray:
        main_width, main_height = _get_main_window_size()
        _window = webview.create_window(
            "School Manager",
            html=_loading_html(),
            width=main_width,
            height=main_height,
            min_size=(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT),
            hidden=True,
            js_api=DesktopApi(),
            background_color="#111827",
        )
        _attach_main_window_events(_window)
        _style_native_title_bar_async(_window)
        return

    _splash_window = webview.create_window(
        "School Manager",
        html=_loading_html(),
        width=560,
        height=430,
        resizable=False,
        frameless=True,
        easy_drag=True,
        transparent=True,
        js_api=SplashApi(),
        background_color="#000000",
    )


def main():
    log_launcher("Launcher starting")
    start_in_tray = should_start_in_tray()
    if start_in_tray:
        log_launcher("Start-in-tray mode enabled")

    _create_initial_window(start_in_tray)

    if sys.platform == "darwin":
        start_macos_tray_detached()
    else:
        threading.Thread(target=run_tray, daemon=True).start()
    start_kwargs = {"debug": False}
    if sys.platform == "win32":
        start_kwargs["gui"] = "edgechromium"
    webview.start(_startup_flow, args=(start_in_tray,), **start_kwargs)


if __name__ == "__main__":
    main()
