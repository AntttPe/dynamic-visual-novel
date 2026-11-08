"""Serwer obrazów na czas sesji gry na żywo. Gra łączy się z nim przez tunel SSH.

  python serve.py                                  # FLUX.2 klein 4B na porcie 8420
  python serve.py --model qwen-image-21-turbo

Regulamin serwera GPU: usługi nie mogą działać na stałe. Dlatego serwer słucha tylko na 127.0.0.1
i sam się wyłącza, zwalniając GPU, gdy przez --idle-minutes nie dostanie żadnego zadania.
Bez dodatkowych zależności: tylko biblioteka standardowa i adaptery z models.py.
"""

import argparse
import base64
import json
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from models import make_adapter

HOST = "127.0.0.1"
SIZE = (1280, 720)
MAX_BODY = 12_000_000  # obrazy wejściowe w base64
MAX_PROMPT = 4_000
MAX_REFS = 4
GAME_MODELS = ("flux2-klein-4b", "qwen-image-21-turbo", "sdxl-ip", "sdxl-ip-face")  # do wyboru w grze


class ImageServer(ThreadingHTTPServer):
    """Jeden model w pamięci GPU, zadania liczone po kolei (blokada)."""

    daemon_threads = True

    def __init__(self, adapter, port: int, idle_s: float, factory=make_adapter, models: tuple[str, ...] = GAME_MODELS):
        super().__init__((HOST, port), Handler)
        self.adapter = adapter
        self.factory = factory
        self.models = models
        self.loaded = True
        self.lock = threading.Lock()
        self.idle_s = idle_s
        self.last_used = time.monotonic()

    def idle(self) -> bool:
        return time.monotonic() - self.last_used > self.idle_s and not self.lock.locked()

    def _use(self, model: str | None) -> None:
        """Na GPU mieści się jeden model naraz, więc inny model wymaga zwolnienia pamięci i wczytania."""
        model = model or self.adapter.name
        if model == self.adapter.name and self.loaded:
            return
        self.adapter.unload()
        self.loaded = False
        self.adapter = self.factory(model)
        self.adapter.load()
        self.loaded = True

    def generate(self, prompt: str, seed: int, refs: list[bytes], model: str | None = None) -> tuple[bytes, str]:
        with self.lock:
            self.last_used = time.monotonic()
            try:
                self._use(model)
                if not getattr(self.adapter, "location_refs", True):
                    refs = refs[1:]  # gra zawsze podaje tło lokacji jako pierwszy obraz
                with tempfile.TemporaryDirectory() as tmp:
                    ref_paths = [Path(tmp) / f"ref{i}.png" for i in range(len(refs))]
                    for path, data in zip(ref_paths, refs, strict=True):
                        path.write_bytes(data)
                    out = Path(tmp) / "image.png"
                    self.adapter.generate(prompt, ref_paths, seed, out, SIZE)
                    return out.read_bytes(), self.adapter.name
            finally:
                self.last_used = time.monotonic()


class Handler(BaseHTTPRequestHandler):
    server: ImageServer

    def _send(self, code: int, body: bytes, content_type: str, **headers: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data: dict) -> None:
        self._send(code, json.dumps(data).encode(), "application/json")

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "ok", "model": self.server.adapter.name})
        else:
            self._json(404, {"error": "nie ma takiej ścieżki"})

    def do_POST(self) -> None:
        if self.path != "/generate":
            self._json(404, {"error": "nie ma takiej ścieżki"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY:
            self._json(400, {"error": "zły rozmiar zapytania"})
            return
        try:
            body = json.loads(self.rfile.read(length))
            prompt, seed = body["prompt"], body["seed"]
            refs = [base64.b64decode(r, validate=True) for r in body.get("refs", [])]
        except (ValueError, KeyError, TypeError, AttributeError):
            self._json(400, {"error": "oczekuję JSON z polami prompt, seed i opcjonalnie refs (base64)"})
            return
        model = body.get("model")
        if (not isinstance(prompt, str) or not 0 < len(prompt) <= MAX_PROMPT or type(seed) is not int
                or len(refs) > MAX_REFS or (model is not None and model not in self.server.models)):
            self._json(400, {"error": "zły prompt, seed, model albo liczba obrazów wejściowych"})
            return
        try:
            image, used = self.server.generate(prompt, seed, refs, model)
        except Exception as e:  # np. brak pamięci GPU: serwer działa dalej, gra pokaże brak tła
            self._json(500, {"error": f"{type(e).__name__}: {e}"})
            return
        self._send(200, image, "image/png", X_Image_Model=used)


def watch_idle(server: ImageServer, poll_s: float = 10.0) -> None:
    """Zatrzymuje serwer po czasie bezczynności."""
    while not server.idle():
        time.sleep(poll_s)
    server.shutdown()


def main() -> None:
    p = argparse.ArgumentParser(description="Serwer obrazów na czas sesji gry na żywo.")
    p.add_argument("--model", default="flux2-klein-4b")
    p.add_argument("--port", type=int, default=8420)
    p.add_argument("--idle-minutes", type=float, default=30, help="wyłączenie po takim czasie bez zadań")
    args = p.parse_args()

    adapter = make_adapter(args.model)
    print(f"Wczytuję model {args.model}...", flush=True)
    adapter.load()
    server = ImageServer(adapter, args.port, args.idle_minutes * 60)
    threading.Thread(target=watch_idle, args=(server,), daemon=True).start()
    print(f"Gotowe: {HOST}:{args.port}. Wyłączenie: Ctrl+C albo samo po {args.idle_minutes:g} min bezczynności.",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        adapter.unload()
        print("Serwer wyłączony, GPU zwolnione.", flush=True)


if __name__ == "__main__":
    main()
