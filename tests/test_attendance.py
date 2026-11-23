"""SQLite and CSV tests that need only the Python standard library."""

from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from attendance import AttendanceStore


class AttendanceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_attendance_is_unique_per_person_per_day(self):
        store = AttendanceStore(self.root / "Attendance_Records" / "attendance.db")
        self.assertTrue(store.record_attendance("Jordan", datetime(2026, 1, 5, 9, 0, 0)))
        self.assertFalse(store.record_attendance("Jordan", datetime(2026, 1, 5, 11, 0, 0)))
        self.assertFalse(store.record_attendance("jordan", datetime(2026, 1, 5, 12, 0, 0)))
        self.assertTrue(store.record_attendance("Jordan", datetime(2026, 1, 6, 9, 0, 0)))
        self.assertEqual(len(store.get_records()), 2)

    def test_csv_export_contains_header_and_records(self):
        store = AttendanceStore(self.root / "attendance.db")
        store.record_attendance("Jordan", datetime(2026, 1, 5, 9, 2, 3))
        destination = self.root / "exports" / "records.csv"
        self.assertEqual(store.export_csv(destination), 1)
        with destination.open(newline="", encoding="utf-8-sig") as file:
            rows = list(csv.reader(file))
        self.assertEqual(rows[0], ["Person Name", "Date", "Time"])
        self.assertEqual(rows[1], ["Jordan", "2026-01-05", "09:02:03"])

    def test_unknown_person_is_not_registered_attendance(self):
        store = AttendanceStore(self.root / "attendance.db")
        with self.assertRaisesRegex(ValueError, "Unknown people"):
            store.record_attendance("Unknown Person")
        self.assertEqual(store.get_records(), [])


if __name__ == "__main__":
    unittest.main()
