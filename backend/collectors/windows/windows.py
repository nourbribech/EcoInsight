from . import display
from . import power
from . import session


def collect():

    return {

        "display": display.collect(),

        "power": power.collect(),

        "session": session.collect(),

    }