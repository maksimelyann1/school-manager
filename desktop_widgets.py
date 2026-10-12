"""Frameless WebView2 widgets sharing the application's existing backend."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import threading
from uuid import uuid4

from desktop_widget_layout import KINDS, SIZES, remember_position, resolve_position, validate_change


def widget_action(manager, method, *args, **kwargs):
    try:
        return getattr(manager, method)(*args, **kwargs)
    except Exception as error:
        labels = {'snapshot': 'прочитати віджети', 'create': 'створити віджет', 'update': 'змінити віджет',
                  'remove': 'видалити віджет', 'resize': 'змінити розмір', 'resize_delta': 'змінити розмір', 'begin_drag': 'перемістити віджет', 'open_target': 'відкрити запис'}
        manager.log(f"Не вдалося {labels[method]}: {type(error).__name__}")
        if isinstance(error, ValueError):
            raise
        raise RuntimeError('Не вдалося виконати дію віджета. Спробуйте ще раз.') from error


def displays():
    if sys.platform != 'win32':
        import webview
        return [{'id': str(i), 'name': f'Екран {i + 1}', 'primary': i == 0, 'scale': 1,
                 'work': {'x': s.x, 'y': s.y, 'width': s.width, 'height': s.height}} for i, s in enumerate(webview.screens)]
    user = ctypes.WinDLL('user32', use_last_error=True)
    class MonitorInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('monitor', wintypes.RECT), ('work', wintypes.RECT), ('flags', wintypes.DWORD), ('device', wintypes.WCHAR * 32)]
    class DisplayDevice(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('name', wintypes.WCHAR * 32), ('label', wintypes.WCHAR * 128), ('flags', wintypes.DWORD), ('identifier', wintypes.WCHAR * 128), ('key', wintypes.WCHAR * 128)]
    result = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DisplayDevice), wintypes.DWORD]
    def collect(monitor, _dc, _rect, _data):
        info = MonitorInfo(); info.cbSize = ctypes.sizeof(info)
        if not user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return True
        device = DisplayDevice(); device.cb = ctypes.sizeof(device)
        user.EnumDisplayDevicesW(info.device, 0, ctypes.byref(device), 1)
        scale = 1
        try:
            dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
            shcore = ctypes.WinDLL('shcore')
            shcore.GetDpiForMonitor.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
            if shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
                scale = dpi_x.value / 96
        except (OSError, AttributeError):
            pass
        result.append({'id': device.identifier or info.device, 'device': info.device,
                       'name': device.label or info.device, 'primary': bool(info.flags & 1), 'scale': scale,
                       'work': {'x': info.work.left, 'y': info.work.top, 'width': info.work.right - info.work.left, 'height': info.work.bottom - info.work.top}})
        return True
    callback = callback_type(collect)
    user.EnumDisplayMonitors(None, None, callback, 0)
    return sorted(result, key=lambda display: (not display['primary'], display['work']['x'], display['work']['y']))


class WidgetApi:
    def __init__(self, manager, widget_id):
        self._manager, self._id = manager, widget_id

    def get_widget_state(self):
        return widget_action(self._manager, 'snapshot', self._id)

    def update_widget(self, changes):
        return widget_action(self._manager, 'update', self._id, changes)

    def hide_widget(self):
        return widget_action(self._manager, 'update', self._id, {'visible': False})

    def open_widget_target(self, date=None, item_id=None):
        return widget_action(self._manager, 'open_target', date, item_id)

    def open_widget_lesson(self, lesson_id):
        return widget_action(self._manager, 'open_target', lesson_id=lesson_id)

    def begin_widget_drag(self):
        return widget_action(self._manager, 'begin_drag', self._id)

    def resize_widget(self, delta_x, delta_y, pixel_ratio):
        return widget_action(self._manager, 'resize_delta', self._id, delta_x, delta_y, pixel_ratio)


class WidgetManager:
    def __init__(self, path, open_target, log, base_url='http://127.0.0.1:8001', create_window=None):
        import webview
        self.path = Path(path)
        self.open_target, self.log, self.base_url = open_target, log, base_url
        self.create_window = create_window or webview.create_window
        self.windows, self.timers, self.applied, self.widgets = {}, {}, {}, []
        self.lock = threading.RLock()
        self.stopping, self.started = False, False
        self.display_timer = None
        self._display_handler = None
        self.load_error = None
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('version') != 1 or not isinstance(data.get('widgets'), list) or len(data['widgets']) > 8:
                raise ValueError('Некоректний формат')
            ids = set()
            for row in data['widgets']:
                if row['kind'] not in KINDS or len(row['id']) != 32 or any(c not in '0123456789abcdef' for c in row['id']) or row['id'] in ids:
                    raise ValueError('Некоректний віджет')
                ids.add(row['id'])
                validated = validate_change(row, {key: row[key] for key in ('visible', 'locked', 'on_top', 'opacity', 'size')})
                position = validated.get('position')
                if position:
                    if not isinstance(position.get('display_id'), str) or any(type(position.get(k)) not in (int, float) or not 0 <= position[k] <= 1 for k in ('u', 'v')) or any(type(position.get(k)) is not int or not 200 <= position[k] <= 1600 for k in ('width', 'height')):
                        raise ValueError('Некоректна позиція')
                self.widgets.append(validated)
        except Exception as error:
            self.widgets = []
            self.load_error = 'Не вдалося прочитати налаштування віджетів. Початковий файл збережено.'
            self.log(f'Віджети: читання налаштувань, {type(error).__name__}')

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.load_error and self.path.exists():
            backup = self.path.with_name(f'widgets-unreadable-{uuid4().hex[:8]}.json')
            os.replace(self.path, backup)
            self.load_error = None
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': 1, 'widgets': self.widgets}, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, self.path)

    def _find(self, widget_id):
        widget = next((w for w in self.widgets if w['id'] == widget_id), None)
        if widget is None:
            raise ValueError('Віджет уже видалено')
        return widget

    def snapshot(self, widget_id=None):
        with self.lock:
            values = json.loads(json.dumps(self.widgets))
            monitors = displays()
            for widget in values:
                widget['opened'] = widget['id'] in self.windows
                widget['display_missing'] = bool(widget.get('position') and not any(d['id'] == widget['position']['display_id'] for d in monitors))
            return {'widgets': values, 'widget': next((w for w in values if w['id'] == widget_id), None), 'displays': monitors, 'error': self.load_error}

    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True
        if sys.platform == 'win32':
            try:
                from Microsoft.Win32 import SystemEvents
                self._display_handler = lambda *_: self._display_changed()
                SystemEvents.DisplaySettingsChanged += self._display_handler
            except Exception as error:
                self.log(f'Віджети: події екранів, {type(error).__name__}')
        for widget in list(self.widgets):
            if widget['visible']:
                self._show(widget)

    def create(self, kind):
        with self.lock:
            if kind not in KINDS:
                raise ValueError('Невідомий тип віджета')
            if len(self.widgets) >= 8:
                raise ValueError('Можна створити до восьми віджетів')
            widget = {'id': uuid4().hex, 'kind': kind, 'visible': True, 'locked': False, 'on_top': False, 'opacity': 100, 'size': 'regular', 'position': None}
            self.widgets.append(widget)
            self._save()
        self._show(widget)
        return self.snapshot()

    def _show(self, widget):
        with self.lock:
            if self.stopping:
                return
            if widget['id'] in self.windows:
                return
            width, height = SIZES[widget['size']]
            window = self.create_window(f"{KINDS[widget['kind']]} · School Manager", f"{self.base_url}/widgets.html?id={widget['id']}",
                width=width, height=height, min_size=(280, 300), frameless=True, easy_drag=False, resizable=False,
                hidden=True, background_color='#111827', on_top=widget['on_top'], js_api=WidgetApi(self, widget['id']))
            self.windows[widget['id']] = window
            window.events.loaded += lambda: self._ready(widget['id'])
            window.events.moved += lambda *args: self._moved(widget['id'])
            window.events.resized += lambda *args: self._moved(widget['id'])
            window.events.closed += lambda: self._closed(widget['id'], window)

    def _form(self, window):
        from webview.platforms.winforms import BrowserView
        return BrowserView.instances[window.uid]

    def _native(self, window, action):
        if sys.platform != 'win32':
            return
        from System import Action
        form = self._form(window)
        form.Invoke(Action(lambda: action(form)))

    def _bounds(self, window):
        if sys.platform == 'win32':
            user = ctypes.WinDLL('user32')
            user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            rect = wintypes.RECT()
            if user.GetWindowRect(int(self._form(window).Handle.ToInt64()), ctypes.byref(rect)):
                return {'x': rect.left, 'y': rect.top, 'width': rect.right - rect.left, 'height': rect.bottom - rect.top}
        return {key: int(getattr(window, key)) for key in ('x', 'y', 'width', 'height')}

    def _place(self, widget_id):
        with self.lock:
            window = self.windows.get(widget_id)
            if not window or not window.events.shown.is_set():
                return
            widget = self._find(widget_id)
            bounds = resolve_position(widget, displays(), self.widgets.index(widget))
            self.applied[widget_id] = bounds
        if sys.platform == 'win32':
            def apply(form):
                user = ctypes.WinDLL('user32')
                user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
                user.SetWindowPos(int(form.Handle.ToInt64()), None, bounds['x'], bounds['y'], bounds['width'], bounds['height'], 0x14)
                form.ShowInTaskbar = False
                form.TopMost = widget['on_top']
                form.Opacity = widget['opacity'] / 100
                gdi = ctypes.WinDLL('gdi32')
                gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
                gdi.CreateRoundRectRgn.restype = wintypes.HANDLE
                user.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
                radius = round(28 * float(form.DeviceDpi) / 96)
                region = gdi.CreateRoundRectRgn(0, 0, bounds['width'] + 1, bounds['height'] + 1, radius, radius)
                if not user.SetWindowRgn(int(form.Handle.ToInt64()), region, True):
                    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
                    gdi.DeleteObject(region)
            self._native(window, apply)
        else:
            window.move(bounds['x'], bounds['y']); window.resize(bounds['width'], bounds['height'])
            window.on_top = widget['on_top']

    def _ready(self, widget_id):
        try:
            with self.lock:
                window = self.windows.get(widget_id)
                if not window or self.stopping:
                    return
                # Serialize initial positioning with hide/close requests.
                self._place(widget_id)
                window.show()
                self._place(widget_id)
                widget = self._find(widget_id)
                if not widget.get('position'):
                    widget['position'] = remember_position(self._bounds(window), displays())
                    self._save()
        except Exception as error:
            self.log(f'Віджети: відкриття, {type(error).__name__}')

    def _moved(self, widget_id):
        with self.lock:
            window = self.windows.get(widget_id)
            if self.stopping or not window or widget_id not in self.applied:
                return
            if self._bounds(window) == self.applied[widget_id]:
                return
            timer = self.timers.pop(widget_id, None)
            if timer:
                timer.cancel()
            timer = threading.Timer(.35, self._remember, args=(widget_id,))
            timer.daemon = True
            self.timers[widget_id] = timer
            timer.start()

    def _remember(self, widget_id):
        try:
            with self.lock:
                self.timers.pop(widget_id, None)
                window = self.windows.get(widget_id)
                if not window or self.stopping:
                    return
                widget = self._find(widget_id)
                if not widget['locked']:
                    bounds = self._bounds(window)
                    widget['position'] = remember_position(bounds, displays())
                    self.applied[widget_id] = bounds
                    self._save()
                    return
            self._place(widget_id)
        except Exception as error:
            self.log(f'Віджети: збереження позиції, {type(error).__name__}')

    def update(self, widget_id, changes):
        with self.lock:
            widget = self._find(widget_id)
            window = self.windows.get(widget_id)
            if changes.get('locked') is True and not widget['locked'] and window:
                widget['position'] = remember_position(self._bounds(window), displays())
            if 'display_id' in changes and not any(d['id'] == changes['display_id'] for d in displays()):
                raise ValueError('Цей екран зараз не підключений')
            updated = validate_change(widget, changes)
            self.widgets[self.widgets.index(widget)] = updated
            self._save()
        if not updated['visible'] and window:
            with self.lock:
                self.windows.pop(widget_id, None)
                self.applied.pop(widget_id, None)
                timer = self.timers.pop(widget_id, None)
                if timer:
                    timer.cancel()
            window.destroy()
        elif updated['visible'] and not window:
            self._show(updated)
        elif window:
            self._place(widget_id)
            window.evaluate_js("window.dispatchEvent(new Event('widget-settings-changed'))")
        return self.snapshot(widget_id)

    def remove(self, widget_id):
        with self.lock:
            widget = self._find(widget_id)
            self.widgets.remove(widget)
            self._save()
            window = self.windows.pop(widget_id, None)
            self.applied.pop(widget_id, None)
            timer = self.timers.pop(widget_id, None)
            if timer:
                timer.cancel()
        if window:
            window.destroy()
        return self.snapshot()

    def _closed(self, widget_id, window):
        with self.lock:
            registered = self.windows.get(widget_id) is window
            if registered:
                self.windows.pop(widget_id, None)
                timer = self.timers.pop(widget_id, None)
                if timer:
                    timer.cancel()
                self.applied.pop(widget_id, None)
            widget = next((w for w in self.widgets if w['id'] == widget_id), None)
            if registered and widget and not self.stopping and widget['visible']:
                widget['visible'] = False
                self._save()

    def begin_drag(self, widget_id):
        with self.lock:
            if self._find(widget_id)['locked']:
                return False
            window = self.windows.get(widget_id)
        if window and sys.platform == 'win32':
            user = ctypes.WinDLL('user32')
            user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user.SendMessageW.restype = ctypes.c_ssize_t
            def drag(form):
                user.ReleaseCapture()
                user.SendMessageW(int(form.Handle.ToInt64()), 0xA1, 2, 0)
            self._native(window, drag)
            return True
        return False

    def resize(self, widget_id, width, height):
        with self.lock:
            widget = self._find(widget_id)
            if widget['locked']:
                return False
            if type(width) not in (int, float) or type(height) not in (int, float) or not 280 <= width <= 1000 or not 300 <= height <= 1200:
                raise ValueError('Некоректний розмір')
            monitors = displays()
            bounds = self._bounds(self.windows[widget_id])
            from desktop_widget_layout import choose_display
            screen = choose_display(bounds, monitors)
            desired = {**bounds, 'width': round(width * screen.get('scale', 1)), 'height': round(height * screen.get('scale', 1))}
            widget['position'] = remember_position(desired, monitors)
            self._save()
        self._place(widget_id)
        return True

    def resize_delta(self, widget_id, delta_x, delta_y, pixel_ratio):
        import math
        from desktop_widget_layout import choose_display
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in (delta_x, delta_y, pixel_ratio)) or not .5 <= pixel_ratio <= 4 or abs(delta_x) > 5000 or abs(delta_y) > 5000:
            raise ValueError('Некоректна зміна розміру')
        with self.lock:
            widget = self._find(widget_id)
            if widget['locked'] or max(abs(delta_x), abs(delta_y)) < 1:
                return False
            monitors = displays()
            bounds = self._bounds(self.windows[widget_id])
            screen = choose_display(bounds, monitors)
            scale, work = screen.get('scale', 1), screen['work']
            for key, delta, minimum, maximum in (('width', delta_x, 280, 1000), ('height', delta_y, 300, 1200)):
                lower = min(work[key], max(200 * scale, minimum * pixel_ratio))
                upper = min(work[key], 1600 * scale, maximum * pixel_ratio)
                bounds[key] = round(max(lower, min(upper, bounds[key] + delta * pixel_ratio)))
            widget['position'] = remember_position(bounds, monitors)
            self._save()
        self._place(widget_id)
        return True

    def _display_changed(self):
        with self.lock:
            if self.stopping:
                return
            if self.display_timer:
                self.display_timer.cancel()
            for timer in self.timers.values():
                timer.cancel()
            self.timers.clear()
            self.display_timer = threading.Timer(.7, self._restore_positions)
            self.display_timer.daemon = True
            self.display_timer.start()

    def _restore_positions(self):
        for widget_id in list(self.windows):
            try:
                self._place(widget_id)
            except Exception as error:
                self.log(f'Віджети: зміна екрана, {type(error).__name__}')

    def shutdown(self):
        with self.lock:
            self.stopping = True
            for widget_id in list(self.timers):
                window = self.windows.get(widget_id)
                widget = next((w for w in self.widgets if w['id'] == widget_id), None)
                if window and widget and not widget['locked']:
                    widget['position'] = remember_position(self._bounds(window), displays())
            if self.timers:
                self._save()
            for timer in self.timers.values():
                timer.cancel()
            self.timers.clear()
            if self.display_timer:
                self.display_timer.cancel()
            windows = list(self.windows.values())
            self.windows.clear()
        if self._display_handler:
            from Microsoft.Win32 import SystemEvents
            SystemEvents.DisplaySettingsChanged -= self._display_handler
            self._display_handler = None
        for window in windows:
            window.destroy()
