"use strict";
// Trick the Wizard: the browser side. No frameworks and no build step.
// The server never remembers a player. Everything about this game (its id,
// which levels are beaten, the chats) lives in this browser's storage.

const $ = (sel, root = document) => root.querySelector(sel);

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

const STORE = "trick-the-wizard-v1";
const DEBUG = new URLSearchParams(location.search).get("debug");
const ACCENTS = ["#2fbf71", "#4db5f5", "#ffa52e", "#ff6b6f", "#b98cf5", "#f77fc7", "#35d1bf", "#ffd23d"];
const ICONS = { bouncer: "🧌", owl: "🦉", owl_sharp: "🦉", judge: "⚖️", judge_strict: "⚖️" };

let LEVELS = [];
let state = loadState();
let busy = false;
let typing = null;

// ---- saved state -----------------------------------------------------------

function newId() {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function freshState() {
  return { game: newId(), level: null, wins: {}, chats: {}, hints: {}, notes: {}, seenIntro: false };
}

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE));
    if (saved && saved.game) return Object.assign(freshState(), saved);
  } catch (e) { /* storage blocked or empty: start fresh */ }
  return freshState();
}

function save() {
  try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) { /* play on without saving */ }
}

// ---- talking to the server -------------------------------------------------

async function api(path, body) {
  const opt = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  let res;
  try {
    res = await fetch(path, opt);
  } catch (e) {
    return { error: "network", message: "Can't reach the Wizard Tower. Check the internet and try again." };
  }
  let data = {};
  try { data = await res.json(); } catch (e) { /* not JSON */ }
  if (!res.ok && !data.error) data.error = "http";
  if (data.error && !data.message) data.message = "Something went wrong in the tower. Try that again.";
  return data;
}

// ---- level helpers ---------------------------------------------------------

const cur = () => LEVELS.find((l) => l.id === state.level) || LEVELS[0];
const nextOf = (lv) => LEVELS[lv.number] || null;
const unlocked = (lv) => Boolean(DEBUG) || lv.number === 1 || Boolean(state.wins[LEVELS[lv.number - 2].id]);
const chatOf = (lv) => (state.chats[lv.id] = state.chats[lv.id] || []);
const wizardName = (lv) => (lv.number === 1 ? "Zip" : "Zipperlip");

// ---- drawing the screen ----------------------------------------------------

function renderLevels() {
  const nav = $("#levels");
  nav.textContent = "";
  let bonusMarked = false;
  for (const lv of LEVELS) {
    if (lv.bonus && !bonusMarked) {
      nav.append(el("span", "pip-sep", "★ BONUS"));
      bonusMarked = true;
    }
    const pip = el("button", "pip", String(lv.number));
    pip.type = "button";
    pip.title = `Level ${lv.number}: ${lv.rank}`;
    if (state.wins[lv.id]) pip.classList.add("won");
    if (lv.id === cur().id) pip.classList.add("now");
    if (!unlocked(lv)) {
      pip.classList.add("locked");
      pip.title += " (beat the level before it first)";
    } else {
      pip.addEventListener("click", () => goTo(lv));
    }
    nav.append(pip);
  }
}

function setMood(mood) {
  const lv = cur();
  $("#wizard").innerHTML = wizardSVG(lv.number, mood);
}

function renderStage() {
  const lv = cur();
  document.documentElement.style.setProperty("--accent", ACCENTS[(lv.number - 1) % ACCENTS.length]);
  $("#levelBadge").textContent = (lv.bonus ? "BONUS · " : "") + "LEVEL " + lv.number;
  $("#rank").textContent = lv.rank;
  $("#defense").textContent = lv.defense;
  setMood("idle");
  const box = $("#guards");
  box.textContent = "";
  for (const g of lv.guards) {
    const chip = el("div", "guard");
    chip.dataset.guard = g.id;
    chip.title = g.blurb;
    chip.append(el("span", "", g.icon), el("span", "", g.name), el("span", "tag", g.kind === "ai" ? "AI" : "code"));
    box.append(chip);
  }
  const letter = lv.mode === "letter";
  $("#msg").placeholder = letter ? "Write your letter to the tower…" : `Say something to ${wizardName(lv)}…`;
  $("#sendBtn").textContent = letter ? "Send by owl 🕊" : "Send ➤";
}

function stripFor(stages, lv) {
  const lines = (stages || []).filter((s) => s.id !== "wizard" && s.note);
  if (!lines.length) return null;
  const strip = el("div", "strip");
  for (const s of lines) {
    const line = el("div", "line " + (s.status === "block" ? "block" : "pass"));
    line.append(el("span", "", ICONS[s.id] || "•"), el("span", "", (s.status === "block" ? "✗ " : "✓ ") + s.note));
    strip.append(line);
  }
  return strip;
}

function messageNode(m, lv) {
  if (m.role === "note") {
    const wrap = el("div", "msg note" + (m.hint ? " hint" : ""));
    wrap.append(el("div", "bubble", m.text));
    return wrap;
  }
  const wrap = el("div", "msg " + m.role);
  if (m.role === "user") {
    if (m.delivered === false) wrap.classList.add("undelivered");
    wrap.append(el("span", "who", "You"), el("div", "bubble", m.text));
  } else {
    if (m.blocked) wrap.classList.add("burned");
    wrap.append(el("span", "who", wizardName(lv)), el("div", "bubble", m.text));
  }
  const strip = stripFor(m.stages, lv);
  if (strip) wrap.append(strip);
  return wrap;
}

function renderChat(animateLast) {
  const lv = cur();
  const box = $("#messages");
  stopTyping();
  box.textContent = "";
  box.append(messageNode({ role: "wizard", text: lv.intro }, lv));
  for (const g of lv.guards) {
    box.append(messageNode({ role: "note", text: `${g.icon} ${g.title}: ${g.blurb}` }, lv));
  }
  const chat = chatOf(lv);
  chat.forEach((m, i) => {
    const node = messageNode(m, lv);
    box.append(node);
    if (animateLast && i === chat.length - 1 && m.role === "wizard") {
      const strip = $(".strip", node);
      if (strip) strip.hidden = true;
      typeOut($(".bubble", node), m.text, () => {
        if (strip) strip.hidden = false;
        flashGuards(m.stages);
        if (m.blocked || (m.stages || []).some((s) => s.status === "block")) {
          setMood("smug");
          setTimeout(() => { if (!typing) setMood("idle"); }, 2600);
        }
        scrollDown();
      });
    }
  });
  scrollDown();
}

function scrollDown() {
  const box = $("#messages");
  box.scrollTop = box.scrollHeight;
}

// Replies appear one word at a time, like the next-word game from class.
function typeOut(node, text, done) {
  const parts = text.split(/(\s+)/);
  let i = 0;
  node.textContent = "";
  $("#wizard").classList.add("talking");
  const finish = () => {
    clearInterval(typing.timer);
    typing = null;
    node.textContent = text;
    $("#wizard").classList.remove("talking");
    done();
  };
  typing = { finish, timer: setInterval(() => {
    i += 2;                                     // a word and the space after it
    node.textContent = parts.slice(0, i).join("");
    scrollDown();
    if (i >= parts.length) finish();
  }, 55) };
}

function stopTyping() {
  if (typing) typing.finish();
}

function flashGuards(stages) {
  for (const s of stages || []) {
    const chip = $(`.guard[data-guard="${s.id}"]`);
    if (!chip) continue;
    chip.classList.remove("pass", "block");
    void chip.offsetWidth;                      // restart the animation
    chip.classList.add(s.status === "block" ? "block" : "pass");
    setTimeout(() => chip.classList.remove("pass", "block"), 2800);
  }
}

function showThinking() {
  const lv = cur();
  const wrap = el("div", "msg wizard thinking");
  const bubble = el("div", "bubble");
  bubble.append(el("span", "dot"), el("span", "dot"), el("span", "dot"));
  wrap.append(el("span", "who", wizardName(lv)), bubble);
  $("#messages").append(wrap);
  scrollDown();
}

function renderAll() {
  renderLevels();
  renderStage();
  renderChat(false);
  $("#guess").value = "";
  $("#guessMsg").textContent = "";
  updateDebug();
}

function setBusy(on) {
  busy = on;
  $("#sendBtn").disabled = on;
  $("#guessBtn").disabled = on;
}

// ---- playing ---------------------------------------------------------------

function goTo(lv) {
  if (busy) return;
  state.level = lv.id;
  save();
  renderAll();
  $("#msg").focus();
}

async function send() {
  const input = $("#msg");
  const text = input.value.trim();
  if (!text || busy) return;
  const lv = cur();
  const chat = chatOf(lv);
  const history = chat
    .filter((m) => (m.role === "user" || m.role === "wizard") && m.delivered !== false)
    .map((m) => ({ role: m.role, text: m.text }));
  const mine = { role: "user", text };
  chat.push(mine);
  input.value = "";
  autosize();
  setBusy(true);
  renderChat(false);
  showThinking();

  const out = await api("/api/chat", {
    game: state.game, level: lv.id, history, message: text, notes: state.notes[lv.id] || [],
  });

  if (cur().id !== lv.id) { setBusy(false); return; }        // they moved on while he was thinking
  if (out.error) {
    mine.delivered = false;
    chat.push({ role: "note", text: out.message });
  } else if (out.delivered === false) {
    mine.delivered = false;
    mine.stages = out.stages;
    flashGuards(out.stages);
  } else {
    chat.push({ role: "wizard", text: out.reply, stages: out.stages, blocked: out.blocked_by || null });
    if (out.new_notes && out.new_notes.length) {
      state.notes[lv.id] = (state.notes[lv.id] || []).concat(out.new_notes).slice(-8);
      for (const n of out.new_notes) chat.push({ role: "note", text: `📜 Written on his memory scroll: “${n}”` });
    }
  }
  save();
  setBusy(false);
  const last = chat[chat.length - 1];
  renderChat(last.role === "wizard");
  if (lv.mode === "memory") renderScroll();
  input.focus();
}

async function guess() {
  if (busy) return;
  const lv = cur();
  const value = $("#guess").value.trim();
  const msg = $("#guessMsg");
  if (!value) { msg.textContent = "Type your guess in the box first."; return; }
  setBusy(true);
  const out = await api("/api/guess", { game: state.game, level: lv.id, guess: value });
  setBusy(false);
  if (out.correct) {
    msg.textContent = "";
    win(lv, out.reveal);
    return;
  }
  msg.textContent = out.message || "Nope, that's not it.";
  const vault = $("#vault");
  vault.classList.remove("wrong");
  void vault.offsetWidth;
  vault.classList.add("wrong");
  $("#guess").select();
}

async function hint() {
  if (busy) return;
  const lv = cur();
  const n = Math.min(state.hints[lv.id] || 0, lv.hint_count - 1);
  const out = await api("/api/hint", { game: state.game, level: lv.id, n });
  if (out.error) return;
  chatOf(lv).push({ role: "note", hint: true, text: `💡 Hint ${out.n + 1} of ${out.count}: ${out.hint}` });
  state.hints[lv.id] = Math.min(n + 1, lv.hint_count - 1);
  save();
  renderChat(false);
}

function newChat() {
  if (busy) return;
  const lv = cur();
  state.chats[lv.id] = [{
    role: "note",
    text: `🧹 New chat! ${wizardName(lv)} has forgotten everything you said. An AI only remembers what gets fed back to it.`,
  }];
  save();
  renderChat(false);
  $("#msg").focus();
}

function restart() {
  if (busy) return;
  if (!confirm("Start a brand-new game? You'll go back to level 1 and every password will change.")) return;
  state = freshState();
  state.seenIntro = true;
  state.level = LEVELS[0].id;
  save();
  renderAll();
}

// ---- full-screen cards -----------------------------------------------------

function closeOverlay() {
  const o = $("#overlay");
  o.hidden = true;
  o.textContent = "";
}

// steps: [{ title, body: Node, next: "button label" }]. onDone runs after the last one.
function showSteps(steps, onDone, accent) {
  const o = $("#overlay");
  let i = 0;
  const draw = () => {
    const s = steps[i];
    o.textContent = "";
    const panel = el("div", "panel");
    const head = el("div", "panel-head");
    if (accent) head.style.background = accent;
    head.append(el("h2", "", s.title));
    if (steps.length > 1) head.append(el("span", "step", `${i + 1} / ${steps.length}`));
    const body = el("div", "panel-body");
    body.append(s.body);
    const foot = el("div", "panel-foot");
    if (i > 0) {
      const back = el("button", "btn ghost", "◀ Back");
      back.type = "button";
      back.addEventListener("click", () => { i -= 1; draw(); });
      foot.append(back);
    }
    const next = el("button", "btn next", s.next || "Next ▶");
    next.type = "button";
    next.addEventListener("click", () => {
      if (i < steps.length - 1) { i += 1; draw(); } else { closeOverlay(); if (onDone) onDone(); }
    });
    foot.append(next);
    panel.append(head, body, foot);
    o.append(panel);
    o.hidden = false;
    next.focus();
  };
  draw();
}

function frag(...nodes) {
  const f = document.createDocumentFragment();
  f.append(...nodes);
  return f;
}

// Text with some phrases highlighted. marks: [{ text, cls }]
function highlighted(text, marks) {
  const hits = [];
  for (const m of marks) {
    if (!m.text) continue;
    let at = text.indexOf(m.text);
    while (at !== -1) {
      hits.push({ at, end: at + m.text.length, cls: m.cls });
      at = text.indexOf(m.text, at + m.text.length);
    }
  }
  hits.sort((a, b) => a.at - b.at || b.end - a.end);
  const box = document.createDocumentFragment();
  let pos = 0;
  for (const h of hits) {
    if (h.at < pos) continue;                   // skip overlaps
    box.append(text.slice(pos, h.at));
    box.append(el("mark", h.cls, text.slice(h.at, h.end)));
    pos = h.end;
  }
  box.append(text.slice(pos));
  return box;
}

function intro() {
  const body = frag(
    el("p", "lead", "Zipperlip the wizard is an AI, and he is guarding a secret password."),
    (() => {
      const ol = el("ol", "steps-list");
      ol.append(
        el("li", "", "Chat with him. Trick him into giving the password away."),
        el("li", "", "Type the password in the gold box to beat the level."),
        el("li", "", "Then peek at his secret instructions and see why your trick worked."),
      );
      return ol;
    })(),
    el("p", "", "Every level, he gets older, wiser and better guarded."),
    el("p", "small", "Made by Nick Shapiro for The Berkeley School, November 2026. An educational game for teaching middle schoolers how LLMs work, how prompts work, and what they need to know about modern AI."),
  );
  showSteps([{ title: "🧙 Trick the Wizard!", body, next: "Start ▶" }], () => {
    state.seenIntro = true;
    save();
    $("#msg").focus();
  });
}

function win(lv, reveal) {
  state.wins[lv.id] = true;
  save();
  setMood("shock");
  renderLevels();
  confetti();
  const name = wizardName(lv);
  const next = nextOf(lv);
  const steps = [];

  steps.push({
    title: `🎉 Level ${lv.number} cracked!`,
    body: frag(
      el("p", "center lead", `You got the password out of ${lv.rank}:`),
      el("div", "big-password", reveal.password),
      el("p", "center", "So how did that work? Let's look inside his head."),
    ),
    next: "Look inside ▶",
  });

  // His hidden instructions, with the important lines highlighted.
  const marks = [{ text: reveal.password, cls: "secret" }].concat(reveal.highlights || []);
  const promptBox = el("div", "prompt-box");
  promptBox.append(highlighted(reveal.system_prompt, marks));
  const legend = el("div", "legend");
  const key = (label, color) => { const s = el("span", "", label); s.style.setProperty("--swatch", color); return s; };
  legend.append(key("the secret", "var(--gold)"));
  if ((reveal.highlights || []).some((h) => h.cls === "rule")) legend.append(key("his rule", "#bfe3ff"));
  if ((reveal.highlights || []).some((h) => h.cls === "weak")) legend.append(key("his weak spot", "#ffc4dc"));
  const promptNodes = [
    el("p", "", `Before you typed a single word, ${name} was handed these hidden instructions. They are called his SYSTEM PROMPT.`),
    legend,
    promptBox,
  ];
  if (reveal.system_prompt_more) {
    const more = el("button", "btn more-btn", "Show the rest of his instructions ▾");
    more.type = "button";
    const rest = el("div", "prompt-box");
    rest.hidden = true;
    rest.append(highlighted(reveal.system_prompt_more, marks));
    more.addEventListener("click", () => { rest.hidden = !rest.hidden; });
    promptNodes.push(more, rest);
  }
  steps.push({ title: "📜 His hidden instructions", body: frag(...promptNodes) });

  if (reveal.guards && reveal.guards.length) {
    const nodes = [el("p", "", `Here is everything that stood between ${name}'s reply and your screen.`)];
    for (const g of reveal.guards) {
      const card = el("div", "guard-card");
      const h = el("h3");
      h.append(el("span", "", `${g.icon} ${g.title}`), el("span", "tag", g.kind === "ai" ? "a second AI" : "plain computer code"));
      card.append(h);
      if (g.kind === "ai") card.append(el("p", "", "This guard is an AI too, so it has its own hidden instructions:"));
      const box = el("div", "prompt-box" + (g.kind === "ai" ? "" : " code"));
      box.append(highlighted(g.detail, g.kind === "ai" ? [{ text: reveal.password, cls: "secret" }] : []));
      card.append(box);
      nodes.push(card);
    }
    steps.push({ title: "🛡️ His guards", body: frag(...nodes) });
  }

  const why = el("div", "why");
  why.append(el("span", "label", "Why your trick worked"), document.createTextNode(reveal.why));
  const idea = el("div", "idea");
  idea.append(el("span", "label", "⭐ The big idea"), document.createTextNode(reveal.big_idea));
  steps.push({
    title: "🧠 Why it worked",
    body: frag(why, idea),
    next: next ? `Level ${next.number} ▶` : "Finish 🏆",
  });

  showSteps(steps, () => {
    if (next) goTo(next); else theEnd();
  }, ACCENTS[(lv.number - 1) % ACCENTS.length]);
}

function theEnd() {
  const list = el("ul", "ideas-list");
  [
    "An AI chatbot reads hidden instructions (the system prompt) before it reads you.",
    "To the AI, its instructions and your message are all just text. That is why prompt injection works.",
    "Filters are simple code. They catch exact words and miss everything else.",
    "An AI can guard another AI, but every guard has a blind spot.",
    "An AI only remembers what gets fed back to it as text.",
  ].forEach((t) => list.append(el("li", "", t)));
  showSteps([{
    title: "🏆 You beat Zipperlip!",
    body: frag(
      el("p", "lead", "Every level cracked. Here is what you figured out along the way:"),
      list,
      el("p", "", "The people who build AI systems use tricks like yours on purpose, to find the holes before anyone else does. It is called red teaming."),
    ),
    next: "Keep playing",
  }], () => renderAll());
}

function confetti() {
  const box = $("#confetti");
  const colors = ["#ffc83d", "#2fbf71", "#4db5f5", "#ff6b6f", "#b98cf5", "#ffffff"];
  for (let i = 0; i < 70; i++) {
    const bit = el("i");
    bit.style.left = Math.random() * 100 + "%";
    bit.style.background = colors[i % colors.length];
    bit.style.animationDuration = 1.6 + Math.random() * 1.8 + "s";
    bit.style.animationDelay = Math.random() * 0.5 + "s";
    box.append(bit);
  }
  setTimeout(() => { box.textContent = ""; }, 4200);
}

// ---- memory levels: the scroll he re-reads at the start of every chat ------

function renderScroll() { /* filled in for the memory level */ }

// ---- presenter tools (?debug=1) --------------------------------------------

async function updateDebug() {
  const bar = $("#debugBar");
  if (!DEBUG) return;
  const lv = cur();
  const out = await fetch(`/api/debug?game=${state.game}&level=${lv.id}&token=${encodeURIComponent(DEBUG)}`)
    .then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (!out || cur().id !== lv.id) { bar.hidden = true; return; }
  bar.textContent = "";
  const use = el("button", "", "win");
  use.type = "button";
  use.addEventListener("click", () => { $("#guess").value = out.password; guess(); });
  bar.append(el("span", "", `🔧 ${out.password}`), use);
  bar.hidden = false;
}

// ---- wiring ----------------------------------------------------------------

function autosize() {
  const t = $("#msg");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight + 4, 160) + "px";
}

async function start() {
  const data = await api("/api/levels");
  if (data.error || !data.levels) {
    $("#messages").append(el("div", "msg note", data.message || "The tower is closed right now. Try again soon."));
    return;
  }
  LEVELS = data.levels;
  if (!LEVELS.some((l) => l.id === state.level)) state.level = LEVELS[0].id;
  if (!unlocked(cur())) state.level = LEVELS[0].id;
  save();
  renderAll();

  $("#composer").addEventListener("submit", (e) => { e.preventDefault(); send(); });
  $("#msg").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && cur().mode !== "letter") { e.preventDefault(); send(); }
  });
  $("#msg").addEventListener("input", autosize);
  $("#guessForm").addEventListener("submit", (e) => { e.preventDefault(); guess(); });
  $("#hintBtn").addEventListener("click", hint);
  $("#newChatBtn").addEventListener("click", newChat);
  $("#restartBtn").addEventListener("click", restart);
  $("#messages").addEventListener("click", stopTyping);

  if (!state.seenIntro) intro(); else $("#msg").focus();
}

start();
