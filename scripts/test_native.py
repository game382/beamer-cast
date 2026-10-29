r"""Native-capture test (no TV): start Beamer on a test port, begin a native screen session, connect a simulated TV to /live,
and check the stream is clean MPEG-TS that decodes from the first byte.
  .venv\Scripts\python scripts\test_native.py [seconds=8]"""
import asyncio, os, pathlib, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORT = 8799
SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 8


async def main():
    import aiohttp
    env = dict(os.environ, BEAMER_PORT=str(PORT), BEAMER_NO_TRAY="1", PYTHONIOENCODING="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "beamer", "--no-browser"], cwd=ROOT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    await asyncio.sleep(4)
    chunks, msgs = [], []
    async with aiohttp.ClientSession() as s:
        ctl = await s.ws_connect(f"ws://127.0.0.1:{PORT}/native?ll=1&q=1080&dev=", max_msg_size=0)
        t0 = time.time()
        await asyncio.sleep(3)
        live = await s.ws_connect(f"ws://127.0.0.1:{PORT}/live", max_msg_size=0)
        end = time.time() + SECS
        first = None
        while time.time() < end:
            try:
                m = await asyncio.wait_for(live.receive(), 2)
            except asyncio.TimeoutError:
                continue
            if m.type == aiohttp.WSMsgType.BINARY:
                first = first or time.time()
                chunks.append(m.data)
        while True:
            try:
                m = await asyncio.wait_for(ctl.receive(), 0.2)
                msgs.append(m.data)
            except Exception:
                break
        await ctl.close()
    await asyncio.sleep(1)
    server.terminate()
    out = server.communicate(timeout=10)[0]
    print("---- server log ----\n" + "\n".join(l for l in out.splitlines() if l.strip()))
    print("---- page messages ----", msgs)
    data = b"".join(chunks)
    f = pathlib.Path(tempfile.gettempdir()) / "beamer_native_test.ts"
    f.write_bytes(data)
    pk = [data[i:i + 188] for i in range(0, len(data) - len(data) % 188, 188)]
    print(f"received {len(data)} bytes, {len(pk)} packets, sync ok={all(p[0]==0x47 for p in pk)}, starts with PAT={bool(pk) and (((pk[0][1]&0x1f)<<8)|pk[0][2])==0}")
    print(f"bitrate ~ {len(data)*8/SECS/1e6:.2f} Mbit/s; first data {first - t0 - 3:.2f}s after connecting" if first else "NO DATA")
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-f", "null", "-"], capture_output=True, text=True)
    errs = [l for l in r.stderr.splitlines() if l.strip()]
    print("ffmpeg decode:", "CLEAN" if not errs else f"{len(errs)} messages, first: {errs[0][:140]}")
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height,r_frame_rate",
                         "-of", "csv=p=0", str(f)], capture_output=True, text=True)
    print("video stream:", pr.stdout.strip())
    f.unlink(missing_ok=True)
    fl = pathlib.Path(os.environ["APPDATA"]) / "Beamer" / "ffmpeg.log"
    print("---- ffmpeg.log ----\n" + fl.read_text(errors="ignore")[-800:])


asyncio.run(main())
