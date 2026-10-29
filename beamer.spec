# PyInstaller spec: build with  pyinstaller beamer.spec
a = Analysis(["run_beamer.py"],
             datas=[("beamer/assets", "beamer/assets")],
             hiddenimports=["aiowebostv", "pychromecast", "zeroconf", "pystray._win32", "pyaudiowpatch", "pycaw", "comtypes"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Beamer",
          console=False, icon="beamer/assets/beamer.ico")
coll = COLLECT(exe, a.binaries, a.datas, name="Beamer")
