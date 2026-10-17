"""Two isolated native launches; no backend, accounts, or user preferences."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop_app as app
from desktop_window_size import WindowSizeStore

parser = argparse.ArgumentParser()
parser.add_argument('directory', type=Path)
parser.add_argument('--restore', action='store_true')
args = parser.parse_args()
args.directory.mkdir(parents=True, exist_ok=True)
app._window_size_store = WindowSizeStore(args.directory / 'window-size.json', print)
app._style_native_title_bar_async = lambda window: None
app._start_exit_worker = app._window_size_store.flush
app._request_backend_shutdown = lambda: None
width, height = app._get_main_window_size()
window = app.webview.create_window('ТЕСТ · Збереження розміру', html='<p>Перевірка розміру вікна</p>',
                                  width=width, height=height, min_size=(600, 400), hidden=True)
app._window = window
app._attach_main_window_events(window)
result = {}


def wait_for(test):
    deadline = time.monotonic() + 5
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError('Native window event timeout')
        time.sleep(0.05)


def check():
    try:
        window.events.loaded.wait(10)
        window.show()
        wait_for(lambda: app._main_window_size_ready)
        if args.restore:
            result['restored'] = [window.width, window.height]
            assert result['restored'] == [1300, 880], result
        else:
            window.resize(1300, 880)
            wait_for(lambda: app._window_size_store.pending == (1300, 880))
            app._window_size_store.flush()
            result['saved'] = app._window_size_store.read()
            assert result['saved'] == (1300, 880)
            window.maximize()
            wait_for(lambda: app._main_window_maximized)
            time.sleep(0.6)
            assert app._window_size_store.read() == (1300, 880)
            window.minimize()
            wait_for(lambda: app._main_window_minimized)
            time.sleep(0.6)
            assert app._window_size_store.read() == (1300, 880)
            result['maximize_minimize_preserved'] = True
        result['ok'] = True
    except Exception as error:
        result.update(ok=False, error=str(error))
    finally:
        window.destroy()


app.webview.start(check, gui='edgechromium')
(args.directory / ('restore.json' if args.restore else 'resize.json')).write_text(json.dumps(result), encoding='utf-8')
print(json.dumps(result))
sys.exit(0 if result.get('ok') else 1)
