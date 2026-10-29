"""Low-latency fan-out: MPEG-TS from ffmpeg -> every connected TV over WebSocket.

The hub keeps the PAT/PMT and every packet since the most recent video keyframe, so a TV that joins mid-stream
starts at a clean keyframe. A client that falls too far behind has its queue dropped and jumps back to live.
"""
import asyncio

TS = 188
SYNC = 0x47
MAX_QUEUED_BYTES = 2_000_000      # per client; beyond this the client is resynced to live instead of buffering more


class Client:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.queued = 0
        self.started = False       # becomes True once it has been handed a keyframe-aligned start
        self.resyncs = 0

    def put(self, data):
        self.queue.put_nowait(data)
        self.queued += len(data)

    def clear(self):
        while not self.queue.empty():
            self.queue.get_nowait()
        self.queued = 0

    async def get(self):
        data = await self.queue.get()
        self.queued -= len(data)
        return data


class LiveHub:
    def __init__(self):
        self.clients = set()
        self._rest = b""           # trailing bytes that don't yet make a whole 188-byte packet
        self._pat = None
        self._pmt = None
        self._pmt_pid = None
        self._video_pid = None
        self._gop = []             # packets since the latest keyframe, starting with PAT/PMT
        self._gop_bytes = 0
        self.keyframes = 0

    # ----- clients -----
    def add(self):
        c = Client()
        self.clients.add(c)
        if self._gop:              # joined mid-stream: start from the latest keyframe
            c.put(self._snapshot())
            c.started = True
        return c

    def remove(self, c):
        self.clients.discard(c)

    def reset(self):
        """New streaming session: forget old stream state (clients stay connected and wait for a keyframe)."""
        self._rest = b""
        self._pat = self._pmt = self._pmt_pid = self._video_pid = None
        self._gop, self._gop_bytes = [], 0
        for c in self.clients:
            c.clear()
            c.started = False

    def _snapshot(self):
        return b"".join(self._gop)

    # ----- feeding -----
    def feed(self, data):
        buf = self._rest + data
        # re-sync to packet boundaries
        if buf[:1] != bytes([SYNC]):
            i = buf.find(bytes([SYNC]))
            if i < 0:
                self._rest = b""
                return
            buf = buf[i:]
        usable = len(buf) - len(buf) % TS
        self._rest = buf[usable:]
        out = bytearray()          # packets that every started client should receive as-is
        for off in range(0, usable, TS):
            pkt = buf[off:off + TS]
            if pkt[0] != SYNC:
                continue
            pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
            pusi = bool(pkt[1] & 0x40)
            if pid == 0 and pusi:
                self._pat = pkt
                self._pmt_pid = self._parse_pat(pkt)
            elif pid == self._pmt_pid and pusi:
                self._pmt = pkt
            elif self._video_pid is None and pusi and self._is_video_pes(pkt):
                self._video_pid = pid
            if pid == self._video_pid and pusi and self._is_keyframe(pkt):
                # new GOP: flush what came before to started clients, then hand unstarted clients a clean start
                self._send_started(bytes(out))
                out.clear()
                self._gop = [p for p in (self._pat, self._pmt) if p] + [pkt]
                self._gop_bytes = len(self._gop) * TS
                self.keyframes += 1
                snap = self._snapshot()
                for c in self.clients:
                    if not c.started:
                        c.put(snap)
                        c.started = True
                    else:
                        c.put(pkt)
                continue
            if self._gop:
                self._gop.append(pkt)
                self._gop_bytes += TS
            out += pkt
        self._send_started(bytes(out))

    def _send_started(self, data):
        if not data:
            return
        for c in list(self.clients):
            if not c.started:
                continue
            if c.queued > MAX_QUEUED_BYTES:       # too far behind: drop its queue and jump back to live
                c.clear()
                c.put(self._snapshot())
                c.resyncs += 1
            else:
                c.put(data)

    # ----- MPEG-TS helpers -----
    @staticmethod
    def _payload_offset(pkt):
        afc = (pkt[3] >> 4) & 3
        if afc == 1:
            return 4
        if afc == 3:
            return 5 + pkt[4]
        return None                # no payload

    def _parse_pat(self, pkt):
        o = self._payload_offset(pkt)
        if o is None:
            return None
        o += 1 + pkt[o]            # pointer_field
        # table_id(1) section_length(2) tsid(2) ver(1) sec(1) last(1) then program entries (4 bytes each)
        if len(pkt) < o + 12:
            return None
        return ((pkt[o + 10] & 0x1F) << 8) | pkt[o + 11]

    def _is_video_pes(self, pkt):
        o = self._payload_offset(pkt)
        return o is not None and pkt[o:o + 3] == b"\x00\x00\x01" and 0xE0 <= pkt[o + 3] <= 0xEF

    @staticmethod
    def _is_keyframe(pkt):
        """ffmpeg's mpegts muxer sets random_access_indicator in the adaptation field of keyframe packets."""
        afc = (pkt[3] >> 4) & 3
        return afc in (2, 3) and pkt[4] > 0 and bool(pkt[5] & 0x40)
