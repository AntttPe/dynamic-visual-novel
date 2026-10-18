// Interfejs gry: scena VN + panel badawczy. Czysty JS, bez frameworków.
const $ = (s) => document.querySelector(s);
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const ui = { config: null, health: null, game: null, view: null, tab: "turn", busy: false };
let typer = null;
let timer = null;

// ---------- pomocnicze ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtNum = (n, d = 1) => Number(n).toFixed(d).replace(".", ",");
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} },
};
function hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  let data = null;
  try { data = await r.json(); } catch {}
  if (!r.ok) {
    const d = data?.detail;
    const msg = typeof d === "string" ? d : d ? d.map((x) => x.msg).join("; ") : `Błąd HTTP ${r.status}`;
    const err = new Error(msg);
    err.status = r.status;
    throw err;
  }
  return data;
}

// ---------- dane bieżące ----------
const turns = () => ui.game?.turns ?? [];
const viewIndex = () => (ui.view ?? turns().length - 1);
const viewedTurn = () => turns()[viewIndex()];
const locationName = (id) => ui.game?.known_locations?.[id] ?? id;
function currentModel() { return ui.game?.config.model ?? ui.config?.defaults.model ?? ""; }
function modelStatus(model) {
  const p = ui.health?.providers ?? {};
  if (model === "demo") return { cls: "", label: "demo" };
  if (model.startsWith("ollama")) return p.ollama ? { cls: "ok", label: "Ollama działa" } : { cls: "bad", label: "Ollama nie odpowiada" };
  for (const k of ["anthropic", "openai", "gemini"]) if (model.startsWith(k + "/")) return p[k] ? { cls: "ok", label: "klucz API jest" } : { cls: "bad", label: "brak klucza API" };
  return { cls: "", label: "" };
}

// ---------- render ----------
function render({ animate = false } = {}) {
  renderTop();
  renderBanner();
  renderStage(animate);
  renderPanel();
  const playing = !!ui.game && !ui.busy;
  $("#action").disabled = !playing;
  $("#send").disabled = !playing;
}

function renderTop() {
  $("#worldTitle").textContent = ui.game ? `· ${ui.game.world.title}` : "";
  const chips = [];
  const model = currentModel();
  const st = modelStatus(model);
  chips.push(`<span class="chip" title="${esc(st.label)}"><span class="dot ${st.cls}"></span><b>${esc(model)}</b></span>`);
  if (ui.game) {
    const c = ui.game.config;
    chips.push(`<span class="chip">pamięć: <b>${c.history === "full" ? "pełna historia" : `okno ${c.memory_window}`}</b></span>`);
    chips.push(`<span class="chip">stan w prompcie: <b>${c.state_in_prompt ? "tak" : "nie"}</b></span>`);
    chips.push(`<span class="chip">tura: <b>${turns().length}</b></span>`);
  }
  $("#chips").innerHTML = chips.join("");
}

function renderBanner() {
  const b = $("#banner");
  const model = currentModel();
  if (ui.health === null) {
    b.innerHTML = "Nie udało się połączyć z serwerem gry. Sprawdź, czy kontener działa (docker compose up -d).";
    b.hidden = false;
    return;
  }
  if (model.startsWith("ollama") && !ui.health.providers.ollama) {
    b.innerHTML = `<span><b>Ollama nie odpowiada</b> pod ${esc(ui.health.ollama_base_url)}. Uruchom ją na komputerze (<code>ollama serve</code>) albo zestaw tunel do wynajętego GPU.</span>
      <span class="row"><button type="button" class="btn" id="bRetry">Sprawdź ponownie</button><button type="button" class="btn" id="bDemo">Graj w trybie demo</button></span>`;
    b.hidden = false;
    $("#bRetry").onclick = refreshHealth;
    $("#bDemo").onclick = () => startGame({ model: "demo" });
    return;
  }
  b.hidden = true;
}

function setBackground(locationId) {
  const h = hash(locationId || "start") % 360;
  const h2 = (h + 35) % 360;
  $("#bg").style.background =
    `radial-gradient(ellipse at 28% 22%, hsla(${h}, 70%, 65%, .35), transparent 55%),` +
    `radial-gradient(ellipse at 80% 30%, hsla(${h2}, 60%, 55%, .22), transparent 50%),` +
    `linear-gradient(180deg, hsl(${h} 35% 32%) 0%, hsl(${h2} 38% 18%) 58%, hsl(${(h + 60) % 360} 30% 8%) 100%)`;
}

function renderStage(animate) {
  stopTyping();
  const game = ui.game;
  $("#start").hidden = !!game;
  $("#box").hidden = !game;
  if (!game) {
    const w = ui.config?.worlds?.[0];
    $("#startTitle").textContent = w?.title ?? "Dynamic Visual Novel";
    $("#startIntro").textContent = "Wpisujesz dowolne działanie, a model językowy opowiada, co dzieje się dalej. Panel po prawej pokazuje, co dokładnie trafia do modelu i co z niego wraca.";
    $("#loc").innerHTML = "";
    $("#viewing").hidden = true;
    setBackground("start");
    return;
  }
  const t = viewedTurn();
  const loc = t ? t.location : game.world.start_location;
  setBackground(loc);
  $("#loc").innerHTML = `<span class="name">${esc(locationName(loc))}</span><span class="id">location_id: ${esc(loc)}</span>`;

  const past = ui.view !== null && ui.view < turns().length - 1;
  $("#viewing").hidden = !past;
  if (past) {
    $("#viewing").innerHTML = `Podgląd tury ${viewIndex() + 1} z ${turns().length} <button type="button" id="bLatest">wróć do bieżącej</button>`;
    $("#bLatest").onclick = () => { ui.view = null; render(); };
  }

  const err = $("#turnErr");
  err.hidden = true;
  $("#dialogue").innerHTML = "";
  if (!t) {
    $("#lastAction").textContent = "Początek historii";
    showNarration(game.world.intro, [], animate);
    return;
  }
  $("#lastAction").textContent = `› ${t.player_action}`;
  if (!t.response) {
    $("#narr").textContent = "";
    err.textContent = `Narrator nie zwrócił poprawnej odpowiedzi (${t.error}). Surowa odpowiedź jest w zakładce JSON. Spróbuj jeszcze raz.`;
    err.hidden = false;
    return;
  }
  showNarration(t.response.narration, t.response.dialogue, animate);
}

function showNarration(text, dialogue, animate) {
  const narr = $("#narr");
  const finish = () => {
    narr.textContent = text;
    $("#dialogue").innerHTML = dialogue.map((d) => {
      const hue = hash(d.speaker.toLowerCase()) % 360;
      return `<div class="line"><span class="speaker" style="background:hsl(${hue} 65% 72%)">${esc(d.speaker)}</span><span class="said">„${esc(d.text)}”</span></div>`;
    }).join("");
    typer = null;
  };
  if (!animate || reduceMotion) return finish();
  let i = 0;
  narr.textContent = "";
  typer = { finish, id: setInterval(() => {
    i += 2;
    narr.textContent = text.slice(0, i);
    if (i >= text.length) { clearInterval(typer.id); finish(); }
  }, 18) };
}
function stopTyping() { if (typer) { clearInterval(typer.id); typer = null; } }
$("#box").addEventListener("click", () => { if (typer) { clearInterval(typer.id); typer.finish(); } });

// ---------- panel badawczy ----------
function renderPanel() {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === ui.tab));
  const body = $("#tabbody");
  if (!ui.game) { body.innerHTML = `<p class="empty">Zacznij grę, żeby zobaczyć dane tury.</p>`; return; }
  const t = viewedTurn();
  body.innerHTML = { turn: tabTurn, state: tabState, prompt: tabPrompt, json: tabJson, history: tabHistory }[ui.tab](t);
  body.querySelectorAll("[data-view]").forEach((el) => el.addEventListener("click", () => {
    ui.view = Number(el.dataset.view); render();
  }));
}

function tabTurn(t) {
  const c = ui.game.config;
  const cfg = `<div><h3>Konfiguracja gry</h3><dl class="kv">
    <dt>model</dt><dd>${esc(c.model)}</dd>
    <dt>pamięć</dt><dd>${c.history === "full" ? "pełna historia" : `okno ${c.memory_window} tur`}</dd>
    <dt>stan w prompcie</dt><dd>${c.state_in_prompt ? "tak" : "nie"}</dd>
    <dt>temperatura</dt><dd>${c.temperature}</dd>
    <dt>seed</dt><dd>${c.seed ?? "brak"}</dd>
    <dt>wersja promptu</dt><dd><code>${esc(c.prompt_version)}</code></dd>
    <dt>id gry</dt><dd><code>${esc(ui.game.game_id)}</code></dd></dl></div>`;
  if (!t) return `<p class="empty">Wpisz pierwsze działanie. Po każdej turze zobaczysz tu czas, tokeny, poprawność JSON i zmiany stanu.</p>${cfg}`;
  const json = !t.response ? `<span class="pill bad">błąd</span>` : t.json_ok_first_try ? `<span class="pill ok">za 1. razem</span>` : `<span class="pill warn">ponowienia: ${t.retries}</span>`;
  const firstSeen = turns().findIndex((x) => x.location === t.location) === turns().indexOf(t);
  const isStart = t.location === ui.game.world.start_location;
  const r = t.response;
  const upd = [
    ...t.accepted_updates.map((u) => `<li class="ok">${esc(u.entity)}.${esc(u.attribute)} = ${esc(u.value)}<small>przyjęta</small></li>`),
    ...t.rejected_updates.map((x) => `<li class="bad">${esc(x.update.entity)}.${esc(x.update.attribute)} = ${esc(x.update.value)}<small>odrzucona: ${esc(x.reason)}</small></li>`),
  ].join("");
  return `<div class="metrics">
      <div class="metric"><span>Czas odpowiedzi</span><b>${fmtNum(t.latency_ms / 1000)} s</b></div>
      <div class="metric"><span>JSON</span><b>${json}</b></div>
      <div class="metric"><span>Tokeny wejścia</span><b>${t.tokens_in}</b></div>
      <div class="metric"><span>Tokeny wyjścia</span><b>${t.tokens_out}</b></div>
    </div>
    <div><h3>Scena</h3><dl class="kv">
      <dt>location_id</dt><dd><code>${esc(r?.scene.location_id ?? "brak")}</code> → <code>${esc(t.location)}</code>
        ${firstSeen && !isStart ? `<span class="pill warn">pierwsza wizyta: nowe tło</span>` : `<span class="pill ok">znane miejsce: to samo tło</span>`}</dd>
      <dt>opis do tła</dt><dd>${esc(r?.scene.description ?? "")}</dd>
      <dt>postacie</dt><dd>${esc((r?.characters_present ?? []).join(", ") || "brak")}</dd></dl></div>
    <div><h3>Zmiany stanu w tej turze</h3>${upd ? `<ul class="updates">${upd}</ul>` : `<p class="empty">Brak zmian.</p>`}</div>
    ${cfg}`;
}

function tabState(t) {
  const facts = t ? t.state_after : ui.game.state;
  const changed = new Set((t?.accepted_updates ?? []).map((u) => `${u.entity.toLowerCase()}|${u.attribute.toLowerCase()}`));
  const rows = facts.map((f) => `<tr class="${changed.has(`${f.entity.toLowerCase()}|${f.attribute.toLowerCase()}`) ? "changed" : ""}">
      <td>${esc(f.entity)}</td><td>${esc(f.attribute)}</td><td>${esc(f.value)}</td>
      <td>${f.immutable ? `<span class="pill">niezmienne</span>` : ""}</td></tr>`).join("");
  const rejected = (t?.rejected_updates ?? []).map((x) => `<li class="bad">${esc(x.update.entity)}.${esc(x.update.attribute)} = ${esc(x.update.value)}<small>${esc(x.reason)}</small></li>`).join("");
  return `${rejected ? `<div><h3>Odrzucone przez walidator</h3><ul class="updates">${rejected}</ul></div>` : ""}
    <div><h3>Stan ${t ? `po turze ${t.t}` : "początkowy"}</h3>
    <table class="facts"><thead><tr><th>Encja</th><th>Atrybut</th><th>Wartość</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function tabPrompt(t) {
  if (!t) return `<p class="empty">Prompt pojawi się po pierwszej turze. To dokładnie te wiadomości, które dostaje model.</p>`;
  const chars = t.prompt.reduce((a, m) => a + m.content.length, 0);
  const label = { system: "system (instrukcje + stan świata)", user: "gracz", assistant: "narrator (wcześniejsza tura)" };
  return `<p class="muted">${t.prompt.length} wiadomości · ${chars.toLocaleString("pl-PL")} znaków · ${t.tokens_in} tokenów wejścia</p>` +
    t.prompt.map((m, i) => `<details class="msg" ${i === t.prompt.length - 1 ? "open" : ""}>
      <summary><span>${esc(label[m.role] ?? m.role)}</span><span class="muted">${m.content.length} zn.</span></summary>
      <pre>${esc(m.content)}</pre></details>`).join("");
}

function tabJson(t) {
  if (!t) return `<p class="empty">Tu pojawi się surowa odpowiedź modelu.</p>`;
  let pretty = t.raw_output;
  try { pretty = JSON.stringify(JSON.parse(t.raw_output), null, 2); } catch {}
  return `${t.error ? `<p><span class="pill bad">${esc(t.error)}</span></p>` : ""}
    <div><h3>Surowa odpowiedź modelu</h3><pre>${esc(pretty)}</pre></div>`;
}

function tabHistory() {
  if (!turns().length) return `<p class="empty">Brak tur.</p>`;
  const cur = viewIndex();
  return `<ul class="hist">${turns().map((t, i) => `<li><button type="button" data-view="${i}" class="${i === cur ? "cur" : ""}">
      <span class="top"><span>Tura ${t.t} · ${esc(t.location)}</span><span>${fmtNum(t.latency_ms / 1000)} s</span></span>
      <span class="act">› ${esc(t.player_action)}</span>
      <span class="nar">${esc((t.response?.narration ?? t.error ?? "").slice(0, 110))}</span></button></li>`).reverse().join("")}</ul>`;
}

document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => { ui.tab = b.dataset.tab; store.set("dvn.tab", ui.tab); renderPanel(); }));
$("#btnPanel").addEventListener("click", () => {
  const on = $("#btnPanel").getAttribute("aria-pressed") !== "true";
  $("#btnPanel").setAttribute("aria-pressed", on);
  $("#layout").classList.toggle("no-panel", !on);
  store.set("dvn.panel", on ? "1" : "0");
});

// ---------- akcje ----------
function setBusy(busy) {
  ui.busy = busy;
  $("#thinking").hidden = !busy;
  $("#action").disabled = busy || !ui.game;
  $("#send").disabled = busy || !ui.game;
  clearInterval(timer);
  if (busy) {
    const t0 = performance.now();
    $("#elapsed").textContent = "0,0 s";
    timer = setInterval(() => { $("#elapsed").textContent = `${fmtNum((performance.now() - t0) / 1000)} s`; }, 100);
  }
}

$("#form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const action = $("#action").value.trim();
  if (!action || ui.busy || !ui.game) return;
  ui.view = null;
  render();
  setBusy(true);
  $("#lastAction").textContent = `› ${action}`;
  $("#narr").textContent = "";
  $("#dialogue").innerHTML = "";
  try {
    const data = await api(`/api/games/${ui.game.game_id}/turns`, { method: "POST", body: JSON.stringify({ action }) });
    ui.game.turns.push(data.turn);
    ui.game.location = data.location;
    ui.game.known_locations = data.known_locations;
    ui.game.state = data.state;
    $("#action").value = "";
    setBusy(false);
    render({ animate: true });
  } catch (err) {
    setBusy(false);
    if (err.status === 404) {
      ui.game = null;
      store.set("dvn.game", null);
      render();
      return;
    }
    render();
    $("#turnErr").textContent = err.message;
    $("#turnErr").hidden = false;
  } finally {
    $("#action").focus();
  }
});

async function startGame(body) {
  const game = await api("/api/games", { method: "POST", body: JSON.stringify(body) });
  ui.game = game;
  ui.view = null;
  store.set("dvn.game", game.game_id);
  render({ animate: true });
  $("#action").focus();
}

async function refreshHealth() {
  ui.health = await api("/api/health").catch(() => null);
  render();
}

// ---------- okno nowej gry ----------
function openDialog() {
  const d = ui.config.defaults;
  const c = ui.game?.config;
  $("#fWorld").innerHTML = ui.config.worlds.map((w) => `<option value="${esc(w.id)}">${esc(w.title)}</option>`).join("");
  const current = c?.model ?? d.model;
  const models = [...new Set([current, ...ui.config.suggested_models])].filter((m) => !m.includes("<"));
  $("#fModelPick").innerHTML = models.map((m) => `<option value="${esc(m)}">${esc(modelLabel(m))}</option>`).join("") +
    `<option value="__other">Inny model (wpisz nazwę)…</option>`;
  $("#fModelPick").value = current;
  $("#fModel").value = current;
  $("#fModel").hidden = true;
  $("#fHistory").value = c?.history ?? d.history;
  $("#fWindow").value = c?.memory_window ?? d.window;
  $("#fState").checked = c?.state_in_prompt ?? d.state_in_prompt;
  $("#fSeed").value = c?.seed ?? "";
  $("#dlgErr").textContent = "";
  $("#dlg").showModal();
}
function modelLabel(m) {
  if (m === "demo") return "demo (bez modelu, tylko podgląd)";
  if (m.startsWith("openai/strata") || m.startsWith("openai/large")) return `${m} (serwer uczelni)`;
  if (m.startsWith("ollama")) return `${m} (Ollama)`;
  if (m.startsWith("anthropic/")) return `${m} (API)`;
  return m;
}
$("#fModelPick").addEventListener("change", () => {
  const other = $("#fModelPick").value === "__other";
  $("#fModel").hidden = !other;
  $("#fModel").value = other ? "" : $("#fModelPick").value;
  if (other) $("#fModel").focus();
});
$("#btnNew").addEventListener("click", openDialog);
$("#btnStart").addEventListener("click", openDialog);
$("#btnDemo").addEventListener("click", () => startGame({ model: "demo" }).catch((e) => alertStage(e.message)));
$("#dlgCancel").addEventListener("click", () => $("#dlg").close());
$("#newForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const seed = $("#fSeed").value.trim();
  try {
    await startGame({
      world_id: $("#fWorld").value,
      model: $("#fModel").value.trim(),
      history: $("#fHistory").value,
      window: Number($("#fWindow").value) || null,
      state_in_prompt: $("#fState").checked,
      seed: seed === "" ? null : Number(seed),
    });
    $("#dlg").close();
  } catch (err) {
    $("#dlgErr").textContent = err.message;
  }
});
function alertStage(msg) { $("#startIntro").textContent = msg; }

// ---------- start ----------
(async function init() {
  ui.tab = store.get("dvn.tab") || "turn";
  if (store.get("dvn.panel") === "0") { $("#btnPanel").setAttribute("aria-pressed", "false"); $("#layout").classList.add("no-panel"); }
  try {
    ui.config = await api("/api/config");
  } catch {
    ui.health = null;
    render();
    return;
  }
  ui.health = await api("/api/health").catch(() => null);
  const saved = store.get("dvn.game");
  if (saved) {
    try { ui.game = await api(`/api/games/${saved}`); } catch { store.set("dvn.game", null); }
  }
  render();
})();
