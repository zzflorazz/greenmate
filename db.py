"""SQLite storage for the current environment state and chat history."""
import sqlite3
import math
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path


from settings import DB_PATH


def _database_path() -> Path:
    # Resolve relative paths against this project, regardless of the working directory.
    return Path(__file__).resolve().parent / DB_PATH


def init_db() -> None:
    with closing(sqlite3.connect(_database_path())) as connection:
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS current_state (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    temperature REAL,
                    humidity REAL,
                    light REAL,
                    source_type TEXT,
                    timestamp TEXT
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT,
                    content TEXT,
                    timestamp TEXT
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS environment_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    temperature REAL,
                    humidity REAL,
                    light REAL,
                    source_type TEXT,
                    sim_scenario TEXT
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    run_id TEXT PRIMARY KEY,
                    analysis_time TEXT, location TEXT, question TEXT,
                    state_json TEXT, history_window_json TEXT, prediction_json TEXT,
                    judgment_json TEXT, answer TEXT, evidence_status_json TEXT,
                    created_at TEXT
                )
            """)

            columns = {row[1] for row in connection.execute('PRAGMA table_info(analysis_runs)')}
            if 'tool_trace_json' not in columns:
                connection.execute("ALTER TABLE analysis_runs ADD COLUMN tool_trace_json TEXT NOT NULL DEFAULT '[]'")


def get_state_from_db() -> dict | None:
    with closing(sqlite3.connect(_database_path())) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("""
            SELECT temperature, humidity, light, source_type, timestamp
            FROM current_state WHERE id = 1
        """).fetchone()
    return dict(row) if row is not None else None


def save_state_to_db(state: dict) -> None:
    with closing(sqlite3.connect(_database_path())) as connection:
        with connection:
            connection.execute("""
                INSERT INTO current_state
                    (id, temperature, humidity, light, source_type, timestamp)
                VALUES (1, :temperature, :humidity, :light, :source_type, :timestamp)
                ON CONFLICT(id) DO UPDATE SET
                    temperature = excluded.temperature,
                    humidity = excluded.humidity,
                    light = excluded.light,
                    source_type = excluded.source_type,
                    timestamp = excluded.timestamp
            """, state)


def save_chat(role: str, content: str) -> None:
    if role not in ("user", "assistant"):
        raise ValueError("Chat role must be user or assistant.")
    timestamp = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(_database_path())) as connection:
        with connection:
            connection.execute(
                "INSERT INTO chat_history (role, content, timestamp) VALUES (?, ?, ?)",
                (role, content, timestamp),
            )


def load_recent_chat(limit: int = 10) -> list[dict]:
    """Select the newest messages, then return them in conversation order."""
    if limit < 0:
        raise ValueError("Chat limit must be non-negative.")
    with closing(sqlite3.connect(_database_path())) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT id, role, content, timestamp FROM chat_history ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def _sample_values(state: dict) -> tuple:
    timestamp = state.get("timestamp") or datetime.now(timezone.utc).isoformat()
    moment = datetime.fromisoformat(timestamp)
    if moment.tzinfo is None:
        raise ValueError("Sample timestamps must include a timezone.")
    values = [state[key] for key in ("temperature", "humidity", "light")]
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError("Sample values must be finite numbers.")
    return (moment.astimezone(timezone.utc).isoformat(), *values, state["source_type"], state.get("sim_scenario"))


def add_sample(state: dict) -> None:
    values = _sample_values(state)
    with closing(sqlite3.connect(_database_path())) as connection:
        with connection:
            connection.execute("""
                INSERT INTO environment_samples
                    (timestamp, temperature, humidity, light, source_type, sim_scenario)
                VALUES (?, ?, ?, ?, ?, ?)
            """, values)


def get_samples(hours=24) -> list[dict]:
    if type(hours) not in (int, float) or not math.isfinite(hours) or hours <= 0:
        raise ValueError("hours must be a positive finite number.")
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    with closing(sqlite3.connect(_database_path())) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("""
            SELECT id, timestamp, temperature, humidity, light, source_type, sim_scenario
            FROM environment_samples
            WHERE julianday(timestamp) >= julianday(?) AND julianday(timestamp) <= julianday(?)
            ORDER BY timestamp ASC, id ASC
        """, (start.isoformat(), now.isoformat())).fetchall()
    return [dict(row) for row in rows]


def get_samples_at(analysis_time: datetime, hours=3) -> list[dict]:
    """Anchored half-open interval (time-hours, time], independent of wall clock."""
    if analysis_time.tzinfo is None or hours <= 0:
        raise ValueError('时间锚点必须带时区，hours 必须为正数。')
    end = analysis_time.astimezone(timezone.utc)
    start = end - timedelta(hours=hours)
    with closing(sqlite3.connect(_database_path())) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("""
            SELECT * FROM environment_samples
            WHERE julianday(timestamp) >= julianday(?) AND julianday(timestamp) <= julianday(?)
            ORDER BY julianday(timestamp) ASC, id ASC
        """, ((start-timedelta(seconds=1)).isoformat(), (end+timedelta(seconds=1)).isoformat())).fetchall()
    # SQLite's date functions round to milliseconds. Enforce the exact Python
    # microsecond boundary so even a point 1us after the anchor cannot leak in.
    return [dict(row) for row in rows if start < datetime.fromisoformat(row['timestamp']).astimezone(timezone.utc) <= end]


def add_analysis_run(record: dict) -> None:
    import json
    fields = ('state', 'history_window', 'prediction', 'judgment', 'evidence_status', 'tool_trace')
    values = {key: record[key] for key in ('run_id', 'analysis_time', 'location', 'question', 'answer', 'created_at')}
    values.update({key + '_json': json.dumps(record.get(key, []) if key == 'tool_trace' else record[key], ensure_ascii=False, allow_nan=False) for key in fields})
    with closing(sqlite3.connect(_database_path())) as connection, connection:
        connection.execute("""
            INSERT INTO analysis_runs
            (run_id, analysis_time, location, question, state_json, history_window_json,
             prediction_json, judgment_json, answer, evidence_status_json, created_at, tool_trace_json) VALUES
            (:run_id, :analysis_time, :location, :question, :state_json,
             :history_window_json, :prediction_json, :judgment_json, :answer,
             :evidence_status_json, :created_at, :tool_trace_json)
        """, values)


def finish_analysis_run(run_id: str, answer: str, judgment: dict) -> None:
    import json
    with closing(sqlite3.connect(_database_path())) as connection, connection:
        connection.execute('UPDATE analysis_runs SET answer=?, judgment_json=? WHERE run_id=?',
                           (answer, json.dumps(judgment, ensure_ascii=False, allow_nan=False), run_id))


def get_analysis_run(run_id: str) -> dict | None:
    import json
    with closing(sqlite3.connect(_database_path())) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute('SELECT * FROM analysis_runs WHERE run_id=?', (run_id,)).fetchone()
    if row is None:
        return None
    return {key.removesuffix('_json'): json.loads(value) if key.endswith('_json') else value
            for key, value in dict(row).items()}


def list_analysis_runs(limit=5) -> list[dict]:
    with closing(sqlite3.connect(_database_path())) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute('SELECT run_id, analysis_time, location, question, created_at FROM analysis_runs ORDER BY created_at DESC, run_id DESC LIMIT ?', (limit,)).fetchall()
    return [dict(row) for row in rows]
