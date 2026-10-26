// The whole doorbell dashboard in a browser: home (news like a TV channel, market band,
// breaking ticker, photos), the front door live, the recordings, and every setting.
// The Pi publishes named parts (webapp.py); one long poll keeps them current.
// Ring alerts while the page is closed come through the service worker (sw.js).
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const P = {};  // parts from the Pi: state, news, breaking, market, photos, events, log, settings, speaker, camera, outdoor, notice
let version = 0;

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (r.status === 401) { showLogin(); throw new Error("login"); }
  return r.json().catch(() => ({}));
}
async function act(what, data = {}) {
  try {
    const r = await api("/api/do/" + what, data);
    if (r && r.ok === false && r.error) toast(r.error);
    return r;
  } catch (e) { if (e.message !== "login") toast("Not reachable: " + e.message); return { ok: false }; }
}
let toastTimer;
function toast(text) {
  const t = $("toast"); t.textContent = text; t.classList.remove("hidden");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add("hidden"), 3800);
}
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
function ago(t) {
  if (!t) return "";
  const m = Math.max(0, Math.round((Date.now() / 1000 - t) / 60));
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`;
}
const fresh = (t) => t && Date.now() / 1000 - t < 90 * 60;

// ---------- login ----------
async function start() {
  const me = await (await fetch("/api/me")).json();
  if (me.authed) return showApp();
  showLogin(me.has_password);
}
function showLogin(hasPassword = true) {
  $("app").classList.add("hidden"); $("ring").classList.add("hidden"); $("login").classList.remove("hidden");
  if (!hasPassword) $("login-hint").textContent = "No password yet: set one on the dashboard (Settings › Web access).";
}
$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault(); $("login-error").textContent = "";
  const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: $("password").value }) });
  if (r.ok) { $("password").value = ""; showApp(); } else $("login-error").textContent = "Wrong password";
});

function showApp() {
  $("login").classList.add("hidden"); $("app").classList.remove("hidden");
  route(); poll(); registerWorker();
}
async function poll() {
  version = 0;
  for (;;) {
    try {
      const d = await api(`/api/wait?v=${version}`);
      version = d.version; Object.assign(P, d.parts); changed(Object.keys(d.parts));
    } catch (e) { if (e.message === "login") return; await sleep(3000); }
  }
}
function changed(keys) {
  const k = new Set(keys);
  if (k.has("state")) renderState();
  if (k.has("news")) renderNews();
  if (k.has("breaking")) renderTicker();
  if (k.has("market")) renderMarket();
  if (k.has("photos")) photoStep(0);
  if (k.has("log")) $("log").textContent = (P.log || []).join("\n") || "No recent events";
  if (k.has("events")) renderEvents();
  if (k.has("notice") && P.notice && Date.now() / 1000 - P.notice.t < 10) toast(P.notice.text);
  if (["settings", "speaker", "camera", "outdoor", "state"].some((x) => k.has(x))) refreshSection(k);
}

// ---------- pages ----------
let page = "home";
function route() {
  const [p, sub] = (location.hash.slice(1) || "home").split("/");
  const was = page;
  page = ["home", "door", "events", "settings"].includes(p) ? p : "home";
  if (page !== was || sub) window.scrollTo(0, 0);
  document.querySelectorAll(".page").forEach((s) => s.classList.toggle("active", s.id === "page-" + page));
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
  if (page !== "door") stopWatching();
  if (page === "door") alertStatus();
  if (page === "settings") openSection(sub || "", !!sub);
}
window.addEventListener("hashchange", route);
function tickClock() {
  const now = new Date();
  $("clock").textContent = now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  $("date").textContent = now.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
}
setInterval(tickClock, 1000); tickClock();

// ---------- state: pills, ring alert, mute ----------
let wasRinging = false, audio = null;
function renderState() {
  const s = P.state || {}, now = Date.now() / 1000;
  const door = $("pill-door");
  door.className = "pill " + (s.door_online === true ? "ok" : s.door_online === false ? "bad" : "");
  door.textContent = s.door_online === true ? "Doorbell online" : s.door_online === false ? "Doorbell offline" : "Doorbell: waiting";
  const muted = s.muted_until && s.muted_until > now;
  $("pill-mute").classList.toggle("hidden", !muted);
  if (muted) $("pill-mute").textContent = "Muted until " + clock(s.muted_until);
  $("mute-status").textContent = muted ? "Muted until " + clock(s.muted_until) : "On: the bell rings inside";
  $("unmute").classList.toggle("hidden", !muted);
  $("watch").disabled = !s.camera; $("live-note").textContent = s.camera ? "Live camera" : "No camera set up (Settings › Camera)";
  const f = s.festival || {};
  $("festival").classList.toggle("hidden", !f.key); $("festival").textContent = f.text || "";
  if (!viewChosen) setView(s.home_view || "news", false);
  // the ring alert
  $("ring").classList.toggle("hidden", !s.ringing);
  if (s.ringing) {
    $("ring-sub").textContent = "Rang at " + clock(s.rang_at) + (muted ? " · bell muted inside" : " · the bell is ringing inside");
    const total = Math.max(1, s.total || 30), left = s.remaining || 0;
    $("cd-text").textContent = left;
    $("cd-arc").style.strokeDashoffset = String(276.5 * (1 - left / total));
    if (!wasRinging) alertRing();
  } else if (wasRinging) {
    $("ring-live").removeAttribute("src");
  }
  wasRinging = !!s.ringing;
}
function alertRing() {
  if (navigator.vibrate) navigator.vibrate([300, 150, 300, 150, 600]);
  try {  // a short two-tone chime (browsers allow it once the page has been touched)
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    [[659, 0], [523, 0.45]].forEach(([f, t]) => {
      const o = audio.createOscillator(), g = audio.createGain(); o.frequency.value = f; o.connect(g); g.connect(audio.destination);
      g.gain.setValueAtTime(0.25, audio.currentTime + t); g.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + t + 1.2);
      o.start(audio.currentTime + t); o.stop(audio.currentTime + t + 1.2);
    });
  } catch (e) {}
  stopWatching();  // one camera stream at a time
  if ((P.state || {}).camera) $("ring-live").src = "/api/live.mjpg?t=" + Date.now();
}
document.addEventListener("click", () => { if (audio && audio.state === "suspended") audio.resume(); });
$("ring-stop").onclick = () => act("stop");
$("ring-mute").onclick = () => act("mute", { minutes: 60 });
document.querySelectorAll("[data-mute]").forEach((b) => b.onclick = () => act("mute", { minutes: +b.dataset.mute }));
$("unmute").onclick = () => act("unmute");

// ---------- home: news or photos ----------
let viewChosen = false, view = "news";
try { if (localStorage.getItem("view")) { view = localStorage.getItem("view"); viewChosen = true; } } catch (e) {}
function setView(v, chosen = true) {
  view = v === "photos" ? "photos" : "news";
  if (chosen) { viewChosen = true; try { localStorage.setItem("view", view); } catch (e) {} }
  document.querySelectorAll("#home-view button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
  for (const id of ["news-view", "more-stories"]) $(id).classList.toggle("hidden", view !== "news");
  $("photos-view").classList.toggle("hidden", view !== "photos");
}
document.querySelectorAll("#home-view button").forEach((b) => b.onclick = () => setView(b.dataset.view));
setView(view, false);

let newsIdx = 0, lastTouch = 0;
function storyPic(it, cls) {
  return it.img ? `<div class="${cls}" style="background-image:url('${esc(it.img)}')"></div>`
    : `<div class="${cls}" style="background:linear-gradient(135deg, ${esc(it.color)}, #0b1220)">${cls === "pic" ? `<div class="card-art">${esc(it.source)}</div>` : esc(it.source)}</div>`;
}
function renderNews(dir = 0) {
  const n = P.news || {}, items = n.items || [], story = $("story");
  if (!items.length) { story.innerHTML = `<div class="text"><p class="muted">${esc(n.note || "Loading news…")}</p></div>`; $("story-list").innerHTML = ""; return; }
  newsIdx = ((newsIdx % items.length) + items.length) % items.length;
  const it = items[newsIdx];
  story.innerHTML = `${storyPic(it, "pic")}
    <div class="text">
      <div class="meta"><span class="badge" style="background:${esc(it.color)}">${esc(it.source)}</span>
        ${fresh(it.time) ? '<span class="badge breaking">Breaking</span>' : ""}<span>${ago(it.time)}</span>
        ${it.tag || it.region ? `<span>${esc([it.region, it.tag].filter(Boolean).join(" · "))}</span>` : ""}</div>
      <h2>${esc(it.title)}</h2>
      ${it.summary ? `<p class="summary">${esc(it.summary)}</p>` : ""}
      <span class="count">${newsIdx + 1} / ${items.length} · swipe or tap ‹ › for more</span>
    </div>
    ${items.length > 1 ? '<button class="nav-arrow left" data-go="-1">‹</button><button class="nav-arrow right" data-go="1">›</button>' : ""}`;
  if (dir) { story.style.setProperty("--from", dir > 0 ? "40px" : "-40px"); story.classList.remove("slide"); void story.offsetWidth; story.classList.add("slide"); }
  if (!dir) renderList();
}
let listAll = false;
function renderList() {
  const items = (P.news || {}).items || [], n = listAll ? items.length : Math.min(12, items.length);
  $("story-list").innerHTML = items.slice(0, n).map((x, i) => `<button class="story-row" data-story="${i}">${storyPic(x, "thumb")}
      <div><b>${esc(x.title)}</b><small>${esc(x.source)} · ${ago(x.time)}</small></div></button>`).join("")
    + (n < items.length ? `<button class="story-row more" data-more="1">Show all ${items.length} stories</button>` : "");
}
function go(d) {
  const items = (P.news || {}).items || [];
  if (items.length < 2) return;
  newsIdx += d; renderNews(d);
}
$("story").addEventListener("click", (e) => { const b = e.target.closest("[data-go]"); if (b) { lastTouch = Date.now(); go(+b.dataset.go); } });
let press = null;
$("story").addEventListener("pointerdown", (e) => { press = e.clientX; });
$("story").addEventListener("pointerup", (e) => {
  if (press === null) return;
  const dx = e.clientX - press; press = null;
  if (Math.abs(dx) > 60) { lastTouch = Date.now(); go(dx < 0 ? 1 : -1); }
});
$("story-list").addEventListener("click", (e) => {
  if (e.target.closest("[data-more]")) { listAll = true; return renderList(); }
  const b = e.target.closest("[data-story]"); if (!b) return;
  lastTouch = Date.now(); newsIdx = +b.dataset.story; renderNews(1); window.scrollTo({ top: 0, behavior: "smooth" });
});
setInterval(() => {  // the story turns by itself every 12 s, unless someone is reading
  if (!document.hidden && page === "home" && view === "news" && Date.now() - lastTouch > 30000) go(1);
}, 12000);

let tickerKey = "";
function renderTicker() {
  const items = P.breaking || [], key = items.map((i) => i.title).join("|");
  if (key === tickerKey) return;
  tickerKey = key;
  const label = document.querySelector(".ticker-label"), run = document.querySelector(".ticker-run");
  const breaking = items.some((i) => fresh(i.time));
  label.textContent = breaking ? "BREAKING" : "LATEST"; label.classList.toggle("latest", !breaking);
  run.innerHTML = items.map((i) => `<span class="src">${esc(i.source)}</span>${esc(i.title)}`).join("") || "Waiting for headlines…";
  requestAnimationFrame(() => { run.style.animationDuration = Math.max(20, run.scrollWidth / 90) + "s"; });
}

const num = (v) => v.toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const pct = (p) => `<span class="${p >= 0 ? "up" : "down"}">${p >= 0 ? "▲" : "▼"} ${Math.abs(p).toFixed(2)}%</span>`;
function renderMarket() {
  const m = P.market || {}, d = m.data, el = $("market");
  if (!d) { el.innerHTML = `<span class="muted">${esc(m.note || "Market data loading…")}</span>`; return; }
  el.innerHTML = d.indices.map((i) => `<span><span class="lbl">${esc(i.name)}</span> <b>${num(i.ltp)}</b> ${pct(i.pct)}</span>`).join("")
    + (d.gainers.length ? `<span><span class="lbl">GAINERS</span> ${d.gainers.map((g) => `<span class="up">${esc(g.symbol)} +${g.pct.toFixed(1)}%</span>`).join(" ")}</span>` : "")
    + (d.losers.length ? `<span><span class="lbl">LOSERS</span> ${d.losers.map((g) => `<span class="down">${esc(g.symbol)} ${g.pct.toFixed(1)}%</span>`).join(" ")}</span>` : "")
    + `<span class="when">${d.open ? "LIVE · " + clock(d.time) : "CLOSED · " + esc(d.session) + " close"}</span>`;
}

let photoIdx = 0, photoLayer = 0;
function photoStep(d) {
  const ph = P.photos || [];
  if (!ph.length) return;
  photoIdx = ((photoIdx + d) % ph.length + ph.length) % ph.length;
  const imgs = [$("photo-a"), $("photo-b")], next = imgs[1 - photoLayer];
  next.onload = () => { next.style.opacity = 1; imgs[photoLayer].style.opacity = 0; photoLayer = 1 - photoLayer; };
  next.src = ph[photoIdx].url;
  $("photo-credit").textContent = ph[photoIdx].credit ? "Photo: " + ph[photoIdx].credit + " / Unsplash" : "";
}
document.querySelectorAll("[data-photo]").forEach((b) => b.onclick = () => photoStep(+b.dataset.photo));
setInterval(() => { if (!document.hidden && page === "home" && view === "photos") photoStep(1); }, 15000);

// ---------- front door ----------
function watch() {
  $("live").src = "/api/live.mjpg?t=" + Date.now();
  $("live-placeholder").classList.add("hidden"); $("live-close").classList.remove("hidden");
}
function stopWatching() {
  if (!$("live").getAttribute("src")) return;
  $("live").removeAttribute("src");
  $("live-placeholder").classList.remove("hidden"); $("live-close").classList.add("hidden");
}
$("watch").onclick = watch; $("live-close").onclick = stopWatching;
document.addEventListener("visibilitychange", () => {  // no camera stream in the background
  if (document.hidden) { stopWatching(); $("ring-live").removeAttribute("src"); }
  else if ((P.state || {}).ringing && (P.state || {}).camera) $("ring-live").src = "/api/live.mjpg?t=" + Date.now();
});

// ---------- recordings ----------
let evFilter = "all", selecting = false, selected = new Set(), current = null;
function when(t) {
  const d = new Date(t * 1000), today = new Date(), y = new Date(Date.now() - 86400000);
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return "Today " + time;
  if (d.toDateString() === y.toDateString()) return "Yesterday " + time;
  return d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }) + " · " + time;
}
function shown() {
  const start = new Date(); start.setHours(0, 0, 0, 0); const t0 = start / 1000;
  return (P.events || []).filter((e) => evFilter === "all" || (evFilter === "today" && e.time >= t0) ||
    (evFilter === "yesterday" && e.time >= t0 - 86400 && e.time < t0) || (evFilter === "week" && e.time >= t0 - 6 * 86400));
}
function renderEvents() {
  document.querySelectorAll("#ev-filter button").forEach((b) => b.classList.toggle("on", b.dataset.f === evFilter));
  const list = shown(), box = $("events");
  box.classList.toggle("selecting", selecting);
  $("ev-select").textContent = selecting ? "Cancel" : "Select";
  $("ev-delete").classList.toggle("hidden", !selecting);
  $("ev-delete").textContent = selected.size ? `Delete ${selected.size}` : "Delete all shown";
  if (!list.length) { box.innerHTML = '<p class="muted">No rings here.</p>'; return; }
  box.innerHTML = list.map((e) => `<button class="event${selected.has(e.time) ? " sel" : ""}" data-t="${e.time}">
    <div class="thumb" ${e.thumb ? `style="background-image:url('/media/${encodeURI(e.thumb)}')"` : ""}>${e.thumb ? "" : esc(e.note || "No recording")}</div>
    <div class="meta"><b>${when(e.time)}</b><span>${e.video ? `▶ ${e.seconds} s` : "No recording"}</span></div><span class="tick">✓</span></button>`).join("");
}
$("events").addEventListener("click", (e) => {
  const b = e.target.closest("[data-t]"); if (!b) return;
  const t = +b.dataset.t, ev = (P.events || []).find((x) => x.time === t);
  if (selecting) { selected.has(t) ? selected.delete(t) : selected.add(t); renderEvents(); } else if (ev) openEvent(ev);
});
document.querySelectorAll("#ev-filter button").forEach((b) => b.onclick = () => { evFilter = b.dataset.f; selected.clear(); renderEvents(); });
$("ev-select").onclick = () => { selecting = !selecting; selected.clear(); renderEvents(); };
$("ev-delete").onclick = async () => {
  const times = selected.size ? [...selected] : shown().map((e) => e.time);
  if (!times.length || !confirm(`Delete ${times.length} recording${times.length > 1 ? "s" : ""}? This cannot be undone.`)) return;
  await act("delete", { times }); selecting = false; selected.clear(); renderEvents();
};
function openEvent(e) {
  current = e; $("player-title").textContent = "Rang the bell"; $("player-sub").textContent = when(e.time);
  const v = $("video");
  if (e.video) { v.classList.remove("hidden"); v.src = "/media/" + encodeURI(e.video); } else { v.classList.add("hidden"); v.removeAttribute("src"); }
  $("player-note").textContent = e.video ? "" : e.note || "No recording";
  $("player").showModal();
}
$("player-close").onclick = () => $("player").close();
$("player").addEventListener("close", () => $("video").pause());
$("player-delete").onclick = async () => {
  if (!current || !confirm("Delete this recording?")) return;
  await act("delete", { times: [current.time] }); $("player").close();
};

// ---------- ring alerts on this device (Web Push) ----------
const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent);
const standalone = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
function deviceName() {
  const ua = navigator.userAgent;
  const dev = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android phone"
    : /Macintosh/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows PC" : /Linux/.test(ua) ? "Linux computer" : "Device";
  const br = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "browser";
  return `${dev} · ${br}`;
}
async function registerWorker() {
  if (!window.isSecureContext || !("serviceWorker" in navigator)) return;
  try { await navigator.serviceWorker.register("/sw.js"); } catch (e) {}
  navigator.serviceWorker.addEventListener("message", (e) => { if (e.data && e.data.go) location.hash = "#" + e.data.go; });
}
async function pushInfo() {
  if (!window.isSecureContext) return { state: "insecure" };
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return { state: isIOS() && !standalone() ? "ios-home" : "unsupported" };
  if (window.Notification && Notification.permission === "denied") return { state: "denied" };
  const reg = await navigator.serviceWorker.getRegistration("/");
  const sub = reg && await reg.pushManager.getSubscription();
  return { state: sub ? "on" : "off", sub, reg };
}
const ALERT_TEXT = {
  insecure: "Alerts need the secure (https) address: see Settings › Web access.",
  "ios-home": "On iPhone: Share › Add to Home Screen, open Doorbell from there, then turn alerts on.",
  unsupported: "This browser cannot receive alerts.",
  denied: "Notifications are blocked for this site in the browser settings.",
  on: "On: a notification with STOP whenever someone rings.",
  off: "Off on this device.",
};
async function alertStatus() { $("alert-status").textContent = ALERT_TEXT[(await pushInfo()).state]; }
function b64ToBytes(s) {
  const b = atob((s + "=".repeat((4 - s.length % 4) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
}
async function alertsOn() {
  const reg = await navigator.serviceWorker.register("/sw.js"); await navigator.serviceWorker.ready;
  const perm = await Notification.requestPermission();
  if (perm !== "granted") { toast("Notifications were not allowed"); return; }
  const k = await api("/api/push/key");
  if (!k.available) { toast("The Pi cannot send alerts yet (pywebpush missing: run setup_pi.sh)"); return; }
  let sub = await reg.pushManager.getSubscription();
  if (sub) await sub.unsubscribe();
  sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(k.key) });
  const r = await api("/api/push/subscribe", { subscription: sub.toJSON(), name: deviceName() });
  toast(r.ok ? "Ring alerts are on for this device" : r.error || "Could not register");
}
async function alertsOff() {
  const { sub } = await pushInfo();
  if (sub) { await api("/api/push/remove", { endpoint: sub.endpoint }); await sub.unsubscribe(); }
  toast("Ring alerts are off for this device");
}
async function alertsTest() {
  const { sub } = await pushInfo();
  if (!sub) return;
  const r = await api("/api/push/test", { endpoint: sub.endpoint });
  toast(r.ok === false ? r.error || "Not sent" : "Test alert sent: it arrives in a few seconds");
}

// ---------- settings ----------
const SECTIONS = [["speaker", "Speaker"], ["tone", "Bell tone"], ["news", "News"], ["festivals", "Festivals"],
  ["phone", "Phone (ntfy)"], ["camera", "Camera"], ["web", "Web access & alerts"], ["outdoor", "Outdoor unit"]];
const DEPENDS = { speaker: ["speaker", "settings"], tone: ["settings"], news: ["settings"], festivals: ["settings", "state"],
  phone: ["settings"], camera: ["camera", "settings"], web: ["settings"], outdoor: ["outdoor", "settings"] };
let section = "speaker", camDirty = false, odTab = "look", pickedMac = null, pickedNet = null, previewAudio = null;
const vals = () => ((P.settings || {}).values || {});
function openSection(key, open) {
  section = SECTIONS.some((s) => s[0] === key) ? key : section;
  $("set-nav").innerHTML = SECTIONS.map(([k, t]) => `<a href="#settings/${k}" class="${k === section ? "on" : ""}">${t}</a>`).join("");
  document.querySelector(".settings").classList.toggle("open", open);
  camDirty = false; renderSection();
}
function refreshSection(keys) {
  if (page !== "settings" || !P.settings) return;
  if (!DEPENDS[section].some((k) => keys.has(k))) return;
  if (section === "camera" && camDirty) return;  // do not overwrite what is being typed
  if (document.activeElement && document.activeElement.closest && document.activeElement.closest("#set-body input")) return;
  renderSection();
}
const chip = (on, label, attrs) => `<button class="chip${on ? " on" : ""}" ${attrs}>${label}</button>`;
const jattr = (v) => esc(JSON.stringify(v));
function choices(title, key, options) {  // one of: [[value, label]]
  return `<h3 class="section">${title}</h3><div class="chips">${options.map(([v, l]) =>
    chip(vals()[key] === v, esc(l), `data-set="${key}" data-v="${jattr(v)}"`)).join("")}</div>`;
}
function multi(title, key, options) {  // any of: [[key, label, colour]]
  const on = vals()[key] || [];
  return `<h3 class="section">${title}</h3><div class="chips">${options.map(([k, l, c]) =>
    chip(on.includes(k), (c ? `<span class="dot" style="background:${esc(c)}"></span>` : "") + esc(l), `data-multi="${key}" data-k="${esc(k)}"`)).join("")}</div>`;
}
function renderSection() {
  const body = $("set-body");
  if (!P.settings) { body.innerHTML = '<p class="muted">Loading…</p>'; return; }
  body.innerHTML = '<a class="button back-link" href="#settings">‹ Settings</a>' + (RENDER[section] || (() => ""))();
  afterRender();
}
const RENDER = {
  speaker() {
    const sp = P.speaker || {};
    return `<h2>Bluetooth speaker</h2><p class="muted">Sound plays on: ${esc(sp.output || "…")}</p>
      <h3 class="section">VOLUME</h3><div class="row"><input type="range" id="vol" min="0" max="100" value="${sp.volume || 0}" style="flex:1"><b id="vol-v">${sp.volume || 0}%</b></div>
      <div class="row" style="margin-top:12px"><button data-act="speaker" data-d='${jattr({ job: "scan" })}'>Search for speakers</button>
        <button data-act="speaker" data-d='${jattr({ job: "test" })}'>Play test sound</button></div>
      <h3 class="section">SPEAKERS (tap one, then choose below)</h3>
      <div class="list">${(sp.devices || []).map((d) => `<div class="item${d.mac === pickedMac ? " on" : ""}" data-mac="${esc(d.mac)}"><span>${esc(d.name)}</span>
        <small class="muted">${d.connected ? "connected" : d.paired ? "paired" : "found"}</small></div>`).join("") || '<p class="muted">No speakers found yet</p>'}</div>
      <div class="row" style="margin-top:10px">${["connect", "disconnect", "forget"].map((j) =>
        `<button data-act="speaker" data-job="${j}">${j[0].toUpperCase() + j.slice(1)}</button>`).join("")}</div>
      <p class="status-line">${esc(sp.status || "Put a new speaker in pairing mode, then search.")}</p>
      ${choices("TWO-WAY TALK WITH THE DOOR (TRIAL, on the wall screen)", "intercom", [[false, "Off"], [true, "On: Talk button on the door screens"]])}`;
  },
  tone() {
    const tones = P.settings.tones, cur = vals().tone; let html = `<h2>Bell tone</h2>
      <p class="muted">Played on the speaker for the whole ring. ▶ plays it here; the button below plays it on the speaker at home.</p>
      <div class="row" style="margin-top:12px"><button data-act="play_tone">🔈 Play the chosen tone on the speaker</button></div>`;
    for (const cat of [...new Set(tones.map((t) => t.cat))]) {
      html += `<h3 class="section">${esc(cat.toUpperCase())}</h3><div class="tone-grid">${tones.filter((t) => t.cat === cat).map((t) =>
        `<div class="tone">${chip(t.rel === cur, esc(t.name), `data-set="tone" data-v="${jattr(t.rel)}"`)}<button class="play" data-preview="${esc(t.rel)}">▶</button></div>`).join("")}</div>`;
    }
    return html;
  },
  news() {
    const s = P.settings;
    return `<h2>News</h2><p class="muted">The home page's news: the channels' top stories with photos, and their newest headlines in the ticker.</p>
      ${multi("CHANNELS (choose any; their stories are mixed)", "news_channels", s.channels.map((c) => [c.key, c.name, c.color]))}
      ${multi("GOOGLE NEWS: REGIONS", "news_regions", s.regions.map((r) => [r.key, r.name]))}
      ${multi("GOOGLE NEWS: TOPICS", "news_genres", s.genres.map((g) => [g.key, g.name]))}`;
  },
  festivals() {
    const s = P.settings, f = (P.state || {}).festival || {};
    return `<h2>Festivals</h2><p class="muted">Around festivals the dashboard and the doorbell switch to a festive theme by themselves.</p>
      ${choices("FESTIVE THEMES", "festival_themes", [[true, "Automatic"], [false, "Off"]])}
      ${choices("FESTIVE BELL TONES", "festival_tones", [[true, "On"], [false, "Off"]])}
      <h3 class="section">COMING UP</h3><div class="list">${s.upcoming.map((u) => `<div class="item"><b>${esc(u.name)}</b><span class="muted">${esc(u.first)} – ${esc(u.last)}</span></div>`).join("")}</div>
      <h3 class="section">TRY ONE FOR A MINUTE ${f.key ? "· showing " + esc(f.text) : ""}</h3>
      <div class="chips">${s.festivals.map((x) => chip(f.key === x.key, esc(x.name), `data-act="festival_try" data-d='${jattr({ key: x.key })}'`)).join("")}
        ${chip(false, "Back to normal", `data-act="festival_try" data-d='${jattr({ key: "" })}'`)}</div>`;
  },
  phone() {
    const n = P.settings.notify;
    return `<h2>Phone notifications (ntfy)</h2>
      <p class="muted">A push notification through the free ntfy app: install it, tap +, subscribe to this topic. Anyone who knows the topic gets the alerts.
        For alerts without an extra app, see Web access & alerts.</p>
      <h3 class="section">TOPIC TO SUBSCRIBE TO</h3><p class="qr-url">${esc(n.topic)}</p><p class="muted">Server: ${esc(n.server)} · ${esc(n.encryption)}</p>
      ${choices("NOTIFY WHEN THE BELL RINGS", "notify", [[true, "On"], [false, "Off"]])}
      <div class="row" style="margin-top:14px"><button data-act="notify_test">Send a test notification</button>
        <button data-act="notify_topic" data-confirm="A new topic stops alerts on every phone subscribed to the old one. Continue?">New topic</button></div>`;
  },
  camera() {
    const c = P.camera || {}, rs = vals().record_seconds;
    const field = (k, label, v, type = "text", ph = "") => `<label class="field"><span>${label}</span><input id="cam-${k}" type="${type}" value="${esc(v)}" placeholder="${esc(ph)}" autocomplete="off"></label>`;
    return `<h2>Camera</h2><p class="muted">The front-door camera. Its login stays on the Pi; the password is never shown or sent to browsers.</p>
      <div class="row" style="align-items:flex-end">${field("ip", "IP ADDRESS", c.ip || "")}<button data-act="camera_find">Find</button></div>
      <div id="cam-found" class="chips" style="margin-top:8px"></div>
      ${field("user", "USERNAME", c.user || "")}
      ${field("password", "PASSWORD", "", "password", c.has_password ? "unchanged (saved)" : "not set")}
      ${field("main", "STREAM (VIGI: stream1)", c.main || "stream1")}
      ${field("sub", "SMALL STREAM, for the live view here (VIGI: stream2)", c.sub || "stream2")}
      <div class="row" style="margin-top:14px"><button data-act="camera_test">Test connection</button><button class="primary" data-act="camera_save">Save</button></div>
      <p id="cam-msg" class="status-line"></p><img id="cam-snap" class="snap hidden" alt="">
      <h3 class="section">RECORDING WHEN THE BELL RINGS</h3>
      <div class="chips">${P.settings.record_choices.map((s) => chip(rs === s, s + " s", `data-set="record_seconds" data-v="${s}"`)).join("")}</div>`;
  },
  web() {
    const w = P.settings.web;
    return `<h2>Web access & ring alerts</h2>
      <h3 class="section">RING ALERTS ON THIS DEVICE</h3><p id="push-state" class="muted">…</p>
      <div class="row" id="push-buttons" style="margin-top:10px"></div>
      <h3 class="section">DEVICES THAT GET RING ALERTS</h3>
      <div class="list">${w.devices.map((d) => `<div class="item"><span>${esc(d.name)}<br><small class="muted">since ${new Date(d.added * 1000).toLocaleDateString()}</small></span>
        <button data-act="push_remove" data-d='${jattr({ id: d.id })}'>Remove</button></div>`).join("") || '<p class="muted">None yet.</p>'}</div>
      <h3 class="section">OPEN IN A BROWSER</h3>
      <div class="list">${w.secure_url ? `<div class="item"><span>Secure, with ring alerts (Tailscale)<br><a class="qr-url" href="${esc(w.secure_url)}">${esc(w.secure_url)}</a></span></div>` : ""}
        ${w.addresses.map((a) => `<div class="item"><span>${esc(a.name)}<br><a class="qr-url" href="${esc(a.url)}">${esc(a.url)}</a></span></div>`).join("")}</div>
      <h3 class="section">CHANGE THE PASSWORD (logs every device out)</h3>
      <label class="field"><span>CURRENT PASSWORD</span><input id="pw-cur" type="password" autocomplete="current-password"></label>
      <label class="field"><span>NEW PASSWORD (at least 6 characters)</span><input id="pw-new" type="password" autocomplete="new-password"></label>
      <label class="field"><span>NEW PASSWORD AGAIN</span><input id="pw-again" type="password" autocomplete="new-password"></label>
      <div class="row" style="margin-top:12px"><button data-act="password">Change password</button><button data-act="logout">Log out of this device</button></div>`;
  },
  outdoor() {
    const o = P.outdoor || {}, st = o.state || {}, c = P.settings.outdoor;
    const od = (key, options) => `<div class="chips">${options.map(([v, l]) => chip(JSON.stringify(st[key]) === JSON.stringify(v), l,
      `data-od='${jattr({ [key]: v })}'`)).join("")}</div>`;
    const status = o.online == null && !Object.keys(st).length ? "Waiting for the outdoor unit…"
      : (o.online ? "● Online" : "○ Offline (its last known settings)") + (st.firmware ? " · firmware " + esc(st.firmware) : "");
    let html = `<h2>Outdoor unit</h2><p class="muted">${status}</p><div class="subtabs">${["look", "sound", "screen", "network"].map((t) =>
      chip(odTab === t, t[0].toUpperCase() + t.slice(1), `data-odtab="${t}"`)).join("")}</div>`;
    if (odTab === "look") {
      html += `<h3 class="section">THEME</h3>${od("theme", c.themes.map((t, i) => [i, esc(t)]))}
        <h3 class="section">BELL COLOUR</h3>${od("bell_color", c.bells.map((b, i) => [i, `<span class="dot" style="background:${esc(b.color)}"></span>${esc(b.name)}`]))}
        <h3 class="section">BELL STYLE</h3>${od("bell_style", c.styles.map((s, i) => [i, (s.icon ? `<img src="${esc(s.icon)}" alt="">` : "") + esc(s.name)]))}
        <h3 class="section">BACKGROUND GLOW</h3>${od("glow", [[false, "Off"], [true, "Aurora (magenta · cyan)"]])}`;
    } else if (odTab === "sound") {
      html += `<h3 class="section">CHIME (the doorbell's own speaker)</h3>${od("chime", c.chimes.map((t, i) => [i, esc(t)]))}
        <h3 class="section">CHIME PLAYS</h3>${od("chime_repeat", [[false, "Once per press"], [true, "For the whole ring"]])}
        <h3 class="section">VOLUME</h3>${od("volume", c.volumes.map((v) => [v.value, esc(v.name)]))}
        <h3 class="section">RING DURATION (seconds)</h3>${od("ring_seconds", c.durations.map((d) => [d, String(d)]))}`;
    } else if (odTab === "screen") {
      const n = { enabled: true, from: 23, to: 6, ...(st.screen_off || {}) }, rep = "screen_off" in st;
      const hour = (h) => `${h % 12 || 12} ${h < 12 ? "AM" : "PM"}`;
      html += `<h3 class="section">SCREEN OFF AT NIGHT (a touch lights it for 30 s; rings always light it)</h3>
        <div class="chips">${chip(rep && n.enabled, "On", `data-od='${jattr({ screen_off: { enabled: true } })}'`)}${chip(rep && !n.enabled, "Off: always lit", `data-od='${jattr({ screen_off: { enabled: false } })}'`)}</div>
        <div class="row" style="margin-top:14px">${["from", "to"].map((k) => `<span class="step"><span class="muted">${k === "from" ? "From" : "Until"}</span>
          <button data-step="${k}" data-d="-1">−</button><b>${rep ? hour(n[k]) : "—"}</b><button data-step="${k}" data-d="1">+</button></span>`).join("")}</div>
        <h3 class="section">RIGHT NOW</h3><p>${"screen_lit" in st ? "Doorbell screen now: " + (st.screen_lit ? "lit" : "off") : "Needs the doorbell firmware with this setting"}</p>
        <div class="row" style="margin-top:10px"><button data-od='${jattr({ command: "screen_on" })}'>Turn screen on</button><button data-od='${jattr({ command: "screen_off" })}'>Turn screen off</button></div>`;
    } else {
      html += `<h3 class="section">NOW</h3><p>${st.wifi_ssid ? `Wi-Fi: ${esc(st.wifi_ssid)} (doorbell IP ${esc(st.ip || "none")})` : "Wi-Fi: not reported yet"}</p>
        <p>Indoor unit address: ${esc(st.broker || "not reported yet")}</p>
        <h3 class="section">CHANGE (Wi-Fi and indoor unit address, applied together)</h3>
        <div class="row"><button data-od='${jattr({ command: "wifi_scan" })}'>Scan networks</button><button data-act="network">Change network…</button></div>
        <div class="list" style="margin-top:10px">${(o.networks || []).map((n, i) => `<div class="item${i === pickedNet ? " on" : ""}" data-net="${i}">
          <span>${esc(n.ssid)}</span><small class="muted">${n.rssi} dBm${n.secure === false ? " · open" : ""}</small></div>`).join("") || '<p class="muted">Scan to list the networks the doorbell sees.</p>'}</div>
        <p class="muted" style="margin-top:10px">Choose a network to move the doorbell to it, or none to only change the indoor unit address. The doorbell keeps the new settings only if it joins and reaches the indoor unit within 60 s.</p>`;
    }
    return html + `<p class="status-line">${esc(o.msg || "")}</p>`;
  },
};
function afterRender() {
  if (section === "web") pushButtons();
  const vol = $("vol");
  if (vol) {
    vol.oninput = () => { $("vol-v").textContent = vol.value + "%"; };
    vol.onchange = () => act("speaker", { job: "volume", value: +vol.value });
  }
  if (section === "camera") $("set-body").querySelectorAll("input").forEach((i) => i.addEventListener("input", () => { camDirty = true; }));
}
async function pushButtons() {
  const info = await pushInfo(), box = $("push-buttons"), w = P.settings.web;
  if (!box) return;
  let text = ALERT_TEXT[info.state];
  if (info.state === "insecure") text = w.secure_url ? "Alerts work on the secure address: open " + w.secure_url + " (with Tailscale on this device) and log in there."
    : "Alerts need HTTPS through Tailscale: see the README (Web access).";
  if (!w.push) text = "The Pi cannot send alerts yet: run setup_pi.sh to install pywebpush.";
  $("push-state").textContent = text;
  box.innerHTML = info.state === "on" ? '<button data-push="test">Send a test alert</button><button data-push="off">Turn off</button>'
    : info.state === "off" && w.push ? '<button class="primary" data-push="on">Turn on ring alerts</button>'
    : info.state === "insecure" && w.secure_url ? `<a class="button primary" href="${esc(w.secure_url)}">Open the secure address</a>` : "";
}
$("set-body").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-set],[data-multi],[data-act],[data-od],[data-preview],[data-mac],[data-net],[data-odtab],[data-step],[data-push]");
  if (!b) return;
  const d = b.dataset;
  if (d.set) return act("set", { key: d.set, value: JSON.parse(d.v) });
  if (d.multi) {
    const on = new Set(vals()[d.multi] || []); on.has(d.k) ? on.delete(d.k) : on.add(d.k);
    return act("set", { key: d.multi, value: [...on] });
  }
  if (d.od) return act("outdoor", { change: JSON.parse(d.od) });
  if (d.odtab) { odTab = d.odtab; return renderSection(); }
  if (d.mac) { pickedMac = d.mac; return renderSection(); }
  if (d.net) { pickedNet = +d.net; return renderSection(); }
  if (d.step) {
    const st = (P.outdoor || {}).state || {}, n = { enabled: true, from: 23, to: 6, ...(st.screen_off || {}) };
    return act("outdoor", { change: { screen_off: { [d.step]: (n[d.step] + +d.d + 24) % 24 } } });
  }
  if (d.preview) {
    if (previewAudio) { previewAudio.pause(); if (previewAudio.dataset.rel === d.preview) { previewAudio = null; return; } }
    previewAudio = new Audio("/tones/" + d.preview.split("/").map(encodeURIComponent).join("/")); previewAudio.dataset.rel = d.preview;
    return previewAudio.play().catch(() => toast("Could not play it here"));
  }
  if (d.push) {
    b.disabled = true;
    try { await ({ on: alertsOn, off: alertsOff, test: alertsTest })[d.push](); } catch (err) { toast("Alerts: " + err.message); }
    b.disabled = false; return pushButtons();
  }
  if (d.confirm && !confirm(d.confirm)) return;
  const a = d.act;
  if (a === "speaker") {
    const data = d.d ? JSON.parse(d.d) : { job: d.job, mac: pickedMac };
    if (data.job === "scan") toast("Searching for 12 s… put the speaker in pairing mode");
    return act("speaker", data);
  }
  if (a === "camera_find" || a === "camera_test" || a === "camera_save") return camera(a, b);
  if (a === "password") {
    const cur = $("pw-cur").value, nw = $("pw-new").value;
    if (nw !== $("pw-again").value) return toast("The two new passwords do not match");
    const r = await fetch("/api/password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current: cur, new: nw }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return toast(j.error || "Not changed");
    toast("Password changed: log in again"); return setTimeout(() => location.reload(), 1500);
  }
  if (a === "logout") { await api("/api/logout", {}); return location.reload(); }
  if (a === "push_remove") {
    if (!confirm("Stop ring alerts on that device? It can turn them on again from its own browser.")) return;
    return api("/api/push/remove", { id: JSON.parse(d.d).id });
  }
  if (a === "network") return changeNetwork();
  return act(a, d.d ? JSON.parse(d.d) : {});
});
function camForm() {
  const v = (k) => ($("cam-" + k) || {}).value || "";
  return { ip: v("ip"), user: v("user"), password: v("password"), main: v("main"), sub: v("sub") };
}
async function camera(a, b) {
  const msg = $("cam-msg");
  if (a === "camera_find") {
    msg.textContent = "Looking for cameras on the network…"; b.disabled = true;
    const r = await act("camera_find"); b.disabled = false;
    const cams = (r && r.cameras) || [];
    msg.textContent = cams.length ? "Cameras found: tap yours" : "No camera found (is it powered and on this network?)";
    $("cam-found").innerHTML = cams.map((c) => `<button class="chip" data-camip="${esc(c.ip)}">${esc(c.name)} · ${esc(c.ip)}</button>`).join("");
    $("cam-found").onclick = (e) => { const x = e.target.closest("[data-camip]"); if (x) { $("cam-ip").value = x.dataset.camip; camDirty = true; } };
  } else if (a === "camera_test") {
    msg.textContent = "Connecting to the camera…"; b.disabled = true;
    const r = await act("camera_test", camForm()); b.disabled = false;
    if (r.ok) { $("cam-snap").src = "data:image/jpeg;base64," + r.jpeg; $("cam-snap").classList.remove("hidden"); msg.textContent = `✓ Camera works: ${r.size}. Press Save to use it.`; }
    else msg.textContent = "✗ " + (r.error || "failed");
  } else {
    const r = await act("camera_save", camForm());
    if (r.ok !== false) { camDirty = false; toast("Saved. The next ring uses it."); renderSection(); }
  }
}
async function changeNetwork() {
  const o = P.outdoor || {}, st = o.state || {}, change = {}, n = (o.networks || [])[pickedNet];
  if (n) {
    let pw = "";
    if (n.secure !== false) {
      pw = prompt(`Wi-Fi password for ${n.ssid}`);
      if (pw === null) return;
      if (pw.length < 8) return toast("A Wi-Fi password has at least 8 characters");
    }
    Object.assign(change, { ssid: n.ssid, password: pw });
  }
  const host = prompt("Indoor unit address: the Pi's IP on the doorbell's network", st.broker || "");
  if (host === null) return;
  if (host.trim() && host.trim() !== st.broker) change.broker = host.trim();
  if (!Object.keys(change).length) return toast("Nothing to change: choose a network or enter a new address");
  act("outdoor", { change: { network: change } });
}

start();
