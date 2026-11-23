"""SQLite-backed attendance with one entry per person per local calendar day."""

from __future__ import annotations

import csv
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator


class AttendanceStore:
    """Persists attendance and exports records as UTF-8 CSV."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE,
                    attendance_date TEXT NOT NULL,
                    attendance_time TEXT NOT NULL,
                    UNIQUE(name, attendance_date)
                )
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        try:
            connection.execute("PRAGMA busy_timeout = 5000")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record_attendance(self, person_name: str, when: datetime | None = None) -> bool:
        name = person_name.strip()
        if not name:
            raise ValueError("A person's name is required for attendance.")
        if name.casefold() == "unknown person":
            raise ValueError("Unknown people cannot be recorded as attendance.")
        timestamp = when or datetime.now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO attendance (name, attendance_date, attendance_time)
                VALUES (?, ?, ?)
                """,
                (name, timestamp.strftime("%Y-%m-%d"), timestamp.strftime("%H:%M:%S")),
            )
            return cursor.rowcount == 1

    def get_records(self) -> list[tuple[str, str, str]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT name, attendance_date, attendance_time
                FROM attendance
                ORDER BY attendance_date DESC, attendance_time DESC, name COLLATE NOCASE
                """
            ).fetchall()
        return [(str(name), str(day), str(clock)) for name, day, clock in rows]

    def export_csv(self, destination: Path) -> int:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        records = self.get_records()
        with path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(("Person Name", "Date", "Time"))
            writer.writerows(records)
        return len(records)
