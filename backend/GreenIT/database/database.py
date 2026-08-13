"""
SQLite database used to cache hardware
specifications retrieved from online sources.

The database prevents repeated Internet requests
for the same hardware.

Also stores the local measurement history (power/energy/carbon
estimates recorded by the estimation loop) in the same file, as a
separate table.
"""

from datetime import datetime
from pathlib import Path
import sqlite3

from GreenIT.models.power_estimate import PowerEstimate
from GreenIT.models.energy_estimate import EnergyEstimate
from GreenIT.models.carbon_estimate import CarbonEstimate
from GreenIT.models.snapshot import SystemMetricsSnapshot

# Database location
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATABASE_PATH = PROJECT_ROOT / "GreenIT" / "data" / "ecoinsight.db"
# Connection

def get_connection() -> sqlite3.Connection:
    """
    Create a SQLite connection.

    Returns
    -------
    sqlite3.Connection
    """

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row

    return connection


# Initialization

def initialize_database() -> None:
    """
    Create required tables if they do not already exist.
    """

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cpu_specs (

            cpu_model TEXT PRIMARY KEY,
            manufacturer TEXT,
            architecture TEXT,
            cores INTEGER,
            threads INTEGER,
            base_clock REAL,
            boost_clock REAL,
            tdp_watts INTEGER,
            socket TEXT,
            process_node_nm INTEGER,
            release_year INTEGER,
            source TEXT,
            last_updated TEXT
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS measurements (

            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            cpu_watts REAL NOT NULL,
            ram_watts REAL NOT NULL,
            baseline_watts REAL NOT NULL,
            total_watts REAL NOT NULL,
            interval_watt_hours REAL NOT NULL,
            cumulative_watt_hours REAL NOT NULL,
            interval_kg_co2eq REAL NOT NULL,
            cumulative_kg_co2eq REAL NOT NULL
        );
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS telemetry_history (

            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            cpu_usage_percent REAL NOT NULL,
            ram_usage_percent REAL NOT NULL,
            ram_used_bytes INTEGER NOT NULL,
            disk_read_bytes_per_second REAL NOT NULL,
            disk_write_bytes_per_second REAL NOT NULL,
            network_bytes_sent_per_second REAL NOT NULL,
            network_bytes_received_per_second REAL NOT NULL
        );
        """
    )

    connection.commit()
    connection.close()


# CPU Queries

def get_cpu(cpu_model: str):
    """
    Retrieve a CPU from the local cache.

    Parameters
    ----------
    cpu_model : str

    Returns
    -------
    sqlite3.Row | None
    """

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT *
        FROM cpu_specs
        WHERE cpu_model = ?
        """,
        (cpu_model,),
    )

    cpu = cursor.fetchone()

    connection.close()

    return cpu


def save_cpu(
        cpu_model: str,
        manufacturer: str,
        architecture: str,
        cores: int,
        threads: int,
        base_clock: float,
        boost_clock: float,
        tdp_watts: int | None,
        socket: str,
        process_node_nm: int | None,
        release_year: int | None,
        source: str | None,
        last_updated: str,
):
    """
    Save or update a CPU specification.
    """

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO cpu_specs(

            cpu_model,
            manufacturer,
            architecture,
            cores,
            threads,
            base_clock,
            boost_clock,
            tdp_watts,
            socket,
            process_node_nm,
            release_year,
            source,
            last_updated

        )

       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cpu_model,
            manufacturer,
            architecture,
            cores,
            threads,
            base_clock,
            boost_clock,
            tdp_watts,
            socket,
            process_node_nm,
            release_year,
            source,
            last_updated,
        ),
    )

    connection.commit()

    connection.close()


# Measurement history

def save_measurement(
        timestamp: datetime,
        power: PowerEstimate,
        energy: EnergyEstimate,
        carbon: CarbonEstimate,
) -> None:
    """
    Record one estimation-loop tick (power/energy/carbon) to history.
    """

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO measurements (

            timestamp,
            cpu_watts,
            ram_watts,
            baseline_watts,
            total_watts,
            interval_watt_hours,
            cumulative_watt_hours,
            interval_kg_co2eq,
            cumulative_kg_co2eq

        )

        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            timestamp.isoformat(),
            power.cpu_watts,
            power.ram_watts,
            power.baseline_watts,
            power.total_watts,
            energy.interval_watt_hours,
            energy.cumulative_watt_hours,
            carbon.interval_kg_co2eq,
            carbon.cumulative_kg_co2eq,
        ),
    )

    connection.commit()

    connection.close()

def save_telemetry_snapshot(snapshot: SystemMetricsSnapshot) -> None:
    """
    Record one telemetry snapshot to history, for trend/baseline analysis
    by the Recommendation Engine. Written on a slower cadence than power
    measurements — see the caller for the interval logic.
    """

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO telemetry_history (

            timestamp,
            cpu_usage_percent,
            ram_usage_percent,
            ram_used_bytes,
            disk_read_bytes_per_second,
            disk_write_bytes_per_second,
            network_bytes_sent_per_second,
            network_bytes_received_per_second

        )

        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.timestamp.isoformat(),
            snapshot.cpu.usage_percent,
            snapshot.memory.usage_percent,
            snapshot.memory.used_bytes,
            snapshot.disk.read_bytes_per_second,
            snapshot.disk.write_bytes_per_second,
            snapshot.network.bytes_sent_per_second,
            snapshot.network.bytes_received_per_second,
        ),
    )

    connection.commit()

    connection.close()