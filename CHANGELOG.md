# Changelog

## 0.1.2
- Runs as a system-tray app: no console window. Tray menu: Open Beamer, Quit Beamer. Launching a second time just opens the existing one.
- Logs go to `%APPDATA%\Beamer\beamer.log`; background `adb` calls no longer flash a window.

## 0.1.1
- Fire TV: stale "offline" ADB connections are now reset and retried automatically.
- Installer asks for administrator permission once and adds a firewall rule limited to the local network, so TVs can reach Beamer even when Windows marks the Wi-Fi "Public".

## 0.1.0
- First release: browser tab/screen -> HLS -> LG webOS and Amazon Fire TV (tested); Chromecast (untested); multi-TV and quality menu; Ohio State themed UI; Windows installer.
