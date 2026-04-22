"""Task-level time tracking: records actual wall-clock time spent on a task.

Design notes
------------
- A "session" is one contiguous work interval (start → stop). A single task can
  have many sessions; the *actual minutes* for the task is the sum of all its
  session durations.
- Sessions are persisted on `start`, `stop`, and every pause/resume boundary
  (each pause closes the current session; resume opens a new one). This gives
  lightweight crash tolerance: a browser close mid-session leaves an "orphan"
  row with `ended_at=''`, which `recover_orphan_sessions` surfaces to the UI
  so the user can confirm or edit the actual minutes.
- UI-facing language is intentionally **"实际用时" / "专注记录"**, not
  pomodoro / timer / focus mode. The feature exists to feed the LLM an
  execution-quality signal, not to gamify productivity.

Public API
----------
- start_session(date, task_key) -> session_id
- stop_session(session_id) -> duration_sec
- pause_session(session_id) -> duration_sec  (alias of stop_session)
- resume_session(date, task_key) -> new session_id
- get_active_session(date, task_key=None) -> session dict | None
- aggregate_actual_minutes(date, task_key) -> int
- recover_orphan_sessions(date=None) -> list[session dict]
- resolve_orphan_session(session_id, actual_minutes) -> None
- aggregate_by_tag(start_date, end_date) -> dict[tag -> minutes]
"""

from __future__ import annotations

import datetime as dt
import uuid

from data import repository


def _now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _parse_iso(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def _new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def start_session(date: str, task_key: str) -> str:
    """Open a new session for (date, task_key) and return its id.

    If an active session for the same task already exists, it is closed first
    (treated as an implicit pause) so there is never more than one open session
    per task at a time.
    """
    active = get_active_session(date, task_key)
    if active:
        stop_session(active["session_id"])

    session_id = _new_session_id()
    now = _now_iso()
    repository.upsert_task_session(
        {
            "session_id": session_id,
            "record_date": date,
            "task_key": task_key,
            "started_at": now,
            "ended_at": "",
            "duration_sec": 0,
            "created_at": now,
        }
    )
    return session_id


def stop_session(session_id: str) -> int:
    """Close an active session and persist its duration. Returns duration_sec.

    Idempotent: stopping an already-closed session returns its stored duration
    without rewriting timestamps.
    """
    sessions = [s for s in repository.load_task_sessions() if s["session_id"] == session_id]
    if not sessions:
        return 0
    session = sessions[0]
    if session.get("ended_at"):
        return int(session.get("duration_sec", 0) or 0)

    started = _parse_iso(session.get("started_at", ""))
    end_iso = _now_iso()
    if started is None:
        duration_sec = int(session.get("duration_sec", 0) or 0)
    else:
        duration_sec = max(int((dt.datetime.fromisoformat(end_iso) - started).total_seconds()), 0)

    repository.upsert_task_session(
        {
            **session,
            "ended_at": end_iso,
            "duration_sec": duration_sec,
        }
    )
    return duration_sec


# Pause is semantically identical to stop at the data layer: it closes the
# current session. The UI is responsible for opening a fresh session on resume.
pause_session = stop_session


def resume_session(date: str, task_key: str) -> str:
    """Start a new session for the same (date, task_key). Returns new session_id."""
    return start_session(date, task_key)


def get_active_session(date: str, task_key: str | None = None) -> dict | None:
    """Return the first active (un-ended) session for this date (and optional task)."""
    active = repository.load_task_sessions(date=date, task_key=task_key, active_only=True)
    return active[0] if active else None


def aggregate_actual_minutes(date: str, task_key: str) -> int:
    """Sum all closed sessions for a task, rounded up to the nearest whole minute.

    Uses ceiling so that a 30-second session registers as 1 minute rather than
    being lost to rounding — this matches the user expectation that "I did
    something, it should show up" when they glance at actual vs planned minutes.
    """
    total_sec = sum(
        int(s.get("duration_sec", 0) or 0)
        for s in repository.load_task_sessions(date=date, task_key=task_key)
        if s.get("ended_at")
    )
    if total_sec <= 0:
        return 0
    return (total_sec + 59) // 60


def recover_orphan_sessions(date: str | None = None) -> list[dict]:
    """Return all sessions with ``ended_at=''`` — i.e. not cleanly closed.

    If ``date`` is None, scans across all dates (used when a page load needs
    to surface any straggler from previous sessions).
    """
    return repository.load_task_sessions(date=date, active_only=True)


def resolve_orphan_session(session_id: str, actual_minutes: int) -> None:
    """Close an orphan session with a user-supplied duration estimate."""
    minutes = max(int(actual_minutes or 0), 0)
    sessions = [s for s in repository.load_task_sessions() if s["session_id"] == session_id]
    if not sessions:
        return
    session = sessions[0]
    repository.upsert_task_session(
        {
            **session,
            "ended_at": _now_iso(),
            "duration_sec": minutes * 60,
        }
    )


def _daterange(start_date: str, end_date: str) -> list[str]:
    start = _parse_iso(start_date)
    end = _parse_iso(end_date)
    if start is None or end is None:
        return []
    days = (end.date() - start.date()).days
    if days < 0:
        return []
    return [(start.date() + dt.timedelta(days=offset)).isoformat() for offset in range(days + 1)]


def aggregate_by_tag(start_date: str, end_date: str) -> dict[str, int]:
    """Sum actual_minutes per tag across [start_date, end_date] (inclusive).

    Reads from ``history_tasks.actual_minutes`` rather than summing sessions
    directly, so manual time entries (no timer used) are also counted.
    """
    history = repository.load_history()
    window = set(_daterange(start_date, end_date))
    totals: dict[str, int] = {}
    for record in history:
        if window and record.get("date") not in window:
            continue
        for task in record.get("tasks", []) or []:
            minutes = int(task.get("actual_minutes", 0) or 0)
            if minutes <= 0:
                continue
            tag = str(task.get("tag") or "未分类").strip() or "未分类"
            totals[tag] = totals.get(tag, 0) + minutes
    return totals
