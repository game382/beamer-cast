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
