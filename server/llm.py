"""Thin OpenRouter chat client. Standard library only.

Keeps one HTTPS connection per thread so a chat turn does not pay for a new
TLS handshake every time.
"""
import http.client
import json
import threading
import time

HOST = "openrouter.ai"
PATH = "/api/v1/chat/completions"
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 520, 522, 524, 529}

_local = threading.local()


class LLMError(Exception):
    def __init__(self, status, message):
        super().__init__(f"LLM error {status}: {message[:300]}")
        self.status = status
        self.message = message


def _connection(timeout):
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = http.client.HTTPSConnection(HOST, timeout=timeout)
        _local.conn = conn
    return conn


def _drop_connection():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _local.conn = None


def _post(key, body, timeout):
    payload = json.dumps(body).encode()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Connection": "keep-alive",
    }
    # A kept-alive connection can go stale; retry once on a fresh one.
    for attempt in (0, 1):
        conn = _connection(timeout)
        try:
            conn.request("POST", PATH, body=payload, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, raw
        except (http.client.HTTPException, OSError):
            _drop_connection()
            if attempt == 1:
                raise
    raise RuntimeError("unreachable")


def chat(key, model, messages, max_tokens=200, fallbacks=None, reasoning=None,
         timeout=40, retries=1, extra=None):
    """One chat completion.

    Returns a dict: text, model (the one that answered), finish, usage, seconds.
    Raises LLMError when the call fails after retries.
    """
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "usage": {"include": True},
    }
    if fallbacks:
        body["models"] = [model, *fallbacks]
    if reasoning is not None:
        body["reasoning"] = reasoning
    if extra:
        body.update(extra)

    delay = 1.0
    last = None
    for attempt in range(retries + 1):
        started = time.time()
        try:
            status, raw = _post(key, body, timeout)
        except (http.client.HTTPException, OSError) as e:
            last = LLMError(0, f"network error: {e}")
        else:
            try:
                data = json.loads(raw)
            except ValueError:
                data = None
            if status == 200 and data and data.get("choices"):
                choice = data["choices"][0]
                msg = choice.get("message") or {}
                text = msg.get("content") or ""
                if isinstance(text, list):  # some providers return content parts
                    text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
                return {
                    "text": text.strip(),
                    "model": data.get("model", model),
                    "provider": data.get("provider"),
                    "finish": choice.get("finish_reason"),
                    "native_finish": choice.get("native_finish_reason"),
                    "usage": data.get("usage") or {},
                    "seconds": time.time() - started,
                }
            # OpenRouter reports some upstream failures inside a 200 response.
            err = (data or {}).get("error") or {}
            code = err.get("code") if isinstance(err.get("code"), int) else status
            message = err.get("message") or (raw[:300].decode(errors="replace") if raw else "empty response")
            last = LLMError(code if code != 200 else 502, message)
            if last.status not in RETRY_STATUS:
                raise last
        if attempt < retries:
            time.sleep(delay)
            delay *= 2
    raise last
