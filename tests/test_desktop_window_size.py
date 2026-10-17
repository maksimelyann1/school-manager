from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_window_size import WindowSizeStore, fit_window_size


class WindowSizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'desktop/window-size.json'
        self.store = WindowSizeStore(self.path, Mock(), delay=60)

    def tearDown(self):
        self.store.flush()
        self.tmp.cleanup()

    def test_default_big_and_compact_screens(self):
        self.assertEqual(fit_window_size(None, (1536, 1210), (1080, 770), (2560, 1440)), (1536, 1210))
        self.assertEqual(fit_window_size(None, (1536, 1210), (1080, 770), (1920, 1080)), (1536, 770))

    def test_resize_saved_across_new_process_store(self):
        self.store.remember(1700, 1100)
        self.store.flush()
        self.assertEqual(WindowSizeStore(self.path, Mock()).read(), (1700, 1100))

    def test_drag_debounced_and_latest_size_flushed_at_exit(self):
        self.store.remember(1400, 900)
        first_timer = self.store.timer
        self.store.remember(1500, 1000)
        self.assertTrue(first_timer.finished.is_set())
        self.assertFalse(self.path.exists())
        self.store.flush()
        self.assertEqual(self.store.read(), (1500, 1000))
        self.assertIsNone(self.store.timer)

    def test_smaller_monitor_fits_saved_size_without_losing_preference(self):
        self.store.remember(1800, 1200)
        self.store.flush()
        self.assertEqual(fit_window_size(self.store.read(), (1536, 1210), (1080, 770), (1366, 768)), (1286, 688))
        self.assertEqual(self.store.read(), (1800, 1200))

    def test_saved_height_is_not_forced_to_compact_height(self):
        self.assertEqual(fit_window_size((1400, 920), (1536, 1210), (1080, 770), (1920, 1080)), (1400, 920))

    def test_invalid_or_corrupted_file_uses_defaults(self):
        self.path.parent.mkdir()
        for value in ('invalid json', '[]', '{"width": true, "height": 900}', '{"width": -5, "height": 900}'):
            self.path.write_text(value, encoding='utf-8')
            self.assertIsNone(self.store.read())

    def test_atomic_write_failure_retains_previous_file_and_logs(self):
        self.store.remember(1400, 900)
        self.store.flush()
        self.store.remember(1600, 1000)
        with patch('desktop_window_size.os.replace', side_effect=OSError('test')):
            self.store.flush()
        self.assertEqual(self.store.read(), (1400, 900))
        self.store.log.assert_called_once()
        self.store.flush()
        self.assertEqual(self.store.read(), (1600, 1000))

    def test_native_resize_ignores_maximize_and_minimize_then_returns_to_initial_size(self):
        import desktop_app as app
        window = SimpleNamespace(width=1500, height=1000)
        user32 = SimpleNamespace(IsZoomed=Mock(return_value=False), IsIconic=Mock(return_value=False))
        with patch.object(app, '_window', window), patch.object(app, '_main_window_size_ready', True), \
             patch.object(app, '_main_window_last_size', (1536, 1210)), \
             patch.object(app, '_window_size_store', self.store), patch.object(app, '_get_window_hwnd', return_value=1), \
             patch.object(app.ctypes, 'windll', SimpleNamespace(user32=user32)), patch.object(app.sys, 'platform', 'win32'):
            app._on_main_window_resized(1500, 1000)
            user32.IsZoomed.return_value = True
            window.width, window.height = 2560, 1440
            app._on_main_window_resized(2560, 1440)
            user32.IsZoomed.return_value = False
            user32.IsIconic.return_value = True
            window.width, window.height = 160, 30
            app._on_main_window_resized(160, 30)
            self.store.flush()
            self.assertEqual(self.store.read(), (1500, 1000))
            user32.IsIconic.return_value = False
            window.width, window.height = 1536, 1210
            app._on_main_window_resized(1536, 1210)
            self.store.flush()
            self.assertEqual(self.store.read(), (1536, 1210))

    def test_initial_show_does_not_overwrite_preference_with_dpi_scaled_size(self):
        import desktop_app as app
        self.store.remember(1400, 900)
        self.store.flush()
        window = SimpleNamespace(width=1750, height=1125, resize=Mock())
        def resize(width, height):
            window.width, window.height = width, height
        window.resize.side_effect = resize
        with patch.object(app, '_window', window), patch.object(app, '_main_window_size_ready', False), \
             patch.object(app, '_main_window_last_size', None), patch.object(app, '_window_size_store', self.store), \
             patch.object(app, '_get_main_window_size', return_value=(1400, 900)):
            app._on_main_window_shown()
            window.resize.assert_called_once_with(1400, 900)
            self.assertEqual(app._main_window_last_size, (1400, 900))
            app._on_main_window_shown()
            window.resize.assert_called_once()
