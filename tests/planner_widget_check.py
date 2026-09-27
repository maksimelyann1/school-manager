"""Exercise the real WebView2 widget against tests/planner_preview.py; no user services."""
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
import time
from unittest.mock import patch
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import desktop_app
import webview

result = {}
api = desktop_app.DesktopApi()
create_window = webview.create_window
host = create_window('Planner verification host', 'http://127.0.0.1:8766/tasks', hidden=True)

def test_window(title, url, **options):
    options['hidden'] = True
    return create_window(title, url.replace('127.0.0.1:8001', '127.0.0.1:8766'), **options)

def wait_for(window, script):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        value = window.evaluate_js(script)
        if value:
            return value
        time.sleep(.2)
    raise AssertionError('Widget did not reach expected state')

def run():
    try:
        with patch.object(desktop_app.webview, 'create_window', side_effect=test_window):
            api.open_task_widget()
            first = api._task_widget
            first.events.loaded.wait(20)
            result['widget_title'] = wait_for(first, "document.querySelector('.planner-widget h2')?.textContent")
            result['sidebar_hidden'] = first.evaluate_js("getComputedStyle(document.querySelector('.sidebar')).display === 'none'")
            with patch.object(first, 'show'), patch.object(first, 'restore'):
                api.open_task_widget()
            result['same_window'] = first is api._task_widget
            host.events.loaded.wait(20)
            wait_for(host, "!!document.querySelector('.planner')")
            host.evaluate_js("history.pushState({}, '', '/tasks?widget-test'); window.dispatchEvent(new PopStateEvent('popstate'))")
            with patch.object(desktop_app, '_window', host), patch.object(host, 'show'), patch.object(host, 'restore'), patch.object(desktop_app, '_bring_window_to_foreground_async'):
                first.evaluate_js("document.querySelector('.planner-open-main').click()")
                result['opens_main_planner'] = wait_for(host, "location.pathname === '/tasks' && !location.search")
            payload = json.dumps({'title': 'Перевірка віджету', 'date': (datetime.now().date() + timedelta(days=1)).isoformat()}).encode()
            request = urllib.request.Request('http://127.0.0.1:8766/api/tasks', data=payload, headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request) as response:
                task = json.load(response)
            first.evaluate_js("document.querySelector('[aria-label=\"Оновити задачі\"]').click()")
            wait_for(first, f'document.body.innerText.includes({json.dumps(task["title"])})')
            payload = json.dumps({'revision': task['revision'], 'status': 'done'}).encode()
            request = urllib.request.Request('http://127.0.0.1:8766/api/tasks/' + task['id'], data=payload, headers={'Content-Type': 'application/json'}, method='PATCH')
            with urllib.request.urlopen(request) as response:
                result['completion_api'] = json.load(response)['status'] == 'done'
            first.evaluate_js("document.querySelector('[aria-label=\"Оновити задачі\"]').click()")
            result['completion_visible'] = wait_for(first, '!' + f'document.body.innerText.includes({json.dumps(task["title"])})')
            first.destroy()
            deadline = time.monotonic() + 10
            while api._task_widget is not None and time.monotonic() < deadline:
                time.sleep(.1)
            result['closed_reference_cleared'] = api._task_widget is None
            api.open_task_widget()
            second = api._task_widget
            result['reopens_new_window'] = second is not first
            second.events.loaded.wait(20)
            wait_for(second, "!!document.querySelector('.planner-widget')")
            second.destroy()
        result['ok'] = all(v is not False for v in result.values())
    except Exception as error:
        result.update(ok=False, error=f'{type(error).__name__}: {error}')
    finally:
        Path(ROOT / 'output/playwright/widget-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        if api._task_widget is not None:
            api._task_widget.destroy()
        host.destroy()

if __name__ == '__main__':
    webview.start(run, gui='edgechromium', private_mode=True)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result.get('ok') else 1)
