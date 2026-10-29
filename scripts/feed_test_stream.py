"""Feed a realtime synthetic stream (burned-in running clock) to a running Beamer, as the browser would.

  BEAMER_PORT=8799 BEAMER_NO_TRAY=1 .venv\\Scripts\\python -m beamer --no-browser     # terminal 1
  .venv\\Scripts\\python scripts\\feed_test_stream.py 90 [ll|hls]                         # terminal 2
Then open http://localhost:8799/player?mode=ll&badge=1 in a browser. Writes the feed start time (epoch seconds)
to %TEMP%\\beamer_feed_start.txt so a page can compute (now - start) - currentTime.
"""
import asyncio, os, pathlib, subprocess, sys, tempfile, time

import aiohttp

PORT = int(os.environ.get("BEAMER_PORT", 8765))
SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 60
LL = (sys.argv[2] if len(sys.argv) > 2 else "ll") == "ll"


async def main():
    draw = (r"drawtext=fontfile='C\:/Windows/Fonts/consola.ttf':text='%{pts\:hms}':fontcolor=white:fontsize=96:"
            r"box=1:boxcolor=black@0.6:x=(w-tw)/2:y=(h-th)/2")
    src = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-readrate_initial_burst", "0", "-re", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-vf", draw,
         "-c:v", "libvpx", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "3M", "-g", "30",
         "-c:a", "libopus", "-f", "webm", "-cluster_time_limit", "100", "pipe:1"], stdout=subprocess.PIPE)
    async with aiohttp.ClientSession() as s:
        ws = await s.ws_connect(f"ws://127.0.0.1:{PORT}/ws?ll={1 if LL else 0}&q=720&dev=", max_msg_size=0)
        start = time.time()
        (pathlib.Path(tempfile.gettempdir()) / "beamer_feed_start.txt").write_text(str(start))
        print(f"feeding {SECONDS:.0f}s ({'low-latency' if LL else 'HLS'}); start epoch {start:.3f}", flush=True)
        loop = asyncio.get_running_loop()
        while time.time() - start < SECONDS:
            data = await loop.run_in_executor(None, src.stdout.read1, 16384)
            if not data:
                break
            await ws.send_bytes(data)
        await ws.close()
    src.kill()
    print("feed finished")


asyncio.run(main())
