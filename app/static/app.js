// Interfejs gry: scena VN + panel badawczy. Czysty JS, bez frameworków.
const $ = (s) => document.querySelector(s);
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const ui = { config: null, health: null, game: null, view: null, tab: "turn", busy: false, menu: true };
// Tryb deweloperski: panel badawczy, dane techniczne i ustawienia modeli. Na razie jedyny tryb (projekt badawczy),
// tryb gracza (tylko przeglądanie historii) dojdzie później.
const DEV_ONLY = true;
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
function memoryLabel(c) {
  return { full: "pełna historia", full_cached: "pełna historia z cache" }[c.history] ?? `okno ${c.memory_window} tur`;
}
function currentModel() { return ui.game?.config.model ?? ui.config?.defaults.model ?? ""; }
function modelStatus(model) {
  const p = ui.health?.providers ?? {};
  if (model === "demo") return { cls: "", label: "demo" };
  if (ui.game?.custom_text_api && model === ui.game.config.model) return { cls: "ok", label: "własne API" };
  if (model.startsWith("ollama")) return p.ollama ? { cls: "ok", label: "Ollama działa" } : { cls: "bad", label: "Ollama nie odpowiada" };
  for (const k of ["anthropic", "openai", "gemini"]) if (model.startsWith(k + "/")) return p[k] ? { cls: "ok", label: "klucz API jest" } : { cls: "bad", label: "brak klucza API" };
  return { cls: "", label: "" };
}

// ---------- render ----------
function render({ animate = false } = {}) {
  renderMenu();
  renderTop();
  renderBanner();
  renderStage(animate);
  renderEnding();
  renderPanel();
  const playing = !!ui.game && !ui.busy && !gameOver();
  $("#action").disabled = !playing;
  $("#send").disabled = !playing;
  $("#action").placeholder = gameOver() ? "Gra się skończyła. Zacznij nową grę." : "Co robisz? Np. Pytam Borwina o koronę";
}

// ---------- koniec gry ----------
const gameOver = () => !!ui.game && (ui.game.outcome?.status ?? "ongoing") !== "ongoing";
let endingHidden = false; // gracz chce obejrzeć ostatnią scenę bez planszy końca
function renderEnding() {
  const el = $("#ending");
  const latest = ui.view === null || ui.view >= turns().length - 1;
  const show = gameOver() && latest && !endingHidden;
  el.hidden = !show;
  if (!show) return;
  const o = ui.game.outcome;
  el.className = `ending ${o.status}`;
  $("#endTitle").textContent = o.status === "won" ? "Wygrana!" : "Przegrana";
  $("#endReason").textContent = o.reason || (o.status === "won" ? "Cel osiągnięty." : "Cel nie został osiągnięty.");
}
$("#btnEndNew").addEventListener("click", () => openMenu());
$("#btnEndHide").addEventListener("click", () => { endingHidden = true; renderEnding(); });

function renderTop() {
  $("#worldTitle").textContent = ui.game ? `· ${ui.game.world.title}` : "";
  const chips = [];
  const model = currentModel();
  const st = modelStatus(model);
  chips.push(`<span class="chip" title="${esc(st.label)}"><span class="dot ${st.cls}"></span><b>${esc(model)}</b></span>`);
  if (ui.game) {
    const c = ui.game.config;
    chips.push(`<span class="chip">pamięć: <b>${memoryLabel(c)}</b></span>`);
    chips.push(`<span class="chip">stan w prompcie: <b>${c.state_in_prompt ? "tak" : "nie"}</b></span>`);
    if (ui.game.image_model) chips.push(`<span class="chip">grafika: <b>${esc(ui.game.image_model)}</b></span>`);
    if (ui.game.difficulty === "easy") chips.push(`<span class="chip">podpowiedzi: <b>tak</b></span>`);
    chips.push(`<span class="chip">tura: <b>${turns().length}${ui.game.max_turns ? ` / ${ui.game.max_turns}` : ""}</b></span>`);
    if (gameOver()) chips.push(`<span class="chip"><b>${ui.game.outcome.status === "won" ? "wygrana" : "przegrana"}</b></span>`);
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

// Obrazy z serwera: najpierw tło lokacji, potem scena tury, rysowana na jego podstawie.
// Gdy obrazu nie ma (albo serwer jest wyłączony), zostaje gradient.
const stageImages = new Map(); // klucz obrazu -> adres gotowego pliku
let stageWatch = null; // to, na co teraz czekamy

function setStageImage(url) { $("#bg").style.background = `url("${url}") center / cover no-repeat`; }
function showBgNote(text) { $("#bgNote").textContent = text; $("#bgNote").hidden = !text; }
const preload = (url) => new Promise((done) => {
  const im = new Image();
  im.onload = () => done(true);
  im.onerror = () => done(false);
  im.src = url;
});

let imageError = ""; // przyczyna ostatniego nieudanego obrazu, od serwera
async function fetchImage(key, query) {
  let s = null;
  try { s = await api(query); } catch {}
  if (s?.status === "failed") imageError = s.error || imageError;
  if (s?.status !== "ready") return s?.status ?? "none";
  if (!await preload(s.url)) return "failed";
  stageImages.set(key, s.url);
  return "ready";
}

async function watchStage(loc, turn) {
  const gameId = ui.game.game_id;
  const placeKey = `${gameId}|place|${loc}`;
  const sceneKey = turn ? `${gameId}|turn|${turn}` : null;
  const wanted = sceneKey ?? placeKey;
  const paint = () => {
    const url = stageImages.get(sceneKey) ?? stageImages.get(placeKey);
    if (url) setStageImage(url);
  };
  paint();
  if (stageImages.has(wanted)) { stageWatch = null; showBgNote(""); return; }
  if (stageWatch === wanted) return;
  stageWatch = wanted;
  imageError = "";
  showBgNote("");
  const base = `/api/games/${gameId}`;
  for (let i = 0; i < 240 && stageWatch === wanted; i++) {
    const place = stageImages.has(placeKey) ? "ready" : await fetchImage(placeKey, `${base}/image?location=${encodeURIComponent(loc)}`);
    const status = sceneKey ? await fetchImage(sceneKey, `${base}/scene?t=${turn}`) : place;
    if (stageWatch !== wanted) return;
    paint();
    if (status === "pending" || place === "pending") {
      showBgNote(sceneKey ? "Rysuję scenę…" : "Rysuję tło…");
      await new Promise((done) => setTimeout(done, 1500));
      continue;
    }
    const failed = status === "failed" || (place === "failed" && !stageImages.has(placeKey) && status !== "ready");
    showBgNote(failed ? `Nie udało się narysować obrazu${imageError ? `: ${imageError}` : ""}` : "");
    break;
  }
  if (stageWatch === wanted) stageWatch = null;
}

function renderStage(animate) {
  stopTyping();
  const game = ui.game;
  $("#box").hidden = !game;
  if (!game) {
    $("#loc").innerHTML = "";
    $("#viewing").hidden = true;
    setBackground("start");
    stageWatch = null;
    showBgNote("");
    return;
  }
  const t = viewedTurn();
  const loc = t ? t.location : game.world.start_location;
  setBackground(loc);
  $("#loc").innerHTML = `<span class="name">${esc(locationName(loc))}</span><span class="id">location_id: ${esc(loc)}</span>`;
  watchStage(loc, t?.response ? t.t : null);

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
  const w = ui.game.world;
  const world = `<div><h3>Świat${w.custom ? " (stworzony z pomysłu gracza)" : ""}</h3><dl class="kv">
    <dt>tytuł</dt><dd>${esc(w.title)}</dd>
    <dt>bohater</dt><dd>${esc(w.player)}</dd>
    <dt>cel</dt><dd>${esc(w.goal)}</dd>
    <dt>wygrana</dt><dd>${esc(w.win_condition || "osiągnięcie celu")}</dd>
    <dt>przegrana</dt><dd>${esc(w.lose_condition || "śmierć bohatera albo cel nie do osiągnięcia")}</dd>
    <dt>limit tur</dt><dd>${ui.game.max_turns ?? "brak"}</dd>
    <dt>podpowiedzi</dt><dd>${ui.game.difficulty === "easy" ? "tak" : "nie"}</dd>
    <dt>opis</dt><dd>${esc(w.setting)}</dd>
    <dt>zasady</dt><dd>${(w.rules ?? []).map(esc).join("<br>") || "brak"}</dd></dl></div>`;
  const cfg = `${world}<div><h3>Konfiguracja gry</h3><dl class="kv">
    <dt>model</dt><dd>${esc(c.model)}</dd>
    <dt>pamięć</dt><dd>${memoryLabel(c)}</dd>
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
      <div class="metric"><span>Tokeny z cache</span><b>${t.tokens_cached}</b></div>
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
function setTech(on) {
  $("#btnTech").setAttribute("aria-pressed", on);
  document.body.classList.toggle("show-tech", on);
  store.set("dvn.tech", on ? "1" : "0");
}
setTech(store.get("dvn.tech") === "1");
$("#btnTech").addEventListener("click", () => setTech($("#btnTech").getAttribute("aria-pressed") !== "true"));
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
    ui.game.outcome = data.outcome;
    endingHidden = false;
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
  ui.menu = false;
  endingHidden = false;
  store.set("dvn.game", game.game_id);
  render({ animate: true });
  $("#action").focus();
}

async function refreshHealth() {
  ui.health = await api("/api/health").catch(() => null);
  render();
}

// ---------- menu i nowa gra ----------
const IDEAS = [
  "Cyberpunkowy Kraków w 2090 roku. Jestem detektywką i szukam zaginionego androida. Bez magii, dużo neonów i deszczu.",
  "Stacja badawcza na Antarktydzie, zerwana łączność z bazą. Jestem lekarzem wyprawy, a ktoś z załogi kłamie.",
  "Rybacka wioska na Kaszubach w 1890 roku. Po sztormie zaginął statek mojego brata, a w porcie pojawił się obcy.",
];
function renderMenu() {
  $("#menu").hidden = !ui.menu;
  document.body.classList.toggle("in-menu", ui.menu);
  $("#mBack").hidden = !ui.game;
}
function worldCover(w) { return w?.cover ?? null; }
function artGradient(seed) {
  const h = hash(seed) % 360;
  return `radial-gradient(ellipse at 70% 30%, hsla(${h}, 70%, 55%, .35), transparent 60%),` +
    `radial-gradient(ellipse at 20% 80%, hsla(${(h + 40) % 360}, 60%, 40%, .3), transparent 55%),` +
    `linear-gradient(160deg, hsl(${h} 30% 18%), hsl(${(h + 40) % 360} 35% 7%))`;
}
// Tło generatora: niezapisana mapa (ciepła poświata i siatka), bez obrazu, bo świata jeszcze nie ma
const BLANK_MAP = "radial-gradient(ellipse at 68% 42%, rgba(227,178,107,.22), transparent 55%)," +
  "repeating-linear-gradient(0deg, rgba(227,178,107,.07) 0 1px, transparent 1px 64px)," +
  "repeating-linear-gradient(90deg, rgba(227,178,107,.07) 0 1px, transparent 1px 64px)," +
  "linear-gradient(160deg, #1c1610, #0b0907)";
function renderWorlds() {
  const sel = $("#fWorld").value;
  const cards = ui.config.worlds.map((w) => {
    const art = worldCover(w) ? `url("${w.cover}") center / cover` : artGradient(w.id);
    return `<button type="button" class="world" role="radio" aria-checked="${w.id === sel}" data-world="${esc(w.id)}">
      <span class="thumb" style='background:${art}'></span>
      <span class="name">${esc(w.title)}</span><span class="sub">${esc(w.player.split(",")[0])}</span></button>`;
  });
  cards.push(`<button type="button" class="world custom" role="radio" aria-checked="${sel === "custom"}" data-world="custom">
      <span class="thumb" aria-hidden="true"><span class="plus">+</span></span>
      <span class="name">Własny świat</span><span class="sub">z twojego pomysłu</span></button>`);
  $("#worlds").innerHTML = cards.join("");
  $("#worlds").querySelectorAll("[data-world]").forEach((b) => b.addEventListener("click", () => selectWorld(b.dataset.world)));
}
function selectWorld(id) {
  $("#fWorld").value = id;
  const w = ui.config.worlds.find((x) => x.id === id);
  if (w) {
    $("#mEyebrow").textContent = "Opowieść prowadzona przez model językowy";
    $("#mTitle").textContent = w.title;
    $("#mLead").textContent = `Grasz jako ${w.player}. Cel: ${w.goal.charAt(0).toLowerCase()}${w.goal.slice(1)}`;
    $("#menuArt").style.background = worldCover(w) ? `url("${w.cover}") center / cover no-repeat` : artGradient(w.id);
  } else {
    $("#mEyebrow").textContent = "Generator świata";
    $("#mTitle").textContent = "Twój własny świat";
    $("#mLead").textContent = "Opisz pomysł w kilku zdaniach. Model narratora zamieni go w świat gry: bohatera, cel, lokacje, zasady i fakty, których nie da się zmienić.";
    $("#menuArt").style.background = BLANK_MAP;
  }
  renderWorlds();
  showIdea();
}
$("#ideaExamples").innerHTML = IDEAS.map((t, i) => `<button type="button" class="example" data-idea="${i}">${esc(t.split(".")[0])}</button>`).join("");
$("#ideaExamples").querySelectorAll("[data-idea]").forEach((b) => b.addEventListener("click", () => {
  $("#fIdea").value = IDEAS[Number(b.dataset.idea)];
  $("#fIdea").focus();
}));
function openMenu() {
  fillMenu();
  ui.menu = true;
  render();
}
function closeMenu() {
  if (!ui.game) return;
  ui.menu = false;
  render();
}
function fillMenu() {
  const d = ui.config.defaults;
  const c = ui.game?.config;
  selectWorld(ui.game?.world.custom ? "custom" : (ui.game?.world.id ?? ui.config.worlds[0]?.id ?? "custom"));
  const current = c?.model ?? d.model;
  const models = [...new Set([current, ...ui.config.suggested_models])].filter((m) => !m.includes("<"));
  $("#fModelPick").innerHTML = models.map((m) => `<option value="${esc(m)}">${esc(modelLabel(m))}</option>`).join("") +
    `<option value="__other">Inny model (wpisz nazwę)…</option>`;
  $("#fModelPick").value = current;
  $("#fModel").value = current;
  $("#fModel").hidden = true;
  const imageModels = ui.config.image_models;
  $("#fImageModel").innerHTML = imageModels.map((m) => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join("");
  const builtIn = imageModels.some((m) => m.id === ui.game?.image_model) ? ui.game.image_model : d.image_model;
  $("#fImageModel").value = builtIn;
  $("#fImageServerOpt").textContent = ui.config.image_server ? "Serwer obrazów z .env" : "Bez obrazów";
  loadApiFields();
  showImageFields();
  $("#fHistory").value = c?.history ?? d.history;
  $("#fWindow").value = c?.memory_window ?? d.window;
  $("#fState").checked = c?.state_in_prompt ?? d.state_in_prompt;
  $("#fSeed").value = c?.seed ?? "";
  $("#fMaxTurns").value = ui.game?.max_turns ?? "";
  $("#fHints").checked = ui.game?.difficulty === "easy";
  $("#dlgErr").textContent = "";
  updateDevSummary();
}
function updateDevSummary() {
  const model = $("#fModel").value || $("#fModelPick").value;
  $("#devSummary").textContent = model;
}
function showDev(on) {
  $("#devSettings").hidden = !on;
  $("#btnDev").setAttribute("aria-expanded", on);
  if (on) $("#fModelPick").focus();
}
$("#btnDev").addEventListener("click", () => showDev($("#devSettings").hidden));
$("#devClose").addEventListener("click", () => showDev(false));
function modelLabel(m) {
  if (m === "demo") return "demo (bez modelu, tylko podgląd)";
  if (m.startsWith("openai/strata") || m.startsWith("openai/large")) return `${m} (serwer uczelni)`;
  if (m.startsWith("ollama")) return `${m} (Ollama)`;
  if (m.startsWith("anthropic/")) return `${m} (API)`;
  return m;
}
// Własne API: adresy i klucze zostają w przeglądarce tylko po zaznaczeniu „Zapamiętaj”.
// Serwer gry dostaje je przy tworzeniu gry i nie zapisuje ich w bazie.
const API_FIELDS = ["fTextBase", "fTextKey", "fImageKind", "fImageUrl", "fImageLm", "fImageKey", "fImageSize"];
function loadApiFields() {
  let saved = null;
  try { saved = JSON.parse(store.get("dvn.api") || "null"); } catch {}
  $("#fRemember").checked = !!saved;
  for (const id of API_FIELDS) {
    const el = $(`#${id}`);
    if (saved && saved[id] != null) el.value = saved[id];
  }
  $("#fTextApi").open = !!($("#fTextBase").value || $("#fTextKey").value);
}
function saveApiFields() {
  if (!$("#fRemember").checked) { store.set("dvn.api", null); return; }
  store.set("dvn.api", JSON.stringify(Object.fromEntries(API_FIELDS.map((id) => [id, $(`#${id}`).value]))));
}
function showImageFields() {
  const kind = $("#fImageKind").value;
  const own = kind === "dvn" || kind === "litellm";
  $("#fImageApi").hidden = !own;
  $("#fImageWrap").hidden = !(kind === "dvn" || (kind === "server" && ui.config.image_server));
  $("#fImageLmWrap").hidden = kind !== "litellm";
  $("#fImageKeyWrap").hidden = kind !== "litellm";
  $("#fImageUrlWrap").firstChild.textContent = kind === "dvn" ? "Adres serwera obrazów" : "Adres API (opcjonalnie)";
  $("#fImageUrl").placeholder = kind === "dvn" ? "np. http://host.docker.internal:8420" : "puste = domyślny adres providera";
  $("#fImageHint").innerHTML = kind === "dvn"
    ? "Serwer z <code>bench/images/consistency/serve.py</code>, np. przez tunel SSH. Rysuje sceny na podstawie tła i portretów postaci."
    : "Dowolny model obrazów obsługiwany przez LiteLLM, np. <code>openai/gpt-image-1</code>, <code>openai/dall-e-3</code>, <code>gemini/gemini-3.1-flash-image</code> (płatny plan Gemini). Takie API rysuje tylko z opisu, bez obrazów wejściowych, więc postacie mogą wyglądać inaczej w kolejnych turach.";
}
$("#fImageKind").addEventListener("change", showImageFields);
function showIdea() {
  const custom = $("#fWorld").value === "custom";
  $("#fIdeaWrap").hidden = !custom;
  $("#fIdea").required = custom;
  $("#dlgOk").textContent = custom ? "Stwórz świat i zagraj" : "Zacznij grę";
}
function apiPayload() {
  const body = {};
  const base = $("#fTextBase").value.trim();
  const key = $("#fTextKey").value.trim();
  if (base || key) body.text_api = { api_base: base, api_key: key };
  const kind = $("#fImageKind").value;
  if (kind === "dvn" || kind === "litellm") {
    body.image_api = {
      kind,
      url: $("#fImageUrl").value.trim(),
      model: $("#fImageLm").value.trim(),
      api_key: $("#fImageKey").value.trim(),
      size: $("#fImageSize").value.trim() || "1536x1024",
    };
  }
  return body;
}
$("#fModelPick").addEventListener("change", () => {
  const other = $("#fModelPick").value === "__other";
  $("#fModel").hidden = !other;
  $("#fModel").value = other ? "" : $("#fModelPick").value;
  if (other) $("#fModel").focus();
  updateDevSummary();
});
$("#fModel").addEventListener("input", updateDevSummary);
$("#btnNew").addEventListener("click", openMenu);
$("#mBack").addEventListener("click", closeMenu);
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || !ui.menu || !$("#building").hidden) return;
  if (!$("#devSettings").hidden) showDev(false); else closeMenu();
});
$("#mDev").addEventListener("click", () => {
  if (DEV_ONLY) { $("#dlgErr").textContent = "Tryb gracza jeszcze nie istnieje. Na razie gra działa tylko w trybie deweloperskim."; return; }
});
$("#btnDemo").addEventListener("click", () => {
  const custom = $("#fWorld").value === "custom";
  startGame({ model: "demo", world_id: $("#fWorld").value, world_idea: custom ? ($("#fIdea").value.trim() || IDEAS[0]) : null,
    difficulty: $("#fHints").checked ? "easy" : "normal" })
    .catch((e) => { $("#dlgErr").textContent = e.message; });
});
let buildTimer = null;
function showBuilding(idea) {
  $("#building").hidden = !idea;
  clearInterval(buildTimer);
  if (!idea) return;
  $("#buildIdea").textContent = `„${idea.length > 140 ? `${idea.slice(0, 140)}…` : idea}”`;
  const t0 = performance.now();
  $("#buildElapsed").textContent = "0 s";
  buildTimer = setInterval(() => { $("#buildElapsed").textContent = `${Math.round((performance.now() - t0) / 1000)} s`; }, 500);
}
$("#newForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const seed = $("#fSeed").value.trim();
  const custom = $("#fWorld").value === "custom";
  const ok = $("#dlgOk");
  ok.disabled = true;
  ok.textContent = custom ? "Tworzę świat…" : "Zaczynam…";
  $("#dlgErr").textContent = "";
  if (custom) showBuilding($("#fIdea").value.trim());
  try {
    await startGame({
      world_id: $("#fWorld").value,
      world_idea: custom ? $("#fIdea").value.trim() : null,
      max_turns: Number($("#fMaxTurns").value) || null,
      difficulty: $("#fHints").checked ? "easy" : "normal",
      model: $("#fModel").value.trim(),
      history: $("#fHistory").value,
      window: Number($("#fWindow").value) || null,
      state_in_prompt: $("#fState").checked,
      seed: seed === "" ? null : Number(seed),
      image_model: $("#fImageWrap").hidden ? null : $("#fImageModel").value || null,
      ...apiPayload(),
    });
    saveApiFields();
    $("#dlgErr").textContent = "";
  } catch (err) {
    $("#dlgErr").textContent = err.message;
  } finally {
    showDev(false);
    showBuilding(null);
    ok.disabled = false;
    showIdea();
  }
});

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
  fillMenu();
  ui.menu = !ui.game;
  render();
})();
