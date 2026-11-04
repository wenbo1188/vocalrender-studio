#!/usr/bin/env python3
"""Mock VocalRender service for trying VocalRender Studio's remote mode without a GPU.

It implements the same endpoints the editor calls and returns a simple synthesized tone
that follows the submitted score (not real singing). Python standard library only.

    python tools/mock_vocalrender_server.py            # http://127.0.0.1:8000/v1
    python tools/mock_vocalrender_server.py --no-f0    # omit f0 so the editor extracts pitch itself
    python tools/mock_vocalrender_server.py --exact    # follow score timing exactly (the real model does not)

Like the real model, it does not follow the score's timing exactly by default: output starts after a short
silence, and rests (SP) / breaths (AP) and notes come out somewhat longer or shorter than written.
Reference audio must be uploaded with POST /voices before its upload_id can be used in /render.

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
UPLOADS = {}
LOCK = threading.Lock()


def parse_multipart(body, ctype):
    """Minimal multipart/form-data parser: returns {field: (filename or None, bytes)}."""
    m = re.search(r'boundary="?([^";]+)"?', ctype or "")
    if not m:
        raise ValueError("expected multipart/form-data with a boundary")
    sep = b"--" + m.group(1).encode()
    out = {}
    for part in body.split(sep)[1:]:
        if part.startswith(b"--"):
            break
        head, _, data = part.lstrip(b"\r\n").partition(b"\r\n\r\n")
        disp = re.search(rb'name="([^"]*)"(?:; filename="([^"]*)")?', head)
        if disp:
            fname = disp.group(2).decode("utf-8", "replace") if disp.group(2) is not None else None
            out[disp.group(1).decode()] = (fname, data[:-2] if data.endswith(b"\r\n") else data)
    return out


def wav_seconds(data):
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("reference audio must be a WAV file")
    pos, fmt = 12, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", data[pos + 8:pos + 24])
        elif cid == b"data" and fmt:
            return min(size, len(data) - pos - 8) / fmt[4] / fmt[2]
        pos += 8 + size + (size & 1)
    raise ValueError("WAV file has no audio data")


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
    pa = req.get("prompt_audio") or {}
    if "upload_id" in pa:
        if pa["upload_id"] not in UPLOADS:
            raise ValueError(f"unknown upload_id {pa['upload_id']!r}: upload the reference audio with POST /voices first")
    elif pa.get("preset") not in {v["id"] for v in VOICES}:
        raise ValueError("prompt_audio needs a preset voice id or an upload_id")
    return score


def synthesize(score, seed, exact=False):
    """Returns (wav_bytes, f0_hz_list). A buzzy tone with glides and vibrato that follows the score.
    Unless exact, timing is loosened the way a score-native model sings: a lead-in silence,
    rests/breaths noticeably shorter or longer, notes a little uneven."""
    rnd = random.Random(seed)
    spb = 60.0 / float(score["bpm"])
    words = [score["word"][i] for i in score["pitch2word"]]
    notes, t = [], 0.0 if exact else 0.12 + rnd.random() * 0.1
    for p, tok, w in zip(score["pitch"], score["note"], words):
        d = NOTE_BEATS[tok.strip("<>")] * spb
        if not exact:
            d *= rnd.uniform(0.45, 1.5) if w in ("SP", "AP") else rnd.uniform(0.88, 1.14)
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
            try:
                parts = parse_multipart(body, self.headers.get("Content-Type"))
                if "file" not in parts:
                    raise ValueError("multipart field 'file' is required")
                secs = wav_seconds(parts["file"][1])
            except (ValueError, struct.error) as e:
                return self._send(422, {"detail": str(e)})
            if secs < 1.5:
                return self._send(422, {"detail": f"reference audio is {secs:.1f}s; 2-8s of clean singing is needed"})
            uid = "upl_" + uuid.uuid4().hex[:10]
            with LOCK:
                UPLOADS[uid] = {"bytes": len(parts["file"][1]), "seconds": secs}
            return self._send(200, {"upload_id": uid, "duration_s": round(secs, 2)})
        if r == "/render":
            try:
                req = json.loads(body or b"{}")
                score = validate(req)
            except (ValueError, json.JSONDecodeError) as e:
                return self._send(422, {"detail": str(e)})
            seed = (req.get("generation") or {}).get("seed") or random.randrange(1, 10**9)
            wav, f0 = synthesize(score, seed, self.server.exact)
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
    ap.add_argument("--exact", action="store_true", help="follow the score timing exactly (no lead-in, no rest/breath stretching)")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.prefix, srv.delay, srv.token, srv.no_f0, srv.exact = a.prefix.rstrip("/"), a.delay, a.token, a.no_f0, a.exact
    print(f"Mock VocalRender service on http://{a.host}:{a.port}{srv.prefix}  (f0 {'off' if a.no_f0 else 'on'}, timing {'exact' if a.exact else 'natural'})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
