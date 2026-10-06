import threading
import time
import urllib.request
import webview
import server
import ctypes
from ctypes import wintypes

def serve():
    server.main()

def paint_icon():
    time.sleep(0.6)
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "Overlook")
    icon = user32.LoadImageW(None, "overlook.ico", 1, 0, 0, 0x00000010)
    if hwnd and icon:
        user32.SendMessageW(hwnd, 0x0080, 1, icon)
        user32.SendMessageW(hwnd, 0x0080, 0, icon)

threading.Thread(target=paint_icon, daemon=True).start()
webview.start()
if __name__ == "__main__":
    threading.Thread(target=serve, daemon=True).start()
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:8733", timeout=0.2)
            break
        except Exception:
            time.sleep(0.1)
    webview.create_window("Overlook", "http://127.0.0.1:8733", width=1280, height=800)
    threading.Thread(target=paint_icon, daemon=True).start()
    webview.start()