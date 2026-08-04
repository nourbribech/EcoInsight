import psutil


def collect():

    return {
        "virtual": psutil.virtual_memory()._asdict(),
        "swap": psutil.swap_memory()._asdict(),
    }