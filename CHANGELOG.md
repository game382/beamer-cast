# Changelog

## 0.1.5
- Browser screen capture option: avoids Chrome tab-sharing bar on fullscreen content

## 0.1.4
- New: Native screen capture (beta). Pick it under Capture method to cast your whole screen using Intel Quick Sync (falls back to software encoding on PCs without it). Optional PC sound sent to the TV, with an option to mute the PC while casting (it unmutes when you stop, and after a crash on the next start).
- Low latency player: no longer falls back to HLS by mistake after a brief stall.
- Tested on a Fire TV only; LG, Chromecast and several TVs at once are untested.

## 0.1.3
- Low latency (beta): optional MPEG-TS over WebSocket to LG and Fire TV, played with mpegts.js; auto-falls back to HLS. Chromecast stays on HLS. Off by default; target under ~1 s, not yet measured on TVs.

## 0.1.2
- Runs as a system-tray app: no console window. Tray menu: Open Beamer, Quit Beamer. Launching a second time just opens the existing one.
- Logs go to `%APPDATA%\Beamer\beamer.log`; background `adb` calls no longer flash a window.

## 0.1.1
- Fire TV: stale "offline" ADB connections are now reset and retried automatically.
- Installer asks for administrator permission once and adds a firewall rule limited to the local network, so TVs can reach Beamer even when Windows marks the Wi-Fi "Public".

## 0.1.0
- First release: browser tab/screen -> HLS -> LG webOS and Amazon Fire TV (tested); Chromecast (untested); multi-TV and quality menu; Ohio State themed UI; Windows installer.

