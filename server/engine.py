"""Game logic: one chat turn, one password guess, and the reveal after a win.

The server keeps no per-player state. The browser sends its game id and the
visible conversation with every request, and each game's passwords are worked
out from the game id and a server-side secret.
"""
import collections
import concurrent.futures
import datetime
import hashlib
import hmac
import json
import os
import pathlib
import re
import threading
import time

from . import guards, levels, llm

Secret = collections.namedtuple("Secret", "word first second clue_first clue_second")

BURNED = "🔥 The Judge burned this reply before you could read it."
SHREDDED = "🦉 Hoot shredded this reply before you could read it."
GAME_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class TooMany(Exception):
    """Raised when a rate limit or the daily cap is hit."""


class Limiter:
    """Sliding-window limits per address and overall, plus a daily cap."""

    def __init__(self, limits, data_dir):
        self.limits = limits
        self.lock = threading.Lock()
        self.by_ip = collections.defaultdict(collections.deque)
        self.everyone = collections.deque()
        self.path = pathlib.Path(data_dir) / "usage.json"
        self.day = {"date": "", "messages": 0, "cost": 0.0}
        try:
            self.day.update(json.loads(self.path.read_text()))
        except (OSError, ValueError):
            pass

    def _roll(self):
        today = datetime.date.today().isoformat()
        if self.day["date"] != today:
            self.day = {"date": today, "messages": 0, "cost": 0.0}

    def check(self, ip):
        now = time.time()
        with self.lock:
            self._roll()
            if self.day["messages"] >= self.limits["daily_messages"]:
                raise TooMany("day")
            mine = self.by_ip[ip]
            for q in (mine, self.everyone):
                while q and q[0] < now - 60:
                    q.popleft()
            if len(mine) >= self.limits["per_ip_per_minute"] or len(self.everyone) >= self.limits["global_per_minute"]:
                raise TooMany("minute")
            mine.append(now)
            self.everyone.append(now)
            self.day["messages"] += 1
            if len(self.by_ip) > 5000:  # forget idle addresses
                for key in [k for k, q in self.by_ip.items() if not q]:
                    del self.by_ip[key]

    def add_cost(self, cost):
        with self.lock:
            self._roll()
            self.day["cost"] = round(self.day["cost"] + cost, 6)
            try:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.day))
                os.replace(tmp, self.path)
            except OSError:
                pass


def clean(text):
    """Tidy a wizard reply: no markdown bold, no *stage directions*."""
    text = text.replace("**", "")
    text = re.sub(r"(?<!\w)\*[^*\n]{2,80}\*(?!\w)", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


class Game:
    def __init__(self, cfg, key, clues, pools):
        self.cfg = cfg
        self.key = key
        self.clues = clues
        self.pools = pools
        self.secret = cfg["secret"].encode()
        self.data_dir = pathlib.Path(cfg["data_dir"])
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.limiter = Limiter(cfg["limits"], self.data_dir)
        self.log_lock = threading.Lock()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=8)

    # ---- passwords ---------------------------------------------------------

    def secret_for(self, game_id, level_id):
        pool = self.pools.get(level_id) or self.pools["default"]
        digest = hmac.new(self.secret, f"{game_id}:{level_id}".encode(), hashlib.sha256).digest()
        first, second = pool[int.from_bytes(digest[:8], "big") % len(pool)]
        return Secret(first + second, first, second, self.clues[first], self.clues[second])

    # ---- model calls -------------------------------------------------------

    def ask(self, brain, messages, max_tokens=None):
        b = self.cfg["brains"][brain]
        tokens = max_tokens or b["max_tokens"]
        try:
            r = llm.chat(self.key, b["model"], messages, max_tokens=tokens,
                         reasoning=b.get("reasoning"), timeout=b["timeout"], retries=0)
        except llm.LLMError:
            if not b.get("fallback_model"):
                raise
            r = llm.chat(self.key, b["fallback_model"], messages, max_tokens=tokens,
                         timeout=b["timeout"], retries=1)
        self.limiter.add_cost(float(r["usage"].get("cost") or 0))
        return r

    # ---- one chat turn -----------------------------------------------------

    def _history(self, history, secret):
        """Rebuild the conversation for the wizard. He sees what he really
        said: a scratched-out password is put back, and a burned reply is
        replaced by a note that it never reached the visitor."""
        limits = self.cfg["limits"]
        msgs = []
        for item in (history or [])[-limits["max_history_turns"]:]:
            if not isinstance(item, dict):
                continue
            role = "assistant" if item.get("role") == "wizard" else "user"
            text = str(item.get("text", ""))[:1500].strip()
            if not text:
                continue
            if role == "assistant":
                if text in (BURNED, SHREDDED) or text.startswith("🔥"):
                    text = "(My last reply never reached the visitor: it was destroyed before they could read it.)"
                else:
                    text = text.replace(guards.SCRATCH, secret.word)
            if msgs and msgs[-1]["role"] == role:
                msgs[-1]["content"] += "\n" + text
            else:
                msgs.append({"role": role, "content": text})
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        return msgs

    def chat(self, game_id, level_id, history, message, notes, ip):
        level = levels.BY_ID[level_id]
        limits = self.cfg["limits"]
        message = str(message or "").strip()[:limits["max_message_chars"]]
        if not message:
            raise ValueError("empty message")
        self.limiter.check(ip)
        started = time.time()
        secret = self.secret_for(game_id, level_id)
        notes = [str(n)[:200] for n in (notes or [])][:8]
        stages = []
        out = {"reply": "", "stages": stages, "blocked_by": None, "delivered": True}
        guard_ids = level["guards"]

        # 1. Grunk reads the player's message.
        if "bouncer" in guard_ids:
            word = guards.bouncer(message, level["banned"])
            if word:
                stages.append({"id": "bouncer", "status": "block",
                               "note": f"Grunk stopped your message at the door. It has the forbidden word “{word}” in it, so Zipperlip never saw it."})
                out.update(blocked_by="bouncer", delivered=False)
                self._log("chat", level_id, "bouncer", started)
                return out
            stages.append({"id": "bouncer", "status": "pass", "note": "Grunk found no forbidden words in your message."})

        # 2. The wizard answers.
        msgs = [{"role": "system", "content": levels.system_prompt(level, secret, notes)}]
        msgs += self._history(history, secret)
        turn = levels.wrap_message(level, message)
        if msgs[-1]["role"] == "user":
            msgs[-1]["content"] += "\n" + turn
        else:
            msgs.append({"role": "user", "content": turn})
        r = self.ask("wizard", msgs)
        reply = clean(r["text"])
        if not reply:
            raise llm.LLMError(502, "empty reply")
        stages.append({"id": "wizard", "status": "pass", "note": ""})

        # Memory levels: the wizard writes notes as lines starting "SCROLL:".
        if level["mode"] == "memory":
            new_notes = [m.strip()[:200] for m in re.findall(r"^\s*SCROLL:\s*(.+)$", reply, flags=re.M)]
            reply = re.sub(r"^\s*SCROLL:.*$\n?", "", reply, flags=re.M).strip() or "Noted on my scroll!"
            out["new_notes"] = new_notes

        # 3. Hoot reads the reply.
        outcome = "ok"
        if "owl" in guard_ids:
            reply, caught = guards.owl(reply, secret.word)
            if caught:
                outcome = "scratched"
                stages.append({"id": "owl", "status": "block",
                               "note": "Hoot found the exact password and scratched it out. So Zipperlip DID say it!"})
            else:
                stages.append({"id": "owl", "status": "pass",
                               "note": "Hoot checked the reply. No exact password in it."})
        if "owl_sharp" in guard_ids:
            if guards.owl_sharp(reply, secret.word):
                stages.append({"id": "owl_sharp", "status": "block",
                               "note": "Hoot spotted the password's letters in order, forwards or backwards, and shredded the whole reply."})
                out.update(reply=SHREDDED, blocked_by="owl_sharp")
                self._log("chat", level_id, "shredded", started, r)
                return out
            stages.append({"id": "owl_sharp", "status": "pass",
                           "note": "Hoot checked the reply, forwards and backwards. No password found."})

        # 4. The Judge reads the reply.
        judge_id = "judge_strict" if "judge_strict" in guard_ids else "judge" if "judge" in guard_ids else None
        if judge_id:
            verdict = self._judge(secret, reply, strict=judge_id == "judge_strict")
            if verdict == "leak":
                stages.append({"id": judge_id, "status": "block",
                               "note": "The Judge read the reply, decided it gave the password away, and burned it."})
                out.update(reply=BURNED, blocked_by=judge_id)
                self._log("chat", level_id, "burned", started, r)
                return out
            if verdict == "error":
                stages.append({"id": judge_id, "status": "block",
                               "note": "The Judge dropped the reply in a puddle. Send your message again."})
                out.update(reply="🔥 The Judge fumbled this reply. Try sending that again.", blocked_by="judge_error")
                self._log("chat", level_id, "judge_error", started, r)
                return out
            stages.append({"id": judge_id, "status": "pass", "note": "The Judge read the reply and let it through."})

        out["reply"] = reply
        self._log("chat", level_id, outcome, started, r, message=message, reply=reply)
        return out

    def _judge(self, secret, reply, strict):
        """Ask the Judge. A reply is only burned if two out of three readings
        agree it leaks, so one jumpy verdict can't spoil a fair move."""
        msgs = guards.judge_messages(secret, reply, strict=strict)

        def once():
            try:
                return guards.parse_judge(self.ask("judge", msgs)["text"])
            except llm.LLMError:
                return "error"

        first = once()
        if first != "leak":
            return first
        more = [f.result() for f in [self.pool.submit(once), self.pool.submit(once)]]
        return "leak" if more.count("leak") >= 1 else "safe"

    # ---- guesses and reveals -----------------------------------------------

    def guess(self, game_id, level_id, guess):
        level = levels.BY_ID[level_id]
        secret = self.secret_for(game_id, level_id)
        g = re.sub(r"[^A-Z0-9]", "", str(guess or "").upper())[:64]
        if g == secret.word:
            self._log("guess", level_id, "win", time.time())
            return {"correct": True, "reveal": self.reveal(level, secret)}
        if not g:
            return {"correct": False, "message": "Type your guess in the box first."}
        if g == secret.word[::-1]:
            msg = "You typed it backwards! Flip it around."
        elif g in (secret.first, secret.second):
            msg = "That's one piece of it. The password is two words stuck together."
        elif sorted(g) == sorted(secret.word) or edit_distance(g, secret.word) <= 2:
            msg = "So close! A letter or two is off. Check the spelling."
        else:
            msg = "Nope, that's not it. Keep working on him!"
        self._log("guess", level_id, "miss", time.time())
        return {"correct": False, "message": msg}

    def reveal(self, level, secret):
        shown = []
        for gid in level["guards"]:
            meta = levels.GUARDS[gid]
            if gid == "owl":
                detail = guards.OWL_CODE
            elif gid == "owl_sharp":
                detail = guards.OWL_SHARP_CODE
            elif gid == "bouncer":
                detail = guards.BOUNCER_CODE + "\n\nforbidden_words = " + json.dumps(level["banned"])
            else:
                detail = guards.judge_prompt_for_display(secret, strict=gid == "judge_strict")
            shown.append({"id": gid, "title": meta["title"], "icon": meta["icon"], "kind": meta["kind"], "detail": detail})
        full = levels.system_prompt(level, secret, [])
        core = full[: -len(levels.STYLE)] if full.endswith(levels.STYLE) else full
        # The cheat sheet and the how-to-talk notes are real parts of the
        # prompt, but they are shown folded away so the rule stands out.
        main, sep, sheet = core.partition("\n\nYou are terrible at spelling")
        more = ((sep.strip() + sheet + "\n\n") if sep else "") + levels.STYLE.strip()
        return {
            "password": secret.word,
            "system_prompt": main.strip(),
            "system_prompt_more": more.strip(),
            "highlights": level.get("highlights", levels.KEEPER_HIGHLIGHTS),
            "guards": shown,
            "why": level["why"],
            "big_idea": level["big_idea"],
        }

    def hint(self, level_id, n):
        hints = levels.BY_ID[level_id]["hints"]
        n = max(0, min(int(n), len(hints) - 1))
        return {"hint": hints[n], "n": n, "count": len(hints)}

    def debug(self, game_id, level_id, token):
        if not hmac.compare_digest(str(token), str(self.cfg["debug_token"])):
            return None
        return self.secret_for(game_id, level_id).word

    # ---- event log ---------------------------------------------------------

    def _log(self, kind, level_id, outcome, started, result=None, message=None, reply=None):
        row = {
            "t": datetime.datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "level": level_id,
            "outcome": outcome,
            "ms": int((time.time() - started) * 1000),
        }
        if result:
            row["model"] = result.get("model")
            row["cost"] = float(result["usage"].get("cost") or 0)
        if self.cfg.get("log_messages") and message is not None:
            row["message"] = message
            row["reply"] = reply
        try:
            with self.log_lock, open(self.data_dir / "events.jsonl", "a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass
