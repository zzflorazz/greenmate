from datetime import datetime, timezone

from db import get_state_from_db, save_state_to_db


def current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_STATE = {
    "temperature": 24,
    "humidity": 65,
    "light": 12000,
    "source_type": "SIMULATED",
    "timestamp": current_timestamp(),
}

# Populated from SQLite during application startup.
_current_state: dict | None = None


def load_state() -> None:
    global _current_state
    state = get_state_from_db()
    if state is None:
        state = {**DEFAULT_STATE, "timestamp": current_timestamp()}
        save_state_to_db(state)
    _current_state = state


def get_state() -> dict:
    if _current_state is None:
        raise RuntimeError("State has not been loaded during application startup.")
    return _current_state.copy()


def update_state(changes: dict, *, source_type: str = "SIMULATED") -> dict:
    global _current_state
    if source_type not in ("SIMULATED", "REAL_WEATHER", "MANUAL"):
        raise ValueError("Unsupported state source.")
    # Merge into the authoritative database row, not a possibly stale cache.
    next_state = get_state_from_db()
    if next_state is None:
        raise RuntimeError("Current state is missing; initialize the application first.")
    for field in ("temperature", "humidity", "light"):
        if field in changes:
            next_state[field] = changes[field]
    next_state["source_type"] = source_type
    next_state["timestamp"] = current_timestamp()
    # A failed write must leave the cache unchanged.
    save_state_to_db(next_state)
    _current_state = next_state
    return get_state()
