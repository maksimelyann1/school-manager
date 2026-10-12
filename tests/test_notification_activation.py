"""Notification destinations, Windows IPC and queued desktop activation."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
import desktop_app as desktop
from desktop_activation import DesktopActivation, register_notification_protocol
from notification_navigation import normalize_target, notification_uri, target_from_uri
import system_notifications


class NotificationTargetTests(unittest.TestCase):
    def test_each_destination_survives_windows_uri_activation(self):
        for target in ('/', '/parents-report?tab=pending&lesson_id=19',
                       '/parents-report?tab=runs&run_id=106',
                       f'/tasks?item_id={uuid4().hex}', '/tasks?bucket=reminders',
                       '/auto-messages?message_id=8', '/auto-messages'):
            with self.subTest(target=target):
                self.assertEqual(target_from_uri(notification_uri(target)), target)

    def test_invalid_destinations_never_become_commands_or_external_navigation(self):
        for target in ('https://example.com', '//example.com/tasks', '/tasks/../settings',
                       '/settings', '/tasks?item_id=bad', '/tasks?bucket=unknown',
                       '/parents-report?tab=pending&lesson_id=-1', '/parents-report?tab=runs&tab=pending',
                       '/auto-messages?message_id=1%0A', '/tasks#javascript:alert(1)',
                       '/tasks?anything=abc', '/tasks\n'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                normalize_target(target)
        for uri in ('https://open/tasks', 'schoolmanager://evil/tasks',
                    'schoolmanager://open/tasks#x', 'schoolmanager://open/tasks\n'):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                target_from_uri(uri)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows winotify adapter')
    def test_toast_body_contains_valid_xml_and_the_exact_click_target(self):
        import winotify
        with patch.object(winotify, '_run_ps') as powershell, \
             patch.object(system_notifications, '_notification_icon_path', return_value=''):
            self.assertTrue(system_notifications._show_windows_notification(
                'Потрібно відправити звіт', 'Група', '/parents-report?tab=pending&lesson_id=19'))
        script = powershell.call_args.kwargs['command']
        toast = ET.fromstring(re.search(r'<toast .*?</toast>', script, re.S).group())
        self.assertEqual(toast.attrib['activationType'], 'protocol')
        self.assertEqual(target_from_uri(toast.attrib['launch']), '/parents-report?tab=pending&lesson_id=19')

    def test_disabled_notifications_do_not_activate_anything(self):
        with patch.object(system_notifications, '_settings_enabled', return_value=False), \
             patch.object(system_notifications, '_show_windows_notification') as show:
            self.assertFalse(system_notifications.show_system_notification('t', 'm', target='/tasks'))
            show.assert_not_called()


class DesktopNavigationTests(unittest.TestCase):
    def setUp(self):
        self.stack = __import__('contextlib').ExitStack()
        for name, value in [('_window', None), ('_splash_window', None),
                            ('_pending_notification_target', None), ('_activation_requested', threading.Event()),
                            ('_activation_server', None), ('_bring_window_to_foreground_async', Mock()),
                            ('_get_window_hwnd', Mock(return_value=None)),
                            ('log_launcher', Mock()), ('_get_widget_manager', Mock())]:
            self.stack.enter_context(patch.object(desktop, name, value))

    def tearDown(self):
        self.stack.close()

    def test_click_while_starting_is_queued_and_consumed_when_interface_is_ready(self):
        target = '/parents-report?tab=runs&run_id=8'
        desktop._open_notification_target(target)
        self.assertEqual(desktop._pending_notification_target, target)
        window = Mock()
        window.get_current_url.return_value = 'http://127.0.0.1:8001/'
        desktop._window = window
        desktop._on_interface_loaded()
        desktop._get_widget_manager.return_value.start.assert_called_once()
        window.show.assert_called_once()
        window.restore.assert_called_once()
        self.assertIn(json.dumps(target), window.evaluate_js.call_args.args[0])
        self.assertIn('school-manager-navigate', window.evaluate_js.call_args.args[0])
        self.assertIsNone(desktop._pending_notification_target)

    def test_loading_html_does_not_consume_the_queued_navigation(self):
        desktop._window = Mock()
        desktop._window.get_current_url.return_value = None
        desktop._open_notification_target('/tasks?bucket=reminders')
        desktop._window.evaluate_js.assert_not_called()
        self.assertEqual(desktop._pending_notification_target, '/tasks?bucket=reminders')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows window state')
    def test_notification_preserves_an_already_maximized_window(self):
        desktop._window = Mock()
        desktop._window.get_current_url.return_value = 'http://127.0.0.1:8001/'
        with patch.object(desktop, '_get_window_hwnd', return_value=123), \
             patch.object(desktop.ctypes, 'windll') as native:
            native.user32.IsIconic.return_value = False
            desktop._open_notification_target('/parents-report?tab=pending')
        desktop._window.show.assert_called_once()
        desktop._window.restore.assert_not_called()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows process forwarding')
    def test_second_launch_never_creates_another_window_or_backend(self):
        with patch.object(sys, 'argv', ['app', '--notification-url', 'schoolmanager://open/tasks']), \
             patch.object(desktop, 'DesktopActivation') as server, \
             patch.object(desktop, '_create_initial_window') as create, \
             patch.object(desktop.webview, 'start') as start:
            server.return_value.start.return_value = False
            desktop.main()
            server.return_value.start.assert_called_once_with('/tasks', activate=True)
            create.assert_not_called()
            start.assert_not_called()

    def test_invalid_protocol_argument_does_not_start_the_application(self):
        with patch.object(sys, 'argv', ['app', '--notification-url', 'file:///C:/Windows']), \
             patch.object(desktop, 'DesktopActivation') as server:
            desktop.main()
            server.assert_not_called()

    def test_protocol_argument_cannot_inject_extra_launch_flags(self):
        with patch.object(sys, 'argv', ['app', '--notification-url', 'schoolmanager://open/tasks', '--smoke-test']), \
             patch.object(desktop, 'DesktopActivation') as server:
            desktop.main()
            server.assert_not_called()

    def test_old_notification_can_open_archived_report_outside_the_recent_list(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from models import Base, ParentReportRun
        from routers.parents_report import get_report_runs
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            db.add_all(ParentReportRun(lesson_group_name=f'Group {n}', status='success', message=f'Report {n}',
                                      lesson_date='2026-10-10', created_at='2026-10-10T18:00:00+03:00')
                       for n in range(102))
            db.commit()
            rows = get_report_runs(limit=100, run_id=1, db=db)
            self.assertEqual(rows[0]['id'], 1)
            self.assertEqual(rows[0]['message'], 'Report 0')
        engine.dispose()


@unittest.skipUnless(sys.platform == 'win32', 'Windows mutex and named pipes')
class NativeActivationTests(unittest.TestCase):
    def test_windows_shell_launches_registered_handler_and_forwards_the_target(self):
        import winreg
        received, ready = [], threading.Event()
        scheme = 'schoolmanager-test-' + uuid4().hex
        registry_path = rf'Software\Classes\{scheme}'
        def clicked(target):
            received.append(target)
            ready.set()
        with tempfile.TemporaryDirectory() as temp:
            primary = DesktopActivation(temp, clicked, lambda *args: None)
            self.assertTrue(primary.start())
            try:
                handler = Path(temp) / 'notification handler.py'
                handler.write_text(
                    f'import sys\nsys.path[:0] = {[str(ROOT), str(ROOT / "backend")]!r}\n'
                    'from desktop_activation import DesktopActivation\n'
                    'from notification_navigation import target_from_uri\n'
                    f'target = target_from_uri(sys.argv[2].replace({scheme!r}, "schoolmanager-dev", 1))\n'
                    f'DesktopActivation({temp!r}, lambda t: None, print).forward(target)\n', encoding='utf-8')
                register_notification_protocol(scheme, handler)
                os.startfile(f'{scheme}://open/parents-report?tab=pending&lesson_id=19')
                self.assertTrue(ready.wait(10), 'Windows did not activate the registered protocol')
                self.assertEqual(received, ['/parents-report?tab=pending&lesson_id=19'])
            finally:
                primary.close()
                for suffix in (r'\shell\open\command', r'\shell\open', r'\shell', ''):
                    try:
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, registry_path + suffix)
                    except FileNotFoundError:
                        pass

    def test_running_instance_receives_clicks_and_releases_resources(self):
        received, ready = [], threading.Event()
        def clicked(target):
            received.append(target)
            ready.set()
        with tempfile.TemporaryDirectory() as temp:
            primary = DesktopActivation(temp, clicked, lambda *args: None)
            self.assertTrue(primary.start())
            try:
                secondary = DesktopActivation(temp, lambda target: self.fail('Started duplicate'), lambda *args: None)
                self.assertFalse(secondary.start('/parents-report?tab=pending&lesson_id=19'))
                self.assertTrue(ready.wait(2))
                self.assertEqual(received, ['/parents-report?tab=pending&lesson_id=19'])
                self.assertIsNone(secondary.handle)
                quiet = DesktopActivation(temp, Mock(), lambda *args: None)
                self.assertFalse(quiet.start(activate=False))
                self.assertEqual(len(received), 1)
            finally:
                primary.close()
            self.assertFalse(primary.thread.is_alive())
            restarted = DesktopActivation(temp, clicked, lambda *args: None)
            self.assertTrue(restarted.start())
            restarted.close()

    def test_protocol_registration_quotes_executable_and_uri_without_modifying_registry(self):
        import winreg
        with patch.object(winreg, 'CreateKey') as create, patch.object(winreg, 'SetValueEx') as write:
            command = register_notification_protocol('schoolmanager-dev', ROOT / 'desktop_app.py')
        self.assertTrue(command.endswith('--notification-url "%1"'))
        self.assertIn('desktop_app.py"', command)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(write.call_count, 3)


if __name__ == '__main__':
    unittest.main()
