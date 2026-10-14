"""
db.py — SQLite persistence layer for AI Career Advisor.
All user data is keyed by an anonymous student_id (UUID).
No PII is stored or sent to any LLM.
"""

import sqlite3
import json
import os
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

DB_PATH = os.environ.get("DB_PATH", "career_advisor.db")


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    """Create all tables if they do not already exist."""
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                student_id  TEXT PRIMARY KEY,
                role        TEXT NOT NULL,
                skills      TEXT NOT NULL,   -- JSON list
                deadline    TEXT NOT NULL,   -- ISO date string YYYY-MM-DD
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS roadmaps (
                student_id  TEXT PRIMARY KEY,
                roadmap     TEXT NOT NULL,   -- JSON list of week objects
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS progress (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id  TEXT NOT NULL,
                week        INTEGER NOT NULL,
                completed   INTEGER NOT NULL DEFAULT 0,  -- 0 or 1
                recorded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS interview_scores (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id  TEXT NOT NULL,
                question    TEXT NOT NULL,
                answer      TEXT NOT NULL,
                score       INTEGER NOT NULL,
                feedback    TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS nudges (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id  TEXT NOT NULL,
                message     TEXT NOT NULL,
                sent_at     TEXT NOT NULL
            );
            """
        )


# ── Profile ──────────────────────────────────────────────────────────────────

def save_profile(student_id: str, role: str, skills: list[str], deadline: str) -> None:
    with _conn() as con:
        con.execute(
            """
            INSERT INTO profiles (student_id, role, skills, deadline, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(student_id) DO UPDATE SET
                role=excluded.role,
                skills=excluded.skills,
                deadline=excluded.deadline,
                created_at=excluded.created_at
            """,
            (student_id, role, json.dumps(skills), deadline, _now_iso()),
        )


def load_profile(student_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM profiles WHERE student_id = ?", (student_id,)
        ).fetchone()
    if row is None:
        return None
    return {
        "student_id": row["student_id"],
        "role": row["role"],
        "skills": json.loads(row["skills"]),
        "deadline": row["deadline"],
    }


# ── Roadmap ───────────────────────────────────────────────────────────────────

def save_roadmap(student_id: str, roadmap: list[dict]) -> None:
    with _conn() as con:
        con.execute(
            """
            INSERT INTO roadmaps (student_id, roadmap, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(student_id) DO UPDATE SET
                roadmap=excluded.roadmap,
                created_at=excluded.created_at
            """,
            (student_id, json.dumps(roadmap), _now_iso()),
        )


def load_roadmap(student_id: str) -> list[dict] | None:
    with _conn() as con:
        row = con.execute(
            "SELECT roadmap FROM roadmaps WHERE student_id = ?", (student_id,)
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["roadmap"])


# ── Progress ──────────────────────────────────────────────────────────────────

def mark_week_complete(student_id: str, week: int) -> None:
    with _conn() as con:
        con.execute(
            """
            INSERT INTO progress (student_id, week, completed, recorded_at)
            VALUES (?, ?, 1, ?)
            """,
            (student_id, week, _now_iso()),
        )


def load_progress(student_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT week, completed, recorded_at FROM progress WHERE student_id = ? ORDER BY recorded_at",
            (student_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def last_activity_at(student_id: str) -> datetime | None:
    with _conn() as con:
        row = con.execute(
            "SELECT MAX(recorded_at) as ts FROM progress WHERE student_id = ?",
            (student_id,),
        ).fetchone()
    if row and row["ts"]:
        return datetime.fromisoformat(row["ts"])
    return None


# ── Interview scores ──────────────────────────────────────────────────────────

def save_interview_score(
    student_id: str, question: str, answer: str, score: int, feedback: str
) -> None:
    with _conn() as con:
        con.execute(
            """
            INSERT INTO interview_scores
                (student_id, question, answer, score, feedback, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (student_id, question, answer, score, feedback, _now_iso()),
        )


def load_interview_scores(student_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT question, answer, score, feedback, recorded_at "
            "FROM interview_scores WHERE student_id = ? ORDER BY recorded_at",
            (student_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Nudges ────────────────────────────────────────────────────────────────────

def save_nudge(student_id: str, message: str) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO nudges (student_id, message, sent_at) VALUES (?, ?, ?)",
            (student_id, message, _now_iso()),
        )


def load_nudges(student_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT message, sent_at FROM nudges WHERE student_id = ? ORDER BY sent_at DESC LIMIT 5",
            (student_id,),
        ).fetchall()
    return [dict(r) for r in rows]
