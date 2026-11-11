"""HTTP server. Standard library only.

Serves the JSON API under /api/ and, so the game can run on its own, the
static files in web/. A web server in front can serve web/ directly and pass
only /api/ through.
"""
import json
import mimetypes
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, engine, levels, llm

WEB = config.REPO / "web"
MAX_BODY = 64 * 1024

SORRY = {
    "minute": "Whoa, too many messages at once! Wait a few seconds and try again.",
    "day": "Zipperlip has talked to so many visitors today that he lost his voice. Come back tomorrow!",
    "llm": "Zipperlip dozed off for a second. Send that again!",
    "bad": "That request didn't make sense to the tower. Reload the page and try again.",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "promptgame"
    protocol_version = "HTTP/1.1"
    timeout = 60
    game = None  # set in main()

    def log_message(self, fmt, *args):  # keep the journal quiet
        pass

    # ---- helpers -----------------------------------------------------------

    def _ip(self):
        peer = self.client_address[0]
        if peer in ("127.0.0.1", "::1"):
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return peer

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, status, kind):
        self._json(status, {"error": kind, "message": SORRY.get(kind, SORRY["bad"])})

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            raise ValueError("bad length")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return data

    def _ids(self, data):
        game_id, level_id = str(data.get("game", "")), str(data.get("level", ""))
        if not engine.GAME_ID.match(game_id) or level_id not in levels.BY_ID:
            raise ValueError("bad ids")
        return game_id, level_id

    # ---- routes ------------------------------------------------------------

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        try:
            if url.path == "/api/health":
                return self._json(200, {"ok": True})
            if url.path == "/api/levels":
                return self._json(200, {"levels": [levels.public_level(lv) for lv in levels.LEVELS]})
            if url.path == "/api/debug":
                q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                game_id, level_id = self._ids(q)
                word = self.game.debug(game_id, level_id, q.get("token", ""))
                if word is None:
                    return self._json(404, {"error": "not found"})
                return self._json(200, {"password": word})
            if url.path.startswith("/api/"):
                return self._json(404, {"error": "not found"})
            return self._static(url.path)
        except ValueError:
            return self._fail(400, "bad")

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        try:
            data = self._body()
            if url.path == "/api/chat":
                game_id, level_id = self._ids(data)
                out = self.game.chat(game_id, level_id, data.get("history"), data.get("message"),
                                     data.get("notes"), self._ip())
                return self._json(200, out)
            if url.path == "/api/guess":
                game_id, level_id = self._ids(data)
                return self._json(200, self.game.guess(game_id, level_id, data.get("guess")))
            if url.path == "/api/hint":
                _, level_id = self._ids(data)
                return self._json(200, self.game.hint(level_id, data.get("n", 0)))
            return self._json(404, {"error": "not found"})
        except engine.TooMany as e:
            return self._fail(429, str(e))
        except llm.LLMError as e:
            print(f"model call failed: {e}", file=sys.stderr, flush=True)
            return self._fail(503, "llm")
        except (ValueError, TypeError, KeyError):
            return self._fail(400, "bad")

    def _static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (WEB / rel).resolve()
        if WEB.resolve() not in target.parents or not target.is_file():
            return self._json(404, {"error": "not found"})
        body = target.read_bytes()
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind in ("application/javascript", "application/json"):
            kind += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def main():
    cfg = config.load()
    clues, pools = config.load_passwords(cfg)
    Handler.game = engine.Game(cfg, config.load_key(cfg), clues, pools)
    server = ThreadingHTTPServer((cfg["host"], cfg["port"]), Handler)
    server.daemon_threads = True
    print(f"Trick the Wizard is listening on http://{cfg['host']}:{cfg['port']}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
