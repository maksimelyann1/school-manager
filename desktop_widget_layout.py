"""Persistent widget placement independent of Windows and GUI threads."""
from copy import deepcopy

KINDS = {'calendar': 'Календар', 'agenda': 'Мої справи', 'lessons': 'Найближчі уроки'}
SIZES = {'compact': (340, 430), 'regular': (380, 520), 'large': (440, 620)}


def choose_display(bounds, displays):
    def intersection(display):
        area = display['work']
        return max(0, min(bounds['x'] + bounds['width'], area['x'] + area['width']) - max(bounds['x'], area['x'])) * max(0, min(bounds['y'] + bounds['height'], area['y'] + area['height']) - max(bounds['y'], area['y']))
    return max(displays, key=intersection)


def remember_position(bounds, displays):
    display = choose_display(bounds, displays)
    area = display['work']
    scale = display.get('scale', 1)
    return {'display_id': display['id'], 'width': round(bounds['width'] / scale), 'height': round(bounds['height'] / scale),
            'u': max(0, min(1, (bounds['x'] - area['x']) / max(1, area['width'] - bounds['width']))),
            'v': max(0, min(1, (bounds['y'] - area['y']) / max(1, area['height'] - bounds['height'])))}


def resolve_position(widget, displays, index=0):
    preferred = widget.get('position') or {}
    display = next((d for d in displays if d['id'] == preferred.get('display_id')), None)
    display = display or next((d for d in displays if d.get('primary')), displays[0])
    area = display['work']
    scale = display.get('scale', 1)
    defaults = SIZES[widget['size']]
    width = min(area['width'], round(preferred.get('width', defaults[0]) * scale))
    height = min(area['height'], round(preferred.get('height', defaults[1]) * scale))
    u, v = preferred.get('u', 1), preferred.get('v', min(.8, .08 + .12 * index))
    return {'x': round(area['x'] + max(0, area['width'] - width) * u),
            'y': round(area['y'] + max(0, area['height'] - height) * v), 'width': width, 'height': height}


def validate_change(widget, changes):
    if not isinstance(changes, dict) or set(changes) - {'visible', 'locked', 'on_top', 'opacity', 'size', 'display_id'}:
        raise ValueError('Невідоме налаштування віджета')
    result = deepcopy(widget)
    for key in ('visible', 'locked', 'on_top'):
        if key in changes:
            if type(changes[key]) is not bool:
                raise ValueError('Некоректний перемикач віджета')
            result[key] = changes[key]
    if 'opacity' in changes:
        value = changes['opacity']
        if type(value) is not int or not 35 <= value <= 100:
            raise ValueError('Непрозорість має бути від 35 до 100%')
        result['opacity'] = value
    if 'size' in changes:
        if changes['size'] not in SIZES:
            raise ValueError('Невідомий розмір віджета')
        result['size'] = changes['size']
        if result.get('position') and changes['size'] != widget['size']:
            result['position']['width'], result['position']['height'] = SIZES[changes['size']]
    if 'display_id' in changes:
        if not isinstance(changes['display_id'], str):
            raise ValueError('Невідомий екран')
        width, height = SIZES[result['size']]
        result['position'] = {**(result.get('position') or {'u': 1, 'v': .08, 'width': width, 'height': height}), 'display_id': changes['display_id']}
    return result
