"""Beamer launcher: runs the web server in the background and lives in the system tray (no console window)."""
import asyncio, os, socket, sys, threading, webbrowser

from aiohttp import web

from . import config
from .server import ASSETS, HLS, PORT, make_app, state


def _redirect_output():
    """A windowed app has no console; send prints and tracebacks to a log file instead."""
    if sys.stdout is None or getattr(sys, "frozen", False):
        log = open(config.APP_DIR / "beamer.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = log


def _already_running():
    try:
        socket.create_connection(("127.0.0.1", PORT), 0.5).close()
        return True
    except OSError:
        return False


def main(open_browser=True):
    _redirect_output()
    url = f"http://localhost:{PORT}"
    if _already_running():            # a second launch just opens the existing Beamer
        webbrowser.open(url)
        return
    HLS.mkdir(exist_ok=True)

    loop = asyncio.new_event_loop()
    box = {}
    ready = threading.Event()

    def serve():
        asyncio.set_event_loop(loop)

        async def run():
            box["stop"] = asyncio.Event()
            runner = web.AppRunner(make_app())
            await runner.setup()
            await web.TCPSite(runner, "0.0.0.0", PORT).start()
            ready.set()
            await box["stop"].wait()
            await runner.cleanup()

        try:
            loop.run_until_complete(run())
        except Exception as e:        # e.g. port taken
            print("server failed:", repr(e), flush=True)
            ready.set()

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    ready.wait(15)
    if open_browser:
        webbrowser.open(url)

    def stop_server():
        ff = state.get("ffmpeg")
        if ff and ff.poll() is None:
            ff.terminate()
        if "stop" in box:
            loop.call_soon_threadsafe(box["stop"].set)

    try:
        if os.environ.get("BEAMER_NO_TRAY"):      # headless (tests)
            raise ImportError
        import pystray
        from PIL import Image
    except ImportError:               # dev install without the tray extras: just keep serving
        print(f"Beamer is running at {url} (Ctrl+C to quit)")
        try:
            server.join()
        except KeyboardInterrupt:
            stop_server()
        return

    def open_ui(icon=None, item=None):
        webbrowser.open(url)

    def quit_app(icon, item):
        stop_server()
        icon.stop()

    icon = pystray.Icon(
        "Beamer", Image.open(ASSETS / "logo.png"), "Beamer",
        menu=pystray.Menu(pystray.MenuItem("Open Beamer", open_ui, default=True),
                          pystray.MenuItem("Quit Beamer", quit_app)))
    icon.run()                         # blocks until Quit
