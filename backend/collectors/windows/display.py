import screen_brightness_control as sbc


def get_brightness():

    try:
        brightness = sbc.get_brightness()

        if isinstance(brightness, list):
            return int(brightness[0])

        return int(brightness)

    except Exception:
        return None


def get_monitor_count():

    try:
        return len(sbc.list_monitors())

    except Exception:
        return None


def collect():

    return {
        "brightness_percent": get_brightness(),
        "monitor_count": get_monitor_count(),

        # implemented later
        "display_on": None,
    }