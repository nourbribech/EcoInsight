import psutil


def collect():
    
    return {
        "io": psutil.net_io_counters()._asdict(),

        "interfaces": {
            name: {
                "is_up": stat.isup,
                "speed_mbps": stat.speed,
                "duplex": stat.duplex,
                "mtu": stat.mtu,
            }

            for name, stat in psutil.net_if_stats().items()
        }
    }