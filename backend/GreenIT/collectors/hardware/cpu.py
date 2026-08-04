import psutil
#tree -f -I '.venv|.idea|__pycache__'

def collect():

    frequency = psutil.cpu_freq()

    return {
        "usage_percent": psutil.cpu_percent(interval=0.1),
        "per_core_usage": psutil.cpu_percent(interval=0.1, percpu=True),
        "frequency": (
            frequency._asdict()
            if frequency
            else None
        ),
        "times": psutil.cpu_times()._asdict(),
        "stats": psutil.cpu_stats()._asdict(),
        "logical_cores": psutil.cpu_count(logical=True),
        "physical_cores": psutil.cpu_count(logical=False),
    }