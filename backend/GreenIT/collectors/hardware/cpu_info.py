"""
collectors/hardware/cpu_info.py

Retrieve CPU information directly from Windows using WMI.

This module DOES NOT estimate power.
It only reports hardware information.
"""

import platform
import wmi


def get_cpu_info() -> dict | None:
    """
    Retrieve CPU information from Windows.

    Returns
    -------
    dict | None
        Dictionary containing CPU information.
    """

    try:
        connection = wmi.WMI()

        cpu = connection.Win32_Processor()[0]

        return {

            # Human-readable model
            "model": cpu.Name.strip(),

            # Intel / AMD
            "manufacturer": cpu.Manufacturer,

            # Number of physical cores
            "cores": cpu.NumberOfCores,

            # Number of logical processors
            "threads": cpu.NumberOfLogicalProcessors,

            # MHz → GHz
            "base_clock": round(cpu.MaxClockSpeed / 1000, 2),

            # WMI does not expose boost frequency
            "boost_clock": None,

            # x64, x86...
            "architecture": platform.machine(),

            # Usually CPU socket (CPU Socket 1)
            "socket": cpu.SocketDesignation,

            # Filled after online lookup
            "process_node_nm": None,

            # Filled after online lookup
            "release_year": None,

        }

    except Exception as error:

        print(f"[CPU INFO] {error}")

        return None


if __name__ == "__main__":

    from pprint import pprint

    pprint(get_cpu_info())