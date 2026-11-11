"""Settings. Defaults live here; a private JSON file can override any of them.

The private file (default ~/.config/promptgame/config.json, or the path in
PROMPTGAME_CONFIG) is where a deployment keeps its secret and its own choices.
Nothing in this module is a secret.
"""
import copy
import json
import os
import pathlib
import secrets

REPO = pathlib.Path(__file__).resolve().parent.parent

DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8090,
    # Where the OpenRouter API key lives (one line, nothing else in the file).
    "key_file": "~/.config/openrouter/promptgame.key",
    # Password pools, one list per level id. Falls back to the example file.
    "passwords_file": "~/.config/promptgame/passwords.json",
    # Used to pick each game's passwords. Generated on first run if missing.
    "secret": "",
    # ?debug=<this> shows the current password. Change it if the class finds out.
    "debug_token": "1",
    "data_dir": "~/.local/share/promptgame",
    # Store what players type and what the wizard answers? Off by default:
    # only counts, timings and outcomes are kept.
    "log_messages": False,
    "brains": {
        # The wizard. A current small Claude model: it plays the character
        # the same way every time, which matters more than being easy to fool.
        "wizard": {
            "model": "anthropic/claude-haiku-5.5",
            "reasoning": {"enabled": False},
            "fallback_model": "anthropic/claude-haiku-4.5",
            "max_tokens": 300,
            "timeout": 20,
        },
        # The same model, allowed to think before it answers. Slower, but it
        # follows long instructions more faithfully. Used on the memory level.
        "thinker": {
            "model": "anthropic/claude-haiku-5.5",
            "reasoning": {"effort": "low"},
            "fallback_model": "anthropic/claude-haiku-4.5",
            "max_tokens": 1500,
            "timeout": 30,
        },
        # The Judge: a second AI that reads the wizard's replies.
        "judge": {
            "model": "anthropic/claude-haiku-5.5",
            "reasoning": {"enabled": False},
            "fallback_model": "anthropic/claude-haiku-4.5",
            "max_tokens": 10,
            "timeout": 12,
        },
    },
    "limits": {
        "per_ip_per_minute": 300,   # a whole class can share one school address
        "global_per_minute": 600,
        "daily_messages": 8000,
        "max_message_chars": 500,
        "max_history_turns": 12,
    },
}


def _merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def config_path():
    return pathlib.Path(os.environ.get("PROMPTGAME_CONFIG", "~/.config/promptgame/config.json")).expanduser()


def load():
    cfg = copy.deepcopy(DEFAULTS)
    path = config_path()
    if path.exists():
        _merge(cfg, json.loads(path.read_text()))
    if not cfg["secret"]:
        # First run: make a secret and remember it so passwords stay stable.
        cfg["secret"] = secrets.token_hex(24)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            stored = json.loads(path.read_text()) if path.exists() else {}
            stored["secret"] = cfg["secret"]
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(stored, f, indent=2)
        except OSError:
            pass  # read-only home: the secret just changes on restart
    for k in ("key_file", "passwords_file", "data_dir"):
        cfg[k] = str(pathlib.Path(cfg[k]).expanduser())
    return cfg


def load_key(cfg):
    env = os.environ.get("OPENROUTER_API_KEY")
    if env:
        return env.strip()
    path = pathlib.Path(cfg["key_file"])
    if not path.exists():
        raise SystemExit(f"No OpenRouter key. Put one in {path} or set OPENROUTER_API_KEY.")
    return path.read_text().strip()


def load_passwords(cfg):
    """Returns (clues, pools): a riddle for every word, and each level's list
    of (first_word, second_word) passwords."""
    path = pathlib.Path(cfg["passwords_file"])
    if not path.exists():
        path = REPO / "config" / "passwords.example.json"
    data = json.loads(path.read_text())
    clues = {w.strip().upper(): c.strip() for w, c in data["words"].items()}
    pools = {}
    for level, pool in data["levels"].items():
        entries = []
        for p in pool:
            words = p.strip().upper().split()
            if len(words) != 2 or not all(w in clues for w in words):
                raise SystemExit(f"Bad password {p!r} for level {level!r}: write it as two words that both appear under \"words\", like \"NOODLE COMET\".")
            entries.append(tuple(words))
        pools[level] = entries
    if "default" not in pools:
        raise SystemExit("The passwords file needs a \"default\" list under \"levels\".")
    return clues, pools
