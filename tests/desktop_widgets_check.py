"""Real WinForms/WebView2 checks against widgets_preview.py; synthetic data only."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import webview
import desktop_app
from desktop_widgets import WidgetManager, displays
from desktop_widget_layout import resolve_position

temporary = tempfile.TemporaryDirectory(prefix='school-manager-widgets-check-')
result, logs, opened = {}, [], []
def new_manager():
    def open_target(*args, **kwargs):
        opened.append({'args': args, 'kwargs': kwargs})
        return desktop_app._open_widget_target(*args, **kwargs)
    return WidgetManager(Path(temporary.name) / 'widgets.json', open_target, logs.append, 'http://127.0.0.1:8769')


manager = new_manager()
desktop_app._widget_manager = manager


host = webview.create_window('Widgets verification host', 'http://127.0.0.1:8769/widgets', width=1280, height=750, hidden=True, js_api=desktop_app.DesktopApi())
desktop_app._window = host


def wait(window, script, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = window.evaluate_js(script)
            if value: return value
        except Exception:
            pass
        time.sleep(.15)
    raise AssertionError('Timed out: ' + script)


def check(name, condition):
    result[name] = bool(condition)
    if not condition: raise AssertionError(name)


def resources():
    import os
    command = f"$taskPids = [System.Collections.Generic.HashSet[int]]::new(); [void]$taskPids.Add({os.getpid()}); $taskProcesses = Get-CimInstance Win32_Process; do {{ $taskCount = $taskPids.Count; foreach ($taskProcess in $taskProcesses) {{ if ($taskPids.Contains([int]$taskProcess.ParentProcessId)) {{ [void]$taskPids.Add([int]$taskProcess.ProcessId) }} }} }} while ($taskCount -ne $taskPids.Count); $taskNative = Get-Process -Id @($taskPids) -ErrorAction SilentlyContinue; [pscustomobject]@{{ workingMB = [math]::Round(($taskNative | Measure-Object WorkingSet64 -Sum).Sum / 1MB, 1); privateMB = [math]::Round(($taskNative | Measure-Object PrivateMemorySize64 -Sum).Sum / 1MB, 1); cpuSeconds = ($taskNative | Measure-Object CPU -Sum).Sum; processes = $taskNative.Count }} | ConvertTo-Json -Compress"
    value = subprocess.check_output(['powershell.exe', '-NoProfile', '-Command', command], creationflags=subprocess.CREATE_NO_WINDOW)
    return json.loads(value)


def run():
    global manager
    try:
        host.events.loaded.wait(30)
        wait(host, "!!document.querySelector('.widgets-page')")
        manager.start()
        result['resource_host_only'] = resources()
        ids = {}
        for index, kind in enumerate(('calendar', 'agenda', 'lessons')):
            wait(host, "!!document.querySelector('.widget-choice button') && !document.querySelector('.widget-choice button').disabled")
            host.evaluate_js(f"document.querySelectorAll('.widget-choice button')[{index}].click()")
            deadline = time.monotonic() + 20
            while len(manager.widgets) <= index and time.monotonic() < deadline: time.sleep(.1)
            check('create_from_widgets_tab_' + kind, len(manager.widgets) == index + 1)
            data = manager.snapshot()
            widget_id = data['widgets'][-1]['id']; ids[kind] = widget_id
            window = manager.windows[widget_id]
            window.events.loaded.wait(30)
            wait(window, f"!!document.querySelector('.desktop-widget--{kind}')")
            wait(window, "!document.querySelector('[aria-busy=true]')")
        result['screen_count'] = len(displays())
        result['screens'] = [{k: d[k] for k in ('name', 'scale', 'work')} for d in displays()]
        check('three_live_widget_windows', len(manager.windows) == 3)
        window = manager.windows[ids['calendar']]
        native = {}
        manager._native(window, lambda form: native.update(border=int(form.FormBorderStyle), taskbar=bool(form.ShowInTaskbar), opacity=float(form.Opacity)))
        result['native'] = native
        check('no_system_title_bar', native['border'] == 0)
        check('no_widget_taskbar_button', not native['taskbar'])
        check('standalone_ui', window.evaluate_js("!document.querySelector('.sidebar') && !document.querySelector('.fc')"))
        manager.update(ids['calendar'], {'size': 'compact'})
        time.sleep(.3)
        result['compact_metrics'] = window.evaluate_js("({ width: innerWidth, height: innerHeight, dpr: devicePixelRatio, scrollWidth: document.documentElement.scrollWidth, footer: document.querySelector('.widget-footer').getBoundingClientRect().bottom })")
        result['compact_bounds'] = manager._bounds(window)
        check('compact_viewport_fits', window.evaluate_js("innerWidth >= 280 && innerWidth <= 390 && document.documentElement.scrollWidth <= innerWidth && document.querySelector('.widget-footer').getBoundingClientRect().bottom <= innerHeight"))
        before_resize = manager._bounds(window)
        ratio = window.evaluate_js('devicePixelRatio')
        from desktop_widgets import WidgetApi
        WidgetApi(manager, ids['calendar']).resize_widget(0, 0, ratio)
        check('resize_click_has_no_jump', manager._bounds(window) == before_resize)
        WidgetApi(manager, ids['calendar']).resize_widget(40, 30, ratio)
        resized = manager._bounds(window)
        check('resize_uses_actual_webview_dpi', abs(resized['width'] - before_resize['width'] - round(40 * ratio)) <= 1 and abs(resized['height'] - before_resize['height'] - round(30 * ratio)) <= 1)
        window.evaluate_js("document.querySelector('[aria-label=\"Наступний місяць\"]').click()")
        time.sleep(.2)
        check('month_navigation_keeps_selected_day_in_month', window.evaluate_js("!document.querySelector('.widget-month button[aria-pressed=true]').classList.contains('outside-month')"))
        window.evaluate_js("document.querySelector('.widget-month-title').click()")
        manager.update(ids['calendar'], {'size': 'regular'})
        manager.update(ids['calendar'], {'opacity': 70, 'on_top': True})
        manager._native(window, lambda form: native.update(opacity=float(form.Opacity), top=bool(form.TopMost)))
        check('native_opacity_and_topmost', abs(native['opacity'] - .7) < .01 and native['top'])
        import ctypes
        from ctypes import wintypes
        user = ctypes.WinDLL('user32')
        cursor = wintypes.POINT(); user.GetCursorPos(ctypes.byref(cursor))
        original = manager._bounds(window)
        pointer_x, pointer_y = original['x'] + 70, original['y'] + 25
        try:
            user.SetCursorPos(pointer_x, pointer_y)
            user.mouse_event(2, 0, 0, 0, 0)
            time.sleep(.5)
            for step in range(1, 7):
                user.SetCursorPos(pointer_x - step * 12, pointer_y + step * 8)
                time.sleep(.08)
            user.mouse_event(4, 0, 0, 0, 0)
            time.sleep(.6)
            dragged = manager._bounds(window)
            result['pointer_drag_delta'] = {'x': dragged['x'] - original['x'], 'y': dragged['y'] - original['y']}
            check('real_pointer_drag_header', dragged['x'] != original['x'] and dragged['y'] != original['y'])
        finally:
            user.mouse_event(4, 0, 0, 0, 0)
            user.SetCursorPos(cursor.x, cursor.y)
        manager.update(ids['calendar'], {'opacity': 100, 'on_top': False})
        for monitor in displays():
            manager.update(ids['calendar'], {'display_id': monitor['id']})
            saved = manager._find(ids['calendar'])
            expected = resolve_position(saved, displays())
            check('placement_' + monitor['device'], manager._bounds(window) == expected)
        monitor = displays()[1]
        manager._native(window, lambda form: (setattr(form, 'Left', monitor['work']['x'] + 200), setattr(form, 'Top', monitor['work']['y'] + 100)))
        time.sleep(.6)
        check('manual_move_remembers_actual_monitor', manager._find(ids['calendar'])['position']['display_id'] == monitor['id'])
        manager.update(ids['calendar'], {'locked': True})
        expected = manager._bounds(window)
        window.move(window.x + 80, window.y + 70)
        deadline = time.monotonic() + 8
        while manager._bounds(window) != expected and time.monotonic() < deadline: time.sleep(.2)
        check('locked_native_move_restored', manager._bounds(window) == expected)
        from unittest.mock import patch
        all_monitors = displays()
        preferred = json.loads(json.dumps(manager._find(ids['calendar'])['position']))
        with patch('desktop_widgets.displays', return_value=[all_monitors[0]]):
            manager._display_changed()
            time.sleep(1.1)
            fallback = manager._bounds(window)
            check('missing_monitor_native_fallback', fallback['x'] >= all_monitors[0]['work']['x'])
            check('missing_monitor_keeps_preference', manager._find(ids['calendar'])['position'] == preferred)
        manager._display_changed(); time.sleep(1.1)
        check('reconnected_monitor_native_restore', manager._bounds(window) == expected)
        check('windows_display_events_subscribed', manager._display_handler is not None)
        check('lock_keeps_content_interactive', window.evaluate_js("!!document.querySelector('.widget-month button') && !document.querySelector('.widget-resize')"))
        manager.update(ids['calendar'], {'locked': False})
        target = datetime.now().date() + timedelta(days=2)
        window.evaluate_js(f"[...document.querySelectorAll('.widget-month button')].find(b => b.textContent.trim() === '{target.day}' && !b.classList.contains('outside-month')).click()")
        wait(window, "!!document.querySelector('.widget-quick-form')")
        from uuid import uuid4
        title = 'ТЕСТ · Подія зі справжнього віджета ' + uuid4().hex[:6]
        window.evaluate_js("const input = document.querySelector('.widget-quick-form input'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, " + json.dumps(title) + "); input.dispatchEvent(new Event('input', { bubbles: true }));")
        wait(window, "!document.querySelector('.widget-save').disabled")
        window.evaluate_js("const select = document.querySelectorAll('.widget-quick-form select')[1]; Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(select, '10'); select.dispatchEvent(new Event('change', { bubbles: true }));")
        window.evaluate_js("const form = document.querySelector('.widget-quick-form'); form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));")
        wait(window, "!document.querySelector('.widget-quick-form')")
        check('calendar_date_creates_event', wait(window, 'document.body.innerText.includes(' + json.dumps(title) + ')'))
        data = json.load(urllib.request.urlopen('http://127.0.0.1:8769/api/tasks?bucket=calendar&start=' + target.isoformat() + '&end=' + (target + timedelta(days=1)).isoformat()))
        created = [item for item in data['items'] if item['title'] == title]
        check('saved_once_in_backend', len(created) == 1)
        saved = json.load(urllib.request.urlopen('http://127.0.0.1:8769/api/tasks/' + created[0]['id']))
        check('event_reminder_created', len(saved['reminders']) == 1 and saved['reminders'][0]['channel'] == 'system')
        window.evaluate_js("[...document.querySelectorAll('.widget-item-body')].find(b => b.textContent.includes(" + json.dumps(title) + ")).click()")
        deadline = time.monotonic() + 5
        while not opened and time.monotonic() < deadline: time.sleep(.1)
        check('click_opens_exact_event', opened[-1]['args'][1] == created[0]['id'])
        check('main_opens_event_editor', wait(host, "location.pathname === '/tasks' && [...document.querySelectorAll('input')].some(input => input.value === " + json.dumps(title) + ")"))
        host.hide()
        agenda = manager.windows[ids['agenda']]
        task_title = 'ТЕСТ · Виконання справи ' + uuid4().hex[:6]
        payload = json.dumps({'title': task_title, 'date': target.isoformat()}).encode()
        request = urllib.request.Request('http://127.0.0.1:8769/api/tasks', data=payload, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request) as response: json.load(response)
        agenda.evaluate_js("document.querySelector('[aria-label=\"Оновити віджет\"]').click()")
        checkbox = wait(agenda, "document.querySelector('.widget-item input[type=checkbox]')?.getAttribute('aria-label')")
        agenda.evaluate_js("document.querySelector('.widget-item input[type=checkbox]').click()")
        wait(agenda, "!document.querySelector('.widget-item input[type=checkbox]') || [...document.querySelectorAll('.widget-item input[type=checkbox]')].every(b => b.getAttribute('aria-label') !== " + json.dumps(checkbox) + ")")
        check('task_completion', True)
        lessons = manager.windows[ids['lessons']]
        check('paused_group_hidden', lessons.evaluate_js("!document.body.innerText.includes('Група на паузі')"))
        check('postponed_lesson_marked', lessons.evaluate_js("document.body.innerText.includes('перенесено')"))
        manager.resize(ids['calendar'], 410, 580)
        saved = manager._find(ids['calendar'])
        check('custom_size_persisted', saved['position']['width'] == 410 and saved['position']['height'] == 580)
        check('settings_reload', len(WidgetManager(manager.path, lambda *_: True, logs.append).widgets) == 3)
        result['resource_before_idle'] = resources()
        time.sleep(15)
        result['resource_after_idle'] = resources()
        result['idle_cpu_seconds'] = round(result['resource_after_idle']['cpuSeconds'] - result['resource_before_idle']['cpuSeconds'], 2)
        agenda.evaluate_js("document.querySelector('[aria-label=\"Приховати віджет\"]').click()")
        deadline = time.monotonic() + 8
        while ids['agenda'] in manager.windows and time.monotonic() < deadline: time.sleep(.1)
        check('hidden_widget_destroyed', ids['agenda'] not in manager.windows)
        manager.update(ids['agenda'], {'visible': True})
        new_window = manager.windows[ids['agenda']]
        new_window.events.loaded.wait(30)
        wait(new_window, "!!document.querySelector('.desktop-widget--agenda')")
        check('hidden_widget_reopens', new_window is not agenda)
        from PIL import ImageGrab
        bounds = manager._bounds(window)
        destination = ROOT / 'output/widgets/calendar-native.png'; destination.parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(bbox=(bounds['x'], bounds['y'], bounds['x'] + bounds['width'], bounds['y'] + bounds['height']), all_screens=True).save(destination)
        for widget_id in ids.values(): manager.update(widget_id, {'visible': False})
        time.sleep(3)
        result['resource_all_hidden'] = resources()
        for _ in range(3):
            manager.update(ids['agenda'], {'visible': True})
            current = manager.windows[ids['agenda']]
            current.events.loaded.wait(30)
            wait(current, "!!document.querySelector('.desktop-widget--agenda')")
            manager.update(ids['agenda'], {'visible': False})
            current.events.closed.wait(10)
        import gc
        gc.collect(); time.sleep(3)
        result['resource_after_reopen_cycles'] = resources()
        check('reopen_cycles_release_windows', len(manager.windows) == 0 and len(webview.windows) == 1)
        result['reopen_private_growth_mb'] = round(result['resource_after_reopen_cycles']['privateMB'] - result['resource_all_hidden']['privateMB'], 1)
        for widget_id in ids.values(): manager.update(widget_id, {'visible': True})
        for current in manager.windows.values(): current.events.loaded.wait(30)
        manager.shutdown()
        manager = new_manager(); desktop_app._widget_manager = manager
        manager.start()
        for current in manager.windows.values():
            current.events.loaded.wait(30)
            wait(current, "!!document.querySelector('.desktop-widget')")
        check('restart_restores_all_widgets', len(manager.windows) == 3)
        check('restart_restores_geometry', manager._find(ids['calendar'])['position']['width'] == 410)
        check('no_native_errors', not logs)
        result['ok'] = True
    except Exception as error:
        result.update(ok=False, error=f'{type(error).__name__}: {error}')
    finally:
        result['logs'] = logs
        manager.shutdown()
        result['shutdown_preserves_visibility'] = all(widget['visible'] for widget in WidgetManager(manager.path, lambda *_: True, logs.append).widgets)
        destination = ROOT / 'output/widgets/native-result.json'; destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        host.destroy(); temporary.cleanup()


if __name__ == '__main__':
    webview.start(run, gui='edgechromium', private_mode=True)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result.get('ok') else 1)
