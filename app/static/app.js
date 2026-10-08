const log = document.getElementById("log");
const form = document.getElementById("input");
const msg = document.getElementById("msg");
const statusEl = document.getElementById("status");

const history = [
  { role: "system", content: "Jesteś narratorem interaktywnej visual novel. Odpowiadaj po polsku, krótko i obrazowo." },
];

function addMessage(text, cls) {
  const div = document.createElement("div");
  div.className = `msg ${cls}`;
  div.textContent = text;
  log.appendChild(div);
  return div;
}

fetch("/api/health")
  .then((r) => r.json())
  .then((h) => {
    const providers = Object.entries(h.providers)
      .map(([name, ok]) => `${ok ? "✅" : "❌"} ${name}`)
      .join("  ");
    statusEl.textContent = `Model: ${h.ollama_model} · ${providers}`;
  })
  .catch(() => (statusEl.textContent = "❌ Backend niedostępny"));

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = msg.value.trim();
  if (!text) return;
  msg.value = "";
  addMessage(text, "user");
  history.push({ role: "user", content: text });

  const pending = addMessage("…", "bot");
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail);
    pending.textContent = data.reply;
    history.push({ role: "assistant", content: data.reply });
  } catch (err) {
    pending.textContent = String(err.message ?? err);
    pending.className = "msg error";
    history.pop();
  }
});
