"""Cluster state assembled from the Live JSON feed. Upsert rules match ClusterRepository."""

from __future__ import annotations

import time
from typing import Any

from protocol import BROADCAST_RECIPIENT, Frame


def normalise_address(address: str | None) -> str:
    if not address:
        return ""
    stripped = address.lstrip("0")
    return stripped or "0"


class ClusterStore:
    def __init__(self) -> None:
        self.connected = False
        self.link_name = ""
        self.mode = "offline"
        self.pin_ok = False
        self.last_rx = 0.0
        self.last_error = ""
        self.cluster = ""
        self.self: dict[str, Any] | None = None
        self.conn: dict[str, Any] | None = None
        self.devices: dict[str, dict[str, Any]] = {}
        self.direct_ids: dict[str, float] = {}
        self.indirect_ids: set[str] = set()
        self.pings: list[dict[str, Any]] = []
        self.graph: dict[str, dict[str, dict[str, Any]]] = {}
        self.messages: dict[str, dict[str, Any]] = {}
        self.traffic: list[dict[str, Any]] = []
        self.pending_locations: dict[str, dict[str, Any]] = {}
        self.log: list[dict[str, str]] = []

    def reset(self) -> None:
        self.connected = False
        self.link_name = ""
        self.mode = "offline"
        self.pin_ok = False
        self.last_rx = 0.0
        self.last_error = ""
        self.cluster = ""
        self.self = None
        self.conn = None
        self.devices = {}
        self.direct_ids = {}
        self.indirect_ids = set()
        self.pings = []
        self.graph = {}
        self.messages = {}
        self.traffic = []
        self.pending_locations = {}
        self.log = []

    def note(self, direction: str, text: str) -> None:
        self.log.append({"dir": direction, "text": text[:500], "ts": str(int(time.time()))})
        self.log = self.log[-80:]

    def restore(self, snapshot: dict) -> None:
        self.cluster = snapshot.get("cluster") or ""
        self.self = snapshot.get("self")
        self.conn = snapshot.get("conn")
        self.devices = {d["id"]: dict(d) for d in snapshot.get("devices") or [] if d.get("id")}
        self.graph = snapshot.get("graph") or {}
        self.messages = {m.get("key") or m.get("id"): m for m in snapshot.get("messages") or []}
        self.pings = list(snapshot.get("pings") or [])
        self.traffic = list(snapshot.get("traffic") or [])
        self.connected = False
        self.pin_ok = False
        self.mode = "offline"
        self.last_error = ""

    def mark_link(self, up: bool, name: str = "", mode: str = "offline", error: str = "") -> None:
        self.connected = up
        self.link_name = name
        self.mode = mode
        self.last_error = error
        if up:
            self.last_rx = time.time()
        else:
            self.pin_ok = False

    def ingest(self, frame: Frame) -> None:
        self.last_rx = time.time()
        if frame.kind == "success":
            self.pin_ok = True
            return
        if frame.kind == "conn":
            self.conn = frame.payload.get("conn") or {}
            return
        if frame.kind == "self":
            self._upsert_self(frame.payload.get("self") or {})
            return
        if frame.kind == "devices":
            for item in frame.payload.get("devices") or []:
                self._upsert_device(item)
            self._flush_locations()
            return
        if frame.kind == "location":
            for item in frame.payload.get("location") or []:
                self._apply_location(item)
            return
        if frame.kind == "neighbors":
            self._apply_neighbors(frame.payload.get("neighbors") or {})
            return
        if frame.kind == "graph":
            self._merge_graph(frame.payload.get("graph") or {})
            return
        if frame.kind == "message":
            body = frame.payload.get("message", frame.payload)
            self._upsert_message(body)
            return
        if frame.kind == "messageStatus":
            self._patch_status(frame.payload.get("messageStatus") or {})
            return
        if frame.kind == "traffic":
            sample = dict(frame.payload.get("traffic") or {})
            sample["at"] = time.time()
            self.traffic.append(sample)
            self.traffic = self.traffic[-240:]

    def _upsert_self(self, self_obj: dict[str, Any]) -> None:
        self.self = self_obj
        if self_obj.get("cluster"):
            self.cluster = str(self_obj["cluster"])
        device = {
            "id": self_obj.get("id"),
            "name": self_obj.get("name"),
            "nickname": self_obj.get("nickname"),
            "address": self_obj.get("address"),
            "icon": self_obj.get("icon"),
            "batteryLevel": self_obj.get("batteryLevel"),
            "lat": self_obj.get("lat"),
            "lon": self_obj.get("lon"),
            "alt": self_obj.get("alt"),
            "head": self_obj.get("head"),
            "speed": self_obj.get("speed"),
            "ts": self_obj.get("ts"),
            "relayState": self_obj.get("relayState"),
            "motion": self_obj.get("motion"),
            "temperature": self_obj.get("temperature"),
            "self": True,
        }
        if device["id"]:
            self._upsert_device(device)
            self._apply_location(device)

    def _upsert_device(self, item: dict[str, Any]) -> None:
        ident = item.get("id")
        if not ident:
            return
        current = self.devices.get(ident, {})
        current.update({k: v for k, v in item.items() if v is not None})
        current["id"] = ident
        self.devices[ident] = current

    def _apply_location(self, item: dict[str, Any]) -> None:
        ident = item.get("id")
        if not ident:
            return
        if ident not in self.devices:
            self.pending_locations[ident] = item
            return
        device = self.devices[ident]
        for key in ("lat", "lon", "head", "speed", "ts", "alt"):
            if item.get(key) is not None:
                device[key] = item[key]
        device["fix_at"] = time.time()

    def _flush_locations(self) -> None:
        ready = [i for i in self.pending_locations if i in self.devices]
        for ident in ready:
            self._apply_location(self.pending_locations.pop(ident))

    def _as_list(self, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
        if isinstance(value, dict):
            return [v for v in value.values() if isinstance(v, dict)]
        return []

    def _apply_neighbors(self, neighbors: dict[str, Any]) -> None:
        now = time.time()
        for item in self._as_list(neighbors.get("direct")):
            ident = item.get("id")
            if not ident:
                continue
            self.direct_ids[ident] = now
            self.indirect_ids.discard(ident)
            self._neighbor_vitals(item)
            self._ping(item, "DIRECT")
        for item in self._as_list(neighbors.get("indirect")):
            ident = item.get("id")
            if not ident:
                continue
            if ident not in self.direct_ids:
                self.indirect_ids.add(ident)
            self._neighbor_vitals(item)
            self._ping(item, "INDIRECT")
        # Direct flags age out after 10 minutes without a refresh.
        expired = [i for i, seen in self.direct_ids.items() if now - seen > 600]
        for ident in expired:
            self.direct_ids.pop(ident, None)

    def _neighbor_vitals(self, item: dict[str, Any]) -> None:
        ident = item.get("id")
        if ident not in self.devices:
            return
        device = self.devices[ident]
        for src, dst in (
            ("battery", "batteryLevel"),
            ("temperature", "temperature"),
            ("motion", "motion"),
            ("relayState", "relayState"),
            ("rssi", "rssi"),
            ("ts", "heard"),
        ):
            if item.get(src) is not None:
                device[dst] = item[src]

    def _ping(self, item: dict[str, Any], kind: str) -> None:
        self.pings.insert(0, {
            "id": item.get("id"),
            "kind": kind,
            "rssi": item.get("rssi"),
            "ts": item.get("ts"),
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "at": time.time(),
        })
        self.pings = self.pings[:30]

    def _merge_graph(self, graph: dict[str, Any]) -> None:
        for src, edges in graph.items():
            if not isinstance(edges, dict):
                continue
            bucket = self.graph.setdefault(str(src), {})
            for dst, edge in edges.items():
                if isinstance(edge, dict):
                    bucket[str(dst)] = edge

    def _message_key(self, body: dict[str, Any]) -> str:
        ident = body.get("id")
        recipient = body.get("recipient") or ""
        if ident:
            return f"{ident}|{recipient}"
        return f"{body.get('sender')}_{body.get('ts')}|{recipient}"

    def _upsert_message(self, body: dict[str, Any]) -> None:
        status = str(body.get("status") or "").lower()
        key = self._message_key(body)
        if status == "deleted":
            self.messages.pop(key, None)
            return
        current = self.messages.get(key, {})
        current.update(body)
        current["key"] = key
        self.messages[key] = current
        if len(self.messages) > 50:
            oldest = sorted(self.messages, key=lambda k: str(self.messages[k].get("ts") or ""))[:-50]
            for item in oldest:
                self.messages.pop(item, None)

    def _patch_status(self, body: dict[str, Any]) -> None:
        key = self._message_key(body)
        if key not in self.messages:
            return
        status = str(body.get("status") or "")
        if status.lower() == "deleted":
            self.messages.pop(key, None)
            return
        self.messages[key]["status"] = status

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        devices = []
        for device in self.devices.values():
            item = dict(device)
            ident = item.get("id")
            item["direct"] = ident in self.direct_ids
            item["indirect"] = ident in self.indirect_ids
            fix_at = item.get("fix_at")
            item["stale"] = bool(fix_at and now - float(fix_at) > 180 and not item.get("self"))
            devices.append(item)
        messages = sorted(self.messages.values(), key=lambda m: str(m.get("ts") or ""), reverse=True)
        age = None if not self.last_rx else round(now - self.last_rx, 1)
        return {
            "connected": self.connected,
            "link_name": self.link_name,
            "mode": self.mode,
            "pin_ok": self.pin_ok,
            "last_rx_age": age,
            "last_error": self.last_error,
            "cluster": self.cluster,
            "self": self.self,
            "conn": self.conn,
            "devices": devices,
            "graph": self.graph,
            "messages": messages[:50],
            "pings": self.pings[:50],
            "neighbors_3m": len({p.get("id") for p in self.pings if p.get("id") and now - float(p.get("at") or 0) <= 180}),
            "traffic": self.traffic[-30:],
            "broadcast_recipient": BROADCAST_RECIPIENT,
        }
