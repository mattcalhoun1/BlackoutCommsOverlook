# Overlook

Overlook is a free desktop companion for a [Blackout Comms](https://chatters.io) mesh. It connects to one of your radios over Bluetooth and shows the private cluster: device locations, mesh links, pings, traffic, and messages. It runs as a normal Windows or Linux app, and it also works well left up on a monitor. After the map tiles are cached, the view keeps working with no Wi-Fi and no other grid service.

<img width="1920" height="1080" alt="overlook_intro_thumbnail" src="https://github.com/user-attachments/assets/d0ae69af-6f39-4698-a473-f477c6480a5b" />

It is an add-on, not a radio. Overlook requires Blackout Comms firmware and at least one Blackout Comms device. The radio keeps the keys and does the mesh routing. This program is only a local view of that cluster.

- Product page: https://chatters.io/overlook
- Blackout Comms: https://chatters.io
- Windows build: https://www.offgridcomms.club/overlook/Overlook_Win.zip
- Source: https://github.com/mattcalhoun1/BlackoutCommsOverlook

## What it is for

Use it when you want a larger view of the cluster than the phone app. On a desk it is a companion window. In a cabin, shop, or staging area it can stay on a monitor. A Raspberry Pi 5 is enough for that always-on case. Windows is supported with the pre-built zip.

Overlook speaks the same Bluetooth GATT JSON feed as the [Blackout Comms Live](https://github.com/mattcalhoun1/BlackoutCommsLive) app. It scans for a `BC-` device, sends the PIN, and then follows `self`, `devices`, `neighbors`, `location`, `graph`, `message`, `traffic`, and `conn` frames. It cannot join a mesh by itself, and it does not talk to other non-Blackout Comms mesh systems.

## What the screen shows

- Connected radio: name, battery, stealth, relay state, temperature, position, heading, and speed
- Other devices on a pan and zoom map, with the same icon set as Blackout Comms Live
- Optional mesh lines, MGRS grid, critical-only filter, and a time filter
- Direct and indirect pings, with distance and bearing when both positions are known
- Broadcast and direct messages, sent back out through the connected radio
- A small packet graph for traffic in, traffic out, and unknown packets
- Saved radios, so the next start reconnects and restores the last map

## Windows

Unzip and run. WebView2 and a Bluetooth adapter are required. Keep `Overlook.exe` and the `_internal` folder together.

https://www.offgridcomms.club/overlook/Overlook_Win.zip

Saved radios and tiles go to `%LOCALAPPDATA%\Overlook`.

## Linux

64-bit Raspberry Pi OS or another Linux machine with BlueZ. The user running Overlook must be in the `bluetooth` group. A Pi 5 can drive the display over HDMI by itself, using kiosk mode.

```bash
sudo apt install python3 python3-pip python3-venv bluetooth bluez
sudo usermod -aG bluetooth "$USER"
git clone https://github.com/mattcalhoun1/BlackoutCommsOverlook.git
cd BlackoutCommsOverlook
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
```

Open http://127.0.0.1:8733. Enter a name, the 6-character device id, and the PIN. The app writes `data/session.json` and reconnects on the next start. Tiles cache under `data/tiles/`.

For a Pi that should come back after power loss, copy `overlook.service` to `/etc/systemd/system/`, point `WorkingDirectory` and `ExecStart` at this checkout, then:

```bash
sudo systemctl enable --now overlook
```

## Build the Windows package

Build on Windows with Python 3.13. A Linux machine cannot produce this binary, because the Bluetooth library is the Windows build of bleak.

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pywebview pyinstaller
pyinstaller --noconfirm --windowed --name Overlook --icon overlook.ico ^
  --add-data "static;static" ^
  --add-data "overlook.ico;." ^
  --collect-data certifi ^
  --hidden-import certifi ^
  --hidden-import bleak ^
  --hidden-import winrt ^
  desktop.py
```

You'll need the whole `dist\Overlook` folder.

## Common questions

Overlook does not replace a Blackout Comms device. It attaches to one.

It does not need an account, a server, or an internet connection after the map tiles for an area have been saved.

The first view of a new area is slow because each tile is downloaded and cached. The same view is read from disk after that.

Disconnect clears the live map and messages. The saved radio name, id, and PIN stay. Tiles stay either way.