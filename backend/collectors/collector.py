from datetime import datetime

from collectors.hardware.hardware import collect as hardware
from collectors.windows.windows import collect as windows


def collect():
    """
    Collect every metric required by EcoInsight.
    """

    return {

        "timestamp": datetime.now().isoformat(),

        "hardware": hardware(),

        "windows": windows(),
    }


if __name__ == "__main__":

    from pprint import pprint

    pprint(collect())