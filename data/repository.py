from __future__ import annotations

import copy
import datetime as dt
import json
import logging
import os
import sqlite3
import uuid

import streamlit as st

from config.settings import (
    DB_FILE,
    GOALS_FILE,
    HISTORY_FILE,
    PROFILE_FILE,
    RAG_MAX_CANDIDATES,
    RAG_TOP_K,
    TODAY,
)

LOGGER = logging.getLogger(__name__)

PROFILE_DEFAULT = {
    "main_goal": "",
    "current_focus": "",
    "priorities": "",
    "constraints": "",
    "not_urgent": "",
    "feedback_style": "rational",
    "career_plan_text": "",
    "updated": "",
}

RECORD_DEFAULT = {
    "date": TODAY,
    "tasks": [],
    "plan": "",
    "result": "",
    "status": "",
    "profile_snapshot": {},
    "ai_plan_result": {},
    "ai_review_result": {},
    "suggestion_tracking": {},
    "top_priority": "",
    "tomorrow_suggestion": "",
    "plan_metrics": {},
}


def _clone_default(value):
    return copy.deepcopy(value)


def _load_json_file(path, default):
    if not os.path.exists(path):
        return _clone_default(default)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
        if not content:
            return _clone_default(default)
        return json.loads(content)
    except (json.JSONDecodeError, OSError):
        return _clone_default(default)


def _json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value, default):
    if value in (None, ""):
        return _clone_default(default)
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return _clone_default(default)


def _connect():
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def _create_tables(connection: sqlite3.Connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS goals (
            goal_id TEXT PRIMARY KEY,
            goal TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            level INTEGER NOT NULL DEFAULT 3,
            deadline TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS profile (
            profile_id INTEGER PRIMARY KEY CHECK (profile_id = 1),
            main_goal TEXT NOT NULL DEFAULT '',
            current_focus TEXT NOT NULL DEFAULT '',
            priorities TEXT NOT NULL DEFAULT '',
            constraints TEXT NOT NULL DEFAULT '',
            not_urgent TEXT NOT NULL DEFAULT '',
            feedback_style TEXT NOT NULL DEFAULT 'rational',
            career_plan_text TEXT NOT NULL DEFAULT '',
            updated TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS history_records (
            date TEXT PRIMARY KEY,
            plan TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            profile_snapshot_json TEXT NOT NULL DEFAULT '{}',
            ai_plan_result_json TEXT NOT NULL DEFAULT '{}',
            ai_review_result_json TEXT NOT NULL DEFAULT '{}',
            suggestion_tracking_json TEXT NOT NULL DEFAULT '{}',
            top_priority TEXT NOT NULL DEFAULT '',
            tomorrow_suggestion TEXT NOT NULL DEFAULT '',
            plan_metrics_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS history_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_date TEXT NOT NULL,
            task_order INTEGER NOT NULL DEFAULT 0,
            text TEXT NOT NULL DEFAULT '',
            goal TEXT NOT NULL DEFAULT '',
            goal_id TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'medium',
            duration INTEGER NOT NULL DEFAULT 30,
            must INTEGER NOT NULL DEFAULT 0,
            done INTEGER NOT NULL DEFAULT 0,
            tag TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS rag_chunks (
            chunk_id TEXT PRIMARY KEY,
            record_date TEXT NOT NULL,
            chunk_type TEXT NOT NULL,
            source_text TEXT NOT NULL,
            summary_text TEXT NOT NULL,
            goal_ids_json TEXT NOT NULL DEFAULT '[]',
            tags_json TEXT NOT NULL DEFAULT '[]',
            embedding_model TEXT NOT NULL DEFAULT '',
            embedding_json TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS task_sessions (
            session_id TEXT PRIMARY KEY,
            record_date TEXT NOT NULL,
            task_key TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL DEFAULT '',
            duration_sec INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_history_tasks_record_date ON history_tasks(record_date);
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_record_date ON rag_chunks(record_date);
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_chunk_type ON rag_chunks(chunk_type);
        CREATE INDEX IF NOT EXISTS idx_task_sessions_record_date ON task_sessions(record_date);
        CREATE INDEX IF NOT EXISTS idx_task_sessions_active ON task_sessions(ended_at);
        """
    )


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str):
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_schema(connection: sqlite3.Connection):
    _ensure_column(connection, "profile", "feedback_style", "TEXT NOT NULL DEFAULT 'rational'")
    _ensure_column(connection, "history_tasks", "actual_minutes", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "history_tasks", "auto_tag_source", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(connection, "history_tasks", "unplanned", "INTEGER NOT NULL DEFAULT 0")


def _has_runtime_data(connection: sqlite3.Connection) -> bool:
    for table_name in ("goals", "history_records", "profile"):
        row = connection.execute(f"SELECT 1 FROM {table_name} LIMIT 1").fetchone()
        if row:
            return True
    return False


def _normalize_goal(goal: dict) -> tuple[dict, bool]:
    changed = False
    normalized = dict(goal)

    if not normalized.get("goal_id"):
        normalized["goal_id"] = str(uuid.uuid4())[:8]
        changed = True
    if "description" not in normalized or not isinstance(normalized.get("description"), str):
        normalized["description"] = str(normalized.get("description") or "")
        changed = True
    if "created" not in normalized:
        normalized["created"] = ""
        changed = True
    if "deadline" not in normalized:
        normalized["deadline"] = ""
        changed = True

    tags = normalized.get("tags", [])
    if not isinstance(tags, list):
        tags = [str(tags)]
        changed = True
    cleaned_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
    if cleaned_tags != tags:
        changed = True
    normalized["tags"] = cleaned_tags
    normalized["level"] = int(normalized.get("level", 3) or 3)
    normalized["goal"] = str(normalized.get("goal") or "").strip()
    normalized["deadline"] = str(normalized.get("deadline") or "").strip()
    normalized["created"] = str(normalized.get("created") or "").strip()
    return normalized, changed


def _normalize_goals(goals: list) -> tuple[list, bool]:
    normalized_goals = []
    changed = False
    for goal in goals:
        normalized_goal, goal_changed = _normalize_goal(goal)
        normalized_goals.append(normalized_goal)
        changed = changed or goal_changed
    return normalized_goals, changed


def _normalize_task(task: dict, goal_name_to_id: dict[str, str]) -> tuple[dict, bool]:
    changed = False
    normalized = dict(task)

    for key, default in (
        ("text", ""),
        ("goal", ""),
        ("priority", "medium"),
        ("duration", 30),
        ("must", False),
        ("done", False),
        ("tag", ""),
        ("note", ""),
        ("actual_minutes", 0),
        ("auto_tag_source", ""),
        ("unplanned", False),
    ):
        if key not in normalized:
            normalized[key] = default
            changed = True

    goal_name = str(normalized.get("goal") or "").strip()
    goal_id = str(normalized.get("goal_id") or "").strip()
    if goal_name and not goal_id and goal_name in goal_name_to_id:
        normalized["goal_id"] = goal_name_to_id[goal_name]
        changed = True
    elif not goal_name and normalized.get("goal_id"):
        normalized["goal_id"] = ""
        changed = True

    normalized["text"] = str(normalized.get("text") or "").strip()
    normalized["goal"] = goal_name
    normalized["priority"] = str(normalized.get("priority") or "medium").strip() or "medium"
    normalized["duration"] = int(normalized.get("duration", 30) or 30)
    normalized["must"] = bool(normalized.get("must"))
    normalized["done"] = bool(normalized.get("done"))
    normalized["tag"] = str(normalized.get("tag") or "").strip()
    normalized["note"] = str(normalized.get("note") or "").strip()
    normalized["goal_id"] = str(normalized.get("goal_id") or "").strip()
    try:
        normalized["actual_minutes"] = int(normalized.get("actual_minutes", 0) or 0)
    except (TypeError, ValueError):
        normalized["actual_minutes"] = 0
    normalized["auto_tag_source"] = str(normalized.get("auto_tag_source") or "").strip()
    normalized["unplanned"] = bool(normalized.get("unplanned"))
    return normalized, changed


def _normalize_history_records(history: list, goal_name_to_id: dict[str, str]) -> tuple[list, bool]:
    normalized_history = []
    changed = False

    for record in history:
        normalized = dict(record)
        for key, default in RECORD_DEFAULT.items():
            if key not in normalized:
                normalized[key] = _clone_default(default)
                changed = True

        normalized["date"] = str(normalized.get("date") or TODAY)
        normalized["plan"] = str(normalized.get("plan") or "")
        normalized["result"] = str(normalized.get("result") or "")
        normalized["status"] = str(normalized.get("status") or "")
        normalized["top_priority"] = str(normalized.get("top_priority") or "")
        normalized["tomorrow_suggestion"] = str(normalized.get("tomorrow_suggestion") or "")
        normalized["profile_snapshot"] = normalized.get("profile_snapshot") or {}
        normalized["ai_plan_result"] = normalized.get("ai_plan_result") or {}
        normalized["ai_review_result"] = normalized.get("ai_review_result") or {}
        normalized["suggestion_tracking"] = normalized.get("suggestion_tracking") or {}
        normalized["plan_metrics"] = normalized.get("plan_metrics") or {}

        normalized_tasks = []
        for task in normalized.get("tasks", []):
            normalized_task, task_changed = _normalize_task(task, goal_name_to_id)
            normalized_tasks.append(normalized_task)
            changed = changed or task_changed
        normalized["tasks"] = normalized_tasks
        normalized_history.append(normalized)

    normalized_history.sort(key=lambda item: item.get("date", ""))
    return normalized_history, changed


def _normalize_profile(profile: dict | None) -> dict:
    merged = {**PROFILE_DEFAULT, **(profile or {})}
    normalized = {key: str(merged.get(key) or "") for key in PROFILE_DEFAULT}
    style = normalized.get("feedback_style", "rational").strip().lower()
    normalized["feedback_style"] = style if style in {"gentle", "rational", "strict"} else "rational"
    return normalized


def _goal_name_to_id_from_connection(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute("SELECT goal, goal_id FROM goals").fetchall()
    return {row["goal"]: row["goal_id"] for row in rows if row["goal"]}


def _serialize_goal_row(goal: dict, sort_order: int) -> tuple:
    return (
        goal["goal_id"],
        goal.get("goal", ""),
        goal.get("description", ""),
        int(goal.get("level", 3) or 3),
        goal.get("deadline", ""),
        goal.get("created", ""),
        _json_dumps(goal.get("tags", [])),
        sort_order,
    )


def _load_goals_from_connection(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT goal_id, goal, description, level, deadline, created, tags_json
        FROM goals
        ORDER BY sort_order, created, goal
        """
    ).fetchall()
    return [
        {
            "goal_id": row["goal_id"],
            "goal": row["goal"],
            "description": row["description"],
            "level": row["level"],
            "deadline": row["deadline"],
            "created": row["created"],
            "tags": _json_loads(row["tags_json"], []),
        }
        for row in rows
    ]


def _write_goals_to_connection(connection: sqlite3.Connection, goals: list[dict]):
    normalized_goals, _ = _normalize_goals(goals)
    connection.execute("DELETE FROM goals")
    connection.executemany(
        """
        INSERT INTO goals (
            goal_id, goal, description, level, deadline, created, tags_json, sort_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [_serialize_goal_row(goal, index) for index, goal in enumerate(normalized_goals)],
    )


def _history_tasks_for_connection(connection: sqlite3.Connection) -> dict[str, list[dict]]:
    rows = connection.execute(
        """
        SELECT record_date, task_order, text, goal, goal_id, priority, duration, must, done, tag, note,
               actual_minutes, auto_tag_source, unplanned
        FROM history_tasks
        ORDER BY record_date, task_order, id
        """
    ).fetchall()
    task_map: dict[str, list[dict]] = {}
    for row in rows:
        task_map.setdefault(row["record_date"], []).append(
            {
                "text": row["text"],
                "goal": row["goal"],
                "goal_id": row["goal_id"],
                "priority": row["priority"],
                "duration": row["duration"],
                "must": bool(row["must"]),
                "done": bool(row["done"]),
                "tag": row["tag"],
                "note": row["note"],
                "actual_minutes": int(row["actual_minutes"] or 0),
                "auto_tag_source": row["auto_tag_source"] or "",
                "unplanned": bool(row["unplanned"]),
            }
        )
    return task_map


def _load_history_from_connection(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            date,
            plan,
            result,
            status,
            profile_snapshot_json,
            ai_plan_result_json,
            ai_review_result_json,
            suggestion_tracking_json,
            top_priority,
            tomorrow_suggestion,
            plan_metrics_json
        FROM history_records
        ORDER BY date
        """
    ).fetchall()
    task_map = _history_tasks_for_connection(connection)
    history = []
    for row in rows:
        history.append(
            {
                "date": row["date"],
                "tasks": task_map.get(row["date"], []),
                "plan": row["plan"],
                "result": row["result"],
                "status": row["status"],
                "profile_snapshot": _json_loads(row["profile_snapshot_json"], {}),
                "ai_plan_result": _json_loads(row["ai_plan_result_json"], {}),
                "ai_review_result": _json_loads(row["ai_review_result_json"], {}),
                "suggestion_tracking": _json_loads(row["suggestion_tracking_json"], {}),
                "top_priority": row["top_priority"],
                "tomorrow_suggestion": row["tomorrow_suggestion"],
                "plan_metrics": _json_loads(row["plan_metrics_json"], {}),
            }
        )
    return history


def _get_record_from_connection(connection: sqlite3.Connection, date: str) -> dict | None:
    row = connection.execute(
        """
        SELECT
            date,
            plan,
            result,
            status,
            profile_snapshot_json,
            ai_plan_result_json,
            ai_review_result_json,
            suggestion_tracking_json,
            top_priority,
            tomorrow_suggestion,
            plan_metrics_json
        FROM history_records
        WHERE date = ?
        """,
        (date,),
    ).fetchone()
    if row is None:
        return None

    tasks = connection.execute(
        """
        SELECT text, goal, goal_id, priority, duration, must, done, tag, note,
               actual_minutes, auto_tag_source, unplanned
        FROM history_tasks
        WHERE record_date = ?
        ORDER BY task_order, id
        """,
        (date,),
    ).fetchall()
    return {
        "date": row["date"],
        "tasks": [
            {
                "text": task["text"],
                "goal": task["goal"],
                "goal_id": task["goal_id"],
                "priority": task["priority"],
                "duration": task["duration"],
                "must": bool(task["must"]),
                "done": bool(task["done"]),
                "tag": task["tag"],
                "note": task["note"],
                "actual_minutes": int(task["actual_minutes"] or 0),
                "auto_tag_source": task["auto_tag_source"] or "",
                "unplanned": bool(task["unplanned"]),
            }
            for task in tasks
        ],
        "plan": row["plan"],
        "result": row["result"],
        "status": row["status"],
        "profile_snapshot": _json_loads(row["profile_snapshot_json"], {}),
        "ai_plan_result": _json_loads(row["ai_plan_result_json"], {}),
        "ai_review_result": _json_loads(row["ai_review_result_json"], {}),
        "suggestion_tracking": _json_loads(row["suggestion_tracking_json"], {}),
        "top_priority": row["top_priority"],
        "tomorrow_suggestion": row["tomorrow_suggestion"],
        "plan_metrics": _json_loads(row["plan_metrics_json"], {}),
    }


def _upsert_record_to_connection(connection: sqlite3.Connection, record: dict):
    connection.execute(
        """
        INSERT INTO history_records (
            date,
            plan,
            result,
            status,
            profile_snapshot_json,
            ai_plan_result_json,
            ai_review_result_json,
            suggestion_tracking_json,
            top_priority,
            tomorrow_suggestion,
            plan_metrics_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            plan = excluded.plan,
            result = excluded.result,
            status = excluded.status,
            profile_snapshot_json = excluded.profile_snapshot_json,
            ai_plan_result_json = excluded.ai_plan_result_json,
            ai_review_result_json = excluded.ai_review_result_json,
            suggestion_tracking_json = excluded.suggestion_tracking_json,
            top_priority = excluded.top_priority,
            tomorrow_suggestion = excluded.tomorrow_suggestion,
            plan_metrics_json = excluded.plan_metrics_json
        """,
        (
            record["date"],
            record.get("plan", ""),
            record.get("result", ""),
            record.get("status", ""),
            _json_dumps(record.get("profile_snapshot", {})),
            _json_dumps(record.get("ai_plan_result", {})),
            _json_dumps(record.get("ai_review_result", {})),
            _json_dumps(record.get("suggestion_tracking", {})),
            record.get("top_priority", ""),
            record.get("tomorrow_suggestion", ""),
            _json_dumps(record.get("plan_metrics", {})),
        ),
    )
    connection.execute("DELETE FROM history_tasks WHERE record_date = ?", (record["date"],))
    if record.get("tasks"):
        connection.executemany(
            """
            INSERT INTO history_tasks (
                record_date, task_order, text, goal, goal_id, priority, duration, must, done, tag, note,
                actual_minutes, auto_tag_source, unplanned
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record["date"],
                    index,
                    task.get("text", ""),
                    task.get("goal", ""),
                    task.get("goal_id", ""),
                    task.get("priority", "medium"),
                    int(task.get("duration", 30) or 30),
                    int(bool(task.get("must"))),
                    int(bool(task.get("done"))),
                    task.get("tag", ""),
                    task.get("note", ""),
                    int(task.get("actual_minutes", 0) or 0),
                    str(task.get("auto_tag_source") or ""),
                    int(bool(task.get("unplanned"))),
                )
                for index, task in enumerate(record["tasks"])
            ],
        )


def _write_history_to_connection(connection: sqlite3.Connection, history: list[dict]):
    goal_name_to_id = _goal_name_to_id_from_connection(connection)
    normalized_history, _ = _normalize_history_records(history, goal_name_to_id)
    connection.execute("DELETE FROM history_tasks")
    connection.execute("DELETE FROM history_records")
    for record in normalized_history:
        _upsert_record_to_connection(connection, record)


def _load_profile_from_connection(connection: sqlite3.Connection) -> dict:
    row = connection.execute(
        """
        SELECT main_goal, current_focus, priorities, constraints, not_urgent, career_plan_text, updated
        , feedback_style
        FROM profile
        WHERE profile_id = 1
        """
    ).fetchone()
    if row is None:
        return _clone_default(PROFILE_DEFAULT)
    return _normalize_profile(dict(row))


def _write_profile_to_connection(connection: sqlite3.Connection, profile: dict):
    normalized = _normalize_profile(profile)
    connection.execute(
        """
        INSERT INTO profile (
            profile_id, main_goal, current_focus, priorities, constraints, not_urgent, feedback_style, career_plan_text, updated
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(profile_id) DO UPDATE SET
            main_goal = excluded.main_goal,
            current_focus = excluded.current_focus,
            priorities = excluded.priorities,
            constraints = excluded.constraints,
            not_urgent = excluded.not_urgent,
            feedback_style = excluded.feedback_style,
            career_plan_text = excluded.career_plan_text,
            updated = excluded.updated
        """,
        (
            normalized["main_goal"],
            normalized["current_focus"],
            normalized["priorities"],
            normalized["constraints"],
            normalized["not_urgent"],
            normalized["feedback_style"],
            normalized["career_plan_text"],
            normalized["updated"],
        ),
    )


def _import_json_backups(connection: sqlite3.Connection):
    raw_goals = _load_json_file(GOALS_FILE, [])
    normalized_goals, _ = _normalize_goals(raw_goals)
    if normalized_goals:
        _write_goals_to_connection(connection, normalized_goals)

    goal_name_to_id = {goal["goal"]: goal["goal_id"] for goal in normalized_goals if goal.get("goal")}
    raw_history = _load_json_file(HISTORY_FILE, [])
    normalized_history, _ = _normalize_history_records(raw_history, goal_name_to_id)
    if normalized_history:
        _write_history_to_connection(connection, normalized_history)

    raw_profile = _load_json_file(PROFILE_FILE, PROFILE_DEFAULT)
    if raw_profile != PROFILE_DEFAULT or os.path.exists(PROFILE_FILE):
        _write_profile_to_connection(connection, raw_profile)


def _clear_caches():
    load_goals.clear()
    load_history.clear()
    load_profile.clear()


def _ensure_database():
    should_rebuild_rag = False
    with _connect() as connection:
        _create_tables(connection)
        _migrate_schema(connection)
        if not _has_runtime_data(connection):
            _import_json_backups(connection)
            should_rebuild_rag = bool(
                connection.execute("SELECT 1 FROM history_records LIMIT 1").fetchone()
            )
        connection.commit()
    if should_rebuild_rag:
        rebuild_all_rag_chunks()


@st.cache_data
def load_goals():
    _ensure_database()
    with _connect() as connection:
        return _load_goals_from_connection(connection)


def save_goals(goals):
    _ensure_database()
    with _connect() as connection:
        _write_goals_to_connection(connection, goals)
        connection.commit()
    _clear_caches()
    rebuild_all_rag_chunks()


@st.cache_data
def load_history():
    _ensure_database()
    with _connect() as connection:
        return _load_history_from_connection(connection)


def save_history(history):
    _ensure_database()
    with _connect() as connection:
        _write_history_to_connection(connection, history)
        connection.commit()
    _clear_caches()
    rebuild_all_rag_chunks()


def get_record(date=TODAY):
    _ensure_database()
    with _connect() as connection:
        return _get_record_from_connection(connection, date)


def upsert_record(
    date=TODAY,
    tasks=None,
    plan=None,
    result=None,
    status=None,
    profile_snapshot=None,
    ai_plan_result=None,
    ai_review_result=None,
    suggestion_tracking=None,
    top_priority=None,
    tomorrow_suggestion=None,
    plan_metrics=None,
):
    _ensure_database()
    with _connect() as connection:
        current = _get_record_from_connection(connection, date) or {**_clone_default(RECORD_DEFAULT), "date": date}
        merged = {**current}
        if tasks is not None:
            merged["tasks"] = tasks
        if plan is not None:
            merged["plan"] = plan
        if result is not None:
            merged["result"] = result
        if status is not None:
            merged["status"] = status
        if profile_snapshot is not None:
            merged["profile_snapshot"] = profile_snapshot
        if ai_plan_result is not None:
            merged["ai_plan_result"] = ai_plan_result
        if ai_review_result is not None:
            merged["ai_review_result"] = ai_review_result
        if suggestion_tracking is not None:
            merged["suggestion_tracking"] = suggestion_tracking
        if top_priority is not None:
            merged["top_priority"] = top_priority
        if tomorrow_suggestion is not None:
            merged["tomorrow_suggestion"] = tomorrow_suggestion
        if plan_metrics is not None:
            merged["plan_metrics"] = plan_metrics

        goal_name_to_id = _goal_name_to_id_from_connection(connection)
        normalized_record, _ = _normalize_history_records([merged], goal_name_to_id)
        _upsert_record_to_connection(connection, normalized_record[0])
        connection.commit()
    _clear_caches()
    upsert_rag_chunks_for_record(date)


def sync_goal_history(goal_id: str, old_name: str, new_name: str):
    history = load_history()
    changed = False
    for record in history:
        for task in record.get("tasks", []):
            same_goal = task.get("goal_id") == goal_id or (
                not task.get("goal_id") and task.get("goal") == old_name
            )
            if same_goal:
                if task.get("goal") != new_name:
                    task["goal"] = new_name
                    changed = True
                if goal_id and task.get("goal_id") != goal_id:
                    task["goal_id"] = goal_id
                    changed = True
    if changed:
        save_history(history)


@st.cache_data
def load_profile():
    _ensure_database()
    with _connect() as connection:
        return _load_profile_from_connection(connection)


def save_profile(profile: dict):
    _ensure_database()
    current = load_profile()
    merged = {**current, **(profile or {})}
    with _connect() as connection:
        _write_profile_to_connection(connection, merged)
        connection.commit()
    _clear_caches()


def _row_to_session(row: sqlite3.Row) -> dict:
    return {
        "session_id": row["session_id"],
        "record_date": row["record_date"],
        "task_key": row["task_key"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"] or "",
        "duration_sec": int(row["duration_sec"] or 0),
        "created_at": row["created_at"] or "",
    }


def load_task_sessions(
    date: str | None = None,
    task_key: str | None = None,
    active_only: bool = False,
) -> list[dict]:
    """Load task_sessions, optionally filtered by date / task_key / active state."""
    _ensure_database()
    sql = "SELECT session_id, record_date, task_key, started_at, ended_at, duration_sec, created_at FROM task_sessions WHERE 1=1"
    params: list = []
    if date is not None:
        sql += " AND record_date = ?"
        params.append(date)
    if task_key is not None:
        sql += " AND task_key = ?"
        params.append(task_key)
    if active_only:
        sql += " AND (ended_at IS NULL OR ended_at = '')"
    sql += " ORDER BY started_at"
    with _connect() as connection:
        rows = connection.execute(sql, params).fetchall()
    return [_row_to_session(row) for row in rows]


def upsert_task_session(session: dict):
    """Idempotent write keyed on session_id."""
    _ensure_database()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO task_sessions (
                session_id, record_date, task_key, started_at, ended_at, duration_sec, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                record_date = excluded.record_date,
                task_key = excluded.task_key,
                started_at = excluded.started_at,
                ended_at = excluded.ended_at,
                duration_sec = excluded.duration_sec,
                created_at = excluded.created_at
            """,
            (
                str(session["session_id"]),
                str(session["record_date"]),
                str(session.get("task_key", "")),
                str(session.get("started_at", "")),
                str(session.get("ended_at", "") or ""),
                int(session.get("duration_sec", 0) or 0),
                str(session.get("created_at", "") or ""),
            ),
        )
        connection.commit()


def delete_task_session(session_id: str):
    _ensure_database()
    with _connect() as connection:
        connection.execute("DELETE FROM task_sessions WHERE session_id = ?", (session_id,))
        connection.commit()


def upsert_rag_chunks_for_record(date: str):
    _ensure_database()
    from services.llm_service import embed_texts, get_embedding_model_name
    from services.rag_service import build_rag_chunks_for_record

    with _connect() as connection:
        record = _get_record_from_connection(connection, date)
        connection.execute("DELETE FROM rag_chunks WHERE record_date = ?", (date,))
        if record is None:
            connection.commit()
            return

        goals = _load_goals_from_connection(connection)
        chunks = build_rag_chunks_for_record(record, goals)
        if not chunks:
            connection.commit()
            return

        embeddings = embed_texts([chunk["source_text"] for chunk in chunks])
        embedding_model = get_embedding_model_name() if any(embeddings) else ""
        updated_at = dt.datetime.now().isoformat(timespec="seconds")

        connection.executemany(
            """
            INSERT INTO rag_chunks (
                chunk_id,
                record_date,
                chunk_type,
                source_text,
                summary_text,
                goal_ids_json,
                tags_json,
                embedding_model,
                embedding_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk["chunk_id"],
                    chunk["record_date"],
                    chunk["chunk_type"],
                    chunk["source_text"],
                    chunk["summary_text"],
                    _json_dumps(chunk.get("goal_ids", [])),
                    _json_dumps(chunk.get("tags", [])),
                    embedding_model,
                    _json_dumps(embeddings[index] if index < len(embeddings) else []),
                    updated_at,
                )
                for index, chunk in enumerate(chunks)
            ],
        )
        connection.commit()


def rebuild_all_rag_chunks():
    _ensure_database()
    with _connect() as connection:
        dates = [row["date"] for row in connection.execute("SELECT date FROM history_records ORDER BY date").fetchall()]
        connection.execute("DELETE FROM rag_chunks")
        connection.commit()
    for record_date in dates:
        upsert_rag_chunks_for_record(record_date)


def retrieve_rag_chunks(
    query_text,
    goal_ids=None,
    tags=None,
    chunk_types=None,
    top_k=None,
    exclude_date=None,
    _allow_rebuild_on_empty=True,
):
    _ensure_database()
    from services.llm_service import embed_texts, get_embedding_model_name
    from services.rag_service import rank_rag_candidates

    cleaned_query = str(query_text or "").strip()
    if not cleaned_query:
        return []

    query_vectors = embed_texts([cleaned_query])
    query_embedding = query_vectors[0] if query_vectors else []
    if not query_embedding:
        LOGGER.info("RAG retrieval skipped because embedding service is unavailable.")
        return []

    top_k = int(top_k or RAG_TOP_K)
    max_candidates = max(int(RAG_MAX_CANDIDATES), top_k)

    sql = """
        SELECT
            chunk_id,
            record_date,
            chunk_type,
            source_text,
            summary_text,
            goal_ids_json,
            tags_json,
            embedding_model,
            embedding_json,
            updated_at
        FROM rag_chunks
        WHERE 1 = 1
    """
    params: list = []

    if chunk_types:
        placeholders = ",".join("?" for _ in chunk_types)
        sql += f" AND chunk_type IN ({placeholders})"
        params.extend(chunk_types)

    if exclude_date:
        sql += " AND record_date <> ?"
        params.append(exclude_date)

    sql += " ORDER BY record_date DESC LIMIT ?"
    params.append(max_candidates)

    with _connect() as connection:
        rows = connection.execute(sql, params).fetchall()

    has_any_rows = bool(rows)
    has_any_embeddings = False
    current_embedding_model = get_embedding_model_name()
    needs_model_refresh = False

    candidates = []
    for row in rows:
        if row["embedding_model"] and current_embedding_model and row["embedding_model"] != current_embedding_model:
            needs_model_refresh = True
        embedding = _json_loads(row["embedding_json"], [])
        if not embedding:
            continue
        has_any_embeddings = True
        candidates.append(
            {
                "chunk_id": row["chunk_id"],
                "record_date": row["record_date"],
                "chunk_type": row["chunk_type"],
                "source_text": row["source_text"],
                "summary_text": row["summary_text"],
                "goal_ids": _json_loads(row["goal_ids_json"], []),
                "tags": _json_loads(row["tags_json"], []),
                "embedding_model": row["embedding_model"],
                "embedding": embedding,
                "updated_at": row["updated_at"],
            }
        )

    if has_any_rows and needs_model_refresh and _allow_rebuild_on_empty:
        rebuild_all_rag_chunks()
        return retrieve_rag_chunks(
            query_text=cleaned_query,
            goal_ids=goal_ids,
            tags=tags,
            chunk_types=chunk_types,
            top_k=top_k,
            exclude_date=exclude_date,
            _allow_rebuild_on_empty=False,
        )

    if has_any_rows and not has_any_embeddings and _allow_rebuild_on_empty:
        rebuild_all_rag_chunks()
        return retrieve_rag_chunks(
            query_text=cleaned_query,
            goal_ids=goal_ids,
            tags=tags,
            chunk_types=chunk_types,
            top_k=top_k,
            exclude_date=exclude_date,
            _allow_rebuild_on_empty=False,
        )

    if not candidates:
        return []

    return rank_rag_candidates(
        query_text=cleaned_query,
        query_embedding=query_embedding,
        candidates=candidates,
        goal_ids=goal_ids or [],
        tags=tags or [],
        top_k=top_k,
    )
