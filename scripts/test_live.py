"""Server-side test of the low-latency path (no TV needed).

Starts Beamer on a test port, feeds it a realtime WebM test stream exactly as the browser would, and connects
three simulated TVs to /live: one on time, one late joiner, one that stops reading (queue-drop test).
Checks clean starts (PAT, PMT, keyframe first), decodability, resyncs, and the pipeline delay.

Run from the repo root:  .venv\\Scripts\\python scripts\\test_live.py
"""
import asyncio, os, pathlib, statistics, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORT = 8799
TS = 188
ABS_ZERO = 0 if os.environ.get('ABS') else None   # ABS=1: treat PTS 0 as the moment the source started


def parse(chunks):
    """Return (packets, first_packet_info) from the concatenated bytes."""
    data = b"".join(c for _, c in chunks)
    return data


def pes_pts(pkt):
    afc = (pkt[3] >> 4) & 3
    o = 4 if afc == 1 else 5 + pkt[4]
    if pkt[o:o + 3] != b"\x00\x00\x01" or not (pkt[o + 7] & 0x80):
        return None
    b = pkt[o + 9:o + 14]
    return (((b[0] >> 1) & 7) << 30) | (b[1] << 22) | ((b[2] >> 1) << 15) | (b[3] << 7) | (b[4] >> 1)


def analyse(name, chunks, t0, pts_zero=None):
    data = b"".join(c for _, c in chunks)
    pkts = [data[i:i + TS] for i in range(0, len(data) - len(data) % TS, TS)]
    ok_sync = all(p[0] == 0x47 for p in pkts)
    pids = [((p[1] & 0x1F) << 8) | p[2] for p in pkts]
    first_video = next((i for i, p in enumerate(pkts) if (p[1] & 0x40) and pkts[i][4:8] != b"" and pids[i] not in (0, 0x1000)
                        and (pes_pts(p) is not None)), None)
    first_is_pat = pids[0] == 0 if pkts else False
    has_pmt = 0x1000 in pids[:5]
    vid_pid = pids[first_video] if first_video is not None else None
    rai = False
    if first_video is not None:
        p = pkts[first_video]
        rai = ((p[3] >> 4) & 3) in (2, 3) and p[4] > 0 and bool(p[5] & 0x40)
    print(f"[{name}] bytes={len(data)} packets={len(pkts)} sync_ok={ok_sync} starts_with_PAT={first_is_pat} "
          f"PMT_in_first_5={has_pmt} first_video_packet_is_keyframe={rai}")
    # decodability from the very first byte
    f = pathlib.Path(tempfile.gettempdir()) / f"beamer_test_{name}.ts"
    f.write_bytes(data)
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-f", "null", "-"], capture_output=True, text=True)
    errs = [l for l in r.stderr.splitlines() if l.strip()]
    print(f"[{name}] ffmpeg decode of the received bytes: {'CLEAN' if not errs else str(len(errs)) + ' messages, first: ' + errs[0][:120]}")
    # pipeline delay: wall-clock arrival vs media time of each video frame (input is realtime)
    lags, first_pts = [], None
    pos = 0
    for tarr, c in chunks:
        for i in range(0, len(c) - len(c) % TS, TS):
            p = c[i:i + TS]
            if vid_pid is not None and (((p[1] & 0x1F) << 8) | p[2]) == vid_pid and (p[1] & 0x40):
                pts = pes_pts(p)
                if pts is None:
                    continue
                if first_pts is None:
                    first_pts = pts if pts_zero is None else pts_zero
                lags.append(tarr - t0 - (pts - (first_pts if ABS_ZERO is None else ABS_ZERO)) / 90000.0)
    print(f"[{name}] first video PTS in this stream = {first_pts / 90000.0:.3f}s (source starts at 0)")
    return lags, (first_pts if pts_zero is None else pts_zero)


def hub_drop_test():
    """A TV that stops reading: its queue must be dropped and resynced to a keyframe, never grow without bound."""
    sys.path.insert(0, str(ROOT))
    from beamer.live import LiveHub, MAX_QUEUED_BYTES
    ts = (pathlib.Path(tempfile.gettempdir()) / "beamer_test_A_on_time.ts").read_bytes()
    async def run():
        hub = LiveHub()
        slow, ok = hub.add(), hub.add()
        peak = 0
        for off in range(0, len(ts) - 3760, 3760):       # feed ~6 MB as fast as possible; `slow` never reads
            hub.feed(ts[off:off + 3760])
            while not ok.queue.empty():                    # `ok` keeps up
                await ok.get()
            peak = max(peak, slow.queued)
        first = slow.queue.get_nowait() if not slow.queue.empty() else b""
        print(f"[hub drop test] fed {len(ts)} bytes; stalled client peak queue={peak} bytes (limit {MAX_QUEUED_BYTES}); "
              f"resyncs={slow.resyncs}; keyframes seen={hub.keyframes}")
        print(f"[hub drop test] after a drop the stalled client's next data starts with PAT: "
              f"{first[:1] == b'G' and (((first[1] & 0x1F) << 8) | first[2]) == 0}; "
              f"bounded={peak <= MAX_QUEUED_BYTES + 2 * len(ts[:3760]) + 200000}")
    asyncio.run(run())


async def main():
    import aiohttp
    env = dict(os.environ, BEAMER_PORT=str(PORT), BEAMER_NO_TRAY="1", PYTHONIOENCODING="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "beamer", "--no-browser"], cwd=ROOT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    await asyncio.sleep(4)
    # realtime WebM test source: moving pattern + tone, like MediaRecorder output
    src = subprocess.Popen(["ffmpeg", "-v", "error", "-readrate_initial_burst", "0", "-re", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-c:v", "libvpx", "-deadline", "realtime",
                            "-cpu-used", "8", "-b:v", "3M", "-g", "30", "-c:a", "libopus", "-f", "webm", "-cluster_time_limit", "100", "pipe:1"],
                           stdout=subprocess.PIPE)
    results = {}
    async with aiohttp.ClientSession() as s:
        ctl = await s.ws_connect(f"ws://127.0.0.1:{PORT}/ws?ll=1&q=720&dev=", max_msg_size=0)
        t0 = time.time()

        async def feed():
            loop = asyncio.get_running_loop()
            while True:
                data = await loop.run_in_executor(None, src.stdout.read1, 16384)
                if not data:
                    break
                await ctl.send_bytes(data)

        async def tv(name, delay, read_until, stall=None):
            await asyncio.sleep(delay)
            ws = await s.ws_connect(f"ws://127.0.0.1:{PORT}/live", max_msg_size=0)
            chunks = []
            end = time.time() + read_until
            while time.time() < end:
                if stall and stall[0] <= time.time() - t0 < stall[1]:
                    await asyncio.sleep(0.2)          # a TV that stops reading: its queue must be dropped, not grow
                    continue
                try:
                    m = await asyncio.wait_for(ws.receive(), 1)
                except asyncio.TimeoutError:
                    continue
                if m.type == aiohttp.WSMsgType.BINARY:
                    chunks.append((time.time(), m.data))
                else:
                    break
            await ws.close()
            results[name] = chunks

        feeder = asyncio.create_task(feed())
        await asyncio.gather(tv("A_on_time", 0.5, 14), tv("B_late_joiner", 7, 7))
        feeder.cancel()
        await ctl.close()
    src.kill()
    server.terminate()
    out = server.communicate(timeout=10)[0]
    print("---- server log ----")
    print("\n".join(l for l in out.splitlines() if "live" in l or "session" in l))
    print("---- results ----")
    zero = None
    for name, chunks in sorted(results.items()):
        if not chunks:
            print(f"[{name}] NO DATA"); continue
        lags, z = analyse(name, chunks, t0, zero)
        zero = zero if zero is not None else z
        if lags:
            base = lags[0]
            steady = lags[len(lags) // 4:]
            print(f"[{name}] pipeline delay (browser-side encode excluded): first frame {base:.2f}s; "
                  f"steady median {statistics.median(steady):.2f}s, p95 {sorted(steady)[int(len(steady) * .95) - 1]:.2f}s over {len(lags)} frames")


asyncio.run(main())
hub_drop_test()
