"""Beamer web app: browser shares a tab/screen -> ffmpeg -> HLS (and optionally low-latency MPEG-TS) -> TVs."""
import asyncio, datetime, os, pathlib, shutil, socket, subprocess, sys, tempfile, threading
from aiohttp import web, WSMsgType

from . import config, drivers, native as nativecap
from .live import LiveHub

PORT = int(os.environ.get("BEAMER_PORT", 8765))   # override for tests
ASSETS = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent.parent)) / "beamer" / "assets"
if not ASSETS.exists():
    ASSETS = pathlib.Path(__file__).parent / "assets"
HLS = pathlib.Path(tempfile.gettempdir()) / "beamer_hls"
state = {"tvs": [], "ffmpeg": None}
hub = LiveHub()

# height, fps, video bitrate
QUALITY = {"720": (720, 30, "3M"), "1080": (1080, 30, "6M"), "1080-60": (1080, 60, "9M"), "2160": (2160, 30, "20M")}
# TV kinds that play the low-latency MPEG-TS WebSocket stream; everything else (Chromecast) stays on HLS
LL_KINDS = {"lg", "fire"}


def log(*a):
    print(datetime.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def lan_ip(host):
    """This PC's address on the route to the TV (what the TV must use to reach us)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((host, 9))
    ip = s.getsockname()[0]
    s.close()
    return ip


def ffmpeg_command(ffmpeg, height, fps, rate, low_latency, native=None):
    """One encode, two outputs when low latency is on: HLS files (Chromecast / fallback) + MPEG-TS on stdout.
    native=None reads browser WebM from stdin; native={'qsv': bool} captures the screen directly."""
    cmd = [ffmpeg, "-loglevel", "warning"]
    if native is not None:
        vf, enc = nativecap.video_args(fps, rate, height, native["qsv"])
        cmd += nativecap.source_args(fps, native["qsv"]) + ["-vf", vf, "-r", str(fps)] + enc + ["-an"]
    else:
        if low_latency:
            cmd += ["-flags", "low_delay", "-probesize", "1000000", "-analyzeduration", "1000000"]
        cmd += ["-i", "pipe:0",
                "-vf", f"scale=-2:min(ih\\,{height})", "-r", str(fps),
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-pix_fmt", "yuv420p",
                "-bf", "0", "-g", str(fps), "-keyint_min", str(fps), "-sc_threshold", "0",
                "-b:v", rate, "-maxrate", rate, "-bufsize", rate,
                "-c:a", "aac", "-b:a", "128k"]
    hls = "hls_time=1:hls_list_size=6:hls_flags=delete_segments+independent_segments"
    if not low_latency:
        return cmd + ["-f", "hls", "-hls_time", "1", "-hls_list_size", "6",
                      "-hls_flags", "delete_segments+independent_segments", "live.m3u8"]
    maps = ["-map", "0:v:0"] + ([] if native is not None else ["-map", "0:a:0?"])
    return cmd + maps + ["-flush_packets", "1", "-muxdelay", "0", "-f", "tee",
                  f"[f=hls:{hls}]live.m3u8|[f=mpegts:max_delay=0:flush_packets=1:mpegts_flags=+resend_headers]pipe\\:1"]


def _pump_stdout(ff, loop):
    """Thread: read MPEG-TS from ffmpeg's stdout and hand it to the hub on the event loop."""
    try:
        while True:
            data = ff.stdout.read1(65536)
            if not data:
                break
            loop.call_soon_threadsafe(hub.feed, data)
    except Exception as e:
        log("live reader stopped:", repr(e))


async def _run_session(req, ws, native=None):
    """Start ffmpeg for one cast session; browser mode feeds it WebM from `ws`, native mode captures the screen itself."""
    height, fps, rate = QUALITY.get(req.query.get("q", "1080"), QUALITY["1080"])
    low_latency = req.query.get("ll") == "1"
    loop = asyncio.get_running_loop()
    try:
        ffmpeg = await loop.run_in_executor(None, config.ensure_tool, "ffmpeg")
    except Exception as e:
        await ws.send_str(f"FAILED: could not find or install ffmpeg: {e}")
        return
    if native is not None:
        caps = await loop.run_in_executor(None, nativecap.capabilities, ffmpeg)
        if not caps["ddagrab"]:
            await ws.send_str("FAILED: this ffmpeg can't capture the screen (no ddagrab); use the browser tab method")
            return
        native = {"qsv": caps["qsv"]}
    shutil.rmtree(HLS, ignore_errors=True)
    HLS.mkdir(parents=True)
    hub.reset()
    ff_log = open(config.APP_DIR / "ffmpeg.log", "w")
    ff = subprocess.Popen(
        ffmpeg_command(ffmpeg, height, fps, rate, low_latency, native), cwd=HLS,
        stdin=subprocess.PIPE if native is None else subprocess.DEVNULL,
        stdout=subprocess.PIPE if low_latency else subprocess.DEVNULL,
        stderr=ff_log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    state["ffmpeg"] = ff
    how = "browser tab" if native is None else f"native screen ({'Quick Sync' if native['qsv'] else 'software x264'})"
    log(f"session start: {how}, {height}p{fps} {rate}, {'low-latency (MPEG-TS over WebSocket + HLS)' if low_latency else 'HLS'}")
    if low_latency:
        threading.Thread(target=_pump_stdout, args=(ff, loop), daemon=True).start()
    launched = False

    async def maybe_launch():
        nonlocal launched
        if not launched and (HLS / "live.m3u8").exists():
            launched = True
            asyncio.create_task(launch_all(ws, req.query.get("dev", ""), low_latency))

    if native is not None:
        async def wait_then_launch():
            for _ in range(100):                  # up to ~20 s for ffmpeg to write the first segment
                if ff.poll() is not None:
                    await ws.send_str("FAILED: screen capture stopped (see ffmpeg.log)")
                    return
                if (HLS / "live.m3u8").exists():
                    await maybe_launch()
                    return
                await asyncio.sleep(0.2)
            await ws.send_str("FAILED: screen capture produced no video in 20 s (see ffmpeg.log)")
        asyncio.create_task(wait_then_launch())
        await ws.send_str(f"INFO: capturing the screen with {'Quick Sync' if native['qsv'] else 'software x264 (no Quick Sync)'}")
    async for m in ws:
        if native is None and m.type == WSMsgType.BINARY:
            try:
                ff.stdin.write(m.data)
                ff.stdin.flush()
            except Exception:
                break
            await maybe_launch()
        elif native is not None:
            pass          # nothing expected from the page; closing the socket ends the session
    # (native sessions poll for the playlist below)
    return ff, ff_log


async def ws_handler(req):
    """The control page sends MediaRecorder (WebM) chunks here."""
    ws = web.WebSocketResponse(max_msg_size=0)
    await ws.prepare(req)
    res = await _run_session(req, ws)
    if res:
        await _end_session(*res)
    return ws


async def native_handler(req):
    """Native screen capture: no chunks arrive; the socket just marks the session's lifetime."""
    ws = web.WebSocketResponse(max_msg_size=0)
    await ws.prepare(req)
    res = await _run_session(req, ws, native=True)
    if res:
        await _end_session(*res)
    return ws


async def _end_session(ff, ff_log):
    try:
        if ff.stdin:
            ff.stdin.close()
    except Exception:
        pass
    ff.terminate()
    ff_log.close()
    log("session end")


async def live_handler(req):
    """TV player pages connect here and receive the MPEG-TS stream."""
    ws = web.WebSocketResponse(max_msg_size=0)
    await ws.prepare(req)
    client = hub.add()
    who = req.remote
    log(f"live client connected: {who} (clients: {len(hub.clients)})")

    async def sender():
        while True:
            await ws.send_bytes(await client.get())

    task = asyncio.create_task(sender())
    try:
        async for _ in ws:        # nothing is expected from the TV; this just waits for it to close
            pass
    finally:
        task.cancel()
        hub.remove(client)
        log(f"live client left: {who} (resyncs: {client.resyncs})")
    return ws


async def launch_one(ws, tv, low_latency):
    base = f"http://{lan_ip(tv['host'])}:{PORT}"
    mode = "ll" if low_latency and tv["kind"] in LL_KINDS else "hls"
    player = f"{base}/player?mode={mode}"
    try:
        await drivers.open_on_device(tv, base + "/hls/live.m3u8", player)
        await ws.send_str(f"OK: {tv['name']} ({'low latency' if mode == 'll' else 'HLS'})")
    except Exception as e:
        await ws.send_str(f"FAILED: {tv['name']}: {e}")
        log("launch failed:", tv["name"], repr(e))


async def launch_all(ws, ids, low_latency=False):
    wanted = ids.split(",")
    tvs = [t for t in state["tvs"] if t["id"] in wanted]
    if not tvs:
        await ws.send_str("FAILED: no TV selected")
        return
    await asyncio.gather(*(launch_one(ws, t, low_latency) for t in tvs))   # one failing TV doesn't stop the others


async def tvs_handler(req):
    if req.query.get("refresh") or not state["tvs"]:
        state["tvs"] = await drivers.discover()
    return web.json_response(state["tvs"])


async def add_handler(req):
    body = await req.json()
    kind, host = body.get("kind"), (body.get("host") or "").strip()
    pair = {"lg": drivers.pair_lg, "fire": drivers.pair_fire, "cast": drivers.pair_cast}.get(kind)
    if not pair or not host:
        return web.json_response({"ok": False, "error": "choose a TV type and enter its IP address"})
    try:
        tv = await pair(host)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e) or repr(e)})
    config.add_tv(tv)
    return web.json_response({"ok": True, "tv": tv})


async def settings_handler(req):
    cfg = config.load()
    if req.method == "POST":
        body = await req.json()
        if "low_latency" in body:
            cfg["low_latency"] = bool(body["low_latency"])
        if body.get("capture") in ("browser", "native"):
            cfg["capture"] = body["capture"]
        config.save(cfg)
    return web.json_response({"low_latency": bool(cfg.get("low_latency", False)), "capture": cfg.get("capture", "browser")})


async def native_caps_handler(req):
    loop = asyncio.get_running_loop()
    try:
        ffmpeg = await loop.run_in_executor(None, config.ensure_tool, "ffmpeg")
        return web.json_response(await loop.run_in_executor(None, nativecap.capabilities, ffmpeg))
    except Exception as e:
        return web.json_response({"ddagrab": False, "qsv": False, "error": str(e)})


async def log_handler(req):
    """TV player pages report which mode they use, and any errors, so they end up in beamer.log."""
    body = await req.json()
    log(f"[player {req.remote}] {str(body.get('msg', ''))[:500]}")
    return web.Response(text="ok")


async def hls_file(req):
    p = HLS / req.match_info["p"]
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"})


def asset(name):
    return lambda r: web.FileResponse(ASSETS / name)


def make_app():
    app = web.Application()
    app.add_routes([
        web.get("/", asset("index.html")), web.get("/player", asset("player.html")), web.get("/clock", asset("clock.html")),
        web.get("/logo.png", asset("logo.png")), web.get("/hls.min.js", asset("hls.min.js")),
        web.get("/mpegts.js", asset("mpegts.js")),
        web.get("/ws", ws_handler), web.get("/native", native_handler), web.get("/api/native/caps", native_caps_handler), web.get("/live", live_handler),
        web.get("/api/tvs", tvs_handler), web.post("/api/tvs/add", add_handler),
        web.get("/api/settings", settings_handler), web.post("/api/settings", settings_handler),
        web.post("/api/log", log_handler),
        web.get("/hls/{p:.*}", hls_file),
    ])
    return app
