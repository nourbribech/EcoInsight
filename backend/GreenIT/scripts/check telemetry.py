"""
One-off check: query telemetry_history and print the most recent rows,
so we can confirm the estimation loop is actually writing telemetry
snapshots (not just power measurements) before trusting it to run
unattended for days.
"""

from GreenIT.database import database


def main() -> None:
    connection = database.get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT *
        FROM telemetry_history
        ORDER BY id DESC
        LIMIT 10
        """
    )
    rows = cursor.fetchall()
    connection.close()

    if not rows:
        print("No rows found in telemetry_history yet.")
        print("Expected if the loop has been running less than ~2 minutes "
              "(TELEMETRY_INTERVAL_SECONDS) since startup.")
        return

    print(f"Found {len(rows)} most recent row(s):\n")
    for row in rows:
        print(dict(row))


if __name__ == "__main__":
    main()