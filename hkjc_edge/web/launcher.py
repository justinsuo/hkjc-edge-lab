"""Launch HKJC Edge Lab as a native macOS window (pywebview) or in the browser."""
from __future__ import annotations

import argparse
import socket
import threading
import time

from .server import create_app
from .service import ServiceLayer


def _free_port(preferred: int = 8099) -> int:
    for p in (preferred, 8100, 8123, 8200, 0):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", p))
            port = s.getsockname()[1]
            s.close()
            return port
        except OSError:
            s.close()
    return preferred


def _wait_up(port: int, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except OSError:
            time.sleep(0.1)
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hkjc-app", description="HKJC Edge Lab desktop app")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--browser", action="store_true", help="open in browser instead of native window")
    ap.add_argument("--no-window", action="store_true", help="serve only; don't open a UI")
    ap.add_argument("--warm", action="store_true", help="warm caches on startup (dataset + validation)")
    args = ap.parse_args(argv)

    port = _free_port(args.port)
    svc = ServiceLayer()
    app = create_app(svc)

    def _serve():
        app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)

    threading.Thread(target=_serve, daemon=True).start()
    if not _wait_up(port):
        print("server failed to start")
        return 1
    url = f"http://127.0.0.1:{port}/"
    print(f"HKJC Edge Lab serving at {url}")

    # Always warm caches in the background so the UI is instant and the verdict populates:
    # build the dataset, the walk-forward OOS frame, and run validation (NO-GO) once.
    def _warm():
        try:
            svc.dataset(); svc.oos(); svc.run_validation()
            print("warm: dataset + OOS + validation ready")
        except Exception as e:  # noqa: BLE001
            print(f"warm failed: {e}")
    threading.Thread(target=_warm, daemon=True).start()

    if args.no_window:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    if not args.browser:
        try:
            import webview  # pywebview
            webview.create_window("HKJC Edge Lab", url, width=1340, height=900,
                                  min_size=(1040, 680), background_color="#0B0D10")
            webview.start()
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"native window unavailable ({e}); opening browser")

    import webbrowser
    webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
