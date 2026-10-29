"""Beamer web app: browser shares a tab/screen -> ffmpeg makes a live HLS stream -> each chosen TV plays it."""
import asyncio, pathlib, shutil, socket, subprocess, sys, tempfile
from aiohttp import web, WSMsgType

from . import config, drivers

PORT = 8765
ASSETS = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent.parent)) / "beamer" / "assets"
if not ASSETS.exists():
    ASSETS = pathlib.Path(__file__).parent / "assets"
HLS = pathlib.Path(tempfile.gettempdir()) / "beamer_hls"
state = {"tvs": [], "ffmpeg": None}

# height, fps, video bitrate
QUALITY = {"720": (720, 30, "3M"), "1080": (1080, 30, "6M"), "1080-60": (1080, 60, "9M"), "2160": (2160, 30, "20M")}


def lan_ip(host):
    """This PC's address on the route to the TV (what the TV must use to reach us)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((host, 9))
    ip = s.getsockname()[0]
    s.close()
    return ip


async def ws_handler(req):
    height, fps, rate = QUALITY.get(req.query.get("q", "1080"), QUALITY["1080"])
    ws = web.WebSocketResponse(max_msg_size=0)
    await ws.prepare(req)
    try:
        ffmpeg = await asyncio.get_running_loop().run_in_executor(None, config.ensure_tool, "ffmpeg")
    except Exception as e:
        await ws.send_str(f"FAILED: could not find or install ffmpeg: {e}")
        return ws
    shutil.rmtree(HLS, ignore_errors=True)
    HLS.mkdir(parents=True)
    ff = subprocess.Popen(
        [ffmpeg, "-loglevel", "error", "-i", "pipe:0",
         "-vf", f"scale=-2:min(ih\\,{height})", "-r", str(fps),
         "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-g", str(fps),
         "-b:v", rate, "-maxrate", rate, "-bufsize", rate,
         "-c:a", "aac", "-b:a", "128k", "-f", "hls", "-hls_time", "1", "-hls_list_size", "6",
         "-hls_flags", "delete_segments+independent_segments", str(HLS / "live.m3u8")],
        stdin=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    state["ffmpeg"] = ff
    started = False
    async for m in ws:
        if m.type == WSMsgType.BINARY:
            try:
                ff.stdin.write(m.data)
                ff.stdin.flush()
            except Exception:
                break
            if not started and (HLS / "live.m3u8").exists():
                started = True
                asyncio.create_task(launch_all(ws, req.query.get("dev", "")))
    try:
        ff.stdin.close()
    except Exception:
        pass
    ff.terminate()
    return ws


async def launch_one(ws, tv):
    base = f"http://{lan_ip(tv['host'])}:{PORT}"
    try:
        await drivers.open_on_device(tv, base + "/hls/live.m3u8", base + "/player")
        await ws.send_str(f"OK: {tv['name']}")
    except Exception as e:
        await ws.send_str(f"FAILED: {tv['name']}: {e}")
        print("launch failed:", tv["name"], repr(e), flush=True)


async def launch_all(ws, ids):
    wanted = ids.split(",")
    tvs = [t for t in state["tvs"] if t["id"] in wanted]
    if not tvs:
        await ws.send_str("FAILED: no TV selected")
        return
    await asyncio.gather(*(launch_one(ws, t) for t in tvs))   # one failing TV doesn't stop the others


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
        web.get("/", asset("index.html")), web.get("/player", asset("player.html")),
        web.get("/logo.png", asset("logo.png")), web.get("/hls.min.js", asset("hls.min.js")),
        web.get("/ws", ws_handler), web.get("/api/tvs", tvs_handler), web.post("/api/tvs/add", add_handler),
        web.get("/hls/{p:.*}", hls_file),
    ])
    return app
