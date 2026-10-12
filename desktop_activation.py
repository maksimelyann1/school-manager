"""Windows protocol registration and forwarding to the existing desktop process."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


def register_notification_protocol(protocol, script_path):
    import winreg
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        command = subprocess.list2cmdline([str(executable), "--notification-url", "%1"])
    else:
        pythonw = executable.with_name("pythonw.exe")
        command = subprocess.list2cmdline([str(pythonw if pythonw.exists() else executable),
                                          str(Path(script_path).resolve()), "--notification-url", "%1"])
    # Always quote the protocol argument, including paths with no spaces.
    command = command.removesuffix("%1") + '"%1"'
    key_path = rf"Software\Classes\{protocol}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:School Manager")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\shell\open\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    return command


class DesktopActivation:
    def __init__(self, identity, callback, log):
        key = hashlib.sha256(os.path.normcase(os.path.abspath(identity)).encode()).hexdigest()[:24]
        self.address = rf"\\.\pipe\SchoolManager-{key}"
        self.mutex_name = rf"Local\SchoolManager-{key}"
        self.callback, self.log = callback, log
        self.listener = self.handle = None
        self.stopped = threading.Event()
        self.thread = None

    def start(self, target=None, *, activate=True):
        from multiprocessing.connection import Listener
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        self.kernel.CreateMutexW.restype = ctypes.c_void_p
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.restype = ctypes.c_bool
        self.handle = self.kernel.CreateMutexW(None, False, self.mutex_name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            try:
                if activate:
                    self.forward(target)
            finally:
                self.close()
            return False
        try:
            self.listener = Listener(self.address, family="AF_PIPE")
            self.thread = threading.Thread(target=self._listen, name="notification-activation", daemon=True)
            self.thread.start()
        except Exception:
            self.close()
            raise
        return True

    def forward(self, target):
        from multiprocessing.connection import Client
        deadline = time.monotonic() + 5
        while True:
            try:
                with Client(self.address, family="AF_PIPE") as connection:
                    connection.send_bytes(json.dumps({"target": target}).encode())
                    if not connection.poll(2) or connection.recv_bytes(16) != b"ok":
                        raise RuntimeError("Програма не підтвердила відкриття сповіщення")
                    return
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Не вдалося передати сповіщення у відкриту програму")
                time.sleep(0.1)

    def _listen(self):
        from notification_navigation import normalize_target
        while not self.stopped.is_set():
            try:
                with self.listener.accept() as connection:
                    if not connection.poll(2):
                        continue
                    payload = json.loads(connection.recv_bytes(4096))
                    target = payload["target"]
                    if target is not None:
                        target = normalize_target(target)
                    connection.send_bytes(b"ok")
                    if not self.stopped.is_set():
                        self.callback(target)
            except Exception as error:
                if not self.stopped.is_set():
                    self.log(f"Не вдалося відкрити сповіщення: {error}")

    def close(self):
        self.stopped.set()
        if self.listener:
            if self.thread and self.thread.is_alive():
                from multiprocessing.connection import Client
                try:
                    with Client(self.address, family="AF_PIPE") as connection:
                        connection.send_bytes(b'{"target": null}')
                except OSError:
                    pass
            self.listener.close()
            self.listener = None
            if self.thread and self.thread is not threading.current_thread():
                self.thread.join(timeout=2)
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
