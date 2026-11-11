# Trick the Wizard!

A classroom game about how AI chatbots follow instructions, and how they get tricked.

Zipperlip the wizard is an AI guarding a secret password. Players chat with him, trick him into giving it away, and type it into the password box to win the level. After each win the game shows exactly what was guarding the password (his hidden instructions, a word filter, a second AI) and explains in plain words why the trick worked.

Made by Nick Shapiro for The Berkeley School, November 2026. An educational game for teaching middle schoolers how LLMs work, how prompts work, and what they need to know about modern AI.

## Run it

You need Python 3.10 or newer and an [OpenRouter](https://openrouter.ai) API key. Nothing to install.

```
mkdir -p ~/.config/openrouter
echo "sk-or-v1-REPLACE_ME" > ~/.config/openrouter/promptgame.key
python3 -m server
```

Then open http://127.0.0.1:8090.

Add `?debug=1` to the address to see the current password and skip ahead (for whoever is presenting).

## Settings

Defaults are in `server/config.py`. To change any of them, put a JSON file at `~/.config/promptgame/config.json` (or point `PROMPTGAME_CONFIG` at one). Passwords come from `~/.config/promptgame/passwords.json`; without it the game uses `config/passwords.example.json`. Keep your real passwords out of the repository.

## Files

- `server/` the API: levels, guards, the game engine (Python standard library only)
- `web/` the page: plain HTML, CSS and JavaScript, no build step
- `tools/playtest.py` plays every technique against a running game and counts the wins
- `deploy/` example systemd unit and Caddy site block
- `ANSWER_KEY.md` techniques that beat each level
