"""Per-user settings and helper binaries (ffmpeg, adb), stored under %APPDATA%/Beamer (or ~/.beamer)."""
import json, os, pathlib, shutil, urllib.request, zipfile

APP_DIR = pathlib.Path(os.environ.get("APPDATA") or pathlib.Path.home() / ".beamer") / "Beamer"
APP_DIR.mkdir(parents=True, exist_ok=True)
CONFIG = APP_DIR / "config.json"
TOOLS = APP_DIR / "tools"

ADB_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def load():
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {"tvs": []}


def save(cfg):
    CONFIG.write_text(json.dumps(cfg, indent=2))


def add_tv(tv):
    cfg = load()
    cfg["tvs"] = [t for t in cfg.get("tvs", []) if t["id"] != tv["id"]] + [tv]
    save(cfg)


def remove_tv(tv_id):
    cfg = load()
    cfg["tvs"] = [t for t in cfg.get("tvs", []) if t["id"] != tv_id]
    save(cfg)


def _download_zip(url, dest):
    dest.mkdir(parents=True, exist_ok=True)
    zpath = dest / "download.zip"
    urllib.request.urlretrieve(url, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(dest)
    zpath.unlink()


def _find(name, root):
    hits = list(root.rglob(name))
    return str(hits[0]) if hits else None


def ensure_tool(name):
    """Return a path to ffmpeg.exe / adb.exe: PATH first, then our tools dir, else download it once."""
    exe = f"{name}.exe" if os.name == "nt" else name
    found = shutil.which(name)
    if not found and (TOOLS / name).exists():
        found = _find(exe, TOOLS / name)
    if found:
        return found
    _download_zip(ADB_URL if name == "adb" else FFMPEG_URL, TOOLS / name)
    found = _find(exe, TOOLS / name)
    if not found:
        raise RuntimeError(f"could not install {name}")
    return found
