#!/usr/bin/env python3
"""Overlook wall view. No simulator unless explicitly requested.

A saved device name and PIN reconnect on startup. The last map and cluster
snapshot stay on screen while the link is down. Disconnect is the only
action that clears them. Tiles stay cached either way.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import session
from cluster import ClusterStore
from transport import BleLink, Simulator, command_from_http

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
TILES = {
    "esri_topo": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}", "zyx"),
    "opentopo": ("https://a.tile.opentopomap.org/{z}/{x}/{y}.png", "zxy"),
    "osm": ("https://tile.openstreetmap.org/{z}/{x}/{y}.png", "zxy"),
    "usgs": ("https://cache.chatters.io/tiles/usgs_topo/{z}/{x}/{y}.png", "zxy"),
}
DEFAULT_TILE = "esri_topo"

store = ClusterStore()
sim = Simulator(store)
ble = BleLink(store)
active = "offline"
active_radio = ""


def radio_name(value: str) -> str:
    raw = value.strip().upper()
    if raw.startswith("BC-"):
        raw = raw[3:]
    ident = "".join(ch for ch in raw if ch.isalnum())[:6]
    return f"BC-{ident}" if ident else ""


def radio_pin(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def remember_link(name: str, address: str, pin: str) -> None:
    device = radio_name(name) or name
    current = session.find(device) or {}
    session.upsert_radio(current.get("label") or device, device, radio_pin(pin) or current.get("pin") or "", bool(current.get("save_state", True)))
    session.update(device_address=address)


ble.on_linked = remember_link


def current_transport():
    return ble if active == "ble" else None


def persist_snapshot() -> None:
    if not active_radio or not store.devices:
        return
    radio = session.find(active_radio)
    if not radio or not radio.get("save_state", True):
        session.set_snapshot(active_radio, None)
        return
    snap = store.snapshot()
    session.set_snapshot(active_radio, {
        "cluster": snap["cluster"],
        "self": snap["self"],
        "conn": snap["conn"],
        "devices": snap["devices"],
        "graph": snap["graph"],
        "messages": snap["messages"],
        "pings": snap["pings"],
        "traffic": snap["traffic"],
    }, session.load().get("view"))


def snapshot_loop() -> None:
    while True:
        time.sleep(30)
        try:
            persist_snapshot()
        except Exception:
            pass


def tile_bytes(source: str, z: int, y: int, x: int) -> bytes:
    spec = TILES.get(source) or TILES[DEFAULT_TILE]
    url, order = spec
    path = session.DATA / "tiles" / source / str(z) / str(y) / f"{x}.png"
    legacy = session.DATA / "tiles" / "ESRI.WorldTopoMap" / str(z) / str(y) / f"{x}.png"
    if path.exists():
        return path.read_bytes()
    if source == "esri_topo" and legacy.exists():
        return legacy.read_bytes()
    req = urllib.request.Request(url.format(z=z, y=y, x=x), headers={"User-Agent": "Overlook/BlackoutComms"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = resp.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/overlook-logo.png":
            data = (STATIC / "overlook-logo.png").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/state":
            body = store.snapshot()
            current = session.load()
            body["view"] = current.get("view")
            body["tilesource"] = current.get("tilesource") or "esri_topo"
            body["keep_centered"] = bool(current.get("keep_centered"))
            body["radios"] = session.public_radios()
            body["active_radio"] = active_radio
            self._send(200, json.dumps(body).encode(), "application/json")
            return
        if path.startswith("/tiles/"):
            parts = path.strip("/").split("/")
            try:
                source, z, y, x = parts[1], int(parts[2]), int(parts[3]), int(parts[4].split(".")[0])
                data = tile_bytes(source, z, y, x)
            except Exception:
                self._send(404, b"", "image/png")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "public, max-age=31536000")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        global active
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            self._send(400, b'{"error":"bad json"}', "application/json")
            return
        path = self.path.split("?", 1)[0]
        if path == "/api/connect":
            global active_radio
            pin = radio_pin(body.get("pin") or "")
            device = radio_name(body.get("device") or "")
            label = str(body.get("label") or device).strip()
            save_state = bool(body.get("save_state", True))
            if not device:
                self._send(400, b'{"error":"device required"}', "application/json")
                return
            session.upsert_radio(label, device, pin, save_state)
            prior = session.find(device) or {}
            sim.stop()
            ble.stop()
            store.reset()
            if save_state and prior.get("snapshot"):
                store.restore(prior["snapshot"])
            active = "ble"
            active_radio = device
            ble.start(pin=pin, device_name=device)
            self._send(200, json.dumps({"ok": True, "device": device}).encode(), "application/json")
            return
        if path == "/api/disconnect":
            sim.stop()
            ble.stop()
            active = "offline"
            active_radio = ""
            store.reset()
            self._send(200, b'{"ok":true}', "application/json")
            return
        if path == "/api/view":
            fields = {"view": {"lat": body.get("lat"), "lon": body.get("lon"), "zoom": body.get("zoom")}}
            if body.get("tilesource"):
                fields["tilesource"] = body.get("tilesource")
            if "keep_centered" in body:
                fields["keep_centered"] = bool(body.get("keep_centered"))
            session.update(**fields)
            self._send(200, b'{"ok":true}', "application/json")
            return
        if path == "/api/send":
            transport = current_transport()
            if transport is None or not store.connected:
                self._send(409, b'{"error":"not connected"}', "application/json")
                return
            try:
                obj = command_from_http(body)
            except ValueError as exc:
                self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return
            transport.send(obj)
            self._send(200, json.dumps({"ok": True, "frame": obj}).encode(), "application/json")
            return
        self._send(404, b"not found", "text/plain")


def main() -> None:
    global active
    parser = argparse.ArgumentParser(description="Overlook wall view")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8733)
    parser.add_argument("--simulate", action="store_true", help="demo feed, off unless asked")
    args = parser.parse_args()
    prior = session.load()
    radios = prior.get("radios") or []
    last = session.find(prior.get("last_device") or "")
    if not (last and last.get("snapshot")):
        last = next((item for item in reversed(radios) if item.get("snapshot")), last or (radios[-1] if radios else None))
    if last and last.get("save_state", True) and last.get("snapshot"):
        store.restore(last["snapshot"])
        print(f"loaded {len(store.devices)} devices from {session.SESSION_PATH}")
    view = (last or {}).get("view") or prior.get("view")
    if view:
        session.update(view=view)
    if last and last.get("device") and last.get("pin"):
        global active_radio
        active = "ble"
        active_radio = last["device"]
        ble.start(pin=last.get("pin") or "", device_name=last["device"])
        print(f"restored {last.get('label') or last['device']} from {session.DATA}")
    elif not radios:
        print(f"no saved radios in {session.SESSION_PATH}")
    threading.Thread(target=snapshot_loop, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Overlook on http://{args.host}:{args.port}  mode={active}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop()
        ble.stop()
        server.server_close()


if __name__ == "__main__":
    main()
