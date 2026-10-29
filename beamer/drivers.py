"""One driver per TV type. Each is given the HLS stream URL and the player page URL and makes the TV show it.

TV records are plain dicts: {id, kind, name, host, model, ...}. kind: lg | fire | cast | roku.
  lg    LG webOS: opens the TV's web browser on the player page   (needs one-time pairing)
  fire  Fire TV: adb launches Silk on the player page            (needs ADB debugging on, one-time allow)
  cast  Chromecast / Google TV: real Cast protocol, default receiver plays the HLS stream
  roku  discovered but NOT supported yet (no browser; see README)
"""
import asyncio, socket, time, urllib.request
import xml.etree.ElementTree as ET

from . import config

SUPPORTED = {"lg", "fire", "cast"}


# ---------- discovery ----------
def _ssdp_roku(timeout=4):
    msg = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\n'
           'MX: 2\r\nST: roku:ecp\r\n\r\n').encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(1)
    for _ in range(2):
        s.sendto(msg, ("239.255.255.250", 1900))
    ips, end = set(), time.time() + timeout
    while time.time() < end:
        try:
            _, addr = s.recvfrom(4096)
            ips.add(addr[0])
        except socket.timeout:
            pass
    s.close()
    return ips


def _roku_info(ip):
    with urllib.request.urlopen(f"http://{ip}:8060/query/device-info", timeout=4) as r:
        root = ET.fromstring(r.read())
    return {c.tag: (c.text or "") for c in root}


def _local_ips():
    ips = {"127.0.0.1"}
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return ips


def discover_sync():
    tvs = [dict(t) for t in config.load().get("tvs", [])]       # TVs the user added by address
    known = {t["host"] for t in tvs} | _local_ips()      # never list this PC (e.g. another cast app running here)
    for ip in sorted(_ssdp_roku() - known):
        try:
            d = _roku_info(ip)
            tvs.append({"id": f"roku:{ip}", "kind": "roku", "host": ip,
                        "name": d.get("user-device-name") or d.get("friendly-device-name") or "Roku",
                        "model": d.get("model-name", "")})
        except Exception:
            pass
    try:
        import pychromecast
        casts, browser = pychromecast.get_chromecasts(timeout=6)
        browser.stop_discovery()
        for c in casts:
            ci = c.cast_info
            if ci.host not in known:
                tvs.append({"id": f"cast:{ci.host}", "kind": "cast", "name": ci.friendly_name,
                            "host": ci.host, "model": ci.model_name or ""})
    except Exception as e:
        print("Cast discovery failed:", repr(e), flush=True)
    for t in tvs:
        t["supported"] = t["kind"] in SUPPORTED
    return tvs


async def discover():
    return await asyncio.get_running_loop().run_in_executor(None, discover_sync)


# ---------- LG webOS ----------
async def open_lg(tv, url, player_url):
    from aiowebostv import WebOsClient
    client = WebOsClient(tv["host"], client_key=tv.get("key"))
    await client.connect()
    try:
        await client.launch_app_with_params("com.webos.app.browser", {"target": player_url})
    finally:
        await client.disconnect()


async def pair_lg(host, timeout=90):
    """Connect and wait for the user to accept the prompt on the TV. Returns the TV record to save."""
    from aiowebostv import WebOsClient
    client = WebOsClient(host)
    await asyncio.wait_for(client.connect(), timeout)
    key = client.client_key
    await client.disconnect()
    return {"id": f"lg:{host}", "kind": "lg", "host": host, "name": f"LG TV ({host})", "model": "webOS", "key": key}


# ---------- Fire TV (adb) ----------
async def _adb(*args):
    exe = await asyncio.get_running_loop().run_in_executor(None, config.ensure_tool, "adb")
    p = await asyncio.create_subprocess_exec(exe, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await asyncio.wait_for(p.communicate(), 25)
    return out.decode(errors="ignore").strip()


async def pair_fire(host):
    target = f"{host}:5555"
    out = await _adb("connect", target)
    state = await _adb("-s", target, "get-state")
    if "device" not in state:
        hint = ("Accept the 'Allow USB debugging?' prompt on the TV (tick Always allow), then try again."
                if "authenticate" in out or "unauthorized" in state else
                "Turn on ADB debugging in the TV's Developer options (Settings > My Fire TV), then try again.")
        raise RuntimeError(f"{out} {hint}")
    model = await _adb("-s", target, "shell", "getprop", "ro.product.model")
    return {"id": f"fire:{host}", "kind": "fire", "host": host, "name": f"Fire TV ({host})", "model": model}


async def open_fire(tv, url, player_url):
    target = f"{tv['host']}:5555"
    out = await _adb("connect", target)
    state = await _adb("-s", target, "get-state")
    if "device" not in state:
        raise RuntimeError(f"ADB not connected/authorized ({out} / {state}). Is the TV on, with ADB debugging enabled?")
    await _adb("-s", target, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", player_url, "com.amazon.cloud9")
    # Silk won't autoplay with sound until a real key event arrives; OK (DPAD_CENTER) also triggers fullscreen.
    for delay in (6, 8):
        await asyncio.sleep(delay)
        await _adb("-s", target, "shell", "input", "keyevent", "23")


# ---------- Chromecast / Google TV ----------
def _cast_play(tv, url):
    import pychromecast
    cast = pychromecast.get_chromecast_from_host((tv["host"], 8009, None, None, None), timeout=15)
    cast.wait(timeout=15)
    mc = cast.media_controller
    mc.play_media(url, "application/x-mpegURL", stream_type="LIVE", title="Beamer")
    mc.block_until_active(timeout=20)


async def open_cast(tv, url, player_url):
    await asyncio.get_running_loop().run_in_executor(None, _cast_play, tv, url)


async def pair_cast(host):
    def probe():
        import pychromecast
        cc = pychromecast.get_chromecast_from_host((host, 8009, None, None, None), timeout=10)
        cc.wait(timeout=10)
        rec = {"id": f"cast:{host}", "kind": "cast", "host": host, "name": cc.name or host,
               "model": cc.cast_info.model_name or ""}
        cc.disconnect()
        return rec
    return await asyncio.get_running_loop().run_in_executor(None, probe)


async def open_roku(tv, url, player_url):
    raise RuntimeError("Roku TVs are not supported yet (they have no web browser to play the stream).")


DRIVERS = {"lg": open_lg, "fire": open_fire, "cast": open_cast, "roku": open_roku}


async def open_on_device(tv, stream_url, player_url):
    await DRIVERS[tv["kind"]](tv, stream_url, player_url)
