<p align="center"><img src="beamer/assets/logo.png" width="120" alt="Beamer logo"></p>

# Beamer

Beam any browser tab or screen to the TVs in your home, even TVs that have no casting support.

Beamer runs on your Windows PC. You pick a TV, share a tab in your browser, and Beamer turns it into a live video
stream that the TV plays. Several TVs can play the same stream at once.

## Supported TVs

| TV | How Beamer reaches it | Status |
|---|---|---|
| **LG webOS** | Opens the TV's built-in web browser on a player page (one-time pairing prompt on the TV) | Tested |
| **Amazon Fire TV** (incl. Toshiba/Insignia Fire TV Edition) | Uses `adb` to open the Silk browser on a player page (needs ADB debugging on) | Tested |
| **Chromecast / Google TV** | Real Cast protocol with Google's default receiver | Implemented, **not yet tested on hardware** |
| **Roku TV / player** | Roku has no web browser | **Not supported yet** (detected, shown greyed out) |
| Samsung / Tizen, Apple TV | - | Not supported |

## Install

Download **`Beamer-Setup.exe`** from the Releases page and run it (it asks for administrator permission once, to
add a firewall rule limited to your home network). Beamer opens in your browser at `http://localhost:8765` and keeps
running as a **system-tray icon**: double-click it to reopen the page, right-click for **Quit Beamer**.

On first use Beamer downloads `ffmpeg` (and `adb`, only if you add a Fire TV) into `%APPDATA%\Beamer\tools`.
Your PC and the TVs must be on the same home network.

### From source

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m beamer
```

## Using it

1. **Choose TVs.** Beamer lists what it finds; use **+ Add a TV by address** for the rest.
   - **LG:** enter the TV's IP; tap **Allow** on the prompt that appears on the TV.
   - **Fire TV:** enable *Settings > My Fire TV > Developer options > ADB debugging*, enter the IP, and tap
     **Always allow** on the TV prompt.
   - **Chromecast / Google TV:** enter the IP if it isn't found automatically.
2. Pick a **quality** (720p up to 4K; 4K needs a fast PC and Wi-Fi).
3. Click **Share tab / screen**, choose a *Chrome tab*, and keep **Share tab audio** ticked. The shared tab goes
   quiet on the PC and plays on the TV.

The TV is a few seconds behind the PC (HLS streaming), so it suits video and music more than games.

## How it works

```
browser tab --MediaRecorder--> Beamer (WebSocket) --ffmpeg--> HLS segments --HTTP--> TV
```

Each TV type has a small driver (`beamer/drivers.py`) that gets the TV to open the stream:
LG via the webOS remote protocol, Fire TV via `adb`, Chromecast via Cast. See `beamer/server.py` for the pipeline.

## Notes and limits

- Settings (TV list, pairing keys) are stored per user in `%APPDATA%\Beamer\config.json`. They never leave your PC.
- Beamer serves the stream unencrypted over your local network on port 8765, so anyone on your Wi-Fi can open it
  while you cast. Don't use it on a network you don't trust.
- Beamer is an independent project. It is not affiliated with LG, Amazon, Google, Roku or any TV maker.
  Ohio State's scarlet and gray are used for the color scheme only.

## Build the installer

```
.venv\Scripts\pip install -r requirements-dev.txt
scripts\build.ps1                                          # build only
scripts\release.ps1 -Version 0.1.3 -Notes "what changed"   # bump, build, tag, publish a GitHub release
```

Needs [Inno Setup 6](https://jrsoftware.org/isinfo.php) for the installer and the GitHub CLI for releases.
See [CLAUDE.md](CLAUDE.md) for the project layout and rules, and [CHANGELOG.md](CHANGELOG.md) for history.

## License

MIT, see [LICENSE](LICENSE). Third-party notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
