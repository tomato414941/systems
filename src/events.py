"""Service event log — shared, per-round event bus."""
from __future__ import annotations

import json
import os
import shutil

EVENTS_FILE = "events.json"
MAX_EVENTS_PER_ROUND = 200


def _events_path(data_dir: str) -> str:
    return os.path.join(data_dir, "managed", EVENTS_FILE)


def load_events(data_dir: str) -> list[dict]:
    path = _events_path(data_dir)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def save_events(events: list[dict], data_dir: str) -> None:
    path = _events_path(data_dir)
    with open(path, "w") as f:
        json.dump(events, f, indent=2)
    public_copy = os.path.join(data_dir, "public", EVENTS_FILE)
    try:
        shutil.copy2(path, public_copy)
    except OSError:
        pass


def append_event(
    data_dir: str,
    service_name: str,
    event_name: str,
    event_data: dict,
    round_num: int,
) -> None:
    events = load_events(data_dir)
    if len(events) >= MAX_EVENTS_PER_ROUND:
        return
    events.append({
        "round": round_num,
        "service": service_name,
        "event": event_name,
        "data": event_data,
    })
    save_events(events, data_dir)


def clear_events(data_dir: str) -> None:
    save_events([], data_dir)
