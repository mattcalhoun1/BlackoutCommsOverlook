"""Named radio configs. Tiles are cached separately and are not cleared on disconnect."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
import sys

if getattr(sys, "frozen", False):
    DATA = Path(os.environ.get("LOCALAPPDATA", ".")) / "Overlook"
else:
    DATA = Path(__file__).resolve().parent / "data"

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SESSION_PATH = DATA / "session.json"
BACKUP_PATH = DATA / "session.json.bak"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return current if isinstance(current, dict) else None


def load() -> dict[str, Any]:
    current = _read(SESSION_PATH)
    if current is None:
        current = _read(BACKUP_PATH) or {}
        if current:
            print(f"session.json unreadable, restored {BACKUP_PATH}")
    radios = current.get("radios")
    if not isinstance(radios, list):
        radios = []
    if not radios and current.get("device_name"):
        radios.append({
            "label": current.get("device_name"),
            "device": current.get("device_name"),
            "pin": current.get("pin") or "",
            "save_state": True,
            "snapshot": current.get("snapshot"),
            "view": current.get("view"),
        })
    current["radios"] = radios
    return current


def save(session: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(session, indent=2).encode("utf-8")
    tmp = SESSION_PATH.with_suffix(".json.tmp")
    with tmp.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    if _read(SESSION_PATH) is not None:
        os.replace(SESSION_PATH, BACKUP_PATH)
    os.replace(tmp, SESSION_PATH)


def update(**fields: Any) -> dict[str, Any]:
    current = load()
    current.update(fields)
    save(current)
    return current


def radios() -> list[dict[str, Any]]:
    return load().get("radios") or []


def public_radios() -> list[dict[str, Any]]:
    return [
        {
            "label": item.get("label") or item.get("device"),
            "device": item.get("device"),
            "pin": item.get("pin") or "",
            "save_state": bool(item.get("save_state", True)),
            "has_state": bool(item.get("snapshot")),
        }
        for item in radios()
    ]


def upsert_radio(label: str, device: str, pin: str, save_state: bool) -> dict[str, Any]:
    current = load()
    items = current.setdefault("radios", [])
    found = next((item for item in items if item.get("device") == device), None)
    if found is None:
        found = {"device": device}
        items.append(found)
    found["label"] = label or found.get("label") or device
    found["pin"] = pin
    found["save_state"] = save_state
    if not save_state:
        found.pop("snapshot", None)
    current["last_device"] = device
    save(current)
    return found


def set_snapshot(device: str, snapshot: dict[str, Any] | None, view: dict[str, Any] | None = None) -> None:
    current = load()
    for item in current.get("radios") or []:
        if item.get("device") != device:
            continue
        if item.get("save_state", True) and snapshot is not None:
            item["snapshot"] = snapshot
            if view:
                item["view"] = view
        else:
            item.pop("snapshot", None)
        break
    if view:
        current["view"] = view
    save(current)


def find(device: str) -> dict[str, Any] | None:
    return next((item for item in radios() if item.get("device") == device), None)
