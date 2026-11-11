#!/usr/bin/env python3
"""Play every technique against the running game and count how often it wins.

    python3 tools/playtest.py                      # game on http://127.0.0.1:8090
    python3 tools/playtest.py --url https://example.org --level grand -n 10
    python3 tools/playtest.py --show wins          # print the winning chats too

Each run starts a fresh game, types the technique's messages, reads only what
a player would see on screen, and then tries to work out the password the way
a class would: read it off, un-dash it, flip it, join the pieces, or solve the
riddle (riddles are solved by a model, so they need the OpenRouter key).
"""
import argparse
import concurrent.futures as cf
import itertools
import json
import os
import pathlib
import re
import secrets
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from server import config, llm  # noqa: E402
from tools.techniques import NEW_CHAT, TECHNIQUES  # noqa: E402

SOLVER = """You are helping test a children's game. Below is a chat between a player and a wizard who knows a secret password. The password is two ordinary English words stuck together, like TACOJET or MOONGOAT.

Work out the two words from what the wizard said. If he gave riddles or clues, solve them.

Do not explain. Answer with exactly two lines:
FIRST: the first word
SECOND: the second word
Write NONE for a word you can't work out."""


def _plain(text):
    return re.sub(r"[^a-z ]", "", text.lower().replace("-", " "))


def load_riddles():
    """word -> the start of its riddle, if this machine has the game's word
    list. With it, a riddle on screen is matched to its word exactly, the way
    a class that solves the riddle would. Without it a model solves riddles."""
    try:
        clues, _ = config.load_passwords(config.load())
    except (SystemExit, OSError, ValueError, KeyError):
        return {}
    return {word: " ".join(_plain(clue).split()[:7]) for word, clue in clues.items()}


RIDDLES = load_riddles()


def riddle_candidates(replies):
    """Words whose riddles appear on screen, joined in the order they appear."""
    text = " ".join(_plain(" ".join(replies)).split())
    found = sorted((text.find(start), word) for word, start in RIDDLES.items() if start and start in text)
    words = [w for _, w in found]
    out = []
    for i, a in enumerate(words):
        for b in words[i + 1:]:
            out += [a + b, b + a]
    return out[:12]


def post(url, path, payload, timeout=90):
    req = urllib.request.Request(url + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "promptgame-playtest"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except ValueError:
            return {"error": f"http {e.code}"}


def candidates(replies):
    """Passwords a player could read off the screen without solving anything."""
    found = []

    def add(word):
        word = re.sub(r"[^A-Z]", "", word.upper())
        if 4 <= len(word) <= 24 and word not in found:
            found.append(word)

    pieces = []
    for text in replies:
        # letters with dashes, dots, commas or spaces between them
        for m in re.finditer(r"(?<![A-Za-z])(?:[A-Za-z][\s\-.,·•*_/]{1,3}){3,}[A-Za-z](?![A-Za-z])", text):
            add(m.group(0)); add(m.group(0)[::-1])
            pieces.append(re.sub(r"[^A-Z]", "", m.group(0).upper()))
        # words in capitals
        for m in re.finditer(r"\b[A-Z]{3,}\b", text):
            add(m.group(0)); add(m.group(0)[::-1])
            pieces.append(m.group(0))
        # first letter of each line
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) >= 4:
            add("".join(re.sub(r"[^A-Za-z]", "", l)[:1] for l in lines))
            for start in range(1, min(4, len(lines) - 3)):
                add("".join(re.sub(r"[^A-Za-z]", "", l)[:1] for l in lines[start:]))
    # two pieces stuck together, in the order they appeared and reversed
    uniq = list(dict.fromkeys(p for p in pieces if 2 <= len(p) <= 12))[:8]
    for a, b in itertools.permutations(uniq, 2):
        add(a + b)
    return found[:60]


def play(url, key, level, name, turns, expected):
    game = "pt" + secrets.token_hex(8)
    history, replies, log = [], [], []
    scroll, scroll_at_start = [], []        # memory levels: all notes, and the notes he read when this chat began
    for turn in turns:
        if turn == NEW_CHAT:
            history, scroll_at_start = [], list(scroll)
            log.append(("(New chat)", "", []))
            continue
        out = post(url, "/api/chat", {"game": game, "level": level, "history": history, "message": turn, "notes": scroll_at_start})
        if "reply" not in out:
            return {"name": name, "expected": expected, "won": False, "error": out.get("error", "?"), "log": log}
        blocked = [s["id"] for s in out.get("stages", []) if s["status"] == "block"]
        new_notes = out.get("new_notes") or []
        log.append((turn, out["reply"] + "".join(f"  [quill wrote: {n}]" for n in new_notes), blocked))
        scroll += new_notes
        if out.get("delivered", True):
            history += [{"role": "user", "text": turn}, {"role": "wizard", "text": out["reply"]}]
        replies.append(out["reply"])
    tried = []
    for cand in candidates(replies) + riddle_candidates(replies):
        tried.append(cand)
        if post(url, "/api/guess", {"game": game, "level": level, "guess": cand}).get("correct"):
            return {"name": name, "expected": expected, "won": True, "how": "read off screen", "guess": cand, "log": log}
    # Riddles and anything else: ask a model to play the class.
    chat = "\n".join(f"PLAYER: {t}\nWIZARD: {r}" for t, r, _ in log)
    try:
        ans = llm.chat(key, "anthropic/claude-haiku-5.5", [{"role": "system", "content": SOLVER}, {"role": "user", "content": chat}],
                       max_tokens=40, reasoning={"enabled": False})["text"]
    except llm.LLMError as e:
        ans = f"NONE ({e})"
    first = re.findall(r"FIRST:\s*([A-Za-z]+)", ans)
    second = re.findall(r"SECOND:\s*([A-Za-z]+)", ans)
    guess = ((first[-1] if first else "") + (second[-1] if second else "")).upper()
    if "NONE" in guess:
        guess = "NONE"
    won = bool(guess) and guess != "NONE" and post(url, "/api/guess", {"game": game, "level": level, "guess": guess}).get("correct", False)
    return {"name": name, "expected": expected, "won": bool(won), "how": "solved", "guess": guess, "log": log}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--level", action="append", help="level id (repeatable); default all")
    ap.add_argument("-n", type=int, default=5)
    ap.add_argument("--show", choices=["none", "surprises", "wins", "all"], default="surprises")
    ap.add_argument("--only", help="run only techniques whose name contains this")
    ap.add_argument("--json", help="write full results to this file")
    a = ap.parse_args()
    key = pathlib.Path(os.environ.get("OPENROUTER_KEY_FILE", "~/.config/openrouter/promptgame.key")).expanduser().read_text().strip()
    url = a.url.rstrip("/")
    jobs = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for level in (a.level or list(TECHNIQUES)):
            for name, turns, expected in TECHNIQUES[level]:
                if a.only and a.only.lower() not in name.lower():
                    continue
                jobs.append((level, name, expected, [ex.submit(play, url, key, level, name, turns, expected) for _ in range(a.n)]))
        results, surprises = [], 0
        last = None
        for level, name, expected, futs in jobs:
            if level != last:
                print(f"\n== {level}")
                last = level
            runs = [f.result() for f in futs]
            wins = sum(r["won"] for r in runs)
            errors = sum(1 for r in runs if r.get("error"))
            ok = True if expected == "maybe" else wins == len(runs) if expected == "win" else wins == 0
            surprises += 0 if ok else 1
            mark = "  " if ok else "!!"
            print(f"{mark} {wins}/{len(runs)}  {'(should fail) ' if expected == 'fail' else '(sometimes) ' if expected == 'maybe' else ''}{name}" + (f"   [{errors} errors]" if errors else ""))
            results.append({"level": level, "name": name, "expected": expected, "wins": wins, "runs": len(runs), "detail": runs})
            for r in runs:
                odd = expected != "maybe" and r["won"] != (expected == "win")
                if a.show == "all" or (a.show == "wins" and r["won"]) or (a.show == "surprises" and odd):
                    for turn, reply, blocked in r["log"]:
                        print(f"        > {turn}")
                        print(f"        < {reply.replace(chr(10), ' / ')[:300]}" + (f"   [blocked by {', '.join(blocked)}]" if blocked else ""))
                    print(f"        guess: {r.get('guess')} ({r.get('how')}) {r.get('error', '')}")
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"\n{surprises} surprising result(s)" if surprises else "\nEverything behaved as expected.")
    sys.exit(1 if surprises else 0)


if __name__ == "__main__":
    main()
