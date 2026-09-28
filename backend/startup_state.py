"""Shared progress for the launcher thread and the local HTTP interface."""
from threading import Lock
from time import monotonic


class StartupState:
    def __init__(self):
        self._lock = Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self._started = monotonic()
            self._steps = {
                "server": {"state": "pending", "message": "Підготовка програми"},
                "telegram": {"state": "pending", "message": "Telegram: перевірка підключення"},
                "logika": {"state": "pending", "message": "Logika: перевірка синхронізації"},
            }

    def set(self, key, state, message):
        with self._lock:
            self._steps[key] = {"state": state, "message": message}

    def snapshot(self):
        with self._lock:
            steps = {key: dict(value) for key, value in self._steps.items()}
            return {
                "steps": steps,
                "ready": steps["server"]["state"] == "done",
                "finished": all(s["state"] not in {"pending", "running"} for s in steps.values()),
                "elapsed_seconds": round(monotonic() - self._started, 1),
            }


startup_state = StartupState()
