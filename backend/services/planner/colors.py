"""Google Calendar event palette (Colors.event IDs)."""
EVENT_COLORS = {
    '1': '#a4bdfc', '2': '#7ae7bf', '3': '#dbadff', '4': '#ff887c',
    '5': '#fbd75b', '6': '#ffb878', '7': '#46d6db', '8': '#e1e1e1',
    '9': '#5484ed', '10': '#51b749', '11': '#dc2127',
}


def google_color_id(color):
    if not color:
        return None
    rgb = tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
    def distance(value):
        return sum((channel - int(value[index:index + 2], 16)) ** 2
                   for channel, index in zip(rgb, (1, 3, 5)))
    return min(EVENT_COLORS, key=lambda key: distance(EVENT_COLORS[key]))


def event_color(color_id):
    return EVENT_COLORS.get(str(color_id))
