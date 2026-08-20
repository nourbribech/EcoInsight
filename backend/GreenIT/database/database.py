"""
SQLite database used to cache hardware
specifications retrieved from online sources.

The database prevents repeated Internet requests
for the same hardware.

Also stores the local measurement history (power/energy/carbon
estimates recorded by the estimation loop) in the same file, as a
separate table.
"""

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Optional

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
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            metric TEXT NOT NULL,
            message TEXT NOT NULL,
            current_value REAL NOT NULL,
            -- Nullable: only the statistical rules (cpu/ram vs a rolling
            -- baseline) have a mean and stdev. Threshold rules such as idle
            -- waste have no baseline at all, and storing 0.0 there would be
            -- a fabricated number rather than an absent one.
            baseline_mean REAL,
            baseline_stdev REAL
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS process_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            name TEXT NOT NULL,
            cpu_percent REAL NOT NULL,
            memory_bytes INTEGER NOT NULL,
            instances INTEGER NOT NULL,
            estimated_watts REAL NOT NULL
        );
        """
    )
    # Every read of this table filters or groups by timestamp, and it grows by
    # ~10 rows every 2 minutes, so the scan gets expensive within days.
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_process_samples_timestamp "
        "ON process_samples (timestamp)"
    )

    _apply_schema_upgrades(cursor)

    connection.commit()
    connection.close()


def _column_names(cursor, table: str) -> set:
    return {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}


def _apply_schema_upgrades(cursor) -> None:
    """
    Brings an existing database up to the current schema.

    CREATE TABLE IF NOT EXISTS silently does nothing when a table already
    exists, so columns added after a machine first ran the agent would never
    appear there. Since the agent is meant to run unattended on many
    machines, upgrades belong here — running automatically at startup —
    rather than in a script somebody has to remember to invoke.

    Every step is written to be safe to run repeatedly.
    """
    # idle_seconds, added for idle-waste detection. Existing rows keep NULL,
    # which reads correctly as "not recorded" rather than "zero idle".
    if "idle_seconds" not in _column_names(cursor, "telemetry_history"):
        cursor.execute("ALTER TABLE telemetry_history ADD COLUMN idle_seconds REAL")

    # Display state. Nullable for the same reason: a panel that does not
    # answer DDC/CI is "unknown", not 0% brightness with 0 monitors.
    for column, sql_type in (("brightness_percent", "INTEGER"),
                             ("monitor_count", "INTEGER")):
        if column not in _column_names(cursor, "telemetry_history"):
            cursor.execute(
                f"ALTER TABLE telemetry_history ADD COLUMN {column} {sql_type}")

    # baseline_mean / baseline_stdev were NOT NULL, which threshold-based
    # rules cannot satisfy. SQLite cannot drop a NOT NULL constraint in
    # place, so the table has to be rebuilt.
    notnull_baselines = any(
        row[1] in ("baseline_mean", "baseline_stdev") and row[3] == 1
        for row in cursor.execute("PRAGMA table_info(recommendations)")
    )
    if notnull_baselines:
        cursor.execute("ALTER TABLE recommendations RENAME TO recommendations_old")
        cursor.execute(
            """
            CREATE TABLE recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                metric TEXT NOT NULL,
                message TEXT NOT NULL,
                current_value REAL NOT NULL,
                baseline_mean REAL,
                baseline_stdev REAL
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO recommendations
                (id, timestamp, metric, message, current_value,
                 baseline_mean, baseline_stdev)
            SELECT id, timestamp, metric, message, current_value,
                   baseline_mean, baseline_stdev
            FROM recommendations_old
            """
        )
        cursor.execute("DROP TABLE recommendations_old")


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
            network_bytes_received_per_second,
            idle_seconds,
            brightness_percent,
            monitor_count

        )

        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            snapshot.idle_seconds,
            snapshot.brightness_percent,
            snapshot.monitor_count,
        ),
    )

    connection.commit()

    connection.close()


def get_latest_measurement() -> Optional[sqlite3.Row]:
    connection = get_connection()
    cursor = connection.cursor()
    row = cursor.execute(
        "SELECT * FROM measurements ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    connection.close()
    return row


def get_measurements_since(since: datetime) -> list[sqlite3.Row]:
    connection = get_connection()
    cursor = connection.cursor()
    rows = cursor.execute(
        "SELECT * FROM measurements WHERE timestamp >= ? ORDER BY timestamp ASC",
        (since.isoformat(),),
    ).fetchall()
    connection.close()
    return rows


def get_measurements_bucketed(
        since: datetime,
        until: datetime,
        buckets: int,
) -> list[sqlite3.Row]:
    """
    Downsampled history: averages measurements into at most `buckets`
    equal-duration time buckets, in SQL.

    Why this exists: a 7-day window is ~54,000 rows, which serialises to
    ~20 MB of JSON and locks up the browser tab. Downsampling in the client
    can't help — the cost is transferring and parsing rows that are then
    thrown away. A chart is ~800px wide, so anything past ~700 points is
    invisible regardless.

    Each column is aggregated according to what it actually means, which is
    not the same function for all of them:

      * watts are instantaneous rates    -> AVG  (the bucket's mean draw)
      * interval_* are per-tick amounts  -> SUM  (they add up over the bucket)
      * cumulative_* are running totals  -> MAX  (monotonic; take the latest)

    Using AVG for all of them would understate cumulative totals and
    silently shrink interval energy as the window widens.

    Buckets containing no rows simply don't appear in the result. That's
    intentional: the client renders a missing bucket as a break in the
    line, so suspend gaps stay visible rather than being interpolated over.
    """
    span_seconds = max((until - since).total_seconds(), 1.0)
    bucket_seconds = max(1, int(span_seconds / max(buckets, 1)))

    connection = get_connection()
    cursor = connection.cursor()
    rows = cursor.execute(
        """
        SELECT
            MIN(id)                     AS id,
            MIN(timestamp)              AS timestamp,
            AVG(cpu_watts)              AS cpu_watts,
            AVG(ram_watts)              AS ram_watts,
            AVG(baseline_watts)         AS baseline_watts,
            AVG(total_watts)            AS total_watts,
            SUM(interval_watt_hours)    AS interval_watt_hours,
            MAX(cumulative_watt_hours)  AS cumulative_watt_hours,
            SUM(interval_kg_co2eq)      AS interval_kg_co2eq,
            MAX(cumulative_kg_co2eq)    AS cumulative_kg_co2eq
        FROM measurements
        WHERE timestamp >= ?
        GROUP BY CAST(strftime('%s', timestamp) AS INTEGER) / ?
        ORDER BY timestamp ASC
        """,
        (since.isoformat(), bucket_seconds),
    ).fetchall()
    connection.close()
    return rows


def get_telemetry_since(since: datetime) -> list[sqlite3.Row]:
    connection = get_connection()
    cursor = connection.cursor()
    rows = cursor.execute(
        "SELECT * FROM telemetry_history WHERE timestamp >= ? ORDER BY timestamp ASC",
        (since.isoformat(),),
    ).fetchall()
    connection.close()
    return rows

def save_recommendation(rec) -> None:
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """INSERT INTO recommendations
           (timestamp, metric, message, current_value, baseline_mean, baseline_stdev)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (rec.triggered_at.isoformat(), rec.metric, rec.message,
         rec.current_value, rec.baseline_mean, rec.baseline_stdev),
    )
    connection.commit()
    connection.close()


TELEMETRY_INTERVAL_SECONDS = 120
IDLE_THRESHOLD_SECONDS = 15 * 60


def get_observed_behaviour(days: int = 7) -> dict:
    """
    What the machine actually did, summarised for the configuration audit.

    The audit compares POLICY against BEHAVIOUR — "you are set to sleep after
    15 minutes, but you averaged 96 idle minutes a day" — so it needs both,
    and this supplies the behaviour half.

    idle_awake minutes are counted by telemetry rows rather than measured
    directly: each row represents one TELEMETRY_INTERVAL_SECONDS window, and a
    row whose idle_seconds exceeds the threshold means nobody touched the
    machine during it. Approximate by exactly one interval at each end, which
    is well inside the precision anything downstream claims.
    """
    connection = get_connection()
    cursor = connection.cursor()
    since = (datetime.now() - timedelta(days=days)).isoformat()

    idle_rows, days_seen = cursor.execute(
        "SELECT COUNT(*), COUNT(DISTINCT substr(timestamp, 1, 10)) "
        "FROM telemetry_history WHERE timestamp >= ? AND idle_seconds > ?",
        (since, IDLE_THRESHOLD_SECONDS),
    ).fetchone()

    # Days on which idle was TRACKED, not days in the window. idle_seconds was
    # added partway through this database's life, so dividing by `days` would
    # average real idle time across days that could never have reported any,
    # understating it by whatever fraction of history predates the column.
    tracked_days = cursor.execute(
        "SELECT COUNT(DISTINCT substr(timestamp, 1, 10)) FROM telemetry_history "
        "WHERE timestamp >= ? AND idle_seconds IS NOT NULL",
        (since,),
    ).fetchone()[0]

    typical_watts = cursor.execute(
        "SELECT AVG(total_watts) FROM measurements WHERE timestamp >= ?",
        (since,),
    ).fetchone()[0]

    brightness = cursor.execute(
        "SELECT brightness_percent FROM telemetry_history "
        "WHERE brightness_percent IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
    ).fetchone()

    # Energy drawn ONLY on the days idle was actually tracked.
    #
    # This is the denominator the idle share needs, and getting it wrong was a
    # real bug: idle_seconds was added partway through this database's life,
    # so the numerator covered 3 days while the total covered 7. The reported
    # share came out 5.3% where matched coverage gives 13.8% — understating
    # avoidable waste by a factor of 2.6 purely through arithmetic.
    #
    # Matching them means the ratio answers one question about one period,
    # instead of dividing a measurement by a period it was never measured over.
    energy_on_tracked_days = cursor.execute(
        "SELECT SUM(interval_watt_hours) FROM measurements "
        "WHERE substr(timestamp, 1, 10) IN ("
        "  SELECT DISTINCT substr(timestamp, 1, 10) FROM telemetry_history "
        "  WHERE timestamp >= ? AND idle_seconds IS NOT NULL"
        ")",
        (since,),
    ).fetchone()[0]

    idle_minutes_total = (idle_rows or 0) * TELEMETRY_INTERVAL_SECONDS / 60
    connection.close()

    return {
        "idle_awake_minutes_per_day": (
            idle_minutes_total / tracked_days if tracked_days else None
        ),
        "idle_awake_watt_hours": (
            idle_minutes_total / 60 * typical_watts if typical_watts else None
        ),
        "brightness_percent": brightness[0] if brightness else None,
        "typical_watts": typical_watts,
        "days_tracked": tracked_days,
        "energy_on_tracked_days_wh": energy_on_tracked_days,
    }


# A conventional office day. Energy drawn outside it is not automatically
# waste -- people work evenings -- but a machine drawing power at 03:00 on a
# Sunday almost certainly is, and this is the boundary that separates the two
# populations for reporting.
WORKDAY_START_HOUR = 8
WORKDAY_END_HOUR = 19


def get_offhours_summary(days: int = 7) -> dict:
    """
    Energy drawn outside working hours, and the shape of a typical day.

    This is the biggest single lever in an office and it needs no new
    collection: a machine left running from Friday evening to Monday morning
    costs more than a week of careful daytime habits, and the timestamps to
    prove it have been in the measurements table all along.

    The hourly profile is returned as well because the number alone does not
    persuade anybody. Twenty-four bars showing draw continuing straight
    through the night is an argument; "38 Wh outside hours" is a statistic.
    """
    connection = get_connection()
    cursor = connection.cursor()
    since = (datetime.now() - timedelta(days=days)).isoformat()

    # strftime('%w') is 0=Sunday..6=Saturday in SQLite; '%H' is a zero-padded
    # 24-hour clock. Both are computed on the stored local-time string, which
    # is what makes "working hours" mean the user's hours rather than UTC.
    rows = cursor.execute(
        "SELECT CAST(strftime('%H', timestamp) AS INTEGER) AS hour, "
        "       CAST(strftime('%w', timestamp) AS INTEGER) AS weekday, "
        "       SUM(interval_watt_hours) AS watt_hours "
        "FROM measurements WHERE timestamp >= ? "
        "GROUP BY hour, weekday",
        (since,),
    ).fetchall()
    connection.close()

    by_hour = [0.0] * 24
    total = weekend = offhours = 0.0

    for row in rows:
        watt_hours = row["watt_hours"] or 0.0
        by_hour[row["hour"]] += watt_hours
        total += watt_hours

        is_weekend = row["weekday"] in (0, 6)
        outside_day = not (WORKDAY_START_HOUR <= row["hour"] < WORKDAY_END_HOUR)

        if is_weekend:
            weekend += watt_hours
        # Weekend energy is counted once, in both buckets it belongs to: it is
        # off-hours by definition, and reporting it only as "weekend" would
        # understate the off-hours total on any machine used at weekends.
        if is_weekend or outside_day:
            offhours += watt_hours

    return {
        "workday_start_hour": WORKDAY_START_HOUR,
        "workday_end_hour": WORKDAY_END_HOUR,
        "total_watt_hours": total,
        "offhours_watt_hours": offhours,
        "offhours_share": offhours / total if total > 0 else None,
        "weekend_watt_hours": weekend,
        "by_hour": by_hour,
    }


def get_period_summary(days: int = 7) -> dict:
    """
    Energy and carbon for the last `days`, the period before it, a per-day
    breakdown, and the applications that cost the most.

    The previous-period comparison is the point of the whole endpoint: an
    absolute "476 Wh" means nothing to anybody, while "12% less than last
    week" is the only form in which a personal-improvement tool can report
    progress at all.
    """
    connection = get_connection()
    cursor = connection.cursor()
    now = datetime.now()
    current_start = now - timedelta(days=days)
    previous_start = now - timedelta(days=days * 2)

    def totals(start: datetime, end: datetime) -> dict:
        row = cursor.execute(
            "SELECT SUM(interval_watt_hours), SUM(interval_kg_co2eq), COUNT(*) "
            "FROM measurements WHERE timestamp >= ? AND timestamp < ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        return {
            "watt_hours": row[0] or 0.0,
            "grams_co2eq": (row[1] or 0.0) * 1000,
            "samples": row[2],
        }

    current = totals(current_start, now)
    previous = totals(previous_start, current_start)

    per_day = [
        {"date": date, "watt_hours": watt_hours or 0.0}
        for date, watt_hours in cursor.execute(
            "SELECT substr(timestamp, 1, 10), SUM(interval_watt_hours) "
            "FROM measurements WHERE timestamp >= ? GROUP BY 1 ORDER BY 1",
            (current_start.isoformat(),),
        )
    ]

    top_applications = [
        {"name": name, "watt_hours": watt_hours or 0.0}
        for name, watt_hours in cursor.execute(
            # estimated_watts is an instantaneous rate sampled once per
            # telemetry interval, so each sample stands for that interval's
            # worth of energy — hence the x interval / 3600 to reach Wh.
            "SELECT name, SUM(estimated_watts) * ? / 3600.0 AS wh "
            "FROM process_samples WHERE timestamp >= ? "
            "GROUP BY name ORDER BY wh DESC LIMIT 5",
            (TELEMETRY_INTERVAL_SECONDS, current_start.isoformat()),
        )
    ]
    connection.close()

    behaviour = get_observed_behaviour(days)
    wasted = behaviour["idle_awake_watt_hours"]

    change_percent = None
    # Comparable COVERAGE, not merely non-zero data.
    #
    # The first version required previous["watt_hours"] > 1.0 and duly
    # reported "+15,322% vs last week" — 476 Wh against 3.1 Wh, because the
    # agent had only run for ten minutes that week. The comparison was
    # arithmetically correct and completely meaningless: it measured how long
    # the agent was installed, not how much energy anybody used.
    #
    # Requiring the earlier period to hold at least a quarter as many samples
    # makes the denominator trustworthy before anything is divided by it. A
    # missing comparison renders as "not enough history", which is honest;
    # a spectacular fake number is not.
    comparable = previous["samples"] >= current["samples"] * 0.25
    if comparable and previous["watt_hours"] > 1.0:
        change_percent = 100 * (
            current["watt_hours"] - previous["watt_hours"]
        ) / previous["watt_hours"]

    return {
        "days": days,
        "current": current,
        "previous": previous,
        "change_percent": change_percent,
        "per_day": per_day,
        "top_applications": [
            {**application, "label": None} for application in top_applications
        ],
        "idle_awake_watt_hours": wasted,
        # Divided by energy on the tracked days, NOT by the period total —
        # see get_observed_behaviour. Both halves of this ratio now describe
        # the same days.
        "idle_awake_share": (
            wasted / behaviour["energy_on_tracked_days_wh"]
            if wasted and behaviour["energy_on_tracked_days_wh"] else None
        ),
        "energy_on_tracked_days_wh": behaviour["energy_on_tracked_days_wh"],
        "days_tracked": behaviour["days_tracked"],
    }


def get_latest_recommendation_per_metric(since: datetime) -> dict[str, sqlite3.Row]:
    """
    The most recent recommendation for each metric since `since`.

    Lets the engine pick up where it left off after a restart instead of
    re-announcing conditions it already reported. No new table needed: the
    row it already writes is the record of "I told the user about this at
    time T", which is exactly the state worth surviving a restart.
    """
    connection = get_connection()
    cursor = connection.cursor()
    rows = cursor.execute(
        """SELECT * FROM recommendations r
           WHERE timestamp >= ?
             AND timestamp = (SELECT MAX(timestamp) FROM recommendations
                              WHERE metric = r.metric AND timestamp >= ?)""",
        (since.isoformat(), since.isoformat()),
    ).fetchall()
    connection.close()
    return {row["metric"]: row for row in rows}


def get_recommendations_since(since: datetime, limit: int = 20) -> list[sqlite3.Row]:
    connection = get_connection()
    cursor = connection.cursor()
    rows = cursor.execute(
        "SELECT * FROM recommendations WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
        (since.isoformat(), limit),
    ).fetchall()
    connection.close()
    return rows

# Process samples

def save_process_samples(timestamp: datetime, samples: list[dict]) -> None:
    """
    Record one sample of the top power-consuming applications.

    Written on the telemetry cadence rather than every tick: enumerating a
    few hundred processes costs far more than reading four psutil counters,
    and the answer to "what is using my machine" does not meaningfully change
    between one second and the next.
    """
    if not samples:
        return

    connection = get_connection()
    cursor = connection.cursor()

    cursor.executemany(
        """
        INSERT INTO process_samples (
            timestamp, name, cpu_percent, memory_bytes, instances, estimated_watts
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                timestamp.isoformat(),
                sample["name"],
                sample["cpu_percent"],
                sample["memory_bytes"],
                sample["instances"],
                sample["estimated_watts"],
            )
            for sample in samples
        ],
    )

    connection.commit()
    connection.close()


def get_latest_process_samples(limit: int = 10) -> list[sqlite3.Row]:
    """The most recent sample only — this answers "right now", not "over time"."""
    connection = get_connection()
    cursor = connection.cursor()
    rows = cursor.execute(
        """
        SELECT * FROM process_samples
        WHERE timestamp = (SELECT MAX(timestamp) FROM process_samples)
        ORDER BY estimated_watts DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    connection.close()
    return rows
