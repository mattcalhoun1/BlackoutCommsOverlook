# Overlook

Wall or desktop display for a [Blackout Comms](https://chatters.io) mesh. It connects to one radio over Bluetooth, shows the cluster on a map, and can stay up without grid service once map tiles are cached. The radio keeps the keys. Overlook is only a window.

<img width="1920" height="1080" alt="overlook_intro_thumbnail" src="https://github.com/user-attachments/assets/d0ae69af-6f39-4698-a473-f477c6480a5b" />

Overlook requires Blackout Comms firmware and a Blackout Comms device. It speaks the same GATT JSON feed as [Blackout Comms Live](https://github.com/mattcalhoun1/BlackoutCommsLive). It is not a standalone messenger and it requires a Blackout Comms device. It's basically a companion/additional view to a connected Blackout Comms device.

If you're using windows: (Download Overlook for Windows)[https://www.offgridcomms.club/overlook/Overlook_Win.zip]

Setup notes: https://chatters.io/overlook

## Linux

64-bit Raspberry Pi OS or another Linux machine with BlueZ. A Pi Zero 2 W is enough for an HDMI display. The Pi user must be in the `bluetooth` group.

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

Open http://127.0.0.1:8733. Enter the device name, the 6-character id, and the PIN. The app stores them in `data/session.json` and reconnects on the next start. Tiles are cached under `data/tiles/`.

To leave it running on a Pi, copy `overlook.service` to `/etc/systemd/system/`, point `WorkingDirectory` and `ExecStart` at this checkout, then:

```bash
sudo systemctl enable --now overlook
```

## Windows binary

The pre-built zip is the normal way to install on Windows. Unzip it, keep `Overlook.exe` and `_internal` together, and run the exe. WebView2 and a Bluetooth adapter are required. Saved radios and tiles go to `%LOCALAPPDATA%\Overlook`.

To build it yourself, use a Windows machine and Python 3.13. A Linux desktop cannot produce this package.

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

You'll need everything it generates in the `dist\Overlook` folder. `overlook.ico` must be a real icon file, not a renamed PNG.
