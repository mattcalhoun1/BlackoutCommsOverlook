# Overlook

Linux / Raspberry Pi wall view for a Blackout Comms cluster. It speaks the same GATT JSON feed as Blackout Comms Live. The radio keeps the keys. This process is only a window.

## What is real

Taken from `BlackoutCommsLive` `docs/BLE_Interface_Messages.md`:

| Object | UUID | Direction |
|---|---|---|
| Service | `18aeec00-8c60-411b-b958-78c5049be0f3` | — |
| TX | `18aeec01-8c60-411b-b958-78c5049be0f3` | app → device, write |
| RX | `18aeec02-8c60-411b-b958-78c5049be0f3` | device → app, notify or indicate |

- Scan prefix `BC-`. MTU request 247. PIN is plain text `PIN:<pin>`, not JSON.
- Device accepts with `success\n` or by starting the JSON feed. Frames are UTF-8, one JSON object per `\n`.
- Inbound keys, in ingest order: `self`, `devices`, `neighbors`, `location`, `graph`, `sender`, `message`, `traffic`, `messageStatus`, `conn`.
- Outbound commands: `{"bc":{msg,nodes,priority,expiry}}` and `{"dm":{to,msg,priority,fm,expiry}}`.
- Graph edges are keyed by mesh address with leading zeros stripped, not by device id.
- Direct-neighbor flags age out after 10 minutes. `deleted` removes a message.

`samples/session.jsonl` is a fixture in that shape, not a capture from a radio.

## Run the wall view

```bash
cd overlook
python3 server.py
```

Open `http://127.0.0.1:8733`. The default transport is a simulator that replays the fixture and then walks a few nodes, so the screen is usable with no adapter.

Attach to hardware on the Pi:

```bash
pip install -r requirements.txt
python3 server.py --ble --pin 1234
```

`--tx-newline` appends LF on writes. Current Live builds do not. Leave it off unless your firmware's BLE reader requires it.

## Pi kiosk

64-bit Raspberry Pi OS, Pi 4 (4 GB) or Pi 5. BlueZ up, Wi-Fi off if you are using the onboard radio for the long-lived BLE link. A USB adapter on a short extension is the more reliable week-long link.

`overlook.service` is a starting unit. Put the app in `/opt/overlook`, then point a cage or labwc kiosk at `http://127.0.0.1:8733`. Do not put Chromium in the product path if you can avoid it; for a first kiosk, a single Chromium `--kiosk` window is the least work.

## Not done

No bench test against a communicator. BlueZ permissions, pairing popups, and whether firmware wants a newline on TX still have to be confirmed on hardware. Map tiles are a local projection, not offline OSM. USB serial (115200 8N1, same JSON) is documented by Live and not implemented here.
