"""
database.py - ชั้นจัดการฐานข้อมูล SQLite (sqlite3 มาตรฐาน)

ตรรกะสำคัญ (อ้างอิงรายงานบทที่ 3):
- ใช้ threading.Lock ครอบทุกการเขียน เพราะ video thread และ API thread
  อาจเขียนฐานข้อมูลพร้อมกัน
- เปิด connection ใหม่ทุกครั้งที่เรียก (check_same_thread ไม่เป็นปัญหา)
"""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "waste_log.db"
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """สร้างตารางหากยังไม่มี"""
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS detection_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp  TEXT    NOT NULL,
                class_name TEXT    NOT NULL,
                category   TEXT    NOT NULL,
                confidence REAL    NOT NULL,
                bin_name   TEXT    NOT NULL,
                source     TEXT    NOT NULL DEFAULT 'stream'
            )
            """
        )


def insert_log(class_name: str, category: str, confidence: float,
               bin_name: str, source: str = "stream") -> None:
    """บันทึกผลการตรวจจับ 1 รายการ"""
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO detection_log (timestamp, class_name, category, confidence, bin_name, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), class_name, category,
             round(float(confidence), 4), bin_name, source),
        )


def get_history(limit: int = 50) -> list[dict]:
    """ดึงประวัติล่าสุด (เรียงใหม่ -> เก่า)"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM detection_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_summary() -> dict:
    """สรุปจำนวนตามหมวดขยะ"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS n FROM detection_log GROUP BY category"
        ).fetchall()
    return {r["category"]: r["n"] for r in rows}
