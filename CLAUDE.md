# Beamer: project guide

Beamer beams a browser tab or screen to TVs on the home network. Windows app, Python, runs in the system tray.
Repo: https://github.com/game382/beamer-cast (public, MIT).

## Run and build
```
python -m venv .venv && .venv\Scripts\pip install -r requirements-dev.txt   # once
.venv\Scripts\python -m beamer            # run from source (tray icon + browser tab)
.venv\Scripts\python -m beamer --no-browser
scripts\release.ps1 -Version 0.1.3 -Notes "what changed"   # bump, build, commit, tag, publish
scripts\build.ps1                         # build only: dist\Beamer + dist\Beamer-Setup.exe
```
Needs Inno Setup 6 (installer) and the GitHub CLI `gh` (releases). Logs of the packaged app: `%APPDATA%\Beamer\beamer.log`.

## Layout
- `beamer/app.py`: launcher. Server runs on a background thread; the main thread is the tray icon (pystray).
- `beamer/server.py`: aiohttp web app. `/ws` receives MediaRecorder chunks -> ffmpeg -> HLS in a temp dir;
  `/api/tvs` lists TVs; `/api/tvs/add` pairs one; `/player` is the page the TV opens.
- `beamer/live.py`: LiveHub fans MPEG-TS from ffmpeg stdout to WebSocket `/live` clients (low-latency beta; keyframe-aligned joins, slow clients dropped at 2 MB).
- `beamer/drivers.py`: one driver per TV kind (`lg`, `fire`, `cast`, `roku`). Add a TV type by adding
  `open_<kind>` (+ `pair_<kind>`) and registering it in `DRIVERS` and in `server.add_handler`.
- `beamer/config.py`: per-user settings in `%APPDATA%\Beamer\config.json`; downloads ffmpeg/adb on first use.
- `beamer/assets/`: UI (`index.html`), TV player page (`player.html`), logo, hls.js.
- `installer/beamer.iss`: Inno Setup script; installs per machine (admin) and adds a LocalSubnet-only firewall rule.

## Status (keep this current)
| TV | State |
|---|---|
| LG webOS | tested |
| Fire TV (adb + Silk) | tested; needs ADB debugging on; stale `offline` links are auto-reset |
| Chromecast / Google TV | implemented, untested on hardware |
| Roku | unsupported (no browser; my guessed ECP play command returned 404; AirPlay pairing was refused) |
| Low latency (beta, LG + Fire TV) | built in 0.1.3; Fire TV ran it fine; delay not yet measured, LG untested |
| Several TVs at once | implemented, untested |
| Chrome Cast-menu receiver | not built: Cast senders demand Google device-auth and drop a self-signed receiver |

## Rules for changes
- Never commit per-user data: `config.json`, pairing keys, IP addresses of a real home. `.gitignore` covers the usual names.
- Don't claim a TV type works until it has been cast to for real. Say "untested" in README/release notes.
- Do not forge Google Cast certificates or reuse another app's credentials.
- Windows quirks: the app is windowed (`console=False`), so never rely on `print` reaching a console; subprocesses use
  `CREATE_NO_WINDOW`; Windows often marks home Wi-Fi "Public", hence the installer's firewall rule.
- Keep the UI in Ohio State colors: scarlet `#BB0000`, gray `#666666`, silver `#A7B1B7`, dark background.
