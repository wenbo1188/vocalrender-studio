#!/usr/bin/env python3
"""Mock VocalRender service for trying VocalRender Studio's remote mode without a GPU.

It implements the same endpoints the editor calls and returns a simple synthesized tone
that follows the submitted score (not real singing). Python standard library only.

    python tools/mock_vocalrender_server.py            # http://127.0.0.1:8000/v1
    python tools/mock_vocalrender_server.py --no-f0    # omit f0 so the editor extracts pitch itself

Then in the editor: Settings -> 连接 VocalRender 服务 -> 服务地址 http://127.0.0.1:8000/v1
"""
import argparse
import io
import json
import math
import random
import re
import struct
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NOTE_BEATS = {
    "NOTE_32": 0.125, "NOTE_DOT_32": 0.1875, "NOTE_16": 0.25, "NOTE_DOT_16": 0.375,
    "NOTE_8": 0.5, "NOTE_DOT_8": 0.75, "NOTE_4": 1.0, "NOTE_DOT_4": 1.5,
    "NOTE_2": 2.0, "NOTE_DOT_2": 3.0, "NOTE_1": 4.0, "NOTE_DOT_1": 6.0,
}
VOICES = [{"id": f"{k}-{i}", "name": f"{k}-{i}", "source": f"GTSinger ZH-{k}-1"} for k in ("Alto", "Tenor") for i in (1, 2, 3)]
SR = 48000
HOP = 0.01

JOBS = {}
LOCK = threading.Lock()


def validate(req):
    score = req.get("score") or {}
    for k in ("word", "pitch", "note", "pitch2word", "bpm"):
        if k not in score:
            raise ValueError(f"score.{k} is required")
    n = len(score["pitch"])
    if not (len(score["note"]) == len(score["pitch2word"]) == n):
        raise ValueError("pitch, note and pitch2word must have the same length")
    if n > 128 or len(score["word"]) > 64:
        raise ValueError("score exceeds 128 events or 64 lyric units")
    for t in score["note"]:
        if t.strip("<>") not in NOTE_BEATS:
            raise ValueError(f"unsupported note value {t}")
    for w in score["word"]:
        if w not in ("SP", "AP") and not re.fullmatch(r"[㐀-鿿]", w):
            raise ValueError(f"lyric {w!r} is not a single Chinese character")
    return score


def synthesize(score, seed):
    """Returns (wav_bytes, f0_hz_list). A buzzy tone with glides and vibrato that follows the score."""
    rnd = random.Random(seed)
    spb = 60.0 / float(score["bpm"])
    notes, t = [], 0.0
    for p, tok in zip(score["pitch"], score["note"]):
        d = NOTE_BEATS[tok.strip("<>")] * spb
        notes.append((t, t + d, int(p)))
        t += d
    total = t + 0.3
    n = int(total * SR)
    f0 = [0.0] * (int(total / HOP) + 1)
    out = [0.0] * n
    vib_rate, vib_depth = 5.2 + rnd.random(), 0.25 + rnd.random() * 0.15
    phase = 0.0
    prev = None
    for i, (s, e, p) in enumerate(notes):
        if p <= 0:
            prev = None
            continue
        a, b = int(s * SR), int(e * SR)
        for k in range(a, min(b, n)):
            tt = k / SR - s
            midi = p
            if prev is not None and tt < 0.08:
                x = tt / 0.08
                midi = prev + (p - prev) * (x * x * (3 - 2 * x))
            elif prev is None and tt < 0.06:
                midi = p - 0.6 * (1 - tt / 0.06)
            if e - s > 0.45 and tt > 0.3:
                midi += vib_depth * min(1, (tt - 0.3) / 0.3) * math.sin(2 * math.pi * vib_rate * (tt - 0.3))
            hz = 440.0 * 2 ** ((midi - 69) / 12)
            phase += 2 * math.pi * hz / SR
            env = min(1.0, tt / 0.03) * min(1.0, (e - s - tt) / 0.05)
            out[k] = 0.25 * env * (math.sin(phase) + 0.45 * math.sin(2 * phase) + 0.2 * math.sin(3 * phase))
            if k % int(HOP * SR) == 0:
                f0[k // int(HOP * SR)] = round(hz, 2)
        prev = p
    buf = io.BytesIO()
    data = b"".join(struct.pack("<h", int(max(-1, min(1, v)) * 32767)) for v in out)
    buf.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, SR, SR * 2, 2, 16))
    buf.write(b"data" + struct.pack("<I", len(data)) + data)
    return buf.getvalue(), f0


class Handler(BaseHTTPRequestHandler):
    server_version = "MockVocalRender/1.0"

    def log_message(self, fmt, *args):
        print("[mock]", self.command, self.path, "-", fmt % args)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _route(self):
        prefix = self.server.prefix
        if not self.path.startswith(prefix):
            return None
        return self.path[len(prefix):].split("?")[0] or "/"

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        r = self._route()
        if r == "/health":
            return self._send(200, {"status": "ok", "model": "mock", "checkpoints": ["VocalRender-Pro", "VocalRender"]})
        if r == "/voices":
            return self._send(200, {"voices": VOICES})
        m = re.fullmatch(r"/jobs/([\w-]+)(/audio)?", r or "")
        if not m:
            return self._send(404, {"detail": "not found"})
        with LOCK:
            job = JOBS.get(m.group(1))
        if not job:
            return self._send(404, {"detail": "job not found"})
        progress = min(1.0, (time.time() - job["created"]) / job["duration"])
        if m.group(2):
            if progress < 1:
                return self._send(409, {"detail": "job not finished"})
            return self._send(200, job["wav"], "audio/wav")
        if progress < 1:
            return self._send(200, {"job_id": m.group(1), "status": "running" if progress > 0.1 else "queued", "progress": round(progress, 3)})
        res = {"job_id": m.group(1), "status": "succeeded", "progress": 1, "seed": job["seed"],
               "audio_url": f"jobs/{m.group(1)}/audio", "duration_s": round(len(job["wav"]) / 2 / SR, 3)}
        if not self.server.no_f0:
            res["f0"] = {"hop_s": HOP, "hz": job["f0"]}
        return self._send(200, res)

    def do_POST(self):
        r = self._route()
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if self.server.token and self.headers.get("Authorization") != f"Bearer {self.server.token}":
            return self._send(401, {"detail": "invalid token"})
        if r == "/voices":
            return self._send(200, {"upload_id": "upl_" + uuid.uuid4().hex[:10], "bytes": len(body)})
        if r == "/render":
            try:
                req = json.loads(body or b"{}")
                score = validate(req)
            except (ValueError, json.JSONDecodeError) as e:
                return self._send(422, {"detail": str(e)})
            seed = (req.get("generation") or {}).get("seed") or random.randrange(1, 10**9)
            wav, f0 = synthesize(score, seed)
            job_id = uuid.uuid4().hex[:12]
            with LOCK:
                JOBS[job_id] = {"created": time.time(), "duration": self.server.delay, "wav": wav, "f0": f0, "seed": seed}
            return self._send(200, {"job_id": job_id, "status": "queued"})
        if r == "/score/import":
            return self._send(501, {"detail": "score import is not implemented in the mock server"})
        return self._send(404, {"detail": "not found"})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--prefix", default="/v1")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds each render job takes")
    ap.add_argument("--token", default="", help="require this Bearer token on POST requests")
    ap.add_argument("--no-f0", action="store_true", help="do not include f0 in job results")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.prefix, srv.delay, srv.token, srv.no_f0 = a.prefix.rstrip("/"), a.delay, a.token, a.no_f0
    print(f"Mock VocalRender service on http://{a.host}:{a.port}{srv.prefix}  (f0 {'off' if a.no_f0 else 'on'})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
