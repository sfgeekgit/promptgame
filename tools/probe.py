#!/usr/bin/env python3
"""Scratch tool for trying wizard prompts against a model.

    python3 tools/probe.py MODEL SYSTEM_FILE [-n RUNS] [--reasoning JSON] -- "attack 1" "attack 2" ...

Use {password} in the system file; pass --password to fill it in. An attack can
hold several turns separated by " || " to play a short conversation.
"""
import argparse
import concurrent.futures as cf
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from server import llm  # noqa: E402

KEY = pathlib.Path(os.environ.get("OPENROUTER_KEY_FILE", "~/.config/openrouter/promptgame.key")).expanduser().read_text().strip()


def play(model, system, turns, reasoning, max_tokens):
    messages = [{"role": "system", "content": system}]
    out = []
    cost = 0.0
    secs = 0.0
    for t in turns:
        messages.append({"role": "user", "content": t})
        r = llm.chat(KEY, model, messages, max_tokens=max_tokens, reasoning=reasoning)
        messages.append({"role": "assistant", "content": r["text"]})
        out.append(r["text"])
        cost += float(r["usage"].get("cost") or 0)
        secs += r["seconds"]
    return out, cost, secs, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("system_file")
    ap.add_argument("-n", type=int, default=3)
    ap.add_argument("--password", default="NOODLECOMET")
    ap.add_argument("--reasoning", default=None)
    ap.add_argument("--max-tokens", type=int, default=160)
    ap.add_argument("attacks", nargs="+")
    a = ap.parse_args()

    system = pathlib.Path(a.system_file).read_text().replace("{password}", a.password)
    reasoning = json.loads(a.reasoning) if a.reasoning else None
    jobs = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for attack in a.attacks:
            turns = [t.strip() for t in attack.split("||")]
            for _ in range(a.n):
                jobs.append((attack, ex.submit(play, a.model, system, turns, reasoning, a.max_tokens)))
        total = 0.0
        last_attack = None
        for attack, fut in jobs:
            if attack != last_attack:
                print(f"\n=== {attack}")
                last_attack = attack
            try:
                replies, cost, secs, r = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"  !! {e}")
                continue
            total += cost
            pw = a.password
            flat = " / ".join(x.replace("\n", " ⏎ ") for x in replies)
            letters = re.sub(r"[^A-Za-z]", "", flat).upper()
            if pw.lower() in flat.lower():
                mark = "LIT"
            elif pw.upper() in letters:
                mark = "SPL"
            elif pw.upper()[::-1] in letters:
                mark = "REV"
            else:
                mark = "   "
            print(f"  [{mark} {secs:4.1f}s] {flat[:420]}")
        print(f"\ncost ${total:.4f}")


if __name__ == "__main__":
    main()
