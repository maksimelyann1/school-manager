from system_notifications import show_system_notification, system_notifications_supported


def windows_notifications_supported() -> bool:
    return system_notifications_supported()


def show_windows_notification(title: str, message: str) -> bool:
    return show_system_notification(title, message)
