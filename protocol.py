"""Blackout Comms Live BLE/USB application protocol.

Source of truth: BlackoutCommsLive docs/BLE_Interface_Messages.md
(GATT UUIDs, framing, and JSON keys as implemented by the Android companion).

This is the phone-to-communicator link, not the LoRa mesh protocol.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SERVICE_UUID = "18aeec00-8c60-411b-b958-78c5049be0f3"
TX_UUID = "18aeec01-8c60-411b-b958-78c5049be0f3"  # app -> device, write
RX_UUID = "18aeec02-8c60-411b-b958-78c5049be0f3"  # device -> app, notify/indicate

SCAN_PREFIX = "BC-"
REQUEST_MTU = 247
PIN_TIMEOUT_S = 5.0

# ingest() checks keys in this order and handles exactly one.
INGEST_ORDER = (
    "self",
    "devices",
    "neighbors",
    "location",
    "graph",
    "sender",
    "message",
    "traffic",
    "messageStatus",
    "conn",
)

PRIORITIES = ("Low", "Normal", "Medium", "High", "Critical")
BROADCAST_RECIPIENT = "[all devices]"
MESSAGE_STATUSES = ("queued", "delivered", "confirmed", "meshaccepted", "deleted")


@dataclass
class Frame:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    raw: str = ""


class FrameBuffer:
    """Reassemble GATT notifications into newline-terminated frames.

    The Android app concatenates until the first LF, parses that buffer, then clears.
    Two objects without a newline between them fail as one parse.
    """

    def __init__(self) -> None:
        self._buf = ""

    def push(self, chunk: str) -> list[Frame]:
        self._buf += chunk
        frames: list[Frame] = []
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            frame = parse_line(line)
            if frame is not None:
                frames.append(frame)
        return frames

    def clear(self) -> None:
        self._buf = ""


def parse_line(line: str) -> Frame | None:
    text = line.strip("\r").strip()
    if not text:
        return None
    if text == "success":
        return Frame(kind="success", raw=text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    if "sender" in obj and "message" not in obj:
        return Frame(kind="message", payload=obj, raw=text)
    for key in INGEST_ORDER:
        if key in obj and key != "sender":
            return Frame(kind=key, payload=obj, raw=text)
    return None


def encode_pin(pin: str) -> bytes:
    # Live sendPin() does not append LF. Firmware line readers may want one.
    return f"PIN:{pin}".encode("utf-8")


def encode_json(obj: dict[str, Any], newline: bool = False) -> bytes:
    body = json.dumps(obj, separators=(",", ":"))
    if newline:
        body += "\n"
    return body.encode("utf-8")


def build_broadcast(msg: str, nodes: bool = True, priority: str = "Normal", expiry: int = 60) -> dict[str, Any]:
    return {
        "bc": {
            "msg": sanitize_outbound(msg),
            "nodes": bool(nodes),
            "priority": priority if priority in PRIORITIES else "Normal",
            "expiry": int(expiry),
        }
    }


def build_direct(to: str, msg: str, priority: str = "Normal", force_mesh: bool = False, expiry: int = 30) -> dict[str, Any]:
    return {
        "dm": {
            "to": to,
            "msg": sanitize_outbound(msg),
            "priority": priority if priority in PRIORITIES else "Normal",
            "fm": bool(force_mesh),
            "expiry": int(expiry),
        }
    }


def sanitize_outbound(msg: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,")
    cleaned = "".join(ch if ch in allowed else " " for ch in msg)
    return cleaned[:255]
