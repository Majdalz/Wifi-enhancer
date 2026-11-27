"use strict";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = { data: null, band: "2.4 GHz", sort: { key: "signal", dir: -1 }, timer: null };
const REFRESH_MS = 15000;

/* ---------- theme ---------- */
try {
  const t = localStorage.getItem("we-theme");
  if (t) document.documentElement.dataset.theme = t;
} catch {}
$("#theme").onclick = () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("we-theme", root.dataset.theme); } catch {}
};

/* ---------- helpers ---------- */
const qualityColor = (sig) => sig >= 80 ? "var(--good)" : sig >= 60 ? "var(--accent)" : sig >= 40 ? "var(--warn)" : "var(--bad)";

function bars(sig) {
  const n = sig >= 80 ? 4 : sig >= 60 ? 3 : sig >= 40 ? 2 : 1;
  return `<span class="bars" style="--c:${qualityColor(sig)}">${[1, 2, 3, 4].map((i) => `<i class="${i <= n ? "on" : ""}"></i>`).join("")}</span>`;
}

function secClass(sec) {
  const s = sec.toUpperCase();
  if (s === "OPEN" || s === "" || s === "--") return "sec-open";
  if (s.includes("WEP")) return "sec-wep";
  return "";
}

/* ---------- render ---------- */
function renderCurrent(a) {
  const c = a.current;
  const arc = $("#gauge-arc");
  if (!c) {
    arc.style.strokeDashoffset = 314.16;
    $("#gauge-val").textContent = "–";
    $("#gauge-q").textContent = "offline";
    $("#current-info").innerHTML = `<dt>Status</dt><dd>Not connected</dd>`;
    return;
  }
  arc.style.strokeDashoffset = 314.16 * (1 - c.signal / 100);
  arc.style.stroke = qualityColor(c.signal);
  $("#gauge-val").textContent = c.signal + "%";
  $("#gauge-q").textContent = a.quality;
  const rows = [
    ["Network", c.ssid], ["Signal", `${c.dbm} dBm`], ["Band", c.band],
    ["Channel", c.channel], ["Frequency", `${c.frequency} MHz`], ["Security", c.security], ["BSSID", c.bssid],
  ];
  $("#current-info").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");
}

function renderTips(tips) {
  $("#tips").innerHTML = tips.map((t) =>
    `<li class="lvl-${t.level}"><div><b>${esc(t.title)}</b><span>${esc(t.detail)}</span></div></li>`).join("");
}

function renderChart() {
  const a = state.data.analysis;
  const scores = a.congestion[state.band] || {};
  const chans = Object.keys(scores).map(Number).sort((x, y) => x - y);
  const best = a.best_channel[state.band];
  const mine = a.current && a.current.band === state.band ? a.current.channel : null;
  const W = 640, H = 220, pad = { l: 8, r: 8, t: 12, b: 26 };
  if (!chans.length) { $("#chart").innerHTML = `<p class="hint">No data for this band.</p>`; return; }
  const max = Math.max(0.5, ...Object.values(scores));
  const slot = (W - pad.l - pad.r) / chans.length;
  const bw = Math.min(34, slot * 0.66);
  const ih = H - pad.t - pad.b;
  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Channel congestion for ${state.band}">`;
  for (let i = 0; i <= 3; i++) {
    const y = pad.t + (ih * i) / 3;
    svg += `<line class="grid-l" x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}"/>`;
  }
  chans.forEach((ch, i) => {
    const v = scores[ch];
    const h = Math.max(2, (v / max) * ih);
    const x = pad.l + slot * i + (slot - bw) / 2;
    const cls = ch === mine ? "b mine" : ch === best ? "b best" : "b";
    svg += `<rect class="${cls}" x="${x}" y="${pad.t + ih - h}" width="${bw}" height="${h}" rx="3"><title>Channel ${ch}: load ${v.toFixed(2)}</title></rect>`;
    svg += `<text x="${x + bw / 2}" y="${H - 8}">${ch}</text>`;
  });
  $("#chart").innerHTML = svg + "</svg>";
}

function renderTable() {
  const nets = state.data.networks;
  const q = $("#search").value.trim().toLowerCase();
  const band = $("#band-filter").value;
  const { key, dir } = state.sort;
  const rows = nets
    .filter((n) => (!q || n.ssid.toLowerCase().includes(q)) && (!band || n.band === band))
    .sort((a, b) => (a[key] > b[key] ? 1 : a[key] < b[key] ? -1 : 0) * dir);
  $("#count").textContent = `(${rows.length}${rows.length !== nets.length ? " of " + nets.length : ""})`;
  $("#rows").innerHTML = rows.map((n) => `
    <tr class="${n.connected ? "connected" : ""}">
      <td>${esc(n.ssid)}${n.connected ? '<span class="pill">connected</span>' : ""}</td>
      <td>${bars(n.signal)}${n.signal}% <span class="muted">(${n.dbm} dBm)</span></td>
      <td>${n.channel}</td>
      <td>${n.band}</td>
      <td class="${secClass(n.security)}">${esc(n.security)}</td>
      <td class="mono hide-sm">${esc(n.bssid)}</td>
    </tr>`).join("") || `<tr><td colspan="6" class="muted">No networks match.</td></tr>`;
}

function render() {
  const d = state.data;
  const src = $("#source");
  src.textContent = d.demo ? "Demo data" : `Live · ${d.source}`;
  src.className = "badge" + (d.demo ? " demo" : "");
  const note = $("#notice");
  if (d.demo && d.error) {
    note.hidden = false;
    note.textContent = `Showing simulated networks — ${d.error}. Run this on a computer with Wi-Fi to see real data.`;
  } else note.hidden = true;
  renderCurrent(d.analysis);
  renderTips(d.analysis.tips);
  renderChart();
  renderTable();
  $("#updated").textContent = new Date(d.timestamp * 1000).toLocaleTimeString();
}

/* ---------- data ---------- */
async function load() {
  const btn = $("#refresh");
  btn.disabled = true; btn.textContent = "Scanning…";
  try {
    const demo = new URLSearchParams(location.search).get("demo") === "1" ? "?demo=1" : "";
    const r = await fetch("/api/scan" + demo);
    state.data = await r.json();
    render();
  } catch (e) {
    const note = $("#notice");
    note.hidden = false;
    note.textContent = "Could not reach the Wi-Fi Enhancer server: " + e.message;
  } finally {
    btn.disabled = false; btn.textContent = "Scan now";
  }
}

function schedule() {
  clearInterval(state.timer);
  if ($("#auto").checked) state.timer = setInterval(load, REFRESH_MS);
}

async function runPing() {
  const btn = $("#ping");
  btn.disabled = true; btn.textContent = "Testing…";
  $("#lat-msg").textContent = "";
  try {
    const r = await (await fetch("/api/ping?target=" + encodeURIComponent($("#target").value))).json();
    $("#lat-avg").textContent = r.avg ?? "–";
    $("#lat-jit").textContent = r.jitter ?? "–";
    $("#lat-loss").textContent = r.loss ?? "–";
    let msg = r.error ? r.error : `${r.received}/${r.sent} replies from ${r.host} · min ${r.min} / max ${r.max} ms`;
    if (!r.error) {
      if (r.loss > 0) msg += " — packet loss usually means interference or a weak signal.";
      else if (r.avg > 80) msg += " — high latency; check for heavy downloads on your network.";
      else if (r.jitter > 20) msg += " — high jitter may cause choppy calls and games.";
      else msg += " — healthy.";
    }
    $("#lat-msg").textContent = msg;
  } catch (e) {
    $("#lat-msg").textContent = "Test failed: " + e.message;
  } finally {
    btn.disabled = false; btn.textContent = "Run test";
  }
}

/* ---------- events ---------- */
$("#refresh").onclick = load;
$("#auto").onchange = schedule;
$("#ping").onclick = runPing;
$("#search").oninput = () => state.data && renderTable();
$("#band-filter").onchange = () => state.data && renderTable();
document.querySelectorAll(".seg button").forEach((b) => (b.onclick = () => {
  document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("active", x === b));
  state.band = b.dataset.band;
  if (state.data) renderChart();
}));
document.querySelectorAll("th[data-sort]").forEach((th) => (th.onclick = () => {
  const key = th.dataset.sort;
  state.sort = { key, dir: state.sort.key === key ? -state.sort.dir : key === "signal" ? -1 : 1 };
  document.querySelectorAll("th[data-sort]").forEach((x) => x.classList.remove("sorted", "asc", "desc"));
  th.classList.add("sorted", state.sort.dir === 1 ? "asc" : "desc");
  if (state.data) renderTable();
}));

load();
schedule();
