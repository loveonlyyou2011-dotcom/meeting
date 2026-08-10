import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "meetings.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS live_captions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL,
    speaker_label TEXT NOT NULL,
    start_ts REAL NOT NULL,
    end_ts REAL NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS speakers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL,
    label TEXT NOT NULL,
    display_name TEXT,
    sample_path TEXT,
    UNIQUE(meeting_id, label)
);

CREATE TABLE IF NOT EXISTS reports (
    meeting_id TEXT PRIMARY KEY,
    markdown TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def _now():
    return datetime.now(timezone.utc).isoformat()


def create_meeting(title: str) -> str:
    meeting_id = uuid.uuid4().hex[:12]
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO meetings (id, title, status, created_at) VALUES (?, ?, ?, ?)",
            (meeting_id, title, "recording", _now()),
        )
    return meeting_id


def get_meeting(meeting_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        return dict(row) if row else None


def update_meeting_status(meeting_id: str, status: str):
    with get_conn() as conn:
        conn.execute("UPDATE meetings SET status = ? WHERE id = ?", (status, meeting_id))


def add_chunk(meeting_id: str, chunk_index: int, file_path: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chunks (meeting_id, chunk_index, file_path, created_at) VALUES (?, ?, ?, ?)",
            (meeting_id, chunk_index, file_path, _now()),
        )


def list_chunks(meeting_id: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM chunks WHERE meeting_id = ? ORDER BY chunk_index ASC",
            (meeting_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_live_caption(meeting_id: str, chunk_index: int, text: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO live_captions (meeting_id, chunk_index, text, created_at) VALUES (?, ?, ?, ?)",
            (meeting_id, chunk_index, text, _now()),
        )


def get_live_captions_after(meeting_id: str, after_id: int = 0):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM live_captions WHERE meeting_id = ? AND id > ? ORDER BY id ASC",
            (meeting_id, after_id),
        ).fetchall()
        return [dict(r) for r in rows]


def save_segments(meeting_id: str, segments: list):
    with get_conn() as conn:
        conn.execute("DELETE FROM segments WHERE meeting_id = ?", (meeting_id,))
        conn.executemany(
            "INSERT INTO segments (meeting_id, speaker_label, start_ts, end_ts, text) VALUES (?, ?, ?, ?, ?)",
            [
                (meeting_id, s["speaker_label"], s["start"], s["end"], s["text"])
                for s in segments
            ],
        )


def get_segments(meeting_id: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM segments WHERE meeting_id = ? ORDER BY start_ts ASC",
            (meeting_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_speaker(meeting_id: str, label: str, sample_path: str = None):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO speakers (meeting_id, label, sample_path) VALUES (?, ?, ?)
            ON CONFLICT(meeting_id, label) DO UPDATE SET sample_path = excluded.sample_path
            """,
            (meeting_id, label, sample_path),
        )


def set_speaker_name(meeting_id: str, label: str, display_name: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE speakers SET display_name = ? WHERE meeting_id = ? AND label = ?",
            (display_name, meeting_id, label),
        )


def get_speakers(meeting_id: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM speakers WHERE meeting_id = ? ORDER BY label ASC",
            (meeting_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def save_report(meeting_id: str, markdown: str):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO reports (meeting_id, markdown, created_at) VALUES (?, ?, ?)
            ON CONFLICT(meeting_id) DO UPDATE SET markdown = excluded.markdown, created_at = excluded.created_at
            """,
            (meeting_id, markdown, _now()),
        )


def get_report(meeting_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM reports WHERE meeting_id = ?", (meeting_id,)).fetchone()
        return dict(row) if row else None
