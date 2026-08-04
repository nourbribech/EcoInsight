"""
SQLite database used to cache hardware
specifications retrieved from online sources.

The database prevents repeated Internet requests
for the same hardware.
"""

from pathlib import Path
import sqlite3

# Database location

DATABASE_DIRECTORY = Path("data")
DATABASE_DIRECTORY.mkdir(exist_ok=True)

DATABASE_PATH = DATABASE_DIRECTORY / "ecoinsight.db"

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