import threading
import time
import urllib.request
import webview
import server

def serve():
    server.main()

if __name__ == "__main__":
    threading.Thread(target=serve, daemon=True).start()
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:8733", timeout=0.2)
            break
        except Exception:
            time.sleep(0.1)
    webview.create_window("Overlook", "http://127.0.0.1:8733", width=1280, height=800)
    webview.start()