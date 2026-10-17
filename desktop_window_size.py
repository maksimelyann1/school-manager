"""Remember the normal main-window size without continuous disk writes."""
import json
import os
from pathlib import Path
import threading


class WindowSizeStore:
    def __init__(self, path, log, delay=0.5):
        self.path = Path(path)
        self.log = log
        self.delay = delay
        self.lock = threading.RLock()
        self.pending = None
        self.timer = None

    def read(self):
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            size = value['width'], value['height']
            if all(type(number) is int and 200 <= number <= 20000 for number in size):
                return size
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.log(f'Window size read failed: {error}')
        return None

    def remember(self, width, height):
        if not all(type(number) is int and 200 <= number <= 20000 for number in (width, height)):
            return
        with self.lock:
            self.pending = width, height
            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(self.delay, self.flush)
            self.timer.daemon = True
            self.timer.start()

    def flush(self):
        with self.lock:
            if self.timer:
                self.timer.cancel()
                self.timer = None
            if self.pending is None:
                return
            width, height = self.pending
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'width': width, 'height': height}), encoding='utf-8')
                os.replace(temporary, self.path)
                self.pending = None
            except OSError as error:
                self.log(f'Window size save failed: {error}')


def fit_window_size(saved, default, minimum, screen=None):
    width, height = saved or default
    if screen is None:
        return max(minimum[0], width), max(minimum[1], height)
    available = max(1, screen[0] - 80), max(1, screen[1] - 80)
    if saved is None and (available[0] < default[0] or available[1] < default[1]):
        height = minimum[1]
    return (min(max(minimum[0], width), available[0]),
            min(max(minimum[1], height), available[1]))
