"""Native screen capture: ddagrab (Windows Desktop Duplication) -> Intel Quick Sync h264_qsv, falling back to libx264."""
import ctypes, functools, subprocess

WANT_QSV = ("ddagrab", "h264_qsv")


def screen_size():
    u = ctypes.windll.user32
    try:
        u.SetProcessDPIAware()
    except Exception:
        pass
    return u.GetSystemMetrics(0), u.GetSystemMetrics(1)


@functools.lru_cache(maxsize=4)
def capabilities(ffmpeg):
    """What this ffmpeg build can do: {'ddagrab': bool, 'qsv': bool}. QSV is proven by a 1-frame encode, not just listed."""
    def run(args):
        return subprocess.run([ffmpeg, "-hide_banner", *args], capture_output=True, text=True, timeout=30,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    filters = run(["-filters"]).stdout
    caps = {"ddagrab": "ddagrab" in filters, "qsv": False}
    if caps["ddagrab"] and "h264_qsv" in run(["-encoders"]).stdout:
        vf, enc = video_args(30, "2M", 720, True)
        r = run(source_args(30, True) + ["-t", "1", "-vf", vf] + enc + ["-f", "null", "-"])
        caps["qsv"] = r.returncode == 0
    return caps


def audio_input_args(audio):
    """Second ffmpeg input: the raw PCM that AudioFeeder serves on a local port."""
    return ["-thread_queue_size", "512", "-f", "s16le", "-ar", str(audio.rate), "-ac", str(audio.channels),
            "-i", f"tcp://127.0.0.1:{audio.port}"]


def source_args(fps, qsv):
    """Input + filter for the screen at the requested size; returns (input_args, vf_for_encoder)."""
    dev = ["-init_hw_device", "d3d11va=d3d"]
    if qsv:
        dev += ["-init_hw_device", "qsv=qs@d3d", "-filter_hw_device", "qs"]
    return dev + ["-f", "lavfi", "-i", f"ddagrab=framerate={fps}:output_idx=0:draw_mouse=1"]


def video_args(fps, rate, height, qsv):
    """Filter chain + encoder args. Output height is capped at `height`, never upscaled; width keeps the aspect ratio."""
    w, h = screen_size()
    if h > height:
        w, h = round(w * height / h / 2) * 2, height
    w, h = w - w % 2, h - h % 2
    if qsv:
        vf = f"hwmap=derive_device=qsv,format=qsv,vpp_qsv=w={w}:h={h}:format=nv12"
        enc = ["-c:v", "h264_qsv", "-preset", "veryfast", "-async_depth", "1", "-look_ahead", "0", "-bf", "0"]
    else:
        vf = f"hwdownload,format=bgra,scale={w}:{h},format=yuv420p"
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-bf", "0",
               "-sc_threshold", "0"]
    enc += ["-b:v", rate, "-maxrate", rate, "-bufsize", rate, "-g", str(fps), "-keyint_min", str(fps)]
    return vf, enc


# ---------- PC sound ----------
import pathlib, socket, threading, time

from . import config

MUTE_FLAG = config.APP_DIR / "muted_by_beamer.txt"     # exists only while Beamer has the PC muted (crash recovery)


class AudioFeeder:
    """Captures what the PC is playing (WASAPI loopback) and serves it to ffmpeg as steady raw PCM on a local TCP port.
    Loopback stops delivering data when nothing plays, so the writer paces itself on the clock and fills gaps with silence."""

    def __init__(self):
        import pyaudiowpatch as pa
        self._pa = pa
        self.p = pa.PyAudio()
        self.dev = self.p.get_default_wasapi_loopback()
        self.rate = int(self.dev["defaultSampleRate"])
        self.channels = int(self.dev["maxInputChannels"])
        self.frame = 2 * self.channels                      # bytes per sample frame (s16)
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.stop_ev = threading.Event()
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.srv.settimeout(30)
        self.port = self.srv.getsockname()[1]
        self.stream = None

    def _cb(self, data, frames, t, status):
        with self.lock:
            self.buf += data
        return (None, self._pa.paContinue)

    def start(self):
        self.stream = self.p.open(format=self._pa.paInt16, channels=self.channels, rate=self.rate, input=True,
                                  input_device_index=self.dev["index"], frames_per_buffer=480, stream_callback=self._cb)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        try:
            conn, _ = self.srv.accept()                      # ffmpeg connects when it opens this input
        except OSError:
            return
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        with self.lock:
            self.buf.clear()
        t0, sent = time.monotonic(), 0
        cap = self.rate // 5 * self.frame                    # never hold more than ~200 ms (keeps audio from lagging)
        try:
            while not self.stop_ev.is_set():
                time.sleep(0.01)
                want = int((time.monotonic() - t0) * self.rate) - sent
                if want <= 0:
                    continue
                need = want * self.frame
                with self.lock:
                    if len(self.buf) > cap + need:           # capture clock ran ahead: drop the oldest audio
                        del self.buf[:len(self.buf) - cap - need]
                    chunk = bytes(self.buf[:need])
                    del self.buf[:need]
                if len(chunk) < need:
                    chunk += bytes(need - len(chunk))        # silence
                conn.sendall(chunk)
                sent += want
        except OSError:
            pass
        finally:
            conn.close()

    def stop(self):
        self.stop_ev.set()
        for fn in (lambda: self.stream and (self.stream.stop_stream(), self.stream.close()), self.p.terminate, self.srv.close):
            try:
                fn()
            except Exception:
                pass


def _endpoint():
    from pycaw.pycaw import AudioUtilities
    dev = AudioUtilities.GetSpeakers()
    return dev.EndpointVolume


def mute_pc():
    """Mute the PC speakers; returns a function that restores the previous state. Survives a crash via MUTE_FLAG."""
    ep = _endpoint()
    was = int(ep.GetMute())
    if not was:
        ep.SetMute(1, None)
        MUTE_FLAG.write_text("1")

    def restore():
        try:
            if not was:
                _endpoint().SetMute(0, None)
        finally:
            MUTE_FLAG.unlink(missing_ok=True)
    return restore


def recover_mute():
    """At startup: if a previous run died while it had the PC muted, unmute."""
    if MUTE_FLAG.exists():
        try:
            _endpoint().SetMute(0, None)
        finally:
            MUTE_FLAG.unlink(missing_ok=True)
