from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_widget_layout import remember_position, resolve_position, validate_change
from desktop_widgets import WidgetManager, WidgetApi

SCREENS = [
    {'id': 'primary', 'primary': True, 'scale': 1, 'work': {'x': 0, 'y': 0, 'width': 1920, 'height': 1040}},
    {'id': 'left', 'scale': 1.5, 'work': {'x': -2560, 'y': 0, 'width': 2560, 'height': 1400}},
    {'id': 'right', 'scale': 1, 'work': {'x': 1920, 'y': -400, 'width': 1920, 'height': 1040}},
]


class WidgetPlacementTests(unittest.TestCase):
    def widget(self, bounds):
        return {'kind': 'calendar', 'size': 'regular', 'position': remember_position(bounds, SCREENS)}

    def test_three_monitors_negative_coordinates_and_scale(self):
        for bounds in ({'x': -2300, 'y': 200, 'width': 570, 'height': 780}, {'x': 2100, 'y': -300, 'width': 380, 'height': 520}):
            widget = self.widget(bounds)
            self.assertEqual(resolve_position(widget, SCREENS), bounds)

    def test_missing_monitor_fallback_does_not_change_preference(self):
        widget = self.widget({'x': -2300, 'y': 200, 'width': 570, 'height': 780})
        saved = deepcopy(widget)
        fallback = resolve_position(widget, [SCREENS[0]])
        self.assertGreaterEqual(fallback['x'], 0)
        self.assertEqual(widget, saved)
        self.assertEqual(resolve_position(widget, SCREENS)['x'], -2300)

    def test_reordered_screens_and_changed_resolution(self):
        widget = self.widget({'x': -2300, 'y': 200, 'width': 570, 'height': 780})
        altered = deepcopy(SCREENS)
        altered[1]['work'] = {'x': 4000, 'y': 0, 'width': 1920, 'height': 1040}
        altered[1]['scale'] = 1
        bounds = resolve_position(widget, list(reversed(altered)))
        self.assertGreaterEqual(bounds['x'], 4000)
        self.assertLessEqual(bounds['x'] + bounds['width'], 5920)
        self.assertEqual(bounds['width'], 380)

    def test_tiny_work_area_is_fully_visible(self):
        widget = {'size': 'large', 'position': None}
        bounds = resolve_position(widget, [{'id': 'tiny', 'work': {'x': 0, 'y': 0, 'width': 300, 'height': 350}}])
        self.assertEqual(bounds, {'x': 0, 'y': 0, 'width': 300, 'height': 350})

    def test_custom_size_survives_loading_and_lock(self):
        widget = self.widget({'x': 50, 'y': 60, 'width': 400, 'height': 600})
        widget.update(visible=True, locked=False, on_top=False, opacity=85)
        updated = validate_change(widget, {'size': 'regular', 'locked': True})
        self.assertEqual(updated['position']['width'], 400)
        self.assertEqual(widget['locked'], False)

    def test_invalid_changes_rejected(self):
        widget = {'size': 'regular'}
        for values in ({'opacity': 0}, {'opacity': True}, {'locked': 1}, {'size': 'huge'}, {'url': 'https://example.com'}):
            with self.assertRaises(ValueError): validate_change(widget, values)


class WidgetPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'widgets.json'
        self.logs = []
        self.displays = patch('desktop_widgets.displays', return_value=SCREENS)
        self.displays.start()

    def tearDown(self):
        self.displays.stop(); self.temp.cleanup()

    def manager(self):
        manager = WidgetManager(self.path, lambda *_: True, self.logs.append)
        manager._show = lambda widget: None
        return manager

    def test_create_settings_persist_and_remove(self):
        manager = self.manager()
        widget = manager.create('calendar')['widgets'][0]
        manager.update(widget['id'], {'opacity': 70, 'locked': True, 'display_id': 'left'})
        restored = self.manager()
        self.assertEqual(restored.widgets[0]['opacity'], 70)
        self.assertEqual(restored.widgets[0]['position']['display_id'], 'left')
        restored.remove(widget['id'])
        self.assertEqual(self.manager().widgets, [])

    def test_corrupt_settings_preserved_before_new_configuration(self):
        self.path.write_text('not json', encoding='utf-8')
        manager = self.manager()
        self.assertIn('Початковий файл збережено', manager.snapshot()['error'])
        self.assertEqual(self.path.read_text(), 'not json')
        manager.create('agenda')
        backup = next(self.path.parent.glob('widgets-unreadable-*.json'))
        self.assertEqual(backup.read_text(), 'not json')
        self.assertEqual(len(self.manager().widgets), 1)

    def test_custom_dimensions_restored_from_file(self):
        manager = self.manager()
        manager.create('calendar')
        manager.widgets[0]['position'] = remember_position({'x': 50, 'y': 60, 'width': 400, 'height': 600}, SCREENS)
        manager._save()
        self.assertEqual(self.manager().widgets[0]['position']['width'], 400)

    def test_limits_and_invalid_monitor_do_not_damage_config(self):
        manager = self.manager()
        widget = manager.create('agenda')['widgets'][0]
        before = self.path.read_text()
        with self.assertRaises(ValueError): manager.update(widget['id'], {'display_id': 'missing'})
        with self.assertRaises(ValueError): manager.update(widget['id'], {'opacity': 101})
        self.assertEqual(self.path.read_text(), before)
        for _ in range(7): manager.create('agenda')
        with self.assertRaises(ValueError): manager.create('calendar')
        self.assertEqual(len(json.loads(self.path.read_text())['widgets']), 8)

    def test_late_close_does_not_remove_reopened_window_state(self):
        manager = self.manager()
        widget = manager.create('calendar')['widgets'][0]
        old_window, new_window = object(), object()
        manager.windows[widget['id']] = new_window
        manager.applied[widget['id']] = {'x': 30, 'y': 40}
        manager._closed(widget['id'], old_window)
        self.assertIs(manager.windows[widget['id']], new_window)
        self.assertEqual(manager.applied[widget['id']], {'x': 30, 'y': 40})
        self.assertTrue(manager._find(widget['id'])['visible'])

    def test_native_action_errors_logged_without_private_arguments(self):
        manager = self.manager()
        manager.open_target = lambda **kwargs: kwargs
        api = WidgetApi(manager, '11111111111111111111111111111111')
        self.assertEqual(api.open_widget_lesson(12), {'lesson_id': 12})
        with self.assertRaises(ValueError): api.update_widget({'opacity': 0})
        self.assertEqual(self.logs, ['Не вдалося змінити віджет: ValueError'])

    def test_resize_delta_respects_renderer_dpi_without_moving_origin(self):
        manager = self.manager()
        widget_id = manager.create('calendar')['widgets'][0]['id']
        manager.windows[widget_id] = object()
        manager._bounds = lambda window: {'x': 50, 'y': 60, 'width': 400, 'height': 500}
        manager._place = lambda widget_id: None
        before = self.path.read_text()
        self.assertFalse(manager.resize_delta(widget_id, 0, 0, 1.25))
        self.assertEqual(self.path.read_text(), before)
        self.assertTrue(manager.resize_delta(widget_id, 40, 30, 1.25))
        bounds = resolve_position(manager._find(widget_id), SCREENS)
        self.assertEqual(bounds, {'x': 50, 'y': 60, 'width': 450, 'height': 538})
        with self.assertRaises(ValueError): manager.resize_delta(widget_id, float('nan'), 10, 1.25)


if __name__ == '__main__': unittest.main()
