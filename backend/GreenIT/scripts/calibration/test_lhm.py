import clr
import os

# Path to LibreHardwareMonitorLib.dll
dll_path = r"C:\Users\nbribech\Downloads\LibreHardwareMonitor\LibreHardwareMonitorLib.dll"

clr.AddReference(dll_path)

from LibreHardwareMonitor.Hardware import Computer


computer = Computer()

computer.IsCpuEnabled = True
computer.Open()


def update(hardware):
    hardware.Update()

    for sub in hardware.SubHardware:
        update(sub)


for hardware in computer.Hardware:

    update(hardware)

    print("=" * 60)
    print(f"Hardware: {hardware.Name}")
    print(f"Type: {hardware.HardwareType}")
    print()

    for sensor in hardware.Sensors:
        print(
            str(sensor.SensorType),
            "|",
            str(sensor.Name),
            "|",
            sensor.Value
        )

computer.Close()