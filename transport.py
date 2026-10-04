"""Transports: a firmware-shaped simulator, and a BlueZ client via bleak."""

from __future__ import annotations

import asyncio
import json
import random
import threading
import time
from pathlib import Path

from cluster import ClusterStore
from protocol import (
    RX_UUID,
    SCAN_PREFIX,
    SERVICE_UUID,
    TX_UUID,
    FrameBuffer,
    build_broadcast,
    build_direct,
    encode_json,
    encode_pin,
    parse_line,
)

SAMPLES = Path(__file__).with_name("samples")


def _load(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


class Simulator:
    """Speaks the device side of the Live feed so the wall view runs with no radio."""

    def __init__(self, store: ClusterStore) -> None:
        self.store = store
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seq = 10

    def start(self, pin: str = "") -> None:
        self.stop()
        self._stop.clear()
        self.store.mark_link(True, "BC-RIDGE-LINK", "simulator")
        self._thread = threading.Thread(target=self._run, args=(pin,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None

    def send(self, obj: dict) -> None:
        raw = json.dumps(obj)
        self.store.note("tx", raw)
        if "dm" in obj:
            self._echo_dm(obj["dm"])
        elif "bc" in obj:
            self._echo_bc(obj["bc"])

    def _feed(self, line: str) -> None:
        self.store.note("rx", line.strip())
        frame = parse_line(line)
        if frame:
            self.store.ingest(frame)

    def _run(self, pin: str) -> None:
        if pin:
            self.store.note("tx", f"PIN:{pin}")
            time.sleep(0.3)
            self._feed("success\n")
            self.store.pin_ok = True
        else:
            self.store.pin_ok = True
        for name in ("session.jsonl",):
            for line in _load(name).splitlines():
                if self._stop.is_set():
                    return
                if line.strip():
                    self._feed(line if line.endswith("\n") else line + "\n")
                    time.sleep(0.15)
        while not self._stop.is_set():
            self._tick()
            self._stop.wait(4.0)

    def _tick(self) -> None:
        drift = random.choice(["NV002", "NV003", "NV004", "NV005"])
        device = self.store.devices.get(drift)
        if not device or not device.get("lat"):
            return
        lat = float(device["lat"]) + random.uniform(-0.0004, 0.0004)
        lon = float(device["lon"]) + random.uniform(-0.0004, 0.0004)
        head = (float(device.get("head") or 0) + random.uniform(-12, 12)) % 360
        ts = time.strftime("%y%m%d%H%M%S", time.gmtime())
        self._feed(json.dumps({
            "location": [{
                "id": drift,
                "lat": f"{lat:.5f}",
                "lon": f"{lon:.5f}",
                "head": f"{head:.1f}",
                "speed": f"{random.uniform(0, 2.4):.1f}",
                "ts": ts,
            }]
        }) + "\n")
        rssi = random.randint(-78, -46)
        self._feed(json.dumps({
            "neighbors": {
                "direct": [
                    {"id": "NV002", "ts": ts, "rssi": rssi, "battery": "high", "motion": "still"},
                    {"id": "NV004", "ts": ts, "rssi": rssi - 9, "battery": "medium"},
                ],
                "indirect": [
                    {"id": "NV003", "ts": ts, "rssi": -86, "battery": "high"},
                    {"id": "NV005", "ts": ts, "rssi": -91, "battery": "low"},
                ],
            }
        }) + "\n")
        traffic = self.store.traffic[-1] if self.store.traffic else {
            "bytesIn": 18420, "bytesOut": 9240, "packetsIn": 114, "packetsOut": 38, "unknownPackets": 0
        }
        self._feed(json.dumps({
            "traffic": {
                "bytesIn": int(traffic.get("bytesIn", 0)) + random.randint(40, 180),
                "bytesOut": int(traffic.get("bytesOut", 0)) + random.randint(10, 80),
                "packetsIn": int(traffic.get("packetsIn", 0)) + random.randint(1, 3),
                "packetsOut": int(traffic.get("packetsOut", 0)) + 1,
                "unknownPackets": int(traffic.get("unknownPackets", 0)),
            }
        }) + "\n")

    def _echo_dm(self, dm: dict) -> None:
        self._seq += 1
        ident = f"msg{self._seq:03d}"
        sender = (self.store.self or {}).get("id") or "NV001"
        ts = time.strftime("%y%m%d%H%M%S", time.gmtime())
        self._feed(json.dumps({
            "message": {
                "id": ident,
                "sender": sender,
                "recipient": dm.get("to"),
                "delivery": "mesh" if dm.get("fm") else "direct",
                "status": "queued",
                "ts": ts,
                "title": "Direct",
                "text": dm.get("msg"),
                "isNew": True,
                "priority": dm.get("priority") or "Normal",
            }
        }) + "\n")

        def confirm() -> None:
            time.sleep(2.2)
            if self._stop.is_set():
                return
            self._feed(json.dumps({
                "messageStatus": {
                    "id": ident,
                    "sender": sender,
                    "recipient": dm.get("to"),
                    "status": "confirmed",
                }
            }) + "\n")

        threading.Thread(target=confirm, daemon=True).start()

    def _echo_bc(self, bc: dict) -> None:
        self._seq += 1
        ident = f"msg{self._seq:03d}"
        sender = (self.store.self or {}).get("id") or "NV001"
        ts = time.strftime("%y%m%d%H%M%S", time.gmtime())
        self._feed(json.dumps({
            "message": {
                "id": ident,
                "sender": sender,
                "recipient": "[all devices]",
                "delivery": "mesh",
                "status": "meshaccepted",
                "ts": ts,
                "title": "Broadcast",
                "text": bc.get("msg"),
                "isNew": True,
                "priority": bc.get("priority") or "Normal",
            }
        }) + "\n")


class BleLink:
    """BlueZ central. Requires bleak and a Linux Bluetooth adapter. No radio in this sandbox."""

    def __init__(self, store: ClusterStore) -> None:
        self.store = store
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client = None
        self._buf = FrameBuffer()
        self._pin = ""
        self._newline = False
        self._device_name = ""
        self._user_stop = False
        self.on_linked = None

    def start(self, pin: str = "", newline: bool = False, device_name: str = "") -> None:
        self.stop()
        self._pin = pin
        self._newline = newline
        self._device_name = device_name
        self._user_stop = False
        self._buf.clear()
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._user_stop = True
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None
        self._loop = None
        self._client = None

    def send(self, obj: dict) -> None:
        payload = encode_json(obj, newline=self._newline)
        self.store.note("tx", payload.decode("utf-8"))
        self._write(payload)

    def _write(self, payload: bytes) -> None:
        loop = self._loop
        client = self._client
        if not loop or not client:
            self.store.last_error = "BLE link is not up"
            return
        asyncio.run_coroutine_threadsafe(client.write_gatt_char(TX_UUID, payload, response=True), loop)

    def _thread_main(self) -> None:
        try:
            import bleak  # noqa: F401
        except ImportError:
            self.store.mark_link(False, mode="ble", error="bleak is not installed (pip install bleak)")
            return
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._until_stopped())
        self._loop.run_forever()

    async def _until_stopped(self) -> None:
        while not self._user_stop:
            await self._session()
            if self._user_stop:
                break
            self.store.mark_link(False, self.store.link_name, "ble", "reconnecting")
            await asyncio.sleep(3)

    async def _session(self) -> None:
        from bleak import BleakClient, BleakScanner

        wanted = self._device_name
        self.store.mark_link(False, wanted, "ble", "scanning")

        def matches(device, _ad) -> bool:
            name = device.name or ""
            if wanted:
                return name == wanted or device.address == wanted
            return name.startswith(SCAN_PREFIX)

        try:
            device = await BleakScanner.find_device_by_filter(matches, timeout=8.0)
        except Exception as exc:
            self.store.mark_link(False, wanted, "ble", str(exc))
            return
        if device is None or self._user_stop:
            self.store.mark_link(False, wanted, "ble", "disconnected")
            return
        name = device.name or device.address
        self.store.mark_link(True, name, "ble", "")
        if self.on_linked:
            self.on_linked(name, device.address, self._pin)

        def on_notify(_char, data: bytearray) -> None:
            text = data.decode("utf-8", errors="replace")
            if text.strip() == "success":
                self.store.note("rx", "success")
                parsed = parse_line("success")
                if parsed:
                    self.store.ingest(parsed)
            for frame in self._buf.push(text):
                self.store.note("rx", frame.raw or frame.kind)
                self.store.ingest(frame)

        try:
            async with BleakClient(device) as client:
                self._client = client
                uuids = {str(s.uuid).lower() for s in client.services}
                if SERVICE_UUID not in uuids:
                    self.store.mark_link(False, name, "ble", "GATT service missing")
                    return
                await client.start_notify(RX_UUID, on_notify)
                if self._pin:
                    await client.write_gatt_char(TX_UUID, encode_pin(self._pin), response=True)
                    self.store.note("tx", f"PIN:{self._pin}")
                while not self._user_stop and client.is_connected:
                    await asyncio.sleep(0.5)
        except Exception as exc:
            if not self._user_stop:
                self.store.mark_link(False, name, "ble", str(exc))
        finally:
            self._client = None
            if not self._user_stop:
                self.store.mark_link(False, name, "ble", "reconnecting")


def command_from_http(body: dict) -> dict:
    kind = body.get("kind")
    if kind == "bc":
        return build_broadcast(
            body.get("msg") or "",
            nodes=bool(body.get("nodes", True)),
            priority=body.get("priority") or "Normal",
            expiry=int(body.get("expiry") or 60),
        )
    if kind == "dm":
        return build_direct(
            body.get("to") or "",
            body.get("msg") or "",
            priority=body.get("priority") or "Normal",
            force_mesh=bool(body.get("fm")),
            expiry=int(body.get("expiry") or 30),
        )
    raise ValueError("kind must be dm or bc")
