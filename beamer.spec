# PyInstaller spec: build with  pyinstaller beamer.spec
a = Analysis(["run_beamer.py"],
             datas=[("beamer/assets", "beamer/assets")],
             hiddenimports=["aiowebostv", "pychromecast", "zeroconf"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Beamer",
          console=True, icon="beamer/assets/beamer.ico")
coll = COLLECT(exe, a.binaries, a.datas, name="Beamer")
