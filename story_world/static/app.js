"use strict";

const S = { user: null, profilesMeta: null, zeitT: null, episodeId: null, runId: null, world: null, reveal: false, view: "uebersicht", cfg: null, entity: "peoples", jobsRunning: false, sub: "anbieter", settings: null,
  place: null, person: null, open: new Set(), netzFokus: null };
const $ = (sel, el = document) => el.querySelector(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STATUS_LABEL = { neu: "neu", in_arbeit: "KI arbeitet", vorschlag: "Vorschlag bereit", eingearbeitet: "eingearbeitet",
  verworfen: "verworfen", fehler: "Fehler", offen: "offen", uebernommen: "übernommen", laeuft: "läuft", fertig: "fertig",
  abgebrochen: "abgebrochen" };
const chip = (s) => `<span class="chip st-${esc(s)}">${esc(STATUS_LABEL[s] || s)}</span>`;
const who = (c) => `<span class="chip ${esc(c)}">${c === "ki" ? "KI" : c === "nutzer" ? "du" : esc(c)}</span>`;

function store(key, value) { try { localStorage.setItem(key, value); } catch (e) {} }
function load(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }

async function api(path, opts = {}) {
  const headers = { "X-Story-World": "1" };
  if (S.reveal) headers["X-Reveal"] = "1";
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method: opts.method || "GET", headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.fehler || `Fehler ${res.status}`);
  return data;
}
const W = (p) => `/api/w/${S.world}${p}`;

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "bad" ? 9000 : 4000);
}
async function guard(fn) { try { return await fn(); } catch (e) { toast(e.message, "bad"); } }

function modal(html) { $("#modal-box").innerHTML = html; $("#modal").classList.remove("hidden"); }
function closeModal() { $("#modal").classList.add("hidden"); $("#modal-box").innerHTML = ""; }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-close]")) closeModal();
  if (e.target.closest("[data-newworld]")) newWorldDialog();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

// ------------------------------------------------------------ Welten

async function loadWorlds(select) {
  const { welten } = await api("/api/worlds");
  const sel = $("#world-select");
  sel.innerHTML = welten.map((w) => `<option value="${esc(w.slug)}">${esc(w.name)}</option>`).join("");
  if (!welten.length) { S.world = null; return; }
  const wanted = select || load("sw-world");
  S.world = welten.some((w) => w.slug === wanted) ? wanted : welten[0].slug;
  sel.value = S.world;
}
$("#world-select").addEventListener("change", (e) => { S.world = e.target.value; store("sw-world", S.world); S.place = S.person = null; S.open.clear(); render(); });
$("#btn-new-world").addEventListener("click", newWorldDialog);

async function newWorldDialog() {
  const opt = await api("/api/vorlage/optionen").catch(() => null);
  const radio = (name, items, first) => Object.entries(items).map(([k, l]) => `<label class="row small" style="gap:6px;text-transform:none;letter-spacing:0;font-weight:400">
    <input type="radio" name="${name}" value="${k}" ${k === first ? "checked" : ""} style="width:auto"> ${esc(l)}</label>`).join("");
  modal(`<h2>Neue Welt</h2>
  <div class="form">
    <div class="field"><label>Name</label><input id="nw-name" placeholder="z. B. Hauptwelt – bei einer Vorlage sonst ihr Titel"></div>
    <div class="field"><label>Grundidee / Beschreibung (optional)</label><textarea id="nw-desc" rows="2"></textarea></div>
    <div class="field"><label>Womit beginnen?</label>
      ${radio("nw-art", { leer: "Leer", beispiel: "Beispielbestand aus WELT_REGELN.md (Menschen, Aureas, Weltregeln)", vorlage: "Aus einem Buch oder einer Geschichte (Datei)" }, "beispiel")}</div>
    <div id="nw-vorlage" class="stack hidden" style="border-left:3px solid var(--accent);padding-left:12px">
      <div class="field"><label>Datei</label><input type="file" id="nw-file" accept="${opt ? opt.formate.join(",") : ""}">
        <div class="small muted">${opt ? opt.formate.join(" ") : ""} – PDF nur mit installiertem „pdftotext“.</div></div>
      <div class="field"><label>Titel der Vorlage (optional)</label><input id="nw-titel" placeholder="sonst Dateiname"></div>
      <div class="field"><label>Wofür?</label>${opt ? radio("nw-modus", opt.modi, "start") : ""}
        <div class="small muted" id="nw-modus-info"></div></div>
      <div class="field"><label>Genre der Geschichten</label>${opt ? radio("nw-gmodus", opt.genre_modi, "fest") : ""}
        <select id="nw-genre" style="margin-top:6px"><option value="">Genre der Vorlage automatisch erkennen</option>
          ${opt ? opt.genres.map((g) => `<option>${esc(g)}</option>`).join("") : ""}</select></div>
      <div class="field"><label>Wessen Text?</label>
        ${radio("nw-wer", { eigen: "von mir geschrieben", fremd: "Text eines anderen Autors" }, "eigen")}
        <input id="nw-autor" class="hidden" placeholder="Autor des Texts" style="margin-top:6px"></div>
      <div class="note small">Die KI liest die Vorlage abschnittsweise ein (Figuren, Orte, Völker, Technik/Magie, Ereignisse,
        Beziehungen) und erstellt danach einen Steckbrief: Genre, Zusammenfassung, Stand am Ende, Haupthandlung.
        Das läuft im Hintergrund – bei einem ganzen Buch je nach Modell eine Weile. Fortschritt unter „KI-Läufe“.
        ${S.user ? `Der Text wird bei <b>${esc(S.user.name)}</b> unter „Texte als Basis“ abgelegt.` : "Tipp: Mit gewähltem Menschen (oben rechts) wird der Text dort unter „Texte als Basis“ abgelegt."}</div>
    </div>
  </div>
  <div class="row spread"><button class="ghost" data-close="1">Abbrechen</button>
  <button class="primary" id="nw-ok">Anlegen</button></div>`);
  const val = (n) => (document.querySelector(`input[name="${n}"]:checked`) || {}).value;
  const info = { start: "Das Buch ist der Ausgangspunkt – die Welt darf darüber hinaus wachsen.",
    fortsetzung: "Die Welt ist gesetzt: Neue Folgen setzen nach dem Ende des Buchs an, die Welt wird nur erweitert, wo es nötig ist." };
  const sync = () => {
    $("#nw-vorlage").classList.toggle("hidden", val("nw-art") !== "vorlage");
    if ($("#nw-modus-info")) $("#nw-modus-info").textContent = info[val("nw-modus")] || "";
    $("#nw-autor").classList.toggle("hidden", val("nw-wer") !== "fremd");
  };
  document.querySelectorAll('#modal-box input[type="radio"]').forEach((r) => (r.onchange = sync));
  sync();
  $("#nw-name").focus();
  $("#nw-ok").onclick = () => guard(async () => {
    const art = val("nw-art");
    let r;
    if (art === "vorlage") {
      const f = $("#nw-file").files[0];
      if (!f) throw new Error("Bitte eine Datei wählen.");
      $("#nw-ok").disabled = true; $("#nw-ok").textContent = "Lese Datei …";
      try {
        r = await api("/api/worlds/vorlage", { method: "POST", body: { name: $("#nw-name").value, beschreibung: $("#nw-desc").value,
          datei: f.name, daten_b64: b64(await f.arrayBuffer()), titel: $("#nw-titel").value, modus: val("nw-modus"),
          genre_modus: val("nw-gmodus"), genre: $("#nw-genre").value, fremd: val("nw-wer") === "fremd", autor: $("#nw-autor").value,
          profil_id: S.user ? S.user.id : null } });
      } finally { $("#nw-ok").disabled = false; $("#nw-ok").textContent = "Anlegen"; }
    } else {
      r = await api("/api/worlds", { method: "POST", body: { name: $("#nw-name").value,
        beschreibung: $("#nw-desc").value, startbestand: art === "beispiel" } });
    }
    closeModal(); store("sw-world", r.slug); await loadWorlds(r.slug);
    if (r.job) { toast(`Welt angelegt – die KI liest die Vorlage ein (${r.teile} Abschnitt${r.teile === 1 ? "" : "e"}).`, "ok"); pollJobs(); }
    else toast("Welt angelegt.", "ok");
    go("uebersicht");
  });
}

// ------------------------------------------------------------ Spoilerschutz

$("#btn-reveal").addEventListener("click", () => {
  if (!S.reveal && !confirm("Backstage anzeigen? Damit siehst du Geheimnisse, Rätselwahrheiten und KI-Hintergründe – Spoiler!")) return;
  S.reveal = !S.reveal;
  const b = $("#btn-reveal");
  b.classList.toggle("on", S.reveal);
  b.textContent = S.reveal ? "👁 Backstage sichtbar" : "🔒 Spoilerschutz an";
  render();
});

// ------------------------------------------------------------ Einfach / Experte

S.expert = load("sw-experte") === "1";
function applyExpert() {
  document.body.classList.toggle("experte", S.expert);
  const b = $("#btn-expert");
  b.classList.toggle("expert-on", S.expert);
  b.textContent = S.expert ? "🎛 Experte" : "🎛 Einfach";
}
$("#btn-expert").addEventListener("click", () => { S.expert = !S.expert; store("sw-experte", S.expert ? "1" : "0"); applyExpert(); render(); });
applyExpert();

// ------------------------------------------------------------ Navigation

$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-view]");
  if (!b) return;
  go(b.dataset.view);
});
function go(view, id = null) {
  if (view === "laeufe") S.runId = id;
  if (view === "folgen") S.episodeId = id;
  if (view !== "folgen") stopReading();
  S.view = view;
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("active", x.dataset.view === view));
  render();
}

const VIEWS = {};
async function render() {
  const el = $("#view");
  if (!S.world && !["projekt", "einstellungen", "mensch", "stil"].includes(S.view)) {
    el.innerHTML = `<div class="card empty"><h2>Noch keine Welt</h2><p>Lege deine erste Welt an – auf Wunsch mit dem Startbestand aus WELT_REGELN.md.</p>
      <button class="primary" data-newworld="1">+ Neue Welt anlegen</button></div>`;
    return;
  }
  await guard(() => VIEWS[S.view](el));
  if (S.world) guard(updateBadges);
}
async function updateBadges() {
  const o = await api(W("/overview"));
  const bp = $("#badge-proposals"), bg = $("#badge-gaps");
  bp.textContent = o.vorschlaege_offen; bp.classList.toggle("hidden", !o.vorschlaege_offen);
  bg.textContent = o.luecken; bg.classList.toggle("hidden", !o.luecken);
}

// ------------------------------------------------------------ Übersicht

const VORLAGE_MODUS = { start: "Welt aus der Vorlage gestartet", fortsetzung: "Fortsetzung der Vorlage" };
function vorlageCard(o) {
  const v = o.meta.vorlage;
  if (!v) return "";
  const genre = v.genre_name || "";
  const status = v.status === "liest" ? '<span class="chip st-in_arbeit">KI liest die Vorlage ein …</span>'
    : v.status === "analyse_fehlt" ? '<span class="chip st-fehler">Steckbrief fehlt</span> <button class="ki small" id="vl-analyse">Vorlage auswerten</button>'
    : v.status === "fehler" ? '<span class="chip st-fehler">Einlesen fehlgeschlagen – siehe KI-Läufe</span>' : "";
  return `<div class="card stack" style="margin-bottom:14px"><div class="row spread"><div><b>Vorlage: ${esc(v.titel || "")}</b>${v.autor ? ` <span class="muted">von ${esc(v.autor)}</span>` : ""}</div>
      <div class="row small"><span class="chip">${esc(VORLAGE_MODUS[v.modus] || v.modus)}</span>
        <span class="chip">${v.genre_modus === "fest" ? `Genre fest${genre ? `: ${esc(genre)}` : ""}` : "Genre frei"}</span>${status}</div></div>
    ${v.zusammenfassung ? `<div class="small">${esc(v.zusammenfassung)}</div>` : ""}
    ${v.modus === "fortsetzung" && v.ende ? `<div class="note small"><b>Stand am Ende – hier geht es weiter:</b> ${esc(v.ende)}</div>` : ""}
    ${(v.offene_faeden || []).length ? `<div class="small muted">Offene Fäden: ${v.offene_faeden.map(esc).join(" · ")}</div>` : ""}</div>`;
}

VIEWS.uebersicht = async (el) => {
  const o = await api(W("/overview"));
  const b = o.bestand;
  const imp = o.impulse || {};
  el.innerHTML = `
  ${o.ki_eingerichtet ? "" : `<div class="banner"><span><b>Noch keine KI eingerichtet.</b> Pflegen geht schon – damit die KI Impulse einarbeitet und Lücken füllt, richte einen Anbieter ein (dauert zwei Minuten).</span>
    <button class="primary" data-setup="1">Jetzt einrichten</button></div>`}
  <div class="row spread"><h2>${esc(o.meta.name || S.world)}</h2><span class="muted">${esc(o.meta.beschreibung || "")}</span></div>
  ${vorlageCard(o)}
  <div class="grid">
    <div class="card"><h3>Neuer Impuls</h3>
      <div class="form"><div class="field"><input id="q-title" placeholder="Titel, z. B. Schmuggler auf dem Mond Kesh"></div>
      <div class="field"><textarea id="q-content" placeholder="Was soll es in der Welt geben? Ein Volk, ein Ort, ein Informationsstrang, eine Nachricht aus der echten Welt …"></textarea></div></div>
      <div class="row spread"><select id="q-kind">${S.cfg.impuls_arten.map((k) => `<option>${k}</option>`).join("")}</select>
      <button class="ki" id="q-go">An die KI geben</button></div></div>
    <div class="card click" data-go="vorschlaege"><h3>Offene Vorschläge</h3><div class="stat">${o.vorschlaege_offen}</div>
      <div class="muted small">warten auf deine Entscheidung</div></div>
    <div class="card click" data-go="luecken"><h3>Lücken</h3><div class="stat">${o.luecken}</div>
      <div class="muted small">${o.luecken_verborgen ? `+ ${o.luecken_verborgen} im Backstage · ` : ""}fehlende Steckbrief-Angaben</div></div>
    <div class="card click" data-go="impulse"><h3>Impulse</h3>
      <div class="row">${Object.keys(imp).length ? Object.entries(imp).map(([k, v]) => `${chip(k)} <b>${v}</b>`).join(" ") : '<span class="muted">noch keine</span>'}</div></div>
  </div>
  <h3 style="margin-top:22px">Bestand</h3>
  <div class="grid">${Object.entries(b).map(([k, v]) => `
    <div class="card ${k !== "episodes" ? "click" : ""}" data-entity="${k}"><div class="row spread"><span>${esc(v.label)}</span>
      <span class="stat">${v.offen}</span></div>
      ${v.backstage ? `<div class="small locked">+ ${v.backstage} im Backstage</div>` : ""}</div>`).join("")}</div>
  <h3 style="margin-top:22px">Wichtige Termine</h3>
  <div class="card">${o.termine.length ? `<table><tr><th>Weltzeit</th><th>Titel</th><th>Ort</th></tr>${o.termine.map((t) =>
    `<tr><td>${esc(t.world_time)}</td><td>${esc(t.title)}</td><td>${esc(t.location_id__name || "")}</td></tr>`).join("")}</table>`
    : '<div class="muted">Noch keine wichtigen Termine. Markiere Ereignisse als „Wichtiger Termin“.</div>'}</div>`;
  el.querySelectorAll("[data-go]").forEach((c) => (c.onclick = () => go(c.dataset.go)));
  if ($("#vl-analyse")) $("#vl-analyse").onclick = () => guard(async () => {
    await api(W("/vorlage/analyse"), { method: "POST", body: {} }); toast("Die KI wertet die Vorlage aus …"); pollJobs();
  });
  el.querySelectorAll("[data-setup]").forEach((b) => (b.onclick = () => openSettings("anbieter")));
  el.querySelectorAll("[data-entity]").forEach((c) => c.dataset.entity !== "episodes" && (c.onclick = () => { S.entity = c.dataset.entity; go("welt"); }));
  $("#q-go").onclick = () => guard(async () => {
    await api(W("/impulses"), { method: "POST", body: { title: $("#q-title").value, content: $("#q-content").value,
      kind: $("#q-kind").value, ki_sofort: true } });
    toast("Impuls gespeichert – die KI arbeitet daran.", "ok"); pollJobs(); go("impulse");
  });
};

// ------------------------------------------------------------ Impulse

VIEWS.impulse = async (el) => {
  const { impulse } = await api(W("/impulses"));
  el.innerHTML = `<h2>Impulse & Informationsstränge</h2>
  <div class="card stack"><div class="form">
    <div class="row"><div class="field" style="flex:1"><label>Titel</label><input id="i-title"></div>
      <div class="field"><label>Art</label><select id="i-kind">${S.cfg.impuls_arten.map((k) => `<option>${k}</option>`).join("")}</select></div></div>
    <div class="field"><label>Inhalt – was gesetzt ist, ist Kanon. Die KI entwickelt es weiter und füllt die Lücken.</label>
      <textarea id="i-content" style="min-height:120px"></textarea></div></div>
    <div class="row spread"><label class="row" style="margin:0"><input type="checkbox" id="i-now" checked style="width:auto"> KI sofort anwerfen</label>
    <button class="primary" id="i-save">Impuls speichern</button></div></div>
  <div class="stack" style="margin-top:16px">${impulse.length ? impulse.map((i) => `
    <div class="card"><div class="row spread"><div class="row"><b>${esc(i.title)}</b> <span class="chip">${esc(i.kind)}</span> ${chip(i.status)}</div>
      <div class="row">${["neu", "fehler", "eingearbeitet", "verworfen"].includes(i.status) ? `<button class="ki" data-ki="${i.id}">KI anwerfen</button>` : ""}
      ${["neu", "fehler"].includes(i.status) ? `<button class="ghost" data-rej="${i.id}">verwerfen</button>` : ""}
      ${i.status === "vorschlag" ? `<button class="primary" data-goto="1">Vorschlag ansehen</button>` : ""}</div></div>
      <div style="white-space:pre-wrap;margin-top:8px">${esc(i.content)}</div>
      ${i.last_error ? `<div class="err small" style="margin-top:6px">${esc(i.last_error)}</div>` : ""}
      <div class="muted small" style="margin-top:6px">angelegt ${esc(i.created_at)}</div></div>`).join("")
    : '<div class="card empty">Noch keine Impulse. Gib der Welt eine Grundidee, ein Volk, einen Ort oder einen Strang vor.</div>'}</div>`;
  $("#i-save").onclick = () => guard(async () => {
    await api(W("/impulses"), { method: "POST", body: { title: $("#i-title").value, content: $("#i-content").value,
      kind: $("#i-kind").value, ki_sofort: $("#i-now").checked } });
    toast("Impuls gespeichert.", "ok"); if ($("#i-now").checked) pollJobs(); render();
  });
  el.querySelectorAll("[data-ki]").forEach((b) => (b.onclick = () => guard(async () => {
    await api(W(`/impulses/${b.dataset.ki}/ki`), { method: "POST", body: {} }); toast("KI angeworfen."); pollJobs(); render();
  })));
  el.querySelectorAll("[data-rej]").forEach((b) => (b.onclick = () => guard(async () => {
    await api(W(`/impulses/${b.dataset.rej}/verwerfen`), { method: "POST", body: {} }); render();
  })));
  el.querySelectorAll("[data-goto]").forEach((b) => (b.onclick = () => go("vorschlaege")));
};

// ------------------------------------------------------------ Vorschläge

function opHtml(o) {
  const head = `<span class="k">${o.aktion === "anlegen" ? "+ neu" : "✎ ergänzt"}</span> <b>${esc(o.tabelle_label)}</b>${o.ziel ? ` „${esc(o.ziel)}“` : ""}
    ${o.sichtbarkeit === "backstage" ? '<span class="chip backstage">backstage</span>' : ""}`;
  return `<div class="op">${head}<dl>${(o.felder || []).map((f) => `<dt>${esc(f.label)}</dt><dd>${f.wert === "🔒" ? '<span class="locked">🔒 verborgen</span>' : esc(f.wert)}</dd>`).join("")}</dl></div>`;
}

VIEWS.vorschlaege = async (el) => {
  const { vorschlaege } = await api(W("/proposals"));
  const open = vorschlaege.filter((v) => v.status === "offen"), done = vorschlaege.filter((v) => v.status !== "offen");
  const card = (v) => `<div class="card"><div class="row spread"><div class="row">${chip(v.status)}
      <span class="muted small">${esc(v.created_at)} · ${esc(v.model || "")}</span></div>
      ${v.status === "offen" ? `<div class="row"><button class="ghost" data-rej="${v.id}">Verwerfen</button>
        <button class="primary" data-acc="${v.id}" ${v.fehler.length ? "disabled" : ""}>Übernehmen</button></div>` : ""}</div>
    <div class="summary">${esc(v.summary)}</div>
    ${v.fehler.length ? `<div class="err">${v.fehler.map(esc).join("<br>")}</div>` : ""}
    ${v.rueckfragen.length ? `<div class="card" style="border-color:var(--warn)"><b>Rückfragen der KI</b><ul>${v.rueckfragen.map((q) => `<li>${esc(q)}</li>`).join("")}</ul></div>` : ""}
    <details ${v.status === "offen" ? "open" : ""}><summary class="muted">${v.operationen.length} sichtbare Änderung(en)${v.verborgen ? ` · <span class="locked">🔒 ${v.verborgen} verborgen</span>` : ""}</summary>
      ${v.operationen.map(opHtml).join("")}</details>
    ${v.result ? `<div class="muted small">Ergebnis: ${v.result.angelegt} angelegt, ${v.result.ergaenzt} ergänzt${v.result.uebersprungen ? `, ${v.result.uebersprungen} vorhandene Werte geschützt` : ""}</div>` : ""}
    <details><summary class="muted small">Auftrag an die KI</summary><pre class="code">${esc(v.task)}</pre></details></div>`;
  el.innerHTML = `<h2>KI-Vorschläge</h2>
    <p class="muted">Die KI legt nur Neues an oder füllt leere Felder – deine Einträge werden nie überschrieben. Verborgene Elemente (Geheimnisse) werden mit übernommen, ohne dass du sie siehst.
    Ist „automatisch übernehmen“ an (Einstellungen), landen hier nur Vorschläge mit Rückfragen der KI.</p>
    <div class="stack">${open.length ? open.map(card).join("") : '<div class="card empty">Keine offenen Vorschläge.</div>'}</div>
    ${done.length ? `<h3 style="margin-top:22px">Entschieden</h3><div class="stack">${done.map(card).join("")}</div>` : ""}`;
  el.querySelectorAll("[data-acc]").forEach((b) => (b.onclick = () => guard(async () => {
    b.disabled = true;
    const r = await api(W(`/proposals/${b.dataset.acc}/uebernehmen`), { method: "POST", body: {} });
    toast(`Übernommen: ${r.angelegt} angelegt, ${r.ergaenzt} ergänzt.`, "ok"); render();
  })));
  el.querySelectorAll("[data-rej]").forEach((b) => (b.onclick = () => guard(async () => {
    await api(W(`/proposals/${b.dataset.rej}/verwerfen`), { method: "POST", body: {} }); render();
  })));
};

// ------------------------------------------------------------ Folgen

const ABW = [[0, "0 · ruhig – eng am Erwartbaren"], [1, "1 · ab und zu Nebenwege"], [2, "2 · Wendungen"], [3, "3 · wild – Bruch mit der Erwartung"]];
const TYP_LABEL = { gegenwart: "Gegenwart", rueckblende: "Rückblende", vorausblick: "Vorausblick", parallel: "Parallel" };

VIEWS.folgen = async (el) => {
  stopReading();
  if (S.episodeId) return episodeReader(el, S.episodeId);
  const { folgen } = await api(W("/episodes"));
  el.innerHTML = `<div class="row spread"><h2>Folgen</h2><button class="primary" id="ep-new">＋ Neue Folge – Geschichte wählen</button></div>
    <p class="muted">Planer → Autor (kapitelweise) → Kontinuitätsprüfer → Lektor → Archivar. Den Fortschritt siehst du oben und unter „KI-Läufe“.</p>
    ${folgen.length ? `<div class="stack">${folgen.map((f) => `<div class="card click" data-ep="${f.id}">
      <div class="row spread"><div class="row"><span class="stat" style="font-size:20px">${f.release_nr}</span><b>${esc(f.title || "Ohne Titel")}</b>
        <span class="chip">${esc(TYP_LABEL[f.type] || f.type)}</span>${f.form === "geschichte" ? '<span class="chip st-fertig">eigenständige Geschichte</span>' : ""}${f.status === "entwurf" ? '<span class="chip st-offen">Entwurf</span>' : ""}
        ${f.status === "freigabe" ? '<span class="chip st-fehler">wartet auf Freigabe</span>' : ""}${warnChip(f.metrics)}${f.audio_path ? '<span class="chip st-fertig">🎧</span>' : ""}</div>
        <span class="small muted">${f.minuten} min · ${f.word_count || 0} Wörter</span></div>
      <div class="small muted" style="margin-top:4px">${f.genre ? `Genre: ${esc(f.genre)} · ` : ""}${f.age_rating ? `${esc(f.age_rating)} · ` : ""}Strang: ${esc(f.strang || "—")} · Weltzeit ${esc(f.world_start)}–${esc(f.world_end)} · erzeugt ${esc(f.created_at || "")}</div></div>`).join("")}</div>`
      : '<div class="card empty">Noch keine Folgen. „Neue Folge – Geschichte wählen“ – die KI legt fehlende Figuren und Stränge dabei selbst an.</div>'}`;
  $("#ep-new").onclick = () => go("geschichten");
  el.querySelectorAll("[data-ep]").forEach((c) => (c.onclick = () => { S.episodeId = Number(c.dataset.ep); render(); }));
};

function warnCount(m) { return m ? (m.warnungen ? m.warnungen.length : m.warn_anzahl || 0) : 0; }
function warnChip(m) {
  const n = warnCount(m);
  return n ? `<span class="chip st-offen" title="Tabu/Altersfreigabe – blockiert nichts">⚠ ${n} Warnung${n === 1 ? "" : "en"}</span>` : "";
}

function qualityText(raw) {
  let m = raw;
  try { if (typeof raw === "string") m = JSON.parse(raw); } catch (e) { return ""; }
  const codes = Object.values(m.code_wiederholungen || {});
  return `Kanon-Score ${m.kanon_score} (wichtige Hinweise) · Erzähler ${m.erzaehler} · ${m.hinweise} Hinweise gesamt`
    + (codes.length ? ` · Codes bis zu ${Math.max(...codes)}× wiederholt` : "");
}

// ------------------------------------------------------------ Geschichte wählen (Erstellungsseite)

VIEWS.geschichten = async (el) => {
  const [st, o, sz, vc] = await Promise.all([api(W("/stories")), api(W("/overview")), api(W("/szenarien")),
    api("/api/stimmen").catch(() => ({ stimmen: [] }))]);
  const voiceBy = Object.fromEntries(vc.stimmen.map((v) => [v.id, v]));
  const worldVoice = voiceBy[o.meta.einstellungen.stimme || ""];
  const words = Number(o.meta.einstellungen.folge_woerter || 8000);
  const std = Number(o.meta.einstellungen.standard_genre || 0);
  const pick = S.storyPick || { art: "auto" };
  const genreBy = Object.fromEntries(st.genres.map((g) => [g.id, g]));
  const vl = o.meta.vorlage;
  const festGenre = vl && vl.genre_modus === "fest" && vl.genre_id && genreBy[vl.genre_id] ? genreBy[vl.genre_id] : null;
  if (festGenre) st.genres = [festGenre];
  const storyRow = (g) => `<tr class="click${pick.art === "strang" && pick.id === g.id ? " sel" : ""}" data-strang="${g.id}">
      <td><b>${esc(g.title || `Strang ${g.id}`)}</b>${g.premise ? `<div class="small muted">${short(g.premise, 110)}</div>` : ""}</td>
      <td>${esc(g.genre || "")}</td><td>${esc(g.status || "")}</td><td>${g.folgen}</td>
      <td class="small">${g.letzte ? esc(g.letzte.title || "") : '<span class="muted">noch nicht erzählt</span>'}</td>
      <td class="small muted">${esc(g.zeit || "")}</td></tr>`;
  const genreRow = (g) => `<tr class="click${pick.art === "neu" && pick.genre === g.id ? " sel" : ""}" data-genre="${g.id}">
      <td><b>${esc(g.name)}</b></td><td class="small">${short(g.description || "", 140)}</td>
      <td>${g.age_rating ? esc(g.age_rating) : ""}</td>
      <td class="small">${g.taboos ? `<span class="warn-text" title="${esc(g.taboos)}">⚠ Tabus</span>` : ""}</td></tr>`;
  el.innerHTML = `<div class="row spread"><h2>Geschichte wählen</h2><button class="ghost" id="gs-folgen">Alle Folgen →</button></div>
    <p class="muted">Erzähle eine bestehende Geschichte weiter oder beginne eine neue im gewünschten Genre. Die nächste Folge entsteht dann
      über Planer → Autor → Prüfer → Lektor → Archivar.</p>
    ${sz.offen.map((set) => `<div class="card stack"><h3 style="margin:0">Szenarien warten auf deine Wahl</h3>
      <p class="small muted">${set.erwartung && set.erwartung.erwartung ? `Erwartet hätte der Hörer: ${esc(set.erwartung.erwartung)}` : ""}
        ${S.reveal ? "" : " · Widersprüche und Begründungen siehst du mit Backstage."}</p>
      <div class="cmp">${(set.szenarien || []).map((p, i) => { const b = (set.bewertungen || [])[i] || {};
        return `<div class="card stack scen"><b>${i + 1}. ${esc(p.titel || "")}</b><span class="small muted">Stufe ${esc(p.abweichung)}</span>
          ${p.idee ? `<div class="small">${esc(p.idee)}</div>` : ""}
          <div class="small">Kanon <b>${fmtVal("", b.kanonpassung)}</b>/10 · Überraschung <b>${fmtVal("", b.ueberraschung)}</b>/10${b.fair === false ? " · ⚠ unfair" : ""}</div>
          ${b.widersprueche && b.widersprueche.length ? `<ul class="small">${b.widersprueche.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
          ${b.begruendung ? `<div class="small muted">${esc(b.begruendung)}</div>` : ""}
          <button class="ki" data-take="${set.id}:${i + 1}">Dieses Szenario erzählen</button></div>`; }).join("")}</div>
      <div class="row" style="justify-content:flex-end"><button class="ghost" data-drop="${set.id}">Alle verwerfen</button></div></div>`).join("")}
    <div class="card" id="gs-form"></div>
    <div class="row spread" style="margin-top:26px"><h3 style="margin:0">Geschichten <span class="muted">${st.geschichten.length || ""}</span></h3>
      <span class="small muted">Klick öffnet die Geschichte: wer drin ist, wo sie spielt, wohin sie läuft.</span></div>
    <div class="card" style="margin-top:8px">${st.geschichten.length
      ? `<table class="liste"><tr><th>Geschichte</th><th>Genre</th><th>Status</th><th>Folgen</th><th>Zuletzt</th><th>Weltzeit</th></tr>${st.geschichten.map(storyRow).join("")}</table>`
      : '<p class="small muted">Noch keine Geschichten – wähle ein Genre, die KI legt den ersten Strang selbst an.</p>'}</div>
    <h3 style="margin-top:26px">Neue Geschichte beginnen – Genres</h3>
    <p class="small muted">⚠ Tabus der Genres sind Vorgaben – nicht jedes Modell hält sich daran. Verstöße erscheinen als Warnung an der Folge.</p>
    <div class="card">${st.genres.length ? `<table><tr><th>Genre</th><th>Kern</th><th>Vorgabe Alter</th><th>Tabus</th></tr>${st.genres.map(genreRow).join("")}</table>`
      : '<p class="small muted">Noch keine Genres.</p>'}</div>`;
  const form = () => {
    const p = S.storyPick || { art: "auto" };
    const s = p.art === "strang" ? st.geschichten.find((x) => x.id === p.id) : null;
    const gid = p.art === "neu" ? p.genre : s ? s.genre_id : std || null;
    const g = gid ? genreBy[gid] : null;
    const preset = (s && s.letzte && s.letzte.age_rating) || "";
    const title = p.art === "neu" ? `Neue Geschichte: ${esc(g ? g.name : "")}` : s ? `Weiter mit „${esc(s.title || "")}“` : "Nächste Folge – Planer entscheidet";
    const cur = p.art === "strang" ? `s:${p.id}` : p.art === "neu" ? `g:${p.genre}` : "auto";
    $("#gs-form").innerHTML = `<div class="row spread"><h3 style="margin:0">${title}</h3>
        ${s ? `<button class="ghost small" id="gs-info">Worum geht es? ↗</button>` : ""}</div>
      <div class="form" style="margin-top:10px"><div class="field"><label>Grundlage</label><select id="gs-basis">
        <option value="auto" ${cur === "auto" ? "selected" : ""}>Planer entscheidet (passende Geschichte oder neue)</option>
        ${st.geschichten.length ? `<optgroup label="Weitererzählen">${st.geschichten.map((x) => `<option value="s:${x.id}" ${cur === `s:${x.id}` ? "selected" : ""}>${esc(x.title || `Strang ${x.id}`)} (${x.folgen} Folge${x.folgen === 1 ? "" : "n"})</option>`).join("")}</optgroup>` : ""}
        ${st.genres.length ? `<optgroup label="Neue Geschichte im Genre">${st.genres.map((x) => `<option value="g:${x.id}" ${cur === `g:${x.id}` ? "selected" : ""}>Neu: ${esc(x.name)}</option>`).join("")}</optgroup>` : ""}
        </select>${s && s.premise ? `<div class="small muted" style="margin-top:4px">${short(s.premise, 220)}</div>` : ""}</div></div>
      <div class="form">
      <div class="field"><label>Wunsch (optional, keine feste Regel)</label>
        <textarea id="ep-wish" placeholder="z. B. etwas Ruhiges auf dem Mars, ein Wiedersehen, mehr Alltag der Raumfahrer …"></textarea></div>
      <details class="field"><summary class="small">Anfang · Mitte · Ende selbst vorgeben (optional, verbindlich)</summary>
        <div class="stack" style="margin-top:8px">
          <div class="field"><label>Anfang – wer, wie es ihr/ihm geht, Lage, Ort</label>
            <textarea id="ep-anfang" rows="2" placeholder="z. B. Iva, 23, gerade aus der Ausbildung raus, vom Vater vor die Tür gesetzt – genervt, sitzt mit Rucksack an der Küstenbasis"></textarea></div>
          <div class="field"><label>Mitte – was passieren soll</label><textarea id="ep-mitte" rows="2"></textarea></div>
          <div class="field"><label>Ende – womit die Folge zur Ruhe kommt</label><textarea id="ep-ende" rows="2"></textarea></div>
          <div class="small muted">Leer = der Planer entscheidet. Jede Folge beginnt ohnehin mit einer Figur, Gefühl, Lage und Ort.</div></div></details>
      <div class="row">
        ${festGenre ? `<div class="field" style="flex:1"><label>Genre</label><div class="small" style="padding:9px 0">🔒 ${esc(festGenre.name)} – durch die Vorlage festgelegt</div></div>`
          : p.art === "neu" ? "" : `<div class="field" style="flex:1"><label>Genre dieser Folge</label><select id="ep-genre" style="width:100%">
          <option value="">${s && s.genre ? `wie die Geschichte (${esc(s.genre)})` : std ? `Welt-Standard (${esc((genreBy[std] || {}).name || "")})` : "automatisch"}</option>
          ${st.genres.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></div>`}
        <div class="field"><label>Altersfreigabe (legst du fest)</label><select id="ep-age">
          <option value="">${g && g.age_rating ? `Vorgabe des Genres (${esc(g.age_rating)})` : "keine Angabe"}</option>
          ${st.altersstufen.map((a) => `<option${a === preset ? " selected" : ""}>${esc(a)}</option>`).join("")}</select></div>
        <div class="field"><label>Länge (Wörter)</label><input id="ep-words" type="number" min="500" max="20000" step="500" value="${words}"></div>
        <div class="field"><label>Überraschung</label><select id="ep-abw"><option value="">${s && s.abweichung != null ? "wie die Geschichte" : g && g.abweichung != null ? "wie das Genre" : "Welt-Standard"}</option>
          ${ABW.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></div>
        <div class="field"><label>Form</label><select id="ep-form" title="Folge: setzt die Reihe fort. Geschichte: in sich abgeschlossen, für Hörer ohne Vorwissen – trotzdem Teil der Welt.">
          <option value="folge">Folge der Reihe</option><option value="geschichte">Eigenständige Geschichte</option></select></div>
        <div class="field"><label>Stimme (Schreibstil)</label><select id="ep-voice">
          <option value="">${s && voiceBy[s.stimme_id] ? `wie die Geschichte (${esc(voiceBy[s.stimme_id].name)})` : worldVoice ? `Welt-Standard (${esc(worldVoice.name)})` : "keine – Erzählprofil"}</option>
          ${vc.stimmen.map((v) => `<option value="${v.id}">${esc(v.name)}</option>`).join("")}</select></div>
        <div class="field expert"><label>Szenarien</label><select id="ep-szen"><option value="">Welt-Standard</option>
          <option value="1">1 – direkt</option><option value="2">2 – Bewerter wählt</option><option value="3">3 – Bewerter wählt</option></select></div></div>
      <p class="small muted" id="ep-min"></p>
      <div class="note small">ℹ Die Altersfreigabe ist deine Entscheidung: Autor und Lektor richten sich danach, der Prüfer bewertet sie nicht neu.
        ${preset ? `Vorausgewählt ist die Freigabe der letzten Folge (${esc(preset)}).` : ""}<br>
        ⚠ Nicht jedes Modell schreibt jedes Genre oder jede Freigabe mit. Verweigert ein Modell, springt automatisch die nächste Wahl
        unter „Modelle je Aufgabe → Autor“ ein. Tabus sind Vorgaben, keine Garantie – Verstöße erscheinen als Warnung an der Folge.</div>
      <p class="small muted">Stil kommt von der Stimme (Seite „Schreibstil“), Publikum und Tabus vom Erzählprofil:
        ${S.user ? `<b>${esc(S.user.name)}</b>` : "kein Profil gewählt – oben rechts „👤“"}.
        ${!vc.stimmen.length ? ' Noch keine Stimme angelegt – <a href="#" id="ep-to-stil">jetzt anlegen</a>.' : ""}</p></div>
      <div class="row" style="justify-content:flex-end"><button class="ki" id="ep-go">Folge erzeugen</button></div>`;
    $("#gs-basis").onchange = (e) => {
      const v = e.target.value;
      choose(v === "auto" ? { art: "auto" } : v.startsWith("s:") ? { art: "strang", id: Number(v.slice(2)) } : { art: "neu", genre: Number(v.slice(2)) });
    };
    if ($("#gs-info")) $("#gs-info").onclick = () => storyDialog(s.id, choose);
    const upd = () => { $("#ep-min").textContent = `≈ ${Math.round(Number($("#ep-words").value) / 135)} Minuten Hörzeit. Für einen ersten Probelauf reichen 1500–2500 Wörter.`; };
    $("#ep-words").oninput = upd; upd();
    if ($("#ep-to-stil")) $("#ep-to-stil").onclick = (e) => { e.preventDefault(); S.stimmeNeu = true; go("stil"); };
    $("#ep-go").onclick = () => guard(async () => {
      $("#ep-go").disabled = true;
      try {
        await api(W("/episodes/ki"), { method: "POST", body: {
          wunsch: $("#ep-wish").value, woerter: Number($("#ep-words").value),
          anfang: $("#ep-anfang").value, mitte: $("#ep-mitte").value, ende: $("#ep-ende").value,
          thread_id: p.art === "strang" ? p.id : null, neue_geschichte: p.art === "neu",
          genre_id: p.art === "neu" ? p.genre : ($("#ep-genre") && $("#ep-genre").value) || null,
          altersfreigabe: $("#ep-age").value || null, profil_id: S.user ? S.user.id : null,
          abweichung: $("#ep-abw").value || null, szenarien: ($("#ep-szen") && S.expert && $("#ep-szen").value) || null,
          stimme_id: $("#ep-voice").value || null, form: $("#ep-form").value } });
      } finally { $("#ep-go").disabled = false; }
      toast("Die Folge entsteht – Fortschritt oben rechts und unter „KI-Läufe“."); pollJobs();
    });
  };
  const choose = (p, scroll = false) => {
    S.storyPick = p;
    el.querySelectorAll("[data-strang],[data-genre]").forEach((c) => c.classList.toggle("sel",
      (p.art === "strang" && Number(c.dataset.strang) === p.id) || (p.art === "neu" && Number(c.dataset.genre) === p.genre)));
    form();
    if (scroll) $("#gs-form").scrollIntoView({ behavior: "smooth", block: "start" });
  };
  el.querySelectorAll("[data-strang]").forEach((c) => (c.onclick = () => storyDialog(Number(c.dataset.strang), (x) => choose(x, true))));
  el.querySelectorAll("[data-genre]").forEach((c) => (c.onclick = () => choose({ art: "neu", genre: Number(c.dataset.genre) }, true)));
  $("#gs-folgen").onclick = () => go("folgen");
  el.querySelectorAll("[data-take]").forEach((b) => (b.onclick = () => guard(async () => {
    const [id, nr] = b.dataset.take.split(":");
    await api(W(`/szenarien/${id}/waehlen`), { method: "POST", body: { nr: Number(nr), profil_id: S.user ? S.user.id : null } });
    toast("Die Folge entsteht aus deinem Szenario – Fortschritt oben rechts."); pollJobs(); render();
  })));
  el.querySelectorAll("[data-drop]").forEach((b) => (b.onclick = () => confirm("Diese Szenarien verwerfen?") && guard(async () => {
    await api(W(`/szenarien/${b.dataset.drop}/verwerfen`), { method: "POST", body: {} }); render();
  })));
  if (pick.art === "strang" && !st.geschichten.some((x) => x.id === pick.id)) S.storyPick = { art: "auto" };
  if (pick.art === "neu" && !genreBy[pick.genre]) S.storyPick = { art: "auto" };
  form();
};

async function storyDialog(id, onPick) {
  const d = await api(W(`/stories/${id}`));
  const sec = (t, body) => (body ? `<div class="story-sec"><h4>${t}</h4>${body}</div>` : "");
  const chips = [d.genre, d.status, d.ebene && `Ebene ${d.ebene}`, d.massstab, d.zeit].filter(Boolean).map((c) => `<span class="chip">${esc(c)}</span>`).join("");
  const figuren = d.figuren.length ? `<ul class="story-list">${d.figuren.map((f) => `<li><a href="#" data-fig="${f.id}"><b>${esc(f.anzeige)}</b></a>
      ${f.pov ? '<span class="chip st-fertig">Erzählperspektive</span>' : ""}
      <span class="small muted">${[f.role, f.volk, f.gender].filter(Boolean).map(esc).join(" · ")}</span></li>`).join("")}</ul>` : '<p class="small muted">Noch keine Figuren zugeordnet.</p>';
  const orte = d.orte.length ? `<ul class="story-list">${d.orte.map((o) => `<li><a href="#" data-ort="${o.id}">${o.haupt ? `<b>${esc(o.name)}</b>` : esc(o.name)}</a>
      ${o.haupt ? '<span class="chip">Hauptort</span>' : ""}${o.pfad !== o.name ? `<div class="small muted">${esc(o.pfad)}</div>` : ""}</li>`).join("")}</ul>` : '<p class="small muted">Kein Ort festgelegt.</p>';
  const z = d.zuletzt;
  const richtung = (d.praemisse ? `<p>${esc(d.praemisse)}</p>` : "")
    + (z ? `<div class="small muted" style="margin-top:8px">Zuletzt: „${esc(z.titel || "")}“</div>${z.zusammenfassung ? `<p>${esc(z.zusammenfassung)}</p>` : ""}
      ${z.uebergabe ? `<div class="note"><b>So endet es / hier geht es weiter:</b> ${esc(z.uebergabe)}</div>` : ""}` : '<p class="small muted">Noch keine Folge erzählt – die erste legt die Richtung fest.</p>')
    + (d.ripples && d.ripples.length ? `<div class="small locked" style="margin-top:8px"><b>Backstage – kommt noch:</b><ul>${d.ripples.map((r) => `<li>${esc(r.wirkung)} <span class="muted">(ab Weltzeit ${esc(r.ab)})</span></li>`).join("")}</ul></div>` : "");
  const folgen = d.folgen.length ? `<table class="small">${d.folgen.map((f) => `<tr class="click" data-goto-folge="${f.id}"><td style="width:60px">${f.form === "geschichte" ? "Gesch." : `Folge ${f.nr}`}</td>
      <td><b>${esc(f.titel || "")}</b>${f.zusammenfassung ? `<div class="muted">${short(f.zusammenfassung, 160)}</div>` : ""}</td></tr>`).join("")}</table>` : "";
  modal(`<div class="row spread"><h2 style="margin:0">${esc(d.titel || `Strang ${d.id}`)}</h2></div>
    <div class="row small" style="margin:6px 0 4px">${chips}</div>
    ${sec("Worum es geht und wohin es läuft", richtung)}
    <div class="story-cols">${sec("Wer ist dabei", figuren)}${sec("Wo es spielt", orte)}</div>
    ${sec(`Bisherige Folgen (${d.folgen.length})`, folgen)}
    <div class="row spread" style="margin-top:14px"><button class="ghost" data-close="1">Schließen</button>
      <button class="primary" id="sd-pick">Davon eine weitere Folge →</button></div>`);
  $("#sd-pick").onclick = () => { closeModal(); onPick({ art: "strang", id: d.id }); };
  document.querySelectorAll("#modal-box [data-fig]").forEach((a) => (a.onclick = (e) => {
    e.preventDefault(); closeModal(); S.entity = "characters"; S.person = Number(a.dataset.fig); S.place = null; go("welt"); }));
  document.querySelectorAll("#modal-box [data-ort]").forEach((a) => (a.onclick = (e) => {
    e.preventDefault(); closeModal(); S.entity = "locations"; S.place = Number(a.dataset.ort); S.person = null; S.open.add(S.place); go("welt"); }));
  document.querySelectorAll("#modal-box [data-goto-folge]").forEach((r) => (r.onclick = () => { closeModal(); go("folgen", Number(r.dataset.gotoFolge)); }));
}

async function episodeReader(el, id) {
  const f = await api(W(`/episodes/${id}`));
  const speakers = [...new Set(f.segmente.map((s) => s.sprecher))];
  el.innerHTML = `<div class="stack"><div class="row"><button class="ghost" id="ep-back">← Alle Folgen</button>
      <h2 style="margin:0">${f.form === "geschichte" ? "Geschichte" : `Folge ${f.release_nr}`}: ${esc(f.title || "")}</h2>${f.status === "entwurf" ? '<span class="chip st-offen">Entwurf</span>' : ""}</div>
    <div class="card row spread"><div class="row">
        <button class="primary" id="rd-play">▶ Vorlesen</button><button class="ghost" id="rd-pause">❚❚ Pause</button><button class="ghost" id="rd-stop">■ Stopp</button>
        <select id="rd-rate"><option value="0.85">langsam</option><option value="0.95" selected>ruhig</option><option value="1.05">normal</option></select>
        <a class="small" href="${W(`/episodes/${id}/export.pdf`)}">Als PDF</a>
        <a class="small" href="${W(`/episodes/${id}/export`)}">Als Text für das Audiobook Studio</a></div>
      <span class="small muted">${f.minuten} min · ${esc(TYP_LABEL[f.type] || f.type)}${f.genre ? ` · ${esc(f.genre)}` : ""}${f.age_rating ? ` · ${esc(f.age_rating)}` : ""} · Strang: ${esc(f.strang || "—")} · ${speakers.length} Stimmen</span></div>
    ${f.status === "freigabe" ? `<div class="banner"><span><b>${f.metrics && f.metrics.freigabe_gruende ? "Die Folge wartet auf dich:" : "Der Prüfer hat schwere Probleme gefunden."}</b>
      ${f.metrics && f.metrics.freigabe_gruende ? `<ul class="small">${f.metrics.freigabe_gruende.map((g) => `<li>${esc(g)}</li>`).join("")}</ul>` : ""}
      Die Folge zählt erst nach deiner Freigabe für die Fortsetzung. Details im KI-Lauf (mit Backstage) und unten im Stil-Abgleich.</span>
      <button class="primary" id="rd-release">Freigeben</button></div>` : ""}
    ${warnCount(f.metrics) ? `<div class="banner warn"><span><b>⚠ ${warnCount(f.metrics)} Warnung${warnCount(f.metrics) === 1 ? "" : "en"} zu
      ${esc((f.metrics.warn_arten || ["Tabu"]).join(" / "))}.</b> Nicht jedes Modell hält sich an Tabus. Die Folge ist trotzdem fertig – lies sie
      vorher selbst${f.age_rating ? `, Altersfreigabe: ${esc(f.age_rating)}` : ""}.
      ${f.metrics.warnungen ? `<ul class="small">${f.metrics.warnungen.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>`
        : "<br><span class='small'>Details (können Handlung verraten) mit „Spoilerschutz aus“.</span>"}</span></div>` : ""}
    <div class="card row spread"><div class="row">${f.audio_path ? `<audio controls preload="none" src="${W(`/episodes/${id}/audio`)}" style="height:36px"></audio>` : ""}
        <button class="ki" id="rd-audio">${f.audio_path ? "Hörbuch neu erzeugen" : "🎧 Hörbuch erzeugen"}</button>
        <a class="small" href="${W(`/episodes/${id}/export.json`)}" target="_blank">Segmente als JSON (für anderes TTS)</a></div>
      ${f.metrics ? `<span class="small muted">Qualität: ${qualityText(f.metrics)}</span>` : ""}</div>
    <div id="rd-tts"></div>
    <div id="rd-style"></div>
    ${f.metrics && f.metrics.qualitaet ? `<div class="card small expert">Messwerte dieser Folge (per Code):
      ${Object.entries(f.metrics.qualitaet).filter(([k]) => k !== "fehler").map(([k, v]) => `${esc((S.qtests && S.qtests[k]) || k)}: <b>${Array.isArray(v) ? v.map((x) => fmtVal("", x)).join("/") : fmtVal(k, v)}</b>`).join(" · ")}
      · <a href="#" id="rd-q">Qualität der Modelle →</a></div>` : ""}
    <div class="card reader" id="rd-text">${f.segmente.map((s, i) => s.typ === "narrator"
      ? `<p class="seg" data-i="${i}">${esc(s.text)}</p>`
      : `<p class="seg say" data-i="${i}"><span class="who">${esc(s.sprecher)}</span>${esc(s.text)}</p>`).join("")}</div>
    ${f.summary ? `<details class="card"><summary>Zusammenfassung (für später)</summary><p>${esc(f.summary)}</p></details>` : ""}
    ${S.reveal && f.plan ? `<details class="card"><summary>Backstage: Plan und Prüfbericht</summary>
      <pre class="live">${esc(JSON.stringify({ plan: f.plan, pruefung: f.check_report }, null, 1))}</pre></details>` : ""}
    ${f.run_id ? `<button class="ghost" id="rd-run">Entstehung ansehen (KI-Lauf)</button>` : ""}</div>`;
  $("#ep-back").onclick = () => { stopReading(); S.episodeId = null; render(); };
  if ($("#rd-release")) $("#rd-release").onclick = () => guard(async () => {
    await api(W(`/episodes/${id}/freigeben`), { method: "POST", body: {} }); toast("Freigegeben.", "ok"); render();
  });
  $("#rd-audio").onclick = () => guard(async () => {
    await api(W(`/episodes/${id}/audio`), { method: "POST", body: {} }); toast("Hörbuch wird erzeugt – Fortschritt oben rechts."); pollJobs();
  });
  if ($("#rd-run")) $("#rd-run").onclick = () => go("laeufe", f.run_id);
  if ($("#rd-q")) $("#rd-q").onclick = (e) => { e.preventDefault(); openSettings("qualitaet"); };
  $("#rd-play").onclick = () => startReading(f.segmente, Number($("#rd-rate").value));
  $("#rd-pause").onclick = () => { const s = window.speechSynthesis; if (!s) return; s.paused ? s.resume() : s.pause(); };
  $("#rd-stop").onclick = stopReading;
  el.querySelectorAll(".seg").forEach((p) => (p.ondblclick = () => startReading(f.segmente, Number($("#rd-rate").value), Number(p.dataset.i))));
  guard(() => ttsCard(id));
  styleCard($("#rd-style"), id, f.metrics && f.metrics.stilbericht);
}

const STYLE_WORD = { passt: "passt", auffaellig: "auffällig", stark: "deutlich anders", zu_kurz: "zu kurz", unklar: "unklar" };
function styleChip(wert, urteil) {
  const cls = urteil === "passt" ? "st-fertig" : urteil === "stark" ? "st-fehler" : "st-offen";
  return `<span class="chip ${cls}">${wert == null ? "–" : `${wert}/100`} · ${esc(STYLE_WORD[urteil] || urteil || "")}</span>`;
}

// Stil-Abgleich einer Folge: gespeicherter Bericht (beim Schreiben gemessen) oder auf Abruf gegen eine gewählte Stimme.
async function styleCard(box, id, stored, stimme) {
  if (!box) return;
  let live = null;
  if (!stored || stimme !== undefined) {
    try { live = await api(W(`/episodes/${id}/stil${stimme ? `?stimme=${encodeURIComponent(stimme)}` : ""}`)); } catch (e) { box.innerHTML = ""; return; }
  }
  const b = live ? live.bericht : stored;
  const off = b && b.merkmale ? b.merkmale.filter((m) => m.urteil !== "passt") : [];
  const ok = b && b.merkmale ? b.merkmale.filter((m) => m.urteil === "passt") : [];
  const row = (m) => `<tr class="${m.urteil === "stark" ? "bad-row" : m.urteil === "auffaellig" ? "warn-row" : ""}"><td>${esc(m.label)}</td>
    <td><b>${esc(m.folge_text)}</b></td><td>${esc(m.vorbild_text)}</td><td class="muted">${esc(m.spanne_text)}</td>
    <td>${m.urteil === "passt" ? "✔" : m.urteil === "stark" ? "✖ " + esc(m.satz) : "⚠ " + esc(m.satz)}</td></tr>`;
  box.innerHTML = `<div class="card stack"><div class="row spread"><h3 style="margin:0">Stil-Abgleich ${b ? styleChip(b.wert, b.urteil) : ""}</h3>
      <div class="row small"><span class="muted">vergleichen mit</span><select id="sty-voice"><option value="">${live && live.stimme ? `Stimme der Folge (${esc(live.stimme.name)})` : b && b.stimme ? `beim Schreiben: ${esc(b.stimme.name)}` : "Stimme der Folge"}</option></select></div></div>
    ${b ? `<p>${esc(b.satz)} <span class="small muted">Maßstab: ${esc(b.quelle || "–")}${b.titel ? ` („${esc(b.titel)}“)` : ""}${b.gemessen ? ` · gemessen ${esc(b.gemessen)}` : ""}</span></p>
      ${b.merkmale && b.merkmale.length ? `<table class="qtable small"><tr><th>Merkmal</th><th>Folge</th><th>Vorbild</th><th>normal beim Vorbild</th><th></th></tr>
        ${off.map(row).join("")}</table>
        ${ok.length ? `<details><summary class="small muted">${ok.length} Merkmale im Rahmen</summary><table class="qtable small"><tr><th>Merkmal</th><th>Folge</th><th>Vorbild</th><th>normal beim Vorbild</th><th></th></tr>${ok.map(row).join("")}</table></details>` : ""}` : ""}
      ${b.auffaellige_woerter && b.auffaellige_woerter.length ? `<div class="small"><b>Auffällig oft benutzt</b> (beim Vorbild selten – oft KI-Lieblingswörter):
        ${b.auffaellige_woerter.map((w) => `<span class="chip">${esc(w.wort)} ${w.anzahl}×</span>`).join(" ")}</div>` : ""}
      ${b.urteil !== "passt" ? `<p class="small muted">Eingreifen: An der Stimme Regler oder „Hinweise an die Stimme“ anpassen (z. B. „Erzählzeit Präteritum“, „kürzere Sätze“)
        und die Folge neu erzeugen – oder sie so freigeben. Die Messung ändert nichts an der Folge.</p>` : ""}`
      : '<p class="small muted">Kein Maßstab vorhanden – Stimme mit Fingerabdruck wählen.</p>'}
    ${live && live.erkennung && live.erkennung.rangliste.length ? `<div class="small muted">${esc(live.erkennung.satz)}</div>` : ""}</div>`;
  const sel = $("#sty-voice");
  const fill = (list) => list.forEach((x) => { const o = document.createElement("option"); o.value = x.id; o.textContent = x.name; if (x.id === stimme) o.selected = true; sel.appendChild(o); });
  if (live) fill(live.stimmen);
  else api("/api/stimmen").then((d) => fill(d.stimmen.filter((x) => x.fingerabdruck))).catch(() => {});
  sel.onchange = () => styleCard(box, id, stored, sel.value || null);
}

// Vorlesen mit den Stimmen des Systems: Erzähler bekommt eine feste Stimme, Figuren wechseln über die übrigen deutschen Stimmen.
const READ = { active: false };
function germanVoices() {
  const all = (window.speechSynthesis && speechSynthesis.getVoices()) || [];
  const de = all.filter((v) => (v.lang || "").toLowerCase().startsWith("de"));
  return de.length ? de : all;
}
function startReading(segments, rate, from = 0) {
  if (!window.speechSynthesis) { toast("Dieser Browser kann nicht vorlesen.", "bad"); return; }
  stopReading();
  const voices = germanVoices();
  const map = {};
  let next = 1;
  const voiceFor = (s) => {
    if (!voices.length) return null;
    if (s.typ === "narrator") return voices[0];
    if (!(s.sprecher in map)) { map[s.sprecher] = voices[voices.length > 1 ? next % voices.length || 1 : 0]; next++; }
    return map[s.sprecher];
  };
  READ.active = true;
  const speak = (i) => {
    if (!READ.active || i >= segments.length) { READ.active = false; markSeg(-1); return; }
    const u = new SpeechSynthesisUtterance(segments[i].text);
    const v = voiceFor(segments[i]);
    if (v) { u.voice = v; u.lang = v.lang; } else u.lang = "de-DE";
    u.rate = rate;
    u.pitch = segments[i].typ === "narrator" ? 1 : 1 + ((Object.keys(map).indexOf(segments[i].sprecher) % 3) - 1) * 0.08;
    u.onstart = () => markSeg(i);
    u.onend = () => speak(i + 1);
    u.onerror = () => speak(i + 1);
    speechSynthesis.speak(u);
  };
  speak(from);
}
function stopReading() { READ.active = false; if (window.speechSynthesis) speechSynthesis.cancel(); markSeg(-1); }
function markSeg(i) {
  document.querySelectorAll(".seg.now").forEach((p) => p.classList.remove("now"));
  const p = document.querySelector(`.seg[data-i="${i}"]`);
  if (p) { p.classList.add("now"); p.scrollIntoView({ block: "center", behavior: "smooth" }); }
}

// ------------------------------------------------------------ Zeit & Reisen

VIEWS.zeit = async (el) => {
  const [locs, z] = await Promise.all([api(W("/rows/locations")), api(W(`/zeit${S.zeitT != null ? `?t=${S.zeitT}` : ""}`))]);
  const st = z.zustand;
  const opts = locs.rows.map((l) => `<option value="${l.id}">${esc(l.__title)}</option>`).join("");
  el.innerHTML = `<h2>Zeit &amp; Reisen</h2>
  <div class="card stack"><div class="row spread"><h3 style="margin:0">Zeitreise – Weltzustand zu einem Zeitpunkt</h3>
      <div class="row"><input id="z-t" type="number" step="any" value="${esc(z.weltzeit)}" style="max-width:140px">
      <button class="ghost" id="z-go">Anzeigen</button><button class="ghost" id="z-now">Aktuell (${esc(z.aktuell)})</button></div></div>
    <p class="small muted">Nur was zu diesem Zeitpunkt galt – spätere Ereignisse bleiben ausgeblendet (Vergangenheit ist kanon-gesperrt).</p>
    <div class="grid">${st.kalender.map((k) => `<div class="card"><b>${esc(k.kalender)}</b><div>${k.text ? esc(k.text) : `<span class="muted small">${esc(k.fehlt)}</span>`}</div></div>`).join("")}</div>
    <h3>Figuren</h3>${st.figuren.length ? `<table><tr><th>Figur</th><th>Status</th><th>Ort</th><th>Jobs</th><th>Wissen</th></tr>
      ${st.figuren.map((f) => `<tr><td>${esc(f.name)}</td><td>${esc(f.status)}</td><td>${esc(f.ort)}</td><td class="small">${esc(f.jobs.join(", "))}</td><td>${f.wissen}</td></tr>`).join("")}</table>`
      : '<div class="muted small">Noch keine Figuren.</div>'}
    <h3>Ereignisse bis hier</h3>${st.ereignisse.length ? `<table>${st.ereignisse.map((e) => `<tr><td style="width:110px">${esc(e.weltzeit)}</td><td>${esc(e.titel)}</td><td class="small muted">${esc(e.ort || "")}</td></tr>`).join("")}</table>`
      : '<div class="muted small">Keine.</div>'}
    <div class="small muted">Folgen bis hier: ${st.folgen_bis_hier.map((f) => esc(`${f.release_nr}. ${f.title}`)).join(" · ") || "keine"} ·
      Technik verfügbar: ${esc(st.technik.join(", ") || "—")}</div></div>
  <div class="card stack" style="margin-top:14px"><h3 style="margin:0">Reiserechner</h3>
    <p class="small muted">Kürzeste bekannte Entfernung über „Entfernungen“; Orte erben die Entfernung ihres größeren Orts.
      Reisezeit = Vorbereitung + Entfernung ÷ Geschwindigkeit der Technik.</p>
    <div class="row"><select id="r-von">${opts}</select><span>→</span><select id="r-nach">${opts}</select><button class="primary" id="r-go">Berechnen</button></div>
    <div id="r-out"></div></div>`;
  $("#z-go").onclick = () => { S.zeitT = $("#z-t").value; render(); };
  $("#z-now").onclick = () => { S.zeitT = null; render(); };
  $("#r-go").onclick = () => guard(async () => {
    const r = await api(W(`/reise?von=${$("#r-von").value}&nach=${$("#r-nach").value}`));
    $("#r-out").innerHTML = r.entfernung == null ? `<div class="muted">${esc(r.hinweis)}</div>`
      : `<div><b>${esc(r.von)} → ${esc(r.nach)}</b>: Entfernung ${esc(r.entfernung)} <span class="small muted">(${esc(r.pfad.join(" → "))})</span></div>
        ${r.reisezeiten.length ? `<table>${r.reisezeiten.map((x) => `<tr><td>${esc(x.technik)}</td><td>${esc(x.dauer)} Weltzeit-Einheiten</td></tr>`).join("")}</table>`
          : `<div class="muted small">${esc(r.hinweis || "")}</div>`}`;
  });
};

async function consistencyCard() {
  const k = await api(W("/konsistenz"));
  return `<div class="card stack" style="margin-bottom:14px"><h3 style="margin:0">Konsistenzprüfung</h3>
    <p class="small muted">Automatisch: Figur an zwei Orten gleichzeitig, Reisezeit unterschritten, tote Figuren in der Gegenwart.
      ${k.verborgen ? `<span class="locked">+ ${k.verborgen} im Backstage.</span>` : ""}</p>
    ${k.probleme.length ? `<table>${k.probleme.map((p) => `<tr><td style="width:90px"><span class="chip ${p.schwere === "hoch" ? "st-fehler" : "st-offen"}">${esc(p.art)}</span></td>
      <td><b>${esc(p.figur)}</b> ${esc(p.text)}</td></tr>`).join("")}</table>` : '<div class="muted">Keine Widersprüche gefunden. ✔</div>'}</div>`;
}

// ------------------------------------------------------------ Menschen & Erzählprofil

const ago = (ts) => (ts ? `zuletzt genutzt ${esc(ts)}` : "noch nie genutzt");

function showUser() {
  const b = $("#btn-user");
  b.textContent = S.user ? `👤 ${S.user.name}` : "👤 Wer bist du?";
}

async function setActiveUser(p) {
  S.user = await api(`/api/profiles/${p.id}/aktiv`, { method: "POST", body: { welt: S.world || null } });
  store("sw-user", S.user.id);
  showUser();
}

async function chooseUser() {
  const data = await api("/api/profiles");
  S.profilesMeta = { fragen: data.fragen, felder: data.felder };
  modal(`<h2>Wer bedient gerade?</h2>
    <p class="muted">Kein Login – nur damit die Geschichten nach dir klingen. Dein Erzählprofil bleibt auf diesem Rechner.</p>
    <div class="stack">${data.profiles.map((p) => `<button class="preset" data-pick="${p.id}" style="width:100%">
      <b>${esc(p.name)}</b><span class="small muted">${ago(p.last_used)}${p.status === "interview" ? " · Interview noch offen" : ""}</span></button>`).join("")}
      <button class="primary" id="u-new">＋ Neuer Mensch – kurzes Interview</button></div>
    ${S.user ? `<p class="small" style="margin-top:10px"><a href="#" id="u-page">Seite von ${esc(S.user.name)} öffnen – Befragung, Einschätzung, Texte →</a></p>` : ""}
    <div class="row spread" style="margin-top:14px"><span class="small muted">${data.profiles.length ? "" : "Noch niemand angelegt."}</span>
      <button class="ghost" data-close="1">Ohne Profil weiter</button></div>`);
  document.querySelectorAll("[data-pick]").forEach((b) => (b.onclick = () => guard(async () => {
    const p = data.profiles.find((x) => x.id === b.dataset.pick);
    await setActiveUser(p);
    closeModal();
    toast(`Hallo ${p.name}!`, "ok");
    if (p.status === "interview") interview(p.id);
  })));
  $("#u-new").onclick = () => interview(null);
  if ($("#u-page")) $("#u-page").onclick = (e) => { e.preventDefault(); closeModal(); openPerson(S.user.id); };
}

async function interview(pid, step = 0) {
  if (!S.profilesMeta) { const d = await api("/api/profiles"); S.profilesMeta = { fragen: d.fragen, felder: d.felder }; }
  const qs = S.profilesMeta.fragen;
  let profile = pid ? (await api("/api/profiles")).profiles.find((p) => p.id === pid) : null;
  const q = qs[step];
  const value = profile ? profile.antworten[q.id] || "" : "";
  modal(`<div class="row spread"><h2 style="margin:0">Interview</h2><span class="small muted">Frage ${step + 1} von ${qs.length}</span></div>
    <div class="progress" style="margin:10px 0 16px"><span class="p-ok" style="width:${(step / qs.length) * 100}%"></span></div>
    ${step === 0 ? `<p class="small muted">Es gibt kein Richtig oder Falsch. Antworte so, wie es dir in den Sinn kommt – auch die Art, wie du
      schreibst, fließt ein. Die Antworten bleiben auf diesem Rechner; zur Auswertung gehen sie an die eingestellte KI.</p>` : ""}
    <div class="form"><div class="field"><label style="text-transform:none;letter-spacing:0;font-size:16px;color:var(--text);font-weight:500">${esc(q.frage)}</label>
      ${q.art === "kurz" ? `<input id="iv-a" value="${esc(value)}">` : `<textarea id="iv-a" style="min-height:130px">${esc(value)}</textarea>`}</div></div>
    <div class="row spread"><button class="ghost" id="iv-back" ${step === 0 ? "disabled" : ""}>← Zurück</button>
      <div class="row">${step > 0 ? `<button class="ghost" id="iv-skip">Überspringen</button>` : ""}
      <button class="primary" id="iv-next">${step === qs.length - 1 ? "Fertig – Profil erstellen" : "Weiter"}</button></div></div>`);
  $("#iv-a").focus();
  const saveAnswer = async () => {
    const answer = $("#iv-a").value.trim();
    if (!profile) {
      if (q.id !== "name" || !answer) throw new Error("Bitte zuerst einen Namen angeben.");
      profile = await api("/api/profiles", { method: "POST", body: { name: answer } });
      await setActiveUser(profile);
    } else if (answer || value) {
      profile = await api(`/api/profiles/${profile.id}/antworten`, { method: "PUT", body: { antworten: { [q.id]: answer } } });
    }
  };
  $("#iv-next").onclick = () => guard(async () => {
    await saveAnswer();
    if (step < qs.length - 1) interview(profile.id, step + 1);
    else analyzeProfile(profile.id);
  });
  if ($("#iv-skip")) $("#iv-skip").onclick = () => (step < qs.length - 1 ? interview(profile.id, step + 1) : analyzeProfile(profile.id));
  $("#iv-back").onclick = () => guard(async () => { await saveAnswer(); interview(profile.id, step - 1); });
  $("#iv-a").onkeydown = (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey || q.art === "kurz")) $("#iv-next").click(); };
}

async function analyzeProfile(pid) {
  modal(`<h2>Dein Erzählprofil entsteht …</h2><div class="bar laeuft"><span style="width:60%"></span></div>
    <p class="muted small">Die KI liest deine Antworten – auch zwischen den Zeilen – und beschreibt, wie deine Geschichten klingen sollen.</p>`);
  try {
    const p = await api(`/api/profiles/${pid}/auswerten`, { method: "POST", body: {} });
    S.user = p; showUser();
    profileDialog(p, true);
  } catch (e) {
    modal(`<h2>Auswertung nicht möglich</h2><p class="err">${esc(e.message)}</p>
      <p class="small muted">Die Antworten sind gespeichert. Du kannst die Auswertung später unter Einstellungen → Menschen & Profile starten.</p>
      <div class="row spread"><button class="ghost" data-close="1">Schließen</button><button class="ki" id="pa-retry">Erneut versuchen</button></div>`);
    $("#pa-retry").onclick = () => analyzeProfile(pid);
  }
}

function profileDialog(p, fresh = false) {
  const fields = (S.profilesMeta && S.profilesMeta.felder) || [];
  const open = (p.nachfragen || []).filter((n) => !n.antwort);
  modal(`<div class="row spread"><h2 style="margin:0">Erzählprofil: ${esc(p.name)}</h2><span class="small muted">${esc(p.ausgewertet || "")}</span></div>
    ${fresh ? `<p class="muted small">So würde die KI dich als Erzähler:in beschreiben. Du kannst alles ändern – es ist deine Stimme.</p>` : ""}
    ${open.length ? `<div class="card stack" style="border-color:var(--accent)"><b>Nachfragen</b>
      ${open.map((n, i) => `<div class="field"><label style="text-transform:none;letter-spacing:0;font-size:14px;color:var(--text)">${esc(n.frage)}</label>
        <textarea data-nf="${i}" style="min-height:60px"></textarea></div>`).join("")}
      <div class="row"><button class="ki" id="pf-refine">Beantworten und Profil verfeinern</button></div></div>` : ""}
    <form class="form" id="pf-form" style="margin-top:12px">${fields.map((f) => `<div class="field"><label>${esc(f.label)}</label>
      <textarea name="${f.id}" style="min-height:56px">${esc((p.profil || {})[f.id] || "")}</textarea></div>`).join("")}</form>
    <div class="row spread"><button class="ghost" id="pf-interview">Interview ansehen / ergänzen</button>
      <div class="row"><button class="ghost" data-close="1">Schließen</button><button class="primary" id="pf-save">Speichern</button></div></div>`);
  $("#pf-save").onclick = () => guard(async () => {
    const profil = Object.fromEntries(new FormData($("#pf-form")).entries());
    S.user = await api(`/api/profiles/${p.id}/profil`, { method: "PUT", body: { profil } });
    showUser(); closeModal(); toast("Erzählprofil gespeichert.", "ok");
    if (S.view === "einstellungen") render();
  });
  $("#pf-interview").onclick = () => interview(p.id, 0);
  if ($("#pf-refine")) $("#pf-refine").onclick = () => guard(async () => {
    const antworten = open.map((n, i) => ({ frage: n.frage, antwort: document.querySelector(`[data-nf="${i}"]`).value }));
    await api(`/api/profiles/${p.id}/nachfragen`, { method: "PUT", body: { antworten } });
    analyzeProfile(p.id);
  });
}

async function subMenschen(el) {
  const data = await api("/api/profiles");
  S.profilesMeta = { fragen: data.fragen, felder: data.felder };
  el.innerHTML = `<div class="row spread"><h2>Menschen &amp; Erzählprofile</h2><button class="primary" id="m-new">＋ Neuer Mensch</button></div>
    <p class="muted">Wer Story World nutzt, bekommt ein Erzählprofil aus einem kurzen Interview. Planer, Autor, Lektor und Prüfer
      richten sich danach, damit die Folgen wie aus deiner Feder klingen. Der tägliche Lauf nutzt das Profil, das die Welt zuletzt genutzt hat.
      Gespeichert nur lokal; an die KI gehen die Angaben beim Auswerten und Schreiben.</p>
    <div class="stack">${data.profiles.map((p) => `<div class="card"><div class="row spread"><div><b>${esc(p.name)}</b>
        ${S.user && S.user.id === p.id ? '<span class="chip st-fertig">aktiv</span>' : ""}
        <span class="chip ${p.status === "fertig" ? "st-fertig" : "st-offen"}">${p.status === "fertig" ? "Profil fertig" : "Interview offen"}</span>
        <div class="small muted">${ago(p.last_used)} · ${Object.keys(p.antworten || {}).length} Antworten · ${(p.texte || []).length} Texte</div></div>
      <div class="row"><button class="ghost" data-use="${p.id}">Als aktiv wählen</button><button class="ghost" data-iv="${p.id}">Interview</button>
        <button class="primary" data-page="${p.id}">Seite öffnen</button>
        ${p.status === "fertig" ? "" : `<button class="ki" data-an="${p.id}">Auswerten</button>`}
        <button class="danger" data-arch="${p.id}">Ins Archiv</button></div></div>
      ${p.profil && p.profil.zusammenfassung ? `<p class="small" style="margin:8px 0 0">${esc(p.profil.zusammenfassung)}</p>` : ""}</div>`).join("")
      || '<div class="card empty">Noch niemand angelegt.</div>'}</div>
    ${data.archiv.length ? `<details style="margin-top:12px"><summary class="muted">Archiv (${data.archiv.length})</summary>${data.archiv.map((p) =>
      `<div class="row spread card" style="margin-top:8px"><span>${esc(p.name)} <span class="small muted">archiviert ${esc(p.archiviert_am || "")}</span></span>
       <button class="ghost" data-restore-p="${p.id}">Wiederherstellen</button></div>`).join("")}</details>` : ""}`;
  $("#m-new").onclick = () => interview(null);
  const find = (id) => data.profiles.find((p) => p.id === id);
  el.querySelectorAll("[data-use]").forEach((b) => (b.onclick = () => guard(async () => { await setActiveUser(find(b.dataset.use)); render(); })));
  el.querySelectorAll("[data-iv]").forEach((b) => (b.onclick = () => interview(b.dataset.iv, 0)));
  el.querySelectorAll("[data-page]").forEach((b) => (b.onclick = () => openPerson(b.dataset.page)));
  el.querySelectorAll("[data-an]").forEach((b) => (b.onclick = () => analyzeProfile(b.dataset.an)));
  el.querySelectorAll("[data-arch]").forEach((b) => (b.onclick = () => confirm("Profil ins Archiv verschieben? (wiederherstellbar)") && guard(async () => {
    await api(`/api/profiles/${b.dataset.arch}/archivieren`, { method: "POST", body: {} });
    if (S.user && S.user.id === b.dataset.arch) { S.user = null; showUser(); }
    render();
  })));
  el.querySelectorAll("[data-restore-p]").forEach((b) => (b.onclick = () => guard(async () => {
    await api(`/api/profiles/${b.dataset.restoreP}/wiederherstellen`, { method: "POST", body: {} }); render();
  })));
}

// ------------------------------------------------------------ Seite eines Menschen: Befragung, Einschätzung, Texte

function openPerson(pid) { S.mensch = pid; go("mensch"); }

function b64(buf) {
  const bytes = new Uint8Array(buf);
  let out = "";
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(out);
}

VIEWS.mensch = async (el) => {
  const pid = S.mensch || (S.user && S.user.id);
  if (!pid) { el.innerHTML = `<div class="card empty"><p>Noch kein Mensch gewählt.</p><button class="primary" id="mp-choose">Wer bist du?</button></div>`;
    $("#mp-choose").onclick = () => guard(chooseUser); return; }
  const p = await api(`/api/profiles/${pid}`);
  S.profilesMeta = { fragen: p.fragen, felder: p.felder };
  const { welten } = await api("/api/worlds");
  const prof = p.profil || {};
  const open = (p.nachfragen || []).filter((n) => !n.antwort);
  const texte = p.texte || [];
  const textCard = (t) => `<div class="card" data-text="${t.id}"><div class="row spread"><div><b>${esc(t.titel)}</b>
      <div class="small muted">${t.fremd ? `<span class="chip st-offen">fremder Text${t.autor ? ` · ${esc(t.autor)}` : ""}</span> · ` : ""}${esc(t.quelle || "")} · ${t.woerter.toLocaleString("de-DE")} Wörter · ${esc(t.erstellt)}
        ${(t.eingelesen || []).map((e) => ` · <span class="chip st-fertig">in „${esc(e.welt)}“ eingelesen ${esc(e.am)}</span>`).join("")}</div></div>
      <div class="row"><label class="small row" style="gap:6px"><input type="checkbox" data-stil="${t.id}" ${t.stil ? "checked" : ""} ${t.fremd ? "disabled" : ""} style="width:auto"> Stilprobe</label>
        <label class="small row" style="gap:6px" title="Text eines anderen Autors: keine Stilprobe, im Welt-Export nicht enthalten"><input type="checkbox" data-fremd="${t.id}" ${t.fremd ? "checked" : ""} style="width:auto"> fremder Text</label>
        <button class="ghost" data-show-text="${t.id}">Lesen</button>
        <button class="ki" data-import="${t.id}">In Welt einlesen</button>
        <button class="danger" data-arch-text="${t.id}">Ins Archiv</button></div></div>
      <pre class="textprev hidden" id="tp-${t.id}"></pre></div>`;
  el.innerHTML = `<div class="row spread"><div><h2 style="margin-bottom:4px">${esc(p.name)}</h2>
      <div class="small muted">${ago(p.last_used)} · angelegt ${esc(p.created || "")}
        ${S.user && S.user.id === p.id ? ' · <span class="chip st-fertig">aktiv</span>' : ""}</div></div>
      <div class="row"><button class="ghost" id="mp-switch">Anderen Menschen wählen</button>
        ${S.user && S.user.id === p.id ? "" : `<button class="ghost" id="mp-use">Als aktiv wählen</button>`}</div></div>

    <h3 class="mp-h">Einschätzung – dein Erzählprofil</h3>
    <div class="card">
      <div class="row spread"><span class="small muted">${p.ausgewertet ? `ausgewertet ${esc(p.ausgewertet)}${p.modell ? ` · ${esc(p.modell)}` : ""}` : "noch nicht ausgewertet"}
        ${p.bearbeitet ? ` · von dir bearbeitet ${esc(p.bearbeitet)}` : ""}</span>
        <button class="ki" id="mp-analyze">${p.ausgewertet ? "Neu auswerten" : "Jetzt auswerten"}</button></div>
      <p class="small muted">Die KI beschreibt aus Befragung und Stilproben, wie deine Geschichten klingen sollen. Alles änderbar – es ist deine Stimme.</p>
      ${open.length ? `<div class="card stack" style="border-color:var(--accent)"><b>Nachfragen der KI</b>
        ${open.map((n, i) => `<div class="field"><label style="text-transform:none;letter-spacing:0;font-size:14px;color:var(--text)">${esc(n.frage)}</label>
          <textarea data-nf="${i}" style="min-height:60px"></textarea></div>`).join("")}
        <div class="row"><button class="ki" id="mp-refine">Beantworten und Profil verfeinern</button></div></div>` : ""}
      <form class="form" id="mp-profil">${p.felder.map((f) => `<div class="field"><label>${esc(f.label)}</label>
        <textarea name="${f.id}" style="min-height:52px">${esc(prof[f.id] || "")}</textarea></div>`).join("")}</form>
      <div class="row" style="justify-content:flex-end"><button class="primary" id="mp-save-profil">Einschätzung speichern</button></div></div>

    <h3 class="mp-h">Befragung</h3>
    <details class="card" id="mp-befragung"><summary><b>${p.fragen.filter((q) => (p.antworten || {})[q.id]).length} von ${p.fragen.length} Fragen beantwortet</b>
      <span class="small muted"> · aufklappen zum Lesen und Ändern</span></summary><form class="form" id="mp-antworten" style="margin-top:12px">${p.fragen.map((q) => `<div class="field">
        <label style="text-transform:none;letter-spacing:0;font-size:14px;color:var(--text)">${esc(q.frage)}</label>
        ${q.art === "kurz" ? `<input name="${q.id}" value="${esc((p.antworten || {})[q.id] || "")}">`
          : `<textarea name="${q.id}" style="min-height:70px">${esc((p.antworten || {})[q.id] || "")}</textarea>`}</div>`).join("")}
      ${(p.nachfragen || []).filter((n) => n.antwort).map((n) => `<div class="field"><label style="text-transform:none;letter-spacing:0;font-size:14px">Nachfrage: ${esc(n.frage)}</label>
        <div class="small">${esc(n.antwort)}</div></div>`).join("")}</form>
      <div class="row" style="justify-content:flex-end"><button class="primary" id="mp-save-antworten">Antworten speichern</button></div></details>

    <h3 class="mp-h">Texte als Basis</h3>
    <p class="small muted">Eigene Texte – Geschichten, Notizen, Weltideen. Als <b>Stilprobe</b> markiert fließen Auszüge in dein Erzählprofil ein.
      Mit <b>In Welt einlesen</b> arbeitet die KI den Text abschnittsweise als Vorschläge in eine Welt ein (Orte, Figuren, Völker, Technik …).
      Texte bleiben lokal; an die KI gehen sie nur beim Auswerten und Einlesen.</p>
    <div class="card"><div class="form">
      <div class="row"><div class="field" style="flex:1"><label>Titel</label><input id="mp-t-titel" placeholder="optional – sonst Dateiname oder erste Zeile"></div>
        <label class="small row" style="gap:6px;align-self:end;margin-bottom:10px"><input type="checkbox" id="mp-t-stil" checked style="width:auto"> von mir geschrieben – als Stilprobe nutzen</label>
        <label class="small row" style="gap:6px;align-self:end;margin-bottom:10px"><input type="checkbox" id="mp-t-fremd" style="width:auto"> fremder Text</label>
        <div class="field hidden" id="mp-t-autor-f" style="flex:1"><label>Autor des fremden Texts</label><input id="mp-t-autor" placeholder="z. B. u/MYSFITS_OFFICIAL"></div></div>
      <div class="field"><label>Text einfügen</label><textarea id="mp-t-text" style="min-height:120px" placeholder="Text hier einfügen …"></textarea></div>
      <div class="row spread"><span class="small muted">oder Dateien: <input type="file" id="mp-t-file" multiple accept="${p.formate.join(",")}" style="width:auto">
        <br>${p.formate.join(" ")}</span>
        <button class="primary" id="mp-t-add">Text hinzufügen</button></div></div></div>
    <div class="stack" style="margin-top:10px">${texte.map(textCard).join("") || '<div class="card empty">Noch keine Texte.</div>'}</div>
    ${(p.texte_archiv || []).length ? `<details style="margin-top:12px"><summary class="muted">Archivierte Texte (${p.texte_archiv.length})</summary>
      ${p.texte_archiv.map((t) => `<div class="row spread card" style="margin-top:8px"><span>${esc(t.titel)} <span class="small muted">archiviert ${esc(t.archiviert_am || "")}</span></span>
        <button class="ghost" data-restore-text="${t.id}">Wiederherstellen</button></div>`).join("")}</details>` : ""}`;

  const P = `/api/profiles/${p.id}`;
  $("#mp-switch").onclick = () => guard(chooseUser);
  if ($("#mp-use")) $("#mp-use").onclick = () => guard(async () => { await setActiveUser(p); render(); });
  $("#mp-analyze").onclick = () => guard(async () => {
    $("#mp-analyze").disabled = true; $("#mp-analyze").textContent = "KI wertet aus …";
    try {
      const np = await api(`${P}/auswerten`, { method: "POST", body: {} });
      if (S.user && S.user.id === np.id) { S.user = np; showUser(); }
      toast("Erzählprofil aktualisiert.", "ok");
    } finally { render(); }
  });
  if ($("#mp-refine")) $("#mp-refine").onclick = () => guard(async () => {
    const antworten = open.map((n, i) => ({ frage: n.frage, antwort: document.querySelector(`[data-nf="${i}"]`).value }));
    await api(`${P}/nachfragen`, { method: "PUT", body: { antworten } });
    $("#mp-analyze").click();
  });
  $("#mp-save-profil").onclick = () => guard(async () => {
    const np = await api(`${P}/profil`, { method: "PUT", body: { profil: Object.fromEntries(new FormData($("#mp-profil")).entries()) } });
    if (S.user && S.user.id === np.id) { S.user = np; showUser(); }
    toast("Einschätzung gespeichert.", "ok"); render();
  });
  $("#mp-save-antworten").onclick = () => guard(async () => {
    await api(`${P}/antworten`, { method: "PUT", body: { antworten: Object.fromEntries(new FormData($("#mp-antworten")).entries()) } });
    toast("Antworten gespeichert. Für ein neues Profil „Neu auswerten“.", "ok"); render();
  });
  $("#mp-t-add").onclick = () => guard(async () => {
    const files = [...$("#mp-t-file").files];
    const fremd = $("#mp-t-fremd").checked, autor = $("#mp-t-autor").value.trim();
    const stil = $("#mp-t-stil").checked && !fremd, titel = $("#mp-t-titel").value.trim();
    if (!files.length && !$("#mp-t-text").value.trim()) throw new Error("Bitte Text einfügen oder eine Datei wählen.");
    $("#mp-t-add").disabled = true;
    try {
      if ($("#mp-t-text").value.trim()) await api(`${P}/texte`, { method: "POST", body: { titel, text: $("#mp-t-text").value, stil, fremd, autor } });
      for (const f of files) {
        if (f.size > 8_000_000) { toast(`${f.name}: zu groß (max. 8 MB).`, "bad"); continue; }
        await api(`${P}/texte`, { method: "POST", body: { titel: files.length === 1 ? titel : "", dateiname: f.name,
          daten_b64: b64(await f.arrayBuffer()), stil, fremd, autor } });
      }
      toast("Text gespeichert.", "ok");
    } finally { render(); }
  });
  $("#mp-t-fremd").onchange = () => { $("#mp-t-autor-f").classList.toggle("hidden", !$("#mp-t-fremd").checked);
    if ($("#mp-t-fremd").checked) $("#mp-t-stil").checked = false; };
  el.querySelectorAll("[data-fremd]").forEach((c) => (c.onchange = () => guard(async () => {
    const autor = c.checked ? (prompt("Autor des fremden Texts (optional):", "") || "") : "";
    await api(`${P}/texte/${c.dataset.fremd}`, { method: "PUT", body: { fremd: c.checked, autor } });
    toast(c.checked ? "Als fremder Text markiert – keine Stilprobe, nicht im Welt-Export." : "Wieder als eigener Text markiert.", "ok"); render();
  })));
  el.querySelectorAll("[data-stil]").forEach((c) => (c.onchange = () => guard(async () => {
    await api(`${P}/texte/${c.dataset.stil}`, { method: "PUT", body: { stil: c.checked } });
    toast(c.checked ? "Fließt ab der nächsten Auswertung ins Profil ein." : "Keine Stilprobe mehr.", "ok");
  })));
  el.querySelectorAll("[data-show-text]").forEach((b) => (b.onclick = () => guard(async () => {
    const box = $(`#tp-${b.dataset.showText}`);
    if (box.classList.contains("hidden") && !box.textContent) box.textContent = (await api(`${P}/texte/${b.dataset.showText}`)).text;
    box.classList.toggle("hidden");
    b.textContent = box.classList.contains("hidden") ? "Lesen" : "Zuklappen";
  })));
  el.querySelectorAll("[data-arch-text]").forEach((b) => (b.onclick = () => confirm("Text ins Archiv verschieben? (wiederherstellbar)") && guard(async () => {
    await api(`${P}/texte/${b.dataset.archText}/archivieren`, { method: "POST", body: {} }); render();
  })));
  el.querySelectorAll("[data-restore-text]").forEach((b) => (b.onclick = () => guard(async () => {
    await api(`${P}/texte/${b.dataset.restoreText}/wiederherstellen`, { method: "POST", body: {} }); render();
  })));
  el.querySelectorAll("[data-import]").forEach((b) => (b.onclick = () => {
    const t = texte.find((x) => x.id === b.dataset.import);
    if (!welten.length) return toast("Erst eine Welt anlegen.", "bad");
    const teile = Math.max(1, Math.ceil(t.zeichen / 12000));
    modal(`<h2>„${esc(t.titel)}“ in eine Welt einlesen</h2>
      <p class="muted">Die KI liest den Text in ${teile > 1 ? `etwa ${teile} Abschnitten` : "einem Durchgang"} und macht daraus Vorschläge für den Kanon.
        Was schon da ist, wird ergänzt statt doppelt angelegt; Widersprüche kommen als Rückfrage. Je nach Einstellung „automatisch übernehmen“
        landen die Vorschläge direkt in der Welt oder warten unter „Vorschläge“.</p>
      <div class="form"><div class="field"><label>Welt</label><select id="ti-welt">${welten.map((w) => `<option value="${esc(w.slug)}" ${w.slug === S.world ? "selected" : ""}>${esc(w.name)}</option>`).join("")}</select></div>
        <div class="field"><label>Hinweis an die KI (optional)</label><textarea id="ti-hint" placeholder="z. B. Das ist meine Vorgeschichte der Familie Berger; Namen bitte übernehmen."></textarea></div></div>
      ${teile > 8 ? `<p class="small warn-text">⚠ Langer Text: ${teile} KI-Aufträge nacheinander – das dauert und kostet entsprechend.</p>` : ""}
      <div class="row spread"><button class="ghost" data-close="1">Abbrechen</button><button class="ki" id="ti-go">Einlesen starten</button></div>`);
    $("#ti-go").onclick = () => guard(async () => {
      const slug = $("#ti-welt").value;
      const r = await api(`/api/w/${slug}/texte/einlesen`, { method: "POST", body: { profil_id: p.id, text_id: t.id, hinweis: $("#ti-hint").value } });
      closeModal();
      toast(`Einlesen läuft (${r.teile} Abschnitt${r.teile === 1 ? "" : "e"}) – Fortschritt unter „KI-Läufe“.`, "ok");
      pollJobs();
    });
  }));
};

// ------------------------------------------------------------ KI-Läufe

const bar = (status, progress, small) => `<div class="bar ${status} ${small ? "small" : ""}"><span style="width:${status === "laeuft" ? Math.max(progress, 4) : progress}%"></span></div>`;
const fmtSec = (s) => (s == null ? "" : s < 60 ? `${s.toFixed ? s.toFixed(1) : s} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`);

// ------------------------------------------------------------ Schreibstil (Stimmen = virtueller Autor)

const ART_TEXT = { autor: "Vorbild: Autor", mensch: "Vorbild: Mensch & eigene Texte", frei: "freie Beschreibung" };
const MESS_LABEL = { satzlaenge: "Satzlänge Ø (Wörter)", dialoganteil: "Dialoganteil", wortlaenge: "Wortlänge Ø (Buchstaben)",
  absatzlaenge: "Absatzlänge Ø (Wörter)" };

VIEWS.stil = async (el) => {
  const data = await api("/api/stimmen");
  const [st, o] = S.world ? await Promise.all([api(W("/stories")), api(W("/overview"))]) : [null, null];
  const worldVoice = o ? o.meta.einstellungen.stimme || "" : "";
  const voices = data.stimmen;
  if (S.stimme && !voices.some((v) => v.id === S.stimme)) S.stimme = null;
  if (!S.stimme && voices.length && !S.stimmeNeu) S.stimme = voices[0].id;
  const uses = (v) => {
    const parts = [];
    if (v.id === worldVoice) parts.push("Welt-Standard");
    const n = st ? st.geschichten.filter((g) => g.stimme_id === v.id).length : 0;
    if (n) parts.push(`${n} Geschichte${n === 1 ? "" : "n"}`);
    return parts.join(" · ");
  };
  const card = (v) => `<div class="card click pick${S.stimme === v.id && !S.stimmeNeu ? " sel" : ""}" data-voice="${v.id}">
      <div class="row spread"><b>${esc(v.name)}</b>${uses(v) ? `<span class="chip st-fertig">${esc(uses(v))}</span>` : ""}</div>
      <div class="small muted" style="margin-top:4px">${esc(ART_TEXT[v.art] || v.art)}${v.vorbild && v.art !== "frei" ? ` · ${esc(v.vorbild)}` : ""}</div>
      <div class="small" style="margin-top:6px">${Object.keys(v.steckbrief || {}).length ? "✔ Steckbrief" : "○ noch kein Steckbrief"}
        · ${v.probe && v.probe.freigegeben ? "✔ Probe freigegeben" : v.probe ? "○ Probe nicht freigegeben" : "○ keine Probe"}
        · ${v.fingerabdruck ? `✔ Fingerabdruck (${Number(v.fingerabdruck.woerter || 0).toLocaleString("de-DE")} Wörter)` : v.messwerte ? "✔ Maßstab" : "○ kein Maßstab"}</div></div>`;
  el.innerHTML = `<div class="row spread"><h2>Schreibstil</h2><div class="row">
      <button class="ghost" id="st-import" title="Einen exportierten Schreibstil (Datei) übernehmen">⇧ Schreibstil importieren</button>
      <button class="primary" id="st-new">+ Neue Stimme</button></div></div>
    <p class="muted">Eine <b>Stimme</b> ist der virtuelle Autor deiner Folgen – „schreibt wie Stanisław Lem“ oder „schreibt wie Ralf“
      auf Basis deiner eigenen Texte. Planer, Autor und Lektor schreiben danach, der Prüfer prüft dagegen, die Stil-Messung
      vergleicht mit deinen Texten oder der freigegebenen Probe. Es gilt: Folge vor Geschichte vor Welt.
      Die Befragung im Erzählprofil liefert nur noch Publikum, Genres und Tabus.</p>
    <div class="grid">${voices.map(card).join("") || '<div class="card empty">Noch keine Stimme – leg oben rechts die erste an.</div>'}</div>
    ${data.archiv.length ? `<details style="margin-top:10px"><summary class="muted">Archivierte Stimmen (${data.archiv.length})</summary>
      ${data.archiv.map((v) => `<div class="row spread card" style="margin-top:8px"><span>${esc(v.name)} <span class="small muted">archiviert ${esc(v.archiviert_am || "")}</span></span>
        <button class="ghost" data-voice-back="${v.id}">Wiederherstellen</button></div>`).join("")}</details>` : ""}
    <details class="card" id="st-detect" style="margin-top:14px"><summary><b>Wessen Stil ist das?</b>
      <span class="small muted">Text einfügen – Evel vergleicht ihn mit dem Fingerabdruck jeder Stimme (nur per Code, keine KI).</span></summary>
      <div class="stack" style="margin-top:10px"><textarea id="sd-text" rows="6" placeholder="Mindestens 150 Wörter, besser 1000+ – z. B. ein Kapitel aus einem Buch oder eine Folge"></textarea>
        <div class="row" style="justify-content:flex-end"><button class="primary" id="sd-go">Vergleichen</button></div>
        <div id="sd-out"></div></div></details>
    <div id="st-detail" style="margin-top:22px"></div>`;
  $("#sd-go").onclick = () => guard(async () => {
    const r = await api("/api/stimmen/erkennen", { method: "POST", body: { text: $("#sd-text").value } });
    $("#sd-out").innerHTML = `<p><b>${esc(r.satz)}</b> <span class="small muted">${Number(r.woerter || 0).toLocaleString("de-DE")} Wörter gemessen</span></p>
      ${r.rangliste.length ? `<table class="qtable"><tr><th>Stimme</th><th>Stil-Treue</th><th>Wo es abweicht</th><th>Maßstab</th></tr>
        ${r.rangliste.map((x) => `<tr><td>${esc(x.name)}</td><td>${styleChip(x.wert, x.urteil)}</td>
          <td class="small">${esc(x.abweichungen.join(", ") || "–")}</td>
          <td class="small muted">${esc(x.quelle || "")} · ${Number(x.basis_woerter).toLocaleString("de-DE")} Wörter${x.sicher ? "" : " ⚠ unsicher"}</td></tr>`).join("")}</table>` : ""}`;
  });
  el.querySelectorAll("[data-voice]").forEach((c) => (c.onclick = () => { S.stimme = c.dataset.voice; S.stimmeNeu = false; render(); }));
  el.querySelectorAll("[data-voice-back]").forEach((b) => (b.onclick = () => guard(async () => {
    await api(`/api/stimmen/${b.dataset.voiceBack}/archiv`, { method: "POST", body: { zurueck: true } }); S.stimme = b.dataset.voiceBack; render(); })));
  $("#st-new").onclick = () => { S.stimmeNeu = true; render(); };
  $("#st-import").onclick = voiceImport;
  const box = $("#st-detail");
  if (S.stimmeNeu || !voices.length) return voiceNewForm(box, data);
  if (S.stimme) return voiceDetail(box, data, S.stimme, st, worldVoice);
};

async function voiceExport(vid) {
  const file = await api("/api/stimmen/export", { method: "POST", body: { ids: [vid] } });
  const name = file.stimmen[0].name.replace(/[^\wäöüÄÖÜß-]+/g, "-").replace(/^-+|-+$/g, "") || "stimme";
  const blob = new Blob([JSON.stringify(file, null, 1)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `evel-schreibstil-${name}-${file.exportiert.slice(0, 10)}.json`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  toast(`Schreibstil „${file.stimmen[0].name}“ exportiert.`, "ok");
}

function voiceImport() {
  const input = document.createElement("input");
  input.type = "file"; input.accept = ".json,application/json";
  input.onchange = () => guard(async () => {
    const f = input.files[0];
    if (!f) return;
    let daten;
    try { daten = JSON.parse(await f.text()); } catch (e) { throw new Error("Die Datei ist kein gültiges JSON."); }
    const r = await api("/api/stimmen/import", { method: "POST", body: { daten } });
    const teile = [];
    r.neu.forEach((n) => teile.push(`„${n}“ angelegt`));
    r.umbenannt.forEach((x) => teile.push(`„${x.alt}“ gibt es schon – nicht überschrieben, angelegt als „${x.neu}“`));
    r.vorhanden.forEach((n) => teile.push(`„${n}“ ist bereits genau so vorhanden – nichts geändert`));
    if (r.verborgen) teile.push(`${r.verborgen} mit verborgenen Text-Auszügen`);
    if (r.ungueltig) teile.push(`${r.ungueltig} ungültig übersprungen`);
    modal(`<h2>Schreibstil importiert</h2><ul>${teile.map((t) => `<li>${esc(t)}</li>`).join("") || "<li>Nichts zu übernehmen.</li>"}</ul>
      <div class="row" style="justify-content:flex-end"><button class="primary" data-close="1">OK</button></div>`);
    S.stimmeNeu = false;
    if (r.ids.length) S.stimme = r.ids[r.ids.length - 1];
    render();
  });
  input.click();
}

function voiceNewForm(box, data) {
  const people = data.menschen || [];
  box.innerHTML = `<div class="card stack"><h3 style="margin:0">Neue Stimme</h3>
    <div class="row" id="vn-art">${Object.entries(data.arten).map(([k, l], i) => `<label class="row small" style="gap:6px">
      <input type="radio" name="vn-art" value="${k}" ${i === 0 ? "checked" : ""} style="width:auto"> ${esc(l)}</label>`).join("")}</div>
    <div class="form">
      <div class="field" data-for="autor"><label>Autor, an dem sich die Stimme orientiert</label>
        <input id="vn-vorbild" placeholder="z. B. Stanisław Lem, Ursula K. Le Guin, Douglas Adams"></div>
      <div class="field" data-for="autor"><label>Bücher / Texte dieses Autors als Referenz (optional, sehr empfohlen)</label>
        <div class="stack small">${people.some((p) => p.texte.length) ? people.map((p) => p.texte.map((t) => `<label class="row" style="gap:6px">
          <input type="checkbox" data-vr="${t.id}" data-vr-p="${p.id}" style="width:auto"> ${esc(t.titel)}
          <span class="muted">${(t.woerter || 0).toLocaleString("de-DE")} Wörter${t.autor ? ` · ${esc(t.autor)}` : ""}${t.fremd ? " · fremder Text" : ""} · bei ${esc(p.name)}</span></label>`).join("")).join("")
          : '<span class="muted">Noch keine Texte – unter „👤 Mensch → Texte als Basis“ ein Buch einfügen (als „fremd“ markieren).</span>'}</div>
        <div class="small muted">Daraus misst Evel den Stil-Fingerabdruck (Satzbau, Rhythmus, Dialog, Erzählzeit, kleine Wörter …).
          Der Text selbst geht nie an die Schreib-KI – nur die Kennzahlen.</div></div>
      <div class="field hidden" data-for="mensch"><label>Mensch</label><select id="vn-mensch">
        ${people.map((p) => `<option value="${p.id}">${esc(p.name)} (${p.texte.length} Text${p.texte.length === 1 ? "" : "e"})</option>`).join("")}</select>
        <div id="vn-texte" class="stack small" style="margin-top:8px"></div>
        <div class="small muted">Texte legst du unter „👤 Mensch → Texte als Basis“ an. Auszüge dienen dem Autor als Stilanker.</div></div>
      <div class="field" data-for="frei autor mensch"><label>Beschreibung (optional, ergänzt das Vorbild)</label>
        <textarea id="vn-beschreibung" rows="3" placeholder="z. B. knapp, trocken, viel Technik, warmherzige Figuren …"></textarea></div>
      <div class="field"><label>Name der Stimme (optional)</label><input id="vn-name" placeholder="sonst „Wie …“"></div></div>
    <div class="row" style="justify-content:flex-end"><button class="ghost" id="vn-cancel">Abbrechen</button>
      <button class="ki" id="vn-create">Anlegen und Steckbrief erstellen</button></div></div>`;
  const art = () => box.querySelector('input[name="vn-art"]:checked').value;
  const texts = () => {
    const p = people.find((x) => x.id === $("#vn-mensch").value);
    $("#vn-texte").innerHTML = p && p.texte.length ? p.texte.map((t) => `<label class="row" style="gap:6px"><input type="checkbox" data-vt="${t.id}" ${t.stil ? "checked" : ""} style="width:auto">
      ${esc(t.titel)} <span class="muted">${(t.woerter || 0).toLocaleString("de-DE")} Wörter</span></label>`).join("") : '<span class="muted">Keine Texte hinterlegt.</span>';
  };
  const sync = () => box.querySelectorAll("[data-for]").forEach((f) => f.classList.toggle("hidden", !f.dataset.for.split(" ").includes(art())));
  box.querySelectorAll('input[name="vn-art"]').forEach((r) => (r.onchange = sync));
  if ($("#vn-mensch")) { $("#vn-mensch").onchange = texts; texts(); }
  sync();
  $("#vn-cancel").onclick = () => { S.stimmeNeu = false; render(); };
  $("#vn-create").onclick = () => guard(async () => {
    const refs = [...box.querySelectorAll("[data-vr]:checked")];
    const refOwner = refs.length ? refs[0].dataset.vrP : null;
    const body = { art: art(), vorbild: $("#vn-vorbild").value, name: $("#vn-name").value, beschreibung: $("#vn-beschreibung").value,
      profil_id: art() === "autor" ? (refOwner || (S.user ? S.user.id : null)) : ($("#vn-mensch") ? $("#vn-mensch").value : null),
      texte: [...box.querySelectorAll("[data-vt]:checked")].map((x) => x.dataset.vt),
      referenz_texte: refs.filter((x) => x.dataset.vrP === refOwner).map((x) => x.dataset.vr) };
    $("#vn-create").disabled = true; $("#vn-create").textContent = "KI erstellt den Steckbrief …";
    try {
      const v = await api("/api/stimmen", { method: "POST", body });
      S.stimme = v.id; S.stimmeNeu = false;
      await api(`/api/stimmen/${v.id}/auswerten`, { method: "POST", body: {} }).catch((e) => toast(`Steckbrief: ${e.message}`, "bad"));
      toast("Stimme angelegt.", "ok");
    } finally { render(); }
  });
}

async function voiceDetail(box, data, vid, st, worldVoice) {
  const [v, tt] = await Promise.all([api(`/api/stimmen/${vid}`), api("/api/tts").catch(() => ({ server: [] }))]);
  const pa = v.probe && v.probe.audio;
  const person = (data.menschen || []).find((p) => p.id === v.profil_id);
  const changedSince = v.probe && JSON.stringify(v.probe.regler || {}) !== JSON.stringify(v.regler || {});
  const slider = (r) => { const val = Number((v.regler || {})[r.id] || 0);
    return `<div class="field slider"><label>${esc(r.label)}: <b data-sl-out="${r.id}">${esc(sliderWord(r, val))}</b></label>
      <div class="row small muted" style="gap:8px;flex-wrap:nowrap"><span>${esc(r.stufen[0])}</span>
        <input type="range" min="-2" max="2" step="1" value="${val}" data-sl="${r.id}" style="flex:1">
        <span>${esc(r.stufen[3])}</span></div></div>`; };
  box.innerHTML = `<div class="stack">
    <div class="row spread"><div><h2 style="margin-bottom:4px">${esc(v.name)}</h2>
      <div class="small muted">${esc(ART_TEXT[v.art] || v.art)}${v.vorbild && v.art !== "frei" ? ` · ${esc(v.vorbild)}` : ""}
        ${v.ausgewertet ? ` · Steckbrief vom ${esc(v.ausgewertet)}${v.modell ? ` (${esc(v.modell)})` : ""}` : ""}</div></div>
      <div class="row"><button class="ki" id="vd-analyze">${Object.keys(v.steckbrief || {}).length ? "Steckbrief neu erstellen" : "Steckbrief erstellen"}</button>
        <button class="ghost" id="vd-export" title="Diesen Schreibstil als Datei sichern">⇩ Exportieren</button>
        <button class="danger" id="vd-arch">Ins Archiv</button></div></div>

    <div class="card stack"><h3 style="margin:0">Basis</h3><div class="form">
      <div class="row"><div class="field" style="flex:1"><label>Name</label><input id="vd-name" value="${esc(v.name)}"></div>
        ${v.art === "autor" ? `<div class="field" style="flex:1"><label>Vorbild (Autor)</label><input id="vd-vorbild" value="${esc(v.vorbild)}"></div>` : ""}</div>
      ${v.basis ? `<div class="note small">${v.basis.verborgen
          ? `🔒 Basis aus ${esc(v.basis.quelle || "Import")}: Texte von ${esc(v.basis.owner_name || "einem anderen Autor")} – verborgen.
             Die Stimme nutzt ${v.basis.anker_zeichen.toLocaleString("de-DE")} Zeichen Stilanker und ${v.basis.referenz_zeichen.toLocaleString("de-DE")} Zeichen Maßstab, angezeigt wird nichts davon.
             Sichtbar wird es erst, wenn dieser Mensch per Autor-Export hierher umzieht.`
          : `Basis aus ${esc(v.basis.quelle || "Export")}: ${v.basis.anker_zeichen.toLocaleString("de-DE")} Zeichen Stilanker, ${v.basis.referenz_zeichen.toLocaleString("de-DE")} Zeichen Maßstab.`}</div>` : ""}
      ${v.art === "mensch" ? `<div class="field"><label>Texte von ${esc(person ? person.name : v.vorbild)} als Basis</label>
        <div class="stack small">${person && person.texte.length ? person.texte.map((t) => `<label class="row" style="gap:6px"><input type="checkbox" data-vt="${t.id}" ${(v.texte || []).includes(t.id) ? "checked" : ""} style="width:auto">
          ${esc(t.titel)} <span class="muted">${(t.woerter || 0).toLocaleString("de-DE")} Wörter</span></label>`).join("") : '<span class="muted">Keine Texte – unter „👤 Mensch“ hinzufügen.</span>'}</div></div>` : ""}
      ${v.art === "autor" ? `<div class="field"><label>Bücher / Texte von ${esc(v.vorbild || "diesem Autor")} als Referenz</label>
        <div class="stack small">${person && person.texte.length ? person.texte.map((t) => `<label class="row" style="gap:6px"><input type="checkbox" data-vr="${t.id}" ${(v.referenz_texte || []).includes(t.id) ? "checked" : ""} style="width:auto">
          ${esc(t.titel)} <span class="muted">${(t.woerter || 0).toLocaleString("de-DE")} Wörter${t.autor ? ` · ${esc(t.autor)}` : ""}${t.fremd ? " · fremder Text" : ""}</span></label>`).join("")
          : `<span class="muted">Keine Texte${person ? ` bei ${esc(person.name)}` : ""} – unter „👤 Mensch → Texte als Basis“ ein Buch einfügen.</span>`}</div>
        <div class="small muted">Nur zum Messen (Fingerabdruck) und für kurze Analyse-Auszüge beim Steckbrief – nie als Vorlage für den Autor.</div></div>` : ""}
      <div class="field"><label>${v.art === "frei" ? "Beschreibung der Stimme" : "Ergänzende Beschreibung"}</label>
        <textarea id="vd-beschreibung" rows="2">${esc(v.beschreibung || "")}</textarea></div></div></div>

    <div class="card stack"><h3 style="margin:0">Stil-Steckbrief</h3>
      <p class="small muted">Von der KI aus dem Vorbild abgeleitet – alles änderbar. Genau dieser Text geht an Planer, Autor, Lektor und Prüfer.</p>
      <form class="form" id="vd-brief">${data.felder.map((f) => `<div class="field"><label>${esc(f.label)}</label>
        <textarea name="${f.id}" style="min-height:48px">${esc((v.steckbrief || {})[f.id] || "")}</textarea></div>`).join("")}</form></div>

    <div class="card stack"><h3 style="margin:0">Justieren</h3>
      <p class="small muted">Mitte = wie das Vorbild. Danach eine neue Probe schreiben lassen und vergleichen.</p>
      <div class="sliders">${data.regler.map(slider).join("")}</div>
      <div class="field"><label>Hinweise an die Stimme (verbindlich)</label>
        <textarea id="vd-hinweise" rows="2" placeholder="z. B. keine Anglizismen, Technik nie erklären, Figuren duzen sich">${esc(v.hinweise || "")}</textarea></div>
      <div class="row" style="justify-content:flex-end"><button class="primary" id="vd-save">Speichern</button></div></div>

    <div class="card stack"><div class="row spread"><h3 style="margin:0">Probe</h3>
      <div class="row"><input id="vd-pw" type="number" min="80" max="600" step="20" value="220" style="width:90px"><span class="small muted">Wörter</span>
        <button class="ki" id="vd-probe">${v.probe ? "Neue Probe schreiben" : "Probe schreiben"}</button></div></div>
      <p class="small muted">Eine kurze Szene in ${S.world ? `der Welt „${esc(S.world)}“` : "einer neutralen Welt"} – so klingt die Stimme mit Steckbrief und Reglern.
        Die freigegebene Probe wird zum Stilanker für den Autor${v.art === "mensch" ? "" : " und zum messbaren Maßstab"}.</p>
      ${v.probe ? `<div class="small">${v.probe.freigegeben ? `<span class="chip st-fertig">freigegeben ${esc(v.probe.freigegeben_am || "")}</span>` : '<span class="chip st-offen">nicht freigegeben</span>'}
          · ${esc(v.probe.am)} · ${esc(v.probe.modell || "")}${changedSince ? ' · <span class="warn-text">Regler seit der Probe geändert – neue Probe empfohlen</span>' : ""}</div>
        <pre class="live probe">${esc(v.probe.text)}</pre>
        <div class="row">${tt.server.length ? `<select id="vd-tts" title="Vorlese-Stimme (eine Stimme für alles)">${voiceOptions(tt, (pa && pa.ref) || "", S.world ? "Erzähler-Stimme der Welt" : "— Stimme wählen —")}</select>
          <button class="ki" id="vd-audio">🎙 Als Hörbuch vorlesen</button>
          ${v.probe_audio_aktuell ? `<audio controls preload="none" src="/api/stimmen/${v.id}/probe.wav?t=${encodeURIComponent(pa.am)}" style="height:36px"></audio>
            <a class="small" href="/api/stimmen/${v.id}/probe.wav?download=1">WAV</a>
            <span class="small muted">${esc(pa.server || "")} · ${esc(pa.stimme_name || pa.stimme || "")}</span>` : ""}`
          : '<span class="small muted">Zum Vorlesen erst unter Einstellungen → TTS-Server einen Server einrichten.</span>'}</div>
        <div class="row" style="justify-content:flex-end">${v.probe.freigegeben ? '<button class="ghost" id="vd-unok">Freigabe zurücknehmen</button>'
          : '<button class="primary" id="vd-ok">Passt – als Maßstab freigeben</button>'}</div>` : ""}</div>

    <div class="card stack"><div class="row spread"><h3 style="margin:0">Stil-Fingerabdruck – woran jede Folge gemessen wird</h3>
        <button class="ghost" id="vd-fp" title="Fingerabdruck aus der aktuellen Basis neu messen">↻ Neu messen</button></div>
      ${v.fingerabdruck ? `<p class="small muted">Gemessen aus ${esc(v.fingerabdruck.quelle || "")}${v.fingerabdruck.titel ? ` („${esc(v.fingerabdruck.titel)}“)` : ""}:
          ${Number(v.fingerabdruck.woerter || 0).toLocaleString("de-DE")} Wörter in ${v.fingerabdruck.abschnitte} Abschnitten, ${esc(v.fingerabdruck.erstellt || "")}.
          „Normal“ ist die Spanne, in der das Vorbild selbst schwankt – liegt eine Folge außerhalb, zeigt der Stil-Abgleich an der Folge das Merkmal an.
          ${(v.fingerabdruck.woerter || 0) < 5000 ? '<br><span class="warn-text">Wenig Text als Basis – die Spannen sind geschätzt. Mit eigenen Texten oder einem Buch des Vorbilds wird der Abgleich verlässlich.</span>' : ""}</p>
        <table class="qtable small"><tr><th>Merkmal</th><th>Vorbild</th><th>normal</th></tr>
          ${(v.fingerabdruck_tabelle || []).map((r) => `<tr><td>${esc(r.label)}</td><td><b>${esc(r.wert)}</b></td><td class="muted">${esc(r.spanne)}</td></tr>`).join("")}</table>`
        : `<p class="small muted">Noch kein Fingerabdruck – ${v.art === "mensch" ? "eigene Texte als Basis wählen" : v.art === "autor" ? "ein Buch des Autors als Referenz wählen oder eine Probe freigeben" : "eine Probe freigeben"}.</p>`}
    </div>
    <div class="card stack"><h3 style="margin:0">Maßstab – woran sich alle abgleichen</h3>
      ${v.messwerte ? `<dl class="kv">${Object.entries(MESS_LABEL).map(([k, l]) => `<dt>${esc(l)}</dt><dd>${esc(v.messwerte[k] ?? "–")}</dd>`).join("")}
        <dt>Quelle</dt><dd>${esc(v.messwerte.quelle || "")}</dd></dl>`
        : `<p class="small muted">Noch kein messbarer Maßstab – ${v.art === "mensch" ? "Texte als Basis wählen" : "eine Probe freigeben"}. Bis dahin vergleicht die Stil-Messung mit den letzten Folgen.</p>`}
      <details ${S.expert ? "open" : ""}><summary class="small">So bekommen es Planer, Autor und Lektor</summary><pre class="live qa-pre">${esc(v.schreib_block)}</pre></details>
      <details ${S.expert ? "open" : ""}><summary class="small">So prüft der Prüfer</summary><pre class="live qa-pre">${esc(v.pruef_block)}</pre></details></div>

    ${S.world && st ? `<div class="card stack"><h3 style="margin:0">Verwendung in „${esc(S.world)}“</h3>
      <div class="row spread"><span>Welt-Standard ${worldVoice === v.id ? '<span class="chip st-fertig">diese Stimme</span>' : ""}</span>
        ${worldVoice === v.id ? '<button class="ghost" id="vd-world-off">Nicht mehr Standard</button>' : '<button class="ghost" id="vd-world-on">Als Welt-Standard setzen</button>'}</div>
      ${st.geschichten.length ? `<table class="qtable"><tr><th>Geschichte</th><th>Stimme</th></tr>${st.geschichten.map((g) => `<tr><td>${esc(g.title || `Strang ${g.id}`)}</td>
        <td><select data-story-voice="${g.id}"><option value="">wie Welt</option>${data.stimmen.map((x) => `<option value="${x.id}" ${g.stimme_id === x.id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></td></tr>`).join("")}</table>`
        : '<p class="small muted">Noch keine Geschichten in dieser Welt.</p>'}
      <p class="small muted">Beim Erzeugen einer Folge kannst du die Stimme auch nur für diese Folge wählen; eine neue Geschichte behält sie dann.</p></div>` : ""}
  </div>`;
  const P = `/api/stimmen/${vid}`;
  box.querySelectorAll("[data-sl]").forEach((r) => (r.oninput = () => {
    const spec = data.regler.find((x) => x.id === r.dataset.sl);
    box.querySelector(`[data-sl-out="${r.dataset.sl}"]`).textContent = sliderWord(spec, Number(r.value));
  }));
  const collect = () => ({ name: $("#vd-name").value, vorbild: $("#vd-vorbild") ? $("#vd-vorbild").value : undefined,
    beschreibung: $("#vd-beschreibung").value, hinweise: $("#vd-hinweise").value,
    steckbrief: Object.fromEntries(new FormData($("#vd-brief")).entries()),
    regler: Object.fromEntries([...box.querySelectorAll("[data-sl]")].map((r) => [r.dataset.sl, Number(r.value)])),
    ...(v.art === "mensch" ? { texte: [...box.querySelectorAll("[data-vt]:checked")].map((x) => x.dataset.vt) } : {}),
    ...(v.art === "autor" && person ? { referenz_texte: [...box.querySelectorAll("[data-vr]:checked")].map((x) => x.dataset.vr) } : {}) });
  const save = () => api(P, { method: "PUT", body: collect() });
  $("#vd-save").onclick = () => guard(async () => { await save(); toast("Stimme gespeichert.", "ok"); render(); });
  $("#vd-analyze").onclick = () => guard(async () => {
    if (Object.keys(v.steckbrief || {}).length && !confirm("Steckbrief neu erstellen? Deine Änderungen am Steckbrief werden überschrieben (Regler und Hinweise bleiben).")) return;
    $("#vd-analyze").disabled = true; $("#vd-analyze").textContent = "KI arbeitet …";
    try { await save(); await api(`${P}/auswerten`, { method: "POST", body: {} }); toast("Steckbrief erstellt.", "ok"); } finally { render(); }
  });
  $("#vd-probe").onclick = () => guard(async () => {
    $("#vd-probe").disabled = true; $("#vd-probe").textContent = "Stimme schreibt …";
    try { await save(); await api(`${P}/probe`, { method: "POST", body: { welt: S.world || null, woerter: Number($("#vd-pw").value) } }); } finally { render(); }
  });
  if ($("#vd-audio")) $("#vd-audio").onclick = () => guard(async () => {
    $("#vd-audio").disabled = true; $("#vd-audio").textContent = "TTS spricht …";
    try { await api(`${P}/probe/audio`, { method: "POST", body: { stimme: $("#vd-tts").value || null, welt: S.world || null } });
      toast("Probe vertont.", "ok"); } finally { render(); }
  });
  if ($("#vd-ok")) $("#vd-ok").onclick = () => guard(async () => { await api(`${P}/probe/freigeben`, { method: "POST", body: { ok: true } }); toast("Probe ist jetzt Maßstab.", "ok"); render(); });
  if ($("#vd-unok")) $("#vd-unok").onclick = () => guard(async () => { await api(`${P}/probe/freigeben`, { method: "POST", body: { ok: false } }); render(); });
  $("#vd-export").onclick = () => guard(() => voiceExport(v.id));
  $("#vd-fp").onclick = () => guard(async () => { await save(); await api(`${P}/fingerabdruck`, { method: "POST", body: {} }); toast("Fingerabdruck neu gemessen.", "ok"); render(); });
  $("#vd-arch").onclick = () => confirm(`„${v.name}“ ins Archiv legen?`) && guard(async () => { await api(`${P}/archiv`, { method: "POST", body: {} }); S.stimme = null; render(); });
  if ($("#vd-world-on")) $("#vd-world-on").onclick = () => guard(async () => { await api(W("/settings"), { method: "POST", body: { stimme: vid } }); toast("Welt-Standard gesetzt.", "ok"); render(); });
  if ($("#vd-world-off")) $("#vd-world-off").onclick = () => guard(async () => { await api(W("/settings"), { method: "POST", body: { stimme: "" } }); render(); });
  box.querySelectorAll("[data-story-voice]").forEach((s) => (s.onchange = () => guard(async () => {
    await api(W(`/stories/${s.dataset.storyVoice}/stimme`), { method: "PUT", body: { stimme_id: s.value || null } }); toast("Gespeichert.", "ok");
  })));
}

function sliderWord(spec, val) {
  if (!val) return "wie das Vorbild";
  return spec.stufen[{ "-2": 0, "-1": 1, "1": 2, "2": 3 }[String(val)]];
}

VIEWS.laeufe = async (el) => {
  if (S.runId) return runDetail(el, S.runId);
  const { laeufe } = await api(W("/runs"));
  el.innerHTML = `<h2>KI-Läufe</h2><p class="muted">Jeder Auftrag an die KI mit Fortschritt, Weg und Ergebnis – dauerhaft gespeichert.</p>
    <div class="card">${laeufe.length ? `<table><tr><th>Start (UTC)</th><th>Art</th><th>Ziel</th><th>Status</th><th style="width:28%">Fortschritt</th><th>Modell</th></tr>
    ${laeufe.map((r) => `<tr class="click" data-run="${r.id}"><td class="small">${esc(r.started_at)}</td><td>${esc(r.art)}</td>
      <td>${esc(r.ziel || "")}</td><td>${chip(r.status)}</td>
      <td>${bar(r.status, r.progress, true)}<div class="small muted">${r.status === "laeuft" ? esc(r.phase || "") : fmtSec(r.duration)}</div></td>
      <td class="small">${esc(r.model || "")}</td></tr>`).join("")}</table>` : '<div class="empty">Noch keine KI-Läufe.</div>'}</div>`;
  el.querySelectorAll("[data-run]").forEach((tr) => (tr.onclick = () => { S.runId = Number(tr.dataset.run); render(); }));
  if (laeufe.some((r) => r.status === "laeuft")) scheduleRefresh(() => S.view === "laeufe" && !S.runId && render());
};

let refreshTimer = null;
function scheduleRefresh(fn) { clearTimeout(refreshTimer); refreshTimer = setTimeout(fn, 1000); }

function stepsHtml(steps) {
  return `<ul class="steps">${steps.map((st) => `<li class="${esc(st.stufe)}"><span class="t">${esc(st.zeit)}</span>
    <span class="t">+${esc(st.sekunden)} s</span><span class="x">${esc(st.text)}</span></li>`).join("")}</ul>`;
}

async function runDetail(el, id) {
  const r = await api(W(`/runs/${id}`));
  const v = r.vorschlag;
  el.innerHTML = `<div class="stack"><div class="row"><button class="ghost" id="r-back">← Alle Läufe</button>
      <h2 style="margin:0">${esc(r.art)}${r.ziel ? ": " + esc(r.ziel) : ""}</h2>${chip(r.status)}</div>
    <div class="card stack"><div class="row spread"><span id="r-phase">${esc(r.status === "laeuft" ? r.phase || "" : r.status === "fertig" ? "Abgeschlossen" : r.error || r.status)}</span>
      <span class="small muted" id="r-meta">${esc(r.model || "")} · Start ${esc(r.started_at)} UTC${r.duration ? " · " + fmtSec(r.duration) : ""}</span></div>
      <div id="r-bar">${bar(r.status, r.progress)}</div></div>
    <div class="card stack" id="r-trace">${traceHtml(r.nachvollzug, r.status)}</div>
    <div class="card stack"><h3>Auftrag (Frage an die KI)</h3><pre class="code">${esc(r.auftrag || "")}</pre></div>
    <div class="card stack"><h3>Weg</h3><div id="r-steps">${stepsHtml(r.steps)}</div></div>
    <div class="card stack" id="r-result">${resultHtml(r, v)}</div>
    ${(r.aufrufe || []).length ? `<details class="card" ${S.expert ? "open" : ""}><summary>KI-Aufrufe (${r.aufrufe.length}) – einzeln mit anderen Modellen vergleichen</summary>
      <table class="qtable"><tr><th>Schritt</th><th>Modell</th><th>Prompt</th><th>Antwort</th><th>Dauer</th><th></th></tr>
      ${r.aufrufe.map((c) => `<tr><td>${esc(c.step || c.task)}${c.ok ? "" : ` <span class="chip st-fehler" title="${esc(c.error || "")}">Fehler</span>`}</td>
        <td class="small">${esc(c.model || "")}</td><td class="small">${fmtVal("", c.prompt_chars)}</td><td class="small">${fmtVal("", c.response_chars)}</td>
        <td class="small">${c.seconds != null ? fmtSec(c.seconds) : ""}</td>
        <td>${c.ok ? `<button class="ghost" data-cmp="${c.id}">Vergleichen</button>` : ""}</td></tr>`).join("")}</table>
      <p class="small muted">Messwerte sind immer sichtbar; Antworttexte der Modelle nur mit Backstage.</p></details>` : ""}
    ${S.reveal ? `<div class="card stack"><h3>${r.status === "laeuft" ? "Antwort der KI – live" : "Rohantwort der KI"}</h3>
        <pre class="live" id="r-live">${esc(r.status === "laeuft" ? r.live_text || "…" : r.response || "(keine)")}</pre></div>
      <details class="card"><summary>Vollständiger Prompt (System + Kontext)</summary>${(r.prompt || []).map((m) =>
        `<h3 style="margin-top:12px">${esc(m.role)}</h3><pre class="live">${esc(m.content)}</pre>`).join("")}</details>`
      : `<div class="card small muted">🔒 Live-Antwort, Rohantwort und vollständiger Prompt können Geheimnisse enthalten –
         sichtbar nur mit „Backstage“ (oben rechts).</div>`}</div>`;
  $("#r-back").onclick = () => { S.runId = null; render(); };
  el.querySelectorAll("[data-cmp]").forEach((b) => (b.onclick = () => compareDialog(r.aufrufe.find((c) => String(c.id) === b.dataset.cmp))));
  bindResult();
  bindTrace();
  if (r.status === "laeuft") scheduleRefresh(() => liveUpdate(id));
}

// ------------------------------------------------------------ Nachvollzug eines Laufs

const OUTCOME = { ok: ["✔", "weitergeleitet"], eingriff: ["✋", "eingegriffen"], warnung: ["⚠", "Warnung"],
  mensch: ["👤", "bei dir"], fehler: ["✖", "Fehler"], info: ["•", "Info"] };
const ART_LABEL = { gewichtung: "Gewichtung", frage: "Antwort der KI", bewertung: "Bewertung", pruefung: "Prüfung",
  eingriff: "Eingriff", weiterleitung: "Weiterleitung", korrektur: "Korrekturrunde", ersatzmodell: "Ersatzmodell",
  entscheidung: "Entscheidung", warnung: "Warnung", fehler: "Fehler" };
const KEY_LABEL = { ziel_woerter: "Ziel (Wörter)", woerter: "Wörter", laenge_quote: "Länge / Ziel", kanonpassung: "Kanonpassung",
  ueberraschung: "Überraschung", widersprueche: "Widersprüche", begruendung: "Begründung", schwere_original: "Schwere vorher",
  geaendert_anteil: "Text geändert", im_text_erkennbar: "Im Text erkennbar", woerter_vorher: "Wörter vorher",
  woerter_nachher: "Wörter nachher", wendung_geschuetzt: "Wendung geschützt", min_kanon: "Mindest-Kanon",
  erzaehlprofil: "Erzählprofil", altersfreigabe: "Altersfreigabe", nur_warnung: "Nur Warnung", rueckfragen: "Rückfragen",
  uebersprungen: "übersprungen", ergaenzt: "ergänzt", raetsel: "Rätsel", ende_uebergabe: "Ende-Übergabe" };
const traceOpen = new Set();
const keyLabel = (k) => KEY_LABEL[k] || String(k).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

function kvHtml(v, depth = 0) {
  if (v == null || v === "") return '<span class="muted">–</span>';
  if (typeof v === "boolean") return v ? "ja" : "nein";
  if (typeof v === "number") return esc(Number.isInteger(v) ? v : Math.round(v * 1000) / 1000);
  if (typeof v === "string") return v.length > 160 ? `<div class="kv-long">${esc(v)}</div>` : esc(v);
  if (depth > 3) return `<code>${esc(JSON.stringify(v))}</code>`;
  if (Array.isArray(v)) {
    if (!v.length) return '<span class="muted">keine</span>';
    if (v.every((x) => x == null || typeof x !== "object")) return v.map((x) => esc(x)).join(" · ");
    return `<ol class="kv-list">${v.map((x) => `<li>${kvHtml(x, depth + 1)}</li>`).join("")}</ol>`;
  }
  return `<dl class="kv">${Object.entries(v).map(([k, x]) => `<dt>${esc(keyLabel(k))}</dt><dd>${kvHtml(x, depth + 1)}</dd>`).join("")}</dl>`;
}

function eventHtml(e) {
  const [icon, word] = OUTCOME[e.ausgang] || OUTCOME.info;
  const hasData = (e.eingaben != null && e.eingaben !== "") || (e.ergebnis != null && e.ergebnis !== "");
  return `<li class="ev o-${esc(e.ausgang)}"><span class="ev-i" title="${esc(word)}">${icon}</span><div class="ev-b">
    <div class="ev-t">${esc(e.titel)} <span class="ev-a">${(ART_LABEL[e.art] || e.art) === word ? "" : esc(ART_LABEL[e.art] || e.art) + " · "}${esc(word)}${e.sekunden != null ? ` · +${esc(e.sekunden)} s` : ""}</span></div>
    ${e.regel ? `<div class="ev-r">Regel: ${esc(e.regel)}</div>` : ""}
    ${e.verborgen ? '<div class="ev-r">🔒 Werte können Geheimnisse enthalten – sichtbar mit „Backstage“.</div>' : ""}
    ${hasData ? `<details class="ev-d" ${S.expert ? "open" : ""}><summary>Werte</summary>
      ${e.eingaben != null ? `<div class="ev-h">Eingaben</div>${kvHtml(e.eingaben)}` : ""}
      ${e.ergebnis != null ? `<div class="ev-h">Ergebnis</div>${kvHtml(e.ergebnis)}` : ""}</details>` : ""}
    ${e.call_id && S.reveal ? `<button class="ghost small" data-qa="${e.call_id}">Frage &amp; Antwort ansehen</button><div class="qa" id="qa-ev-${e.call_id}-${esc(e.id ?? "")}"></div>` : ""}
  </div></li>`;
}

function traceHtml(t, status) {
  if (!t) return "<h3>Nachvollzug</h3><div class='muted'>Keine Daten.</div>";
  if (t.modus === "fehler") return `<h3>Nachvollzug</h3><div class="err">${esc(t.fehler || "")}</div>`;
  const sums = t.summen || {};
  const chips = ["ok", "eingriff", "warnung", "mensch", "fehler"].filter((k) => sums[k])
    .map((k) => `<span class="oc o-${k}">${OUTCOME[k][0]} ${sums[k]} ${OUTCOME[k][1]}</span>`).join("");
  const strip = t.phasen.map((p, i) => `${i ? '<span class="ps-arrow">→</span>' : ""}<button class="ps o-${esc(p.status)}${status === "laeuft" && i === t.phasen.length - 1 ? " ps-live" : ""}" data-ph="${esc(p.id)}" title="${esc((OUTCOME[p.status] || OUTCOME.info)[1])}">${(OUTCOME[p.status] || OUTCOME.info)[0]} ${esc(p.label)}</button>`).join("");
  const phases = t.phasen.map((p, i) => {
    const auto = ["eingriff", "mensch", "fehler"].includes(p.status) || (status === "laeuft" && i === t.phasen.length - 1);
    const open = traceOpen.has(p.id) || (!traceOpen.has("!" + p.id) && (S.expert || auto));
    const calls = p.aufrufe.length ? `<table class="qtable tr-calls"><tr><th>KI-Aufruf</th><th>Modell</th><th>Frage</th><th>Antwort</th><th>Dauer</th><th></th></tr>
      ${p.aufrufe.map((c) => `<tr><td>${esc(c.step || c.task)}${c.ok ? "" : ` <span class="chip st-fehler" title="${esc(c.error || "")}">Fehler</span>`}${c.wiederholung ? ' <span class="chip st-offen">Wiederholung</span>' : ""}</td>
        <td class="small">${esc(c.model || "")}</td><td class="small">${fmtVal("", c.prompt_chars)} Z.</td><td class="small">${fmtVal("", c.response_chars)} Z.</td>
        <td class="small">${c.seconds != null ? fmtSec(c.seconds) : ""}</td>
        <td>${S.reveal ? `<button class="ghost small" data-qa="${c.id}">Frage &amp; Antwort</button>` : ""}</td></tr>
        <tr class="qa-row"><td colspan="6"><div class="qa" id="qa-call-${c.id}"></div></td></tr>`).join("")}</table>` : "";
    return `<details class="phase o-${esc(p.status)}" data-phase="${esc(p.id)}" ${open ? "open" : ""}>
      <summary><span class="ph-i">${(OUTCOME[p.status] || OUTCOME.info)[0]}</span> ${esc(p.label)}
        <span class="small muted">${p.ereignisse.length} ${p.ereignisse.length === 1 ? "Schritt" : "Schritte"}${p.aufrufe.length ? ` · ${p.aufrufe.length} ${p.aufrufe.length === 1 ? "KI-Aufruf" : "KI-Aufrufe"}` : ""}</span></summary>
      ${p.ereignisse.length ? `<ul class="evs">${p.ereignisse.map(eventHtml).join("")}</ul>` : ""}${calls}</details>`;
  }).join("");
  const ch = t.aenderungen || {};
  const changes = ch.anzahl ? `<div class="small">Änderungen an der Welt aus diesem Lauf: ${Object.entries(ch.sichtbar || {}).map(([k, n]) => `${esc(k)} ×${n}`).join(" · ")}${ch.verborgen ? ` · 🔒 ${ch.verborgen} Backstage` : ""}</div>` : "";
  return `<div class="row spread"><h3 style="margin:0">Nachvollzug – wie diese ${status === "laeuft" ? "Folge gerade entsteht" : "Ausgabe entstanden ist"}</h3><div class="ocs">${chips}</div></div>
    ${t.modus === "rekonstruiert" ? `<div class="small muted">Aus den vorhandenen Daten zusammengesetzt (Lauf von vor dem Entscheidungsprotokoll).${(t.fehlt || []).length ? ` Nicht erfasst: ${t.fehlt.map(esc).join(" · ")}.` : ""}</div>` : ""}
    ${t.modus === "leer" ? '<div class="muted small">Für diesen Lauf gibt es keine Entscheidungen zum Nachvollziehen.</div>' : ""}
    <div class="pstrip">${strip}</div>${phases}${changes}
    ${S.reveal ? "" : '<div class="small muted">🔒 Fragen an die KI, Antworten und manche Werte sind nur mit „Backstage“ sichtbar.</div>'}`;
}

function bindTrace() {
  const box = $("#r-trace");
  if (!box) return;
  box.querySelectorAll("details.phase").forEach((d) => d.addEventListener("toggle", () => {
    const id = d.dataset.phase;
    traceOpen.delete(id); traceOpen.delete("!" + id);
    traceOpen.add(d.open ? id : "!" + id);
  }));
  box.querySelectorAll("[data-ph]").forEach((b) => (b.onclick = () => {
    const d = box.querySelector(`details.phase[data-phase="${b.dataset.ph}"]`);
    if (d) { d.open = true; d.scrollIntoView({ behavior: "smooth", block: "start" }); }
  }));
  box.querySelectorAll("[data-qa]").forEach((b) => (b.onclick = async () => {
    const target = b.nextElementSibling && b.nextElementSibling.classList.contains("qa") ? b.nextElementSibling : $(`#qa-call-${b.dataset.qa}`);
    if (!target) return;
    if (target.innerHTML) { target.innerHTML = ""; return; }
    target.innerHTML = '<div class="muted small">Lade …</div>';
    try {
      const c = await api(W(`/aufrufe/${b.dataset.qa}`));
      target.innerHTML = `<div class="small muted">${esc(c.model || "")} · ${esc(c.step || c.task || "")}${c.error ? ` · <span class="err">${esc(c.error)}</span>` : ""}</div>
        ${(c.nachrichten || []).map((m) => `<div class="ev-h">${m.role === "system" ? "Rolle & Regeln (System)" : m.role === "user" ? "Frage (Kontext + Aufgabe)" : "Vorige Antwort"} · ${fmtVal("", m.zeichen)} Zeichen${m.gekuerzt ? " · Mitte gekürzt" : ""}</div><pre class="live qa-pre">${esc(m.content)}</pre>`).join("")}
        <div class="ev-h">Antwort der KI</div><pre class="live qa-pre">${esc(c.response || "(keine)")}</pre>`;
    } catch (err) { target.innerHTML = `<div class="err">${esc(err.message || err)}</div>`; }
  }));
}

function resultHtml(r, v) {
  if (r.status === "laeuft") return `<h3>Ergebnis</h3><div class="muted">Läuft noch …</div>`;
  if (r.status === "fehler" || r.status === "abgebrochen")
    return `<h3>Ergebnis</h3><div class="err">${esc(r.error || "Lauf wurde abgebrochen (Server beendet).")}</div>`;
  if (r.folge) return `<h3>Ergebnis</h3><div class="summary">${r.folge.form === "geschichte" ? "Eigenständige Geschichte" : `Folge ${r.folge.release_nr}`}: „${esc(r.folge.title || "")}“</div>
    <div class="row"><span class="small">${r.folge.word_count || 0} Wörter ≈ ${Math.round((r.folge.word_count || 0) / 135)} Minuten</span>
    <button class="primary" data-goto-ep="${r.folge.id}">Folge lesen / hören</button></div>`;
  if (!v) return `<h3>Ergebnis</h3><div class="muted">Kein Vorschlag.</div>`;
  const res = v.result;
  return `<h3>Ergebnis</h3><div class="summary">${esc(v.summary)}</div>
    <div class="row">${chip(v.status)}${res ? `<span class="small">${res.angelegt} angelegt, ${res.ergaenzt} ergänzt${res.fehlgeschlagen ? `, ${res.fehlgeschlagen} übersprungen` : ""}</span>` : ""}
    <button class="ghost" data-goto-prop="1">Zum Vorschlag</button></div>`;
}
function bindResult() {
  document.querySelectorAll("[data-goto-prop]").forEach((b) => (b.onclick = () => go("vorschlaege")));
  document.querySelectorAll("[data-goto-ep]").forEach((b) => (b.onclick = () => go("folgen", Number(b.dataset.gotoEp))));
}

async function liveUpdate(id) {
  if (S.view !== "laeufe" || S.runId !== id) return;
  const r = await api(W(`/runs/${id}`)).catch(() => null);
  if (!r || !$("#r-bar")) return;
  $("#r-bar").innerHTML = bar(r.status, r.progress);
  $("#r-phase").textContent = r.status === "laeuft" ? r.phase || "" : r.status === "fertig" ? "Abgeschlossen" : r.error || r.status;
  $("#r-steps").innerHTML = stepsHtml(r.steps);
  const reading = [...document.querySelectorAll("#r-trace .qa")].some((q) => q.innerHTML.trim());
  if ($("#r-trace") && !reading) { $("#r-trace").innerHTML = traceHtml(r.nachvollzug, r.status); bindTrace(); }
  const live = $("#r-live");
  if (live) {
    const atBottom = live.scrollTop + live.clientHeight >= live.scrollHeight - 30;
    live.textContent = r.status === "laeuft" ? r.live_text || "…" : r.response || "(keine)";
    if (atBottom) live.scrollTop = live.scrollHeight;
  }
  if (r.status === "laeuft") scheduleRefresh(() => liveUpdate(id));
  else { $("#r-result").innerHTML = resultHtml(r, r.vorschlag); bindResult();
    $("#r-meta").textContent = `${r.model || ""} · Start ${r.started_at} UTC · ${fmtSec(r.duration)}`; }
}

// ------------------------------------------------------------ Welt (Datensätze)

const REL_LABEL = { elternteil: "Elternteil", kind: "Kind", partner: "Partner/in", geschwister: "Geschwister",
  grosselternteil: "Großelternteil", enkel: "Enkel/in", verwandt: "Verwandt", freund: "Freund/in", kollege: "Kolleg/in",
  mentor: "Mentor/in", schueler: "Schüler/in", rivale: "Rivale", sonstiges: "Sonstiges" };
const kindLabel = (k) => (S.cfg.stufen && S.cfg.stufen[k]) || k || "";
const rankOf = (k) => (S.cfg.ort_rang && S.cfg.ort_rang[k] != null ? S.cfg.ort_rang[k] : -1);
const val = (v) => (v == null ? "" : esc(v));
const openLink = (table, id, name) => (id ? `<a href="#" data-open="${table}:${id}">${esc(name)}</a>` : "");

function placeTree(rows) {
  const ids = new Set(rows.map((r) => r.id));
  const kids = {};
  rows.forEach((r) => { if (r.parent_id != null && ids.has(r.parent_id)) (kids[r.parent_id] = kids[r.parent_id] || []).push(r); });
  const byId = Object.fromEntries(rows.map((r) => [r.id, r]));
  for (let cur = byId[S.place]; cur && cur.parent_id != null && byId[cur.parent_id]; cur = byId[cur.parent_id]) S.open.add(cur.parent_id);
  const order = (a, b) => rankOf(b.kind) - rankOf(a.kind) || a.name.localeCompare(b.name, "de");
  const node = (r, depth) => {
    const ch = (kids[r.id] || []).sort(order), open = S.open.has(r.id);
    return `<div class="tnode ${S.place === r.id ? "active" : ""}" style="padding-left:${6 + depth * 14}px">
      <span class="tw" ${ch.length ? `data-tog="${r.id}"` : ""}>${ch.length ? (open ? "▾" : "▸") : "·"}</span>
      <span class="tn" data-place="${r.id}" title="${esc(kindLabel(r.kind))}">${esc(r.name)}</span>
      ${ch.length ? `<span class="tc">${ch.length}</span>` : ""}</div>` + (open ? ch.map((c) => node(c, depth + 1)).join("") : "");
  };
  const roots = rows.filter((r) => r.parent_id == null || !ids.has(r.parent_id)).sort(order);
  return `<div class="tree">${roots.map((r) => node(r, 0)).join("") || '<div class="muted small" style="padding:6px">Noch keine Orte.</div>'}</div>`;
}

// Abschnitt mit klickbaren Zeilen; open = "tabelle:id" je Zeile
function sec(title, items, head, cells, open, extra = "", empty = "") {
  if (!items.length && !empty) return "";
  return `<div class="card dsec"><div class="row spread"><h3 style="margin:0">${esc(title)} <span class="muted">${items.length || ""}</span></h3>${extra}</div>
    ${items.length ? `<table><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>${items.map((r) =>
      `<tr class="click" data-open="${open(r)}">${cells(r).map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</table>`
      : `<div class="muted small" style="margin-top:8px">${esc(empty)}</div>`}</div>`;
}

function openItem(table, id) {
  if (table === "locations") { S.entity = "locations"; S.place = id; S.person = null; S.open.add(id); return render(); }
  if (table === "characters") { S.entity = "characters"; S.person = id; S.place = null; return render(); }
  editDialog(table, id);
}

function bindDossier(root) {
  root.querySelectorAll("[data-open]").forEach((x) => (x.onclick = (e) => {
    e.preventDefault();
    if (e.target.closest("[data-edit]") && e.target.closest("[data-edit]") !== x) return;
    const [t, i] = x.dataset.open.split(":"); openItem(t, Number(i));
  }));
  root.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = (e) => {
    e.preventDefault(); e.stopPropagation();
    const [t, i] = b.dataset.edit.split(":"); editDialog(t, Number(i));
  }));
  root.querySelectorAll("[data-add]").forEach((b) => (b.onclick = () => editDialog(b.dataset.add, null, JSON.parse(b.dataset.def || "{}"))));
  root.querySelectorAll("[data-crumb]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); S.place = S.person = null; render(); }));
}

async function placeView(main, id) {
  const d = await api(W(`/dossier/locations/${id}`));
  const p = d.ort, def = (o) => esc(JSON.stringify(o));
  const empty = [["Figuren", d.figuren], ["Völker", d.voelker], ["Firmen", d.organisationen], ["Jobs", d.jobs],
    ["Stränge", d.straenge], ["Ereignisse", d.ereignisse]].filter(([, l]) => !l.length).map(([n]) => n);
  main.innerHTML = `<div class="crumbs"><a href="#" data-crumb="1">Orte & Welten</a>${d.pfad.map((x) => ` › ${openLink("locations", x.id, x.name)}`).join("")} › <b>${esc(p.name)}</b></div>
    <div class="row spread"><div><h2 style="margin:0">${esc(p.name)}</h2>
      <div class="row small" style="margin-top:4px"><span class="chip">${esc(d.art)}</span>${p.level ? `<span class="chip">${esc(p.level)}</span>` : ""}
      ${d.unterorte_gesamt ? `<span class="muted">${d.unterorte_gesamt} Orte darin</span>` : ""}${p.visibility === "backstage" ? '<span class="chip backstage">backstage</span>' : ""}</div></div>
      <div class="row"><button class="ghost" data-edit="locations:${p.id}">Bearbeiten</button>
        <button class="primary" data-add="locations" data-def="${def({ parent_id: p.id })}">+ Ort darin</button>
        <button class="ghost" data-add="characters" data-def="${def({ location_id: p.id })}">+ Figur</button>
        <button class="ghost" data-add="organizations" data-def="${def({ location_id: p.id })}">+ Firma</button></div></div>
    ${p.description ? `<p class="desc">${esc(p.description)}</p>` : ""}
    <div class="stack" style="margin-top:14px">
    ${sec("Orte darin", d.unterorte, ["Name", "Art", "Ebene"], (r) => [esc(r.name), esc(kindLabel(r.kind)), val(r.level)], (r) => `locations:${r.id}`)}
    ${sec("Völker", d.voelker, ["Name", "Status", "Heimat"], (r) => [esc(r.name), val(r.status), val(r.home_location_id__name)], (r) => `peoples:${r.id}`)}
    ${sec("Figuren", d.figuren, ["Name", "Rolle", "Volk", "Lebt in"], (r) => [esc(r.name), val(r.role), val(r.people_id__name), val(r.location_id__name)], (r) => `characters:${r.id}`)}
    ${sec("Firmen & Organisationen", d.organisationen, ["Name", "Art", "Sitz"], (r) => [esc(r.name), val(r.kind), val(r.location_id__name)], (r) => `organizations:${r.id}`)}
    ${sec("Jobs", d.jobs, ["Figur", "Tätigkeit", "Bei", "Ort"], (r) => [val(r.character_id__name), esc(r.title), val(r.organization_id__name), val(r.location_id__name)], (r) => `jobs:${r.id}`)}
    ${sec("Stränge", d.straenge, ["Titel", "Ebene", "Status", "POV"], (r) => [esc(r.title), val(r.level), val(r.status), val(r.pov_id__name)], (r) => `threads:${r.id}`)}
    ${sec("Ereignisse", d.ereignisse, ["Weltzeit", "Titel", "Ort"], (r) => [val(r.world_time), esc(r.title), val(r.location_id__name)], (r) => `events:${r.id}`)}
    ${sec("Technik & Phänomene", d.technik, ["Name", "Art", "Ort"], (r) => [esc(r.name), val(r.kind), val(r.location_id__name)], (r) => `technologies:${r.id}`)}
    ${sec("Einschübe", d.einschuebe, ["Titel", "Art", "Ort"], (r) => [esc(r.title), val(r.kind), val(r.location_id__name)], (r) => `snippets:${r.id}`)}
    ${empty.length ? `<div class="muted small">Hier noch nichts: ${empty.map(esc).join(", ")}</div>` : ""}</div>`;
  bindDossier(main);
}

async function personView(main, id) {
  const d = await api(W(`/dossier/characters/${id}`));
  const f = d.figur, def = (o) => esc(JSON.stringify(o));
  const rel = (list, title, emptyText) => sec(title, list, ["", "Name", "Grund", "Seit", "Bruch", ""],
    (r) => [esc(REL_LABEL[r.art] || r.art), esc(r.name), `<span class="small">${val(r.grund)}</span>`, val(r.seit),
      r.bruch != null ? `<span class="chip st-fehler">gebrochen ${esc(r.bruch)}</span>${r.bruch_grund ? `<div class="small muted">${esc(r.bruch_grund)}</div>` : ""}` : "",
      `<button class="ghost small" data-edit="character_relations:${r.beziehung_id}">✎</button>`],
    (r) => `characters:${r.figur_id}`, "", emptyText);
  const told = [...d.straenge_pov.map((t) => ({ ...t, _wie: "Erzählperspektive" })), ...d.erwaehnt.straenge.map((t) => ({ ...t, _wie: "erwähnt" }))];
  main.innerHTML = `<div class="crumbs"><a href="#" data-crumb="1">Figuren</a> › <b>${esc(f.name)}</b></div>
    <div class="row spread"><div><h2 style="margin:0">${esc(f.name)}</h2>
      <div class="row small" style="margin-top:4px">${f.gender ? `<span class="chip">${esc(f.gender)}</span>` : ""}${f.role ? `<span class="chip">${esc(f.role)}</span>` : ""}
        ${f.people_id ? `Volk: ${openLink("peoples", f.people_id, f.people_id__name)}` : ""}
        ${f.location_id ? `· lebt in ${openLink("locations", f.location_id, f.location_id__name)}` : ""}</div></div>
      <div class="row"><button class="ghost" id="p-netz" title="Diese Figur im Beziehungsnetz zeigen">◉ Im Netz</button>
        <button class="ghost" data-edit="characters:${f.id}">Bearbeiten</button>
        <button class="primary" data-add="jobs" data-def="${def({ character_id: f.id, location_id: f.location_id || undefined })}">+ Job</button>
        <button class="ghost" data-add="character_relations" data-def="${def({ character_id: f.id })}">+ Familie / Beziehung</button></div></div>
    ${f.description ? `<p class="desc">${esc(f.description)}</p>` : ""}
    <div class="stack" style="margin-top:14px">
    ${sec("Jobs & Laufbahn", d.jobs, ["Von", "Bis", "Tätigkeit", "Bei", "Ort", "Aufgaben & Entwicklung"],
      (r) => [val(r.from_world_time), r.to_world_time == null ? '<span class="chip st-fertig">aktuell</span>' : val(r.to_world_time), `<b>${esc(r.title)}</b>`,
        val(r.organization_id__name), val(r.location_id__name), `<span class="small">${val(r.description)}</span>`],
      (r) => `jobs:${r.id}`, "", "Noch keine Jobs – über „+ Job“ die Laufbahn anlegen, um die Figur zu entwickeln.")}
    ${rel(d.familie, "Familie", "Noch keine Familie eingetragen.")}
    ${rel(d.beziehungen, "Weitere Beziehungen", "")}
    ${sec("Firmen & Organisationen", d.organisationen, ["Name", "Art", "Sitz"], (r) => [esc(r.name), val(r.kind), val(r.location_id__name)], (r) => `organizations:${r.id}`)}
    ${sec("Geschichten (Stränge)", told, ["Titel", "Rolle", "Ebene", "Status", "Ort"], (r) => [esc(r.title), esc(r._wie), val(r.level), val(r.status), val(r.location_id__name)], (r) => `threads:${r.id}`, "", "In noch keinem Strang.")}
    ${sec("Erwähnt in Ereignissen", d.erwaehnt.ereignisse, ["Weltzeit", "Titel", "Ort"], (r) => [val(r.world_time), esc(r.title), val(r.location_id__name)], (r) => `events:${r.id}`)}
    ${sec("Erwähnt in Einschüben", d.erwaehnt.einschuebe, ["Titel", "Art"], (r) => [esc(r.title), val(r.kind)], (r) => `snippets:${r.id}`)}
    ${sec("Wissen", d.wissen, ["Seit", "Inhalt", "Quelle", "Status"], (r) => [val(r.since_world_time), esc(r.content), val(r.source), val(r.status)], (r) => `knowledge:${r.id}`)}
    </div>`;
  bindDossier(main);
  $("#p-netz").onclick = () => { S.entity = "characters"; S.person = null; S.netzFokus = f.id; netzSetzen(true); render(); };
}

const short = (v, n = 90) => { const t = String(v ?? ""); return esc(t.length > n ? t.slice(0, n - 1) + "…" : t); };
const personName = (r) => [r.first_name, r.last_name].filter((x) => x && String(x).trim()).join(" ") || r.name || "";
const OPT_LABEL = { "character_relations.kind": REL_LABEL };

function listCell(table, f, r) {
  const v = r[f.name];
  if (table === "characters" && f.name === "first_name" && !r.first_name && !r.last_name) return `<span class="muted">${esc(r.name)}</span>`;
  if (f.type.startsWith("ref:")) return val(r[f.name + "__name"]);
  if (table === "character_relations" && f.name === "ended_world_time" && v != null) return `<span class="chip st-fehler">gebrochen ${esc(v)}</span>`;
  if (f.type.startsWith("select:")) return esc((OPT_LABEL[`${table}.${f.name}`] || {})[v] || v || "");
  if (f.type === "bool") return v ? "ja" : "";
  return short(v);
}

VIEWS.welt = async (el) => {
  const o = await api(W("/overview"));
  if (!S.cfg.entities[S.entity]) S.entity = "peoples";
  const cfg = S.cfg.entities[S.entity];
  const data = await api(W(`/rows/${S.entity}`));
  const detail = (S.entity === "locations" && S.place) || (S.entity === "characters" && S.person);
  const side = Object.entries(S.cfg.entities).map(([k, v]) =>
    `<button data-e="${k}" class="${k === S.entity && !detail ? "active" : ""}"><span>${esc(v.label)}</span><span>${o.bestand[k] ? o.bestand[k].offen : ""}</span></button>`
    + (k === "locations" && S.entity === "locations" ? placeTree(data.rows) : "")).join("");
  const cols = (cfg.list || []).map(([n, h]) => [cfg.fields.find((f) => f.name === n), h]).filter(([f]) => f);
  const rows = data.rows.map((r) => `<tr class="click" data-id="${r.id}">${cols.length ? cols.map(([f]) => `<td>${listCell(S.entity, f, r)}</td>`).join("")
      : `<td>${esc(r.__title)}</td>`}<td>${who(r.created_by)}
      ${r.visibility === "backstage" ? '<span class="chip backstage">backstage</span>' : ""}</td>
      <td>${r.__missing.length ? `<span class="chip gap">${r.__missing.length} Lücke(n)</span>` : '<span class="chip st-fertig">vollständig</span>'}</td></tr>`).join("");
  el.innerHTML = `<div class="split"><div><input id="w-search" placeholder="Suchen in allen Bereichen …" style="margin-bottom:10px">
    <div class="side">${side}</div></div><div class="card" id="w-main"></div></div>`;
  const main = $("#w-main");
  el.querySelectorAll("[data-e]").forEach((b) => (b.onclick = () => { S.entity = b.dataset.e; S.place = S.person = null; render(); }));
  el.querySelectorAll("[data-tog]").forEach((t) => (t.onclick = () => {
    const id = Number(t.dataset.tog); if (S.open.has(id)) S.open.delete(id); else S.open.add(id); render();
  }));
  el.querySelectorAll("[data-place]").forEach((t) => (t.onclick = () => { S.place = Number(t.dataset.place); S.person = null; S.open.add(S.place); render(); }));
  if (S.entity === "locations" && S.place) {
    try { await placeView(main, S.place); } catch (e) { S.place = null; throw e; }
  } else if (S.entity === "characters" && S.person) {
    try { await personView(main, S.person); } catch (e) { S.person = null; throw e; }
  } else if (NETZ_BEREICHE.has(S.entity) && netzAn()) {
    await netzView(main);
  } else {
    main.innerHTML = `<div class="row spread"><h2>${esc(cfg.label)}</h2><div class="row">
      ${NETZ_BEREICHE.has(S.entity) ? '<button class="ghost" id="w-netz" title="Verbindungen als Netz zeigen">◉ Netz</button>' : ""}
      ${S.entity === "snippets" ? '<button class="ki" id="w-snip">KI: Sammelsurium auffüllen</button>' : '<button class="ki" id="w-fill">KI: Lücken füllen</button>'}<button class="primary" id="w-new">+ ${esc(cfg.singular)}</button></div></div>
      ${S.entity === "locations" ? '<div class="small muted">Links im Baum einen Ort wählen, um alles zu sehen, was dazugehört.</div>' : ""}
      ${data.hidden ? `<div class="small locked">+ ${data.hidden} Einträge im Backstage verborgen</div>` : ""}
      ${data.rows.length ? `<table class="liste"><tr>${cols.length ? cols.map(([, h]) => `<th>${esc(h)}</th>`).join("") : "<th>Name</th>"}<th>Herkunft</th><th>Steckbrief</th></tr>${rows}</table>` : '<div class="empty">Noch keine Einträge.</div>'}`;
    main.querySelectorAll("tr[data-id]").forEach((tr) => (tr.onclick = () => {
      const id = Number(tr.dataset.id);
      if (S.entity === "locations" || S.entity === "characters") openItem(S.entity, id); else editDialog(S.entity, id);
    }));
    $("#w-new").onclick = () => editDialog(S.entity, null);
    if ($("#w-netz")) $("#w-netz").onclick = () => { netzSetzen(true); render(); };
    if ($("#w-fill")) $("#w-fill").onclick = () => fillGaps(S.entity, null);
    if ($("#w-snip")) $("#w-snip").onclick = snippetDialog;
  }
  let timer = null;
  $("#w-search").oninput = (e) => { clearTimeout(timer); timer = setTimeout(() => guard(() => runSearch(e.target.value)), 250); };
};

async function runSearch(q) {
  if (q.trim().length < 2) return render();
  const { treffer } = await api(W(`/search?q=${encodeURIComponent(q)}`));
  $("#w-main").innerHTML = `<h2>Suche: „${esc(q)}“</h2>${treffer.length ? `<table><tr><th>Bereich</th><th>Name</th><th>Fundstelle</th></tr>
    ${treffer.map((t) => `<tr class="click" data-hit="${t.table}:${t.id}"><td>${esc(t.table_label)}</td><td>${esc(t.title)}</td><td class="small muted">${esc(t.snippet)}</td></tr>`).join("")}</table>`
    : '<div class="empty">Keine Treffer.</div>'}`;
  document.querySelectorAll("[data-hit]").forEach((tr) => (tr.onclick = () => { const [t, i] = tr.dataset.hit.split(":"); openItem(t, Number(i)); }));
}

function snippetDialog() {
  modal(`<h2>Sammelsurium auffüllen</h2><p class="muted">Kleine Extras, die eingestreut werden, wenn in einem Zeitraum zu wenig passiert.
    Keine festen Regeln – gib der KI höchstens eine Richtung.</p>
    <div class="form"><div class="field"><label>Anzahl</label><input id="sn-n" type="number" min="1" max="15" value="6"></div>
    <div class="field"><label>Richtung (optional)</label><textarea id="sn-h" placeholder="z. B. mehr Socializing auf der Station, etwas Alltag der Raumfahrer-Aureas"></textarea></div></div>
    <div class="row spread"><button class="ghost" data-close="1">Abbrechen</button><button class="ki" id="sn-go">KI anwerfen</button></div>`);
  $("#sn-go").onclick = () => guard(async () => {
    await api(W("/einschuebe/ki"), { method: "POST", body: { anzahl: Number($("#sn-n").value), hinweis: $("#sn-h").value } });
    closeModal(); toast("KI sammelt Einschübe …"); pollJobs();
  });
}

async function refOptions(table, current) {
  const { rows } = await api(W(`/rows/${table}`));
  const label = (r) => (table === "characters" ? `${personName(r)}${r.role ? ` (${r.role})` : ""}` : r.__title);
  return `<option value="">—</option>` + rows.map((r) => [r, label(r)]).sort((a, b) => a[1].localeCompare(b[1], "de"))
    .map(([r, l]) => `<option value="${r.id}" ${r.id === current ? "selected" : ""}>${esc(l)}</option>`).join("");
}

async function editDialog(table, id, defaults = {}) {
  const cfg = S.cfg.entities[table];
  const row = id ? await api(W(`/rows/${table}/${id}`)) : { ...defaults };
  const missing = new Set(row.__missing || []);
  const parts = [];
  for (const f of cfg.fields) {
    if (f.secret && !S.reveal) {
      parts.push(`<div class="field secret"><label>${esc(f.label)}</label><div class="locked small">${row[f.name + "__hidden"] ? "🔒 gesetzt – nur im Backstage-Modus sichtbar" : "🔒 nur im Backstage-Modus bearbeitbar"}</div></div>`);
      continue;
    }
    const v = row[f.name];
    let input;
    if (f.type === "textarea") input = `<textarea name="${f.name}">${esc(v)}</textarea>`;
    else if (f.type === "bool") input = `<select name="${f.name}"><option value="0">nein</option><option value="1" ${v ? "selected" : ""}>ja</option></select>`;
    else if (f.type.startsWith("select:")) {
      const lab = OPT_LABEL[`${table}.${f.name}`] || {};
      input = `<select name="${f.name}"><option value="">—</option>${f.type.slice(7).split(",").map((o) => `<option value="${esc(o)}" ${o === v ? "selected" : ""}>${esc(lab[o] || o)}</option>`).join("")}</select>`;
    }
    else if (f.type.startsWith("ref:")) input = `<select name="${f.name}">${await refOptions(f.type.slice(4), v)}</select>`;
    else input = `<input name="${f.name}" type="${f.type === "number" ? "number" : "text"}" step="any" value="${esc(v)}">`;
    parts.push(`<div class="field ${f.secret ? "secret" : ""} ${missing.has(f.name) ? "gap" : ""}"><label>${esc(f.label)}${f.required ? " *" : ""}</label>${input}</div>`);
  }
  if (table === "character_relations") parts.unshift('<div class="note rel-satz" id="rel-satz"></div>');
  if (S.reveal) parts.push(`<div class="field"><label>Sichtbarkeit</label><select name="visibility"><option value="offen">offen</option>
    <option value="backstage" ${row.visibility === "backstage" ? "selected" : ""}>backstage</option></select></div>`);
  modal(`<div class="row spread"><h2>${id ? esc(row.__title) : "Neu: " + esc(cfg.singular)}</h2>${id ? who(row.created_by) : ""}</div>
    <form class="form" id="ed">${parts.join("")}</form>
    <div class="row spread"><div class="row">${id ? `<button class="danger" id="ed-del">Löschen</button>` : ""}
      ${id && missing.size ? `<button class="ki" id="ed-fill">KI: Lücken hier füllen</button>` : ""}</div>
      <div class="row"><button class="ghost" data-close="1">Abbrechen</button><button class="primary" id="ed-save">Speichern</button></div></div>`);
  if (table === "character_relations") {
    const form = $("#ed");
    const pick = (n) => { const x = form.elements[n]; return x && x.value ? x.options[x.selectedIndex].text : "…"; };
    const satz = () => {
      const bruch = form.elements.ended_world_time && form.elements.ended_world_time.value;
      $("#rel-satz").innerHTML = `<b>${esc(pick("character_id"))}</b> ist <b>${esc(pick("kind"))}</b> von <b>${esc(pick("other_id"))}</b>`
        + (bruch ? ` <span class="chip st-fehler">gebrochen seit ${esc(bruch)}</span>` : "");
    };
    ["character_id", "kind", "other_id", "ended_world_time"].forEach((n) => form.elements[n] && form.elements[n].addEventListener("input", satz));
    satz();
  }
  $("#ed-save").onclick = () => guard(async () => {
    const body = Object.fromEntries(new FormData($("#ed")).entries());
    if (id) await api(W(`/rows/${table}/${id}`), { method: "PUT", body });
    else await api(W(`/rows/${table}`), { method: "POST", body });
    closeModal(); toast("Gespeichert.", "ok"); render();
  });
  if ($("#ed-del")) $("#ed-del").onclick = () => confirm("Wirklich löschen?") && guard(async () => {
    await api(W(`/rows/${table}/${id}`), { method: "DELETE" }); closeModal(); toast("Gelöscht."); render();
  });
  if ($("#ed-fill")) $("#ed-fill").onclick = () => { closeModal(); fillGaps(table, id); };
}

async function fillGaps(table, id) {
  await guard(async () => {
    await api(W("/gaps/ki"), { method: "POST", body: { table, id } });
    toast("KI füllt Lücken – der Vorschlag erscheint unter „Vorschläge“."); pollJobs();
  });
}

// ------------------------------------------------------------ Lücken

VIEWS.luecken = async (el) => {
  const g = await api(W("/gaps"));
  const groups = {};
  g.items.forEach((i) => (groups[i.table_label] = groups[i.table_label] || []).push(i));
  const cons = await consistencyCard();
  el.innerHTML = `<h2>Prüfung</h2>${cons}<div class="row spread"><h3 style="margin:0">Lücken</h3><button class="ki" id="g-all" ${g.items.length ? "" : "disabled"}>KI: alle Lücken füllen</button></div>
    <p class="muted">Fehlende Steckbrief-Angaben laut WELT_REGELN.md. ${g.hidden ? `<span class="locked">+ ${g.hidden} Lücken im Backstage (die KI kennt sie).</span>` : ""}</p>
    ${Object.keys(groups).length ? Object.entries(groups).map(([label, items]) => `<div class="card" style="margin-bottom:12px"><h3>${esc(label)}</h3>
      <table>${items.map((i) => `<tr><td style="width:30%"><a href="#" data-edit="${i.table}:${i.id}">${esc(i.title)}</a> ${who(i.created_by)}</td>
        <td>${i.missing.map((m) => `<span class="chip gap">${esc(m)}</span>`).join(" ")}</td>
        <td style="width:120px"><button class="ki" data-fill="${i.table}:${i.id}">KI füllen</button></td></tr>`).join("")}</table></div>`).join("")
      : '<div class="card empty">Keine sichtbaren Lücken. 🎉</div>'}`;
  if (g.items.length) $("#g-all").onclick = () => fillGaps(null, null);
  el.querySelectorAll("[data-fill]").forEach((b) => (b.onclick = () => { const [t, i] = b.dataset.fill.split(":"); fillGaps(t, Number(i)); }));
  el.querySelectorAll("[data-edit]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); const [t, i] = a.dataset.edit.split(":"); editDialog(t, Number(i)); }));
};

// ------------------------------------------------------------ Protokoll

VIEWS.protokoll = async (el) => {
  const { eintraege } = await api(W("/audit"));
  const label = (t) => (S.cfg.entities[t] ? S.cfg.entities[t].singular : t || "");
  el.innerHTML = `<h2>Änderungsprotokoll</h2><div class="card">${eintraege.length ? `<table><tr><th>Zeit (UTC)</th><th>Wer</th><th>Aktion</th><th>Bereich</th><th>Details</th></tr>
    ${eintraege.map((a) => `<tr><td class="small">${esc(a.ts)}</td><td>${who(a.actor)}</td><td>${esc(a.action)}</td>
      <td>${esc(label(a.table_name))}${a.row_id ? ` #${a.row_id}` : ""}</td><td class="small">${esc(a.detail || "")}</td></tr>`).join("")}</table>`
    : '<div class="empty">Noch keine Einträge.</div>'}</div>`;
};

// ------------------------------------------------------------ Projektstatus

VIEWS.projekt = async (el) => {
  const st = await api("/api/status");
  el.innerHTML = `<h2>Projektstatus</h2>
  <p class="muted">Live aus den Checklisten in PLAN.md. Ein Häkchen dort heißt: im Dokument abgehakt.</p>
  ${st.fehlende_dateien.length ? `<div class="card" style="border-color:var(--warn);margin-bottom:12px">⚠ Fehlende Dateien: ${st.fehlende_dateien.map(esc).join(", ")}</div>` : ""}
  <div class="stack">${st.quellen.map((q) => {
    const ok = q.gesamt ? (q.erledigt / q.gesamt) * 100 : 0, part = q.gesamt ? (q.teilweise / q.gesamt) * 100 : 0;
    return `<div class="card"><div class="row spread"><h3>${esc(q.quelle)} <span class="muted small">${esc(q.datei)}</span></h3>
      <span>${q.erledigt} / ${q.gesamt} erledigt${q.teilweise ? `, ${q.teilweise} teilweise` : ""}</span></div>
      <div class="progress"><span class="p-ok" style="width:${ok}%"></span><span class="p-part" style="width:${part}%"></span></div>
      ${q.abschnitte.map((s) => { const d = s.items.filter((i) => i.status === "erledigt").length;
        return `<details><summary>${esc(s.titel)} <span class="muted small">${d}/${s.items.length}</span></summary>
        <ul class="items">${s.items.map((i) => `<li class="${i.status}">${esc(i.text)}</li>`).join("")}</ul></details>`; }).join("")}</div>`;
  }).join("")}</div>`;
};

// ------------------------------------------------------------ Themes

const THEME_VARS = [["bg", "Hintergrund"], ["panel", "Karten"], ["panel2", "Flächen"], ["head", "Kopfleiste"],
  ["head-text", "Text Kopfleiste"], ["line", "Linien"], ["input", "Eingabefelder"], ["text", "Text"],
  ["muted", "Text gedämpft"], ["accent", "Akzent"], ["accent-soft", "Akzent hell"], ["accent-text", "Akzent-Text"],
  ["on-accent", "Text auf Akzent"], ["ok", "Erfolg"], ["warn", "Warnung"], ["bad", "Fehler"], ["ki", "KI-Farbe"]];
const THEMES = {
  hell: { name: "Hell", vars: { bg: "#f1efea", panel: "#fbfaf7", panel2: "#ebe8e1", head: "#cfccc6", "head-text": "#2a2826",
    line: "#dcd8cf", input: "#ffffff", text: "#2a2826", muted: "#7c776e", accent: "#d4820a", "accent-soft": "#f7d6a8",
    "accent-text": "#8a4f00", "on-accent": "#ffffff", ok: "#5b8a3a", warn: "#b8730a", bad: "#b8402f", ki: "#2f7472" } },
  dunkel: { name: "Dunkel", vars: { bg: "#17181a", panel: "#212326", panel2: "#2a2d31", head: "#1c1d20", "head-text": "#ebe7e0",
    line: "#363a40", input: "#1a1b1e", text: "#ebe7e0", muted: "#9a958c", accent: "#e8973a", "accent-soft": "#4a3518",
    "accent-text": "#f2b36a", "on-accent": "#1a1205", ok: "#8fbf6a", warn: "#e0a64a", bad: "#e0705c", ki: "#5fb8b4" } },
  bunt: { name: "Bunt", vars: { bg: "#fff6ec", panel: "#ffffff", panel2: "#ffe9d6", head: "#1f6f78", "head-text": "#ffffff",
    line: "#f3cfb0", input: "#ffffff", text: "#23313a", muted: "#6b7a83", accent: "#ff6b4a", "accent-soft": "#ffd3c4",
    "accent-text": "#b83a1e", "on-accent": "#ffffff", ok: "#2e9e5b", warn: "#e39a12", bad: "#d6334f", ki: "#1f6f78" } },
};
function themeVars(theme) {
  if (!theme || theme.active === "eigen") return { ...THEMES.hell.vars, ...((theme && theme.eigen) || {}) };
  return (THEMES[theme.active] || THEMES.hell).vars;
}
function setVars(el, vars) { Object.entries(vars).forEach(([k, v]) => el.style.setProperty(`--${k}`, v)); }
function luminance(hex) {
  const n = parseInt((hex || "#ffffff").slice(1), 16);
  return (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
}
function applyTheme(theme) {
  const vars = themeVars(theme);
  setVars(document.documentElement, vars);
  document.documentElement.style.colorScheme = luminance(vars.bg) < 0.5 ? "dark" : "light";
}

// ------------------------------------------------------------ Einstellungen

const SUBS = [["anbieter", "KI-Anbieter"], ["aufgaben", "Modelle je Aufgabe"], ["qualitaet", "↳ Qualität der Modelle"], ["menschen", "Menschen & Profile"], ["darstellung", "Darstellung"],
  ["tts", "TTS-Server"], ["welt", "Diese Welt"], ["schnittstellen", "Schnittstellen"], ["sicherung", "Sicherung"], ["update", "Update"]];
const STATUS_TXT = { ok: "verbunden", fehler: "Fehler", ungeprueft: "nicht geprüft" };
const statusChip = (s) => `<span class="chip st-${s === "ok" ? "fertig" : s === "fehler" ? "fehler" : "offen"}">${STATUS_TXT[s] || esc(s)}</span>`;
const SUB = {};
SUB.menschen = subMenschen;

function openSettings(sub) { S.sub = sub; go("einstellungen"); }

VIEWS.einstellungen = async (el) => {
  S.settings = await api("/api/settings");
  S.sub = S.sub || "anbieter";
  const active = S.sub.startsWith("anbieter") ? "anbieter" : S.sub;
  el.innerHTML = `<div class="settings"><div class="side">${SUBS.map(([id, label]) =>
    `<button data-sub="${id}" class="${id === active ? "active" : ""}"><span>${label}</span></button>`).join("")}</div>
    <div id="set-main" class="stack"></div></div>`;
  el.querySelectorAll("[data-sub]").forEach((b) => (b.onclick = () => { S.sub = b.dataset.sub; render(); }));
  await SUB[S.sub]($("#set-main"));
};

SUB.anbieter = async (el) => {
  const st = S.settings;
  const cards = st.providers.map((p) => `<div class="card stack">
    <div class="row spread"><div><b>${esc(p.name)}</b> <span class="muted small">${esc(p.preset_name)}</span></div>${statusChip(p.status)}</div>
    ${p.chatgpt ? chatgptStatusHtml(p) : `<div class="small muted">${esc(p.base_url)}</div>
    <div class="small">Schlüssel: ${p.api_key_gesetzt ? esc(p.api_key_maskiert) : '<span class="muted">keiner</span>'} · ${p.models_count} Modelle</div>`}
    ${p.last_error ? `<div class="err small">${esc(p.last_error)}</div>` : ""}
    ${p.readonly ? '<div class="small muted">Aus Umgebungsvariablen – hier nicht änderbar.</div>' : ""}
    <div class="row">${p.readonly ? "" : `<button class="ghost" data-edit="${p.id}">Bearbeiten</button>`}
      ${p.chatgpt && !p.chatgpt.plan ? `<button class="chatgpt-btn" data-cglogin="${p.id}">Continue with ChatGPT</button>` : ""}
      <button class="ki" data-verify="${p.id}">Prüfen</button><button class="ghost" data-models="${p.id}">Modelle laden</button></div></div>`).join("");
  el.innerHTML = `<div class="row spread"><h2>KI-Anbieter</h2><button class="primary" id="p-add">+ Anbieter hinzufügen</button></div>
    ${st.providers.length ? "" : `<div class="guide"><b>In drei Schritten zur KI</b><ol>
      <li>Anbieter hinzufügen – z. B. OpenRouter (ein Schlüssel für viele Modelle) oder Ollama (lokal und kostenlos).</li>
      <li>Schlüssel eintragen und prüfen lassen, dann „Modelle laden“.</li>
      <li>Unter „Modelle je Aufgabe“ festlegen, welches Modell was macht – mit 2. und 3. Wahl als Ausweich.</li></ol></div>`}
    <div class="provider-grid">${cards}</div>
    ${st.archiv.length ? `<details><summary class="muted">Archiv (${st.archiv.length}) – entfernte Anbieter, wiederherstellbar</summary>
      ${st.archiv.map((p) => `<div class="row spread card" style="margin-top:8px"><span>${esc(p.name)} <span class="muted small">archiviert ${esc(p.archiviert_am || "")}</span></span>
        <button class="ghost" data-restore="${p.id}">Wiederherstellen</button></div>`).join("")}</details>` : ""}
    <p class="muted small">Schlüssel werden nur lokal in <code>${esc(st.config_datei)}</code> gespeichert (nur für dein Benutzerkonto lesbar) und nie vollständig angezeigt.</p>`;
  $("#p-add").onclick = () => { S.sub = "anbieter-neu"; render(); };
  el.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => { S.editId = b.dataset.edit; S.sub = "anbieter-edit"; render(); }));
  el.querySelectorAll("[data-verify]").forEach((b) => (b.onclick = () => verifyProvider(b.dataset.verify, b)));
  el.querySelectorAll("[data-models]").forEach((b) => (b.onclick = () => loadModels(b.dataset.models, b)));
  el.querySelectorAll("[data-cglogin]").forEach((b) => (b.onclick = () => chatgptLogin(b.dataset.cglogin, b)));
  chatgptNotice();
  el.querySelectorAll("[data-restore]").forEach((b) => (b.onclick = () => guard(async () => {
    await api(`/api/settings/providers/${b.dataset.restore}/wiederherstellen`, { method: "POST", body: {} }); render();
  })));
};

// ------------------------------------------------------------ Qualität der Modelle

const AMPEL_TXT = { gruen: "im Rahmen", gelb: "auffällig", rot: "schlechter als früher" };
const Q_TXT = { ok: "ok", warnung: "Warnung", drift: "Drift", info: "Info" };
const spark = (vals) => {
  if (!vals || vals.length < 2) return "";
  const max = Math.max(...vals), min = Math.min(...vals), span = max - min || 1;
  return `<span class="spark" title="Verlauf der letzten Messungen">${vals.map((v) => `<span style="height:${3 + 15 * (v - min) / span}px"></span>`).join("")}</span>`;
};

function modelPicker(prefix, entry) {
  const usable = (S.settings.providers || []).filter((p) => (p.models || []).length);
  return `<div class="slot" data-pick="${prefix}"><select class="s-prov"><option value="">— Anbieter —</option>${usable.map((p) =>
    `<option value="${p.id}" ${entry && entry.provider === p.id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
    <input class="s-model" placeholder="Modell" value="${esc(entry ? entry.model : "")}" ${entry ? `list="dl-${entry.provider}"` : ""}></div>`;
}
function modelLists() {
  return (S.settings.providers || []).filter((p) => (p.models || []).length).map((p) =>
    `<datalist id="dl-${p.id}">${p.models.map((m) => `<option value="${esc(m)}">`).join("")}</datalist>`).join("");
}
function bindPickers(root) {
  root.querySelectorAll(".slot[data-pick]").forEach((sl) => {
    $(".s-prov", sl).onchange = (e) => { const m = $(".s-model", sl); m.setAttribute("list", `dl-${e.target.value}`); m.value = ""; m.focus(); };
  });
}
const readPicks = (root, prefix) => [...root.querySelectorAll(`.slot[data-pick^="${prefix}"]`)].map((sl) => ({
  provider: $(".s-prov", sl).value, model: $(".s-model", sl).value.trim() })).filter((e) => e.provider && e.model);

SUB.qualitaet = async (el) => {
  S.settings = await api("/api/settings");
  const q = await api("/api/qualitaet");
  S.qtests = Object.fromEntries(q.tests.map((t) => [t.id, t.label]));
  const running = q.serien.filter((x) => x.status === "laeuft");
  const tasksOf = (m) => m.aufgaben.map((a) => (S.settings.tasks.find((t) => t.id === a) || { label: a }).label).join(", ");
  const card = (m) => `<div class="card stack"><div class="row spread"><div><span class="ampel ${m.ampel}"></span><b>${esc(m.modell)}</b>
      <span class="small muted">${esc(tasksOf(m))}</span></div><span class="small muted">${AMPEL_TXT[m.ampel]} · ${m.messungen} Messungen</span></div>
    <div class="small">${esc(m.satz)}</div>
    <div class="expert"><table class="qtable"><tr><th>Nr</th><th>Test</th><th>zuletzt</th><th>Mittel</th><th>Referenz</th><th>Verlauf</th><th>Status</th><th>n</th></tr>
      ${m.tests.map((t) => `<tr title="${esc((q.tests.find((x) => x.id === t.test) || {}).kurz || "")}"><td class="small muted">${esc(t.nr)}</td>
        <td>${esc(t.label)} <span class="small muted">${esc(t.art)}</span></td><td>${esc(t.letzter_text)}</td><td><b>${esc(t.mittel_text)}</b></td>
        <td>${esc(t.referenz_text)}</td><td>${spark(t.verlauf)}</td><td><span class="chip q-${t.status}">${Q_TXT[t.status]}</span></td>
        <td class="small muted">${t.anzahl}</td></tr>`).join("")}</table>
      <div class="row" style="margin-top:6px"><button class="ghost" data-ref="${esc(m.modell)}">Heutigen Stand als Referenz setzen</button>
        <span class="small muted">Maus über eine Zeile zeigt, was der Test misst.</span></div></div></div>`;
  el.innerHTML = `${modelLists()}<h2>Qualität der Modelle</h2>
    <p class="muted">Jede Folge misst nebenbei (kostenlos, per Code), wie die Modelle arbeiten. Der <b>Prüfstand</b> prüft zusätzlich mit
      einer festen Prüfwelt, deren richtige Antworten bekannt sind. Weicht ein Modell von seinem früheren Stand ab, wird es gelb oder rot.</p>
    ${q.hinweise.map((h) => `<div class="banner"><span>${esc(h.text)}</span><div class="row"><button class="primary" data-bench="schnell">Prüfstand starten</button>
      <button class="ghost" data-done="${esc(h.art)}">später</button></div></div>`).join("")}
    <div class="card stack"><div class="row spread"><h3 style="margin:0">Prüfstand</h3>
      <div class="row"><button class="ki" data-bench="schnell" ${running.length ? "disabled" : ""}>Schnell prüfen</button>
        <button class="ghost expert" data-bench="voll" ${running.length ? "disabled" : ""}>Voll prüfen</button></div></div>
      <div class="small muted">Schnell: Fallen für den Prüfer, Fehlalarme, Archivar (3 KI-Aufrufe je Modell). Voll: zusätzlich Planer, Autor,
        Qualitäts-Richter und Bewerter (≈ 8 Aufrufe je Modell). Ohne Auswahl wird die 1. Wahl jeder Aufgabe geprüft.</div>
      ${running.length ? `<div class="note small">⏳ ${esc(running[0].titel)} läuft: ${esc((running[0].ergebnis || {}).schritt || "")}</div>` : ""}
      <details class="expert"><summary>Einstellungen für den Prüfstand und Modelle gegeneinander</summary><div class="form stack" style="margin-top:10px">
        <div class="row"><div class="field"><label>Ballast (echte Welt als Kontext)</label><select id="b-ballast"><option value="">ohne – kleine Prüfwelt</option>
          ${q.welten.map((w) => `<option value="${esc(w.slug)}">${esc(w.name || w.slug)}</option>`).join("")}</select></div>
          <div class="field"><label>Kontext</label><select id="b-kontext"><option value="voll">voll (ganzer Kanon)</option><option value="kaskade">Kaskade</option></select></div></div>
        <p class="small muted">Mit Ballast und einmal „voll“, einmal „Kaskade“ siehst du direkt, ob die Kaskade die Trefferquote verbessert (K4).</p>
        ${Object.entries(q.pruefstand_aufgaben).map(([task, label]) => `<div class="field"><label>${esc(label)} – bis zu 3 Modelle gegeneinander</label>
          <div>${[0, 1, 2].map((i) => modelPicker(`${task}-${i}`)).join("")}</div></div>`).join("")}
        <div class="field"><label>Qualitäts-Richter (bewertet die Autor-Texte)</label>${modelPicker("richter-0")}</div>
        <h3 style="margin:8px 0 0">Regelmäßig prüfen</h3>
        <div class="row"><div class="field"><label>alle … Tage (0 = aus)</label><input id="q-int" type="number" min="0" max="90" value="${esc(q.einstellungen.intervall_tage)}" style="max-width:90px"></div>
          <div class="field"><label>Umfang</label><select id="q-umf"><option ${q.einstellungen.umfang === "schnell" ? "selected" : ""}>schnell</option><option ${q.einstellungen.umfang === "voll" ? "selected" : ""}>voll</option></select></div>
          <div class="field"><label>Kontext</label><select id="q-kon"><option ${q.einstellungen.kontext === "voll" ? "selected" : ""}>voll</option><option ${q.einstellungen.kontext === "kaskade" ? "selected" : ""}>kaskade</option></select></div>
          <div class="field"><label>Ballast</label><select id="q-bal"><option value="">ohne</option>${q.welten.map((w) => `<option value="${esc(w.slug)}" ${w.slug === q.einstellungen.ballast ? "selected" : ""}>${esc(w.name || w.slug)}</option>`).join("")}</select></div>
          <button class="ghost" id="q-save">Speichern</button></div>
        <p class="small muted">Läuft, solange Story World geöffnet ist${q.einstellungen.letzter ? ` · zuletzt ${esc(q.einstellungen.letzter)}` : ""}. Kostet je Lauf die oben genannten Aufrufe.</p>
      </div></details></div>
    ${q.modelle.length ? q.modelle.map(card).join("") : `<div class="card empty">Noch keine Messwerte. Sie entstehen mit jeder Folge – oder sofort mit „Schnell prüfen“.</div>`}
    <details class="card expert"><summary>Letzte Prüfstand-Läufe und Vergleiche (${q.serien.length})</summary>
      <table class="qtable">${q.serien.map((x) => `<tr class="click" data-serie="${esc(x.id)}"><td class="small">${esc(x.zeit)}</td><td>${esc(x.art)}</td>
        <td>${esc(x.titel || "")}</td><td>${chip(x.status)}</td></tr>`).join("")}</table></details>
    <details class="card expert"><summary>Was die Tests messen</summary><table class="qtable">${q.tests.map((t) =>
      `<tr><td class="small muted">${esc(t.nr)}</td><td><b>${esc(t.label)}</b> <span class="small muted">${esc(t.art)}</span></td><td class="small">${esc(t.kurz)}</td></tr>`).join("")}</table>
      <p class="small muted">Messwerte liegen app-weit in <code>${esc(q.datei)}</code>.</p></details>`;
  bindPickers(el);
  el.querySelectorAll("[data-done]").forEach((b) => (b.onclick = () => guard(async () => {
    await api("/api/qualitaet/hinweise/erledigt", { method: "POST", body: { art: b.dataset.done } }); render(); })));
  el.querySelectorAll("[data-ref]").forEach((b) => (b.onclick = () => guard(async () => {
    const r = await api("/api/qualitaet/referenz", { method: "POST", body: { modell: b.dataset.ref } });
    toast(`${r.gesetzt} Referenzwerte gesetzt.`, "ok"); render(); })));
  el.querySelectorAll("[data-serie]").forEach((tr) => (tr.onclick = () => showSeries(tr.dataset.serie)));
  el.querySelectorAll("[data-bench]").forEach((b) => (b.onclick = () => guard(async () => {
    const modelle = {};
    if (S.expert) {
      Object.keys(q.pruefstand_aufgaben).concat(["richter"]).forEach((task) => { const p = readPicks(el, `${task}-`); if (p.length) modelle[task] = p; });
    }
    const body = { umfang: b.dataset.bench, modelle, ballast: S.expert && $("#b-ballast") ? $("#b-ballast").value : "",
      kontext: S.expert && $("#b-kontext") ? $("#b-kontext").value : "voll" };
    const r = await api("/api/qualitaet/pruefstand", { method: "POST", body });
    toast("Prüfstand läuft – Ergebnis erscheint hier."); pollJobs(); watchSeries(r.job.serie);
  })));
  if ($("#q-save")) $("#q-save").onclick = () => guard(async () => {
    await api("/api/qualitaet/einstellungen", { method: "PUT", body: { intervall_tage: $("#q-int").value, umfang: $("#q-umf").value,
      kontext: $("#q-kon").value, ballast: $("#q-bal").value } });
    toast("Gespeichert.", "ok");
  });
  if (running.length) scheduleRefresh(() => S.view === "einstellungen" && S.sub === "qualitaet" && render());
};

function watchSeries(sid) {
  const tick = async () => {
    const r = await api(`/api/qualitaet/serien/${sid}`).catch(() => null);
    if (!r) return;
    if (r.status === "laeuft") { setTimeout(tick, 2000); if (S.view === "einstellungen" && S.sub === "qualitaet" && !$("#modal-box").innerHTML) render(); return; }
    showSeries(sid);
  };
  setTimeout(tick, 1500);
}

const fmtVal = (k, v) => (v == null ? "–" : typeof v === "boolean" ? (v ? "✓" : "✗")
  : typeof v === "number" ? (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("de-DE") : String(Math.round(v * 100) / 100).replace(".", ",")) : esc(v));
const CMP_LABEL = { zeichen: "Zeichen", json: "gültiges JSON", operationen: "Operationen", strukturfehler: "Fehler", format: "Format",
  befunde: "Befunde", wichtig: "davon wichtig", woerter: "Wörter", konkretheit: "Konkretheit", fehler: "Fehler",
  stil_abweichung_zum_original: "Stil-Abw. zum Original %", laenge_zum_original: "Länge zum Original" };

async function showSeries(sid) {
  const r = await api(`/api/qualitaet/serien/${sid}`);
  const e = r.ergebnis || {};
  let body;
  if (r.art === "vergleich") {
    const judge = e.richter || {};
    body = `<p class="small muted">Aufruf: ${esc((e.aufruf || {}).schritt || "")} · Aufgabe ${esc((e.aufruf || {}).aufgabe || "")} ·
        Prompt ${fmtVal("", (e.aufruf || {}).prompt_zeichen)} Zeichen${judge.modell ? ` · Richter: ${esc(judge.modell)}` : ""}</p>
      ${judge.fehler ? `<div class="err small">Richter: ${esc(judge.fehler)}</div>` : ""}
      <div class="cmp">${(e.ergebnisse || []).map((x) => {
        const j = (judge.werte || {})[x.modell];
        return `<div class="card stack ${judge.bester === x.modell ? "scen best" : ""}"><b>${esc(x.modell)}</b>
          ${judge.bester === x.modell ? '<span class="chip q-ok">bester laut Richter</span>' : ""}
          <div class="small">${x.fehler ? `<span class="err">${esc(x.fehler)}</span>` : ""}
            ${j ? `Richter: <b>${fmtVal("", j.wert)}</b>/10${j.begruendung ? ` – ${esc(j.begruendung)}` : ""}<br>` : ""}
            ${Object.entries(x.werte || {}).filter(([, v]) => !(Array.isArray(v) && !v.length)).map(([k, v]) =>
              `${esc(CMP_LABEL[k] || k)}: ${Array.isArray(v) ? esc(v.join("; ")) : fmtVal(k, v)}`).join(" · ")}
            ${x.sekunden != null ? ` · ${fmtVal("", x.sekunden)} s` : ""}</div>
          ${x.text != null ? `<pre class="live">${esc(x.text)}</pre>` : '<div class="small muted">🔒 Antworttext nur mit Backstage.</div>'}</div>`;
      }).join("")}</div>`;
  } else {
    const models = Object.entries(e.modelle || {});
    body = `<p class="small muted">Umfang ${esc(e.umfang || "")} · Kontext ${esc(e.kontext || "")}${e.ballast ? ` · Ballast ${esc(e.ballast)}` : ""}
      ${e.dauer ? ` · ${fmtSec(e.dauer)}` : ""}${r.status === "laeuft" ? ` · läuft: ${esc(e.schritt || "")}` : ""}</p>
      ${r.fehler ? `<div class="err">${esc(r.fehler)}</div>` : ""}
      <div class="cmp">${models.map(([label, m]) => `<div class="card stack"><b>${esc(label)}</b>
        <table class="qtable">${Object.entries(m.werte).map(([k, v]) => `<tr><td>${esc((S.qtests && S.qtests[k]) || k)}</td><td><b>${fmtVal(k, v)}</b></td></tr>`).join("")}</table>
        ${Object.entries(m.details || {}).map(([task, d]) => d.fehler ? `<div class="err small">${esc(task)}: ${esc(d.fehler)}</div>`
          : d.fallen ? `<div class="small">Fallen: ${Object.entries(d.fallen).map(([k, v]) => `${v ? "✔" : "✗"} ${esc(k.replace(/_/g, " "))}`).join(" · ")}</div>`
          : d.pruefungen ? `<div class="small">Bewerter: ${Object.entries(d.pruefungen).map(([k, v]) => `${v ? "✔" : "✗"} ${esc(k)}`).join(" · ")}</div>`
          : d.gefunden ? `<div class="small">Archivar: ${Object.entries(d.gefunden).map(([k, v]) => `${v ? "✔" : "✗"} ${esc(k)}`).join(" · ")}${d.erfunden && d.erfunden.length ? ` · erfunden: ${esc(d.erfunden.join(", "))}` : ""}</div>`
          : d.richter ? `<div class="small">Richter ${esc(d.richter.modell)}: Streuung ${fmtVal("", d.richter.streuung)} – ${esc(d.richter.begruendung || "")}</div>` : "").join("")}
      </div>`).join("") || '<div class="muted">Noch keine Ergebnisse.</div>'}</div>`;
  }
  modal(`<div class="row spread"><h2 style="margin:0">${esc(r.titel || r.art)}</h2>${chip(r.status)}</div>${body}
    <div class="row" style="justify-content:flex-end;margin-top:12px"><button class="ghost" data-close="1">Schließen</button></div>`);
}

async function compareDialog(call) {
  S.settings = S.settings || await api("/api/settings");
  modal(`${modelLists()}<h2>Modelle vergleichen</h2>
    <p class="small muted">Derselbe gespeicherte Aufruf („${esc(call.step || call.task)}“, ${fmtVal("", call.prompt_chars)} Zeichen Prompt) geht an bis zu
      drei Modelle. Die Originalantwort (${esc(call.model || "")}) läuft als Maßstab mit. Kostet je Modell einen Aufruf.</p>
    <div>${[0, 1, 2].map((i) => modelPicker(`cmp-${i}`)).join("")}</div>
    <label class="row small" style="margin:8px 0"><input type="checkbox" id="cmp-judge" checked style="width:auto"> Qualitäts-Richter bewertet die Antworten (1 Aufruf mehr)</label>
    <div class="row" style="justify-content:flex-end"><button class="ghost" data-close="1">Abbrechen</button><button class="ki" id="cmp-go">Vergleichen</button></div>`);
  bindPickers($("#modal-box"));
  $("#cmp-go").onclick = () => guard(async () => {
    const modelle = readPicks($("#modal-box"), "cmp-");
    if (!modelle.length) { toast("Bitte mindestens ein Modell wählen.", "bad"); return; }
    const r = await api(W(`/aufrufe/${call.id}/vergleich`), { method: "POST", body: { modelle, richter: $("#cmp-judge").checked } });
    closeModal(); toast("Vergleich läuft – das Ergebnis öffnet sich hier."); pollJobs(); watchSeries(r.serie);
  });
}

// ------------------------------------------------------------ ChatGPT-Abo (Sign in with ChatGPT)

const CG_USAGE = "https://chatgpt.com/settings/usage";
function chatgptStatusHtml(p) {
  const c = p.chatgpt;
  if (c.anmeldung_laeuft) return `<div class="small">⏳ Anmeldung läuft im Browser – dort bestätigen, dann kommt es hier von selbst an.</div>`;
  if (!c.angemeldet) return `<div class="small muted">Nicht angemeldet${c.registriert && c.email ? ` (zuletzt ${esc(c.email)})` : ""}.</div>`;
  return `<div class="small">Konto: <b>${esc(c.email || "ChatGPT")}</b> · ${p.models_count} Modelle</div>
    ${c.plan ? `<div class="small cg-plan">✓ Using ChatGPT plan · <a href="${CG_USAGE}" target="_blank" rel="noopener">Manage usage</a></div>`
      : `<div class="small err">Die Nutzung deines ChatGPT-Abos ist nicht freigegeben – ohne Freigabe schreibt die KI nicht.</div>`}`;
}

async function chatgptLogin(id, btn, again = false) {
  const p = (S.settings.providers || []).find((x) => x.id === id);
  const repeat = again || (p && p.chatgpt && p.chatgpt.angemeldet && !p.chatgpt.plan);
  const r = await api(`/api/settings/providers/${id}/chatgpt/anmelden`, { method: "POST", body: { abo_erneut: repeat } })
    .catch((e) => ({ fehler: e.message }));
  if (!r.url) return toast(`Anmeldung nicht möglich: ${r.fehler}`, "bad");
  window.open(r.url, "_blank", "noopener");
  if (btn) { btn.disabled = true; btn.textContent = "warte auf Browser …"; }
  toast("Im Browser bei ChatGPT anmelden und die Nutzung deines Abos erlauben.", "ok");
  const until = Date.now() + 15 * 60 * 1000;
  while (Date.now() < until) {
    await new Promise((res) => setTimeout(res, 2000));
    const st = await api("/api/settings").catch(() => null);
    const q = st && st.providers.find((x) => x.id === id);
    if (q && q.chatgpt && !q.chatgpt.anmeldung_laeuft) {
      S.settings = st;
      toast(q.chatgpt.plan ? `✓ Angemeldet als ${q.chatgpt.email || "ChatGPT-Konto"}.` : (q.last_error || "Anmeldung nicht abgeschlossen."),
        q.chatgpt.plan ? "ok" : "bad");
      return render();
    }
  }
  render();
}

async function chatgptLogout(id) {
  const r = await api(`/api/settings/providers/${id}/chatgpt/abmelden`, { method: "POST", body: {} });
  toast(r.meldung, r.widerrufen ? "ok" : "bad");
  render();
}

function chatgptNotice() {
  const p = (S.settings.providers || []).find((x) => x.chatgpt && x.chatgpt.hinweis_zeigen);
  if (!p) return;
  modal(`<div class="stack"><h2 style="margin:0">You're using your ChatGPT plan</h2>
    <p>KI-Anfragen über „${esc(p.name)}“ zählen ab jetzt auf das Kontingent deines ChatGPT-Abos. Wie viel diese App davon
    nutzen darf, legst du in ChatGPT fest: <a href="${CG_USAGE}" target="_blank" rel="noopener">Manage usage</a>.</p>
    <div class="row"><button class="primary" id="cg-ok">Got it</button></div></div>`);
  $("#cg-ok").onclick = () => guard(async () => {
    await api(`/api/settings/providers/${p.id}/chatgpt/hinweis-gesehen`, { method: "POST", body: {} });
    $("#modal").classList.add("hidden");
  });
}

async function verifyProvider(id, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "prüfe …"; }
  const r = await api(`/api/settings/providers/${id}/pruefen`, { method: "POST", body: {} }).catch((e) => ({ ok: false, fehler: e.message }));
  toast(r.ok ? `✓ ${r.meldung}` : `Prüfung fehlgeschlagen: ${r.fehler}`, r.ok ? "ok" : "bad");
  render();
  return r.ok;
}
async function loadModels(id, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "lade …"; }
  const r = await api(`/api/settings/providers/${id}/modelle`, { method: "POST", body: {} }).catch((e) => ({ ok: false, fehler: e.message }));
  toast(r.ok ? `${r.anzahl} Modelle geladen.` : `Modelle laden fehlgeschlagen: ${r.fehler}`, r.ok ? "ok" : "bad");
  render();
}

SUB["anbieter-neu"] = async (el) => {
  el.innerHTML = `<div class="row"><button class="ghost" id="back">← Zurück</button><h2 style="margin:0">Anbieter hinzufügen</h2></div>
    <p class="muted">Wähle einen Anbieter. Adresse und Anleitung sind schon vorbereitet – du brauchst meist nur deinen Schlüssel.</p>
    <div class="provider-grid">${S.settings.presets.map((p) => `<button class="preset" data-preset="${p.id}">
      <b>${esc(p.name)}</b><span class="small muted">${esc(p.info)}</span>
      <div class="small" style="margin-top:6px">${p.oauth ? "Anmeldung mit ChatGPT-Konto" : p.needs_key ? "🔑 Schlüssel nötig" : "Kein Schlüssel nötig"}</div></button>`).join("")}</div>`;
  $("#back").onclick = () => { S.sub = "anbieter"; render(); };
  el.querySelectorAll("[data-preset]").forEach((b) => (b.onclick = () => { S.newPreset = b.dataset.preset; S.editId = null; S.sub = "anbieter-edit"; render(); }));
};

function guideHtml(preset) {
  const link = preset.key_url ? `<a href="${esc(preset.key_url)}" target="_blank" rel="noopener">${esc(preset.key_url)}</a>` : "";
  let steps;
  if (preset.oauth) {
    return `<div class="guide"><b>So geht’s – ${esc(preset.name)}</b><p class="small" style="margin:4px 0">${esc(preset.info)}</p>
    <ol class="small"><li>„Continue with ChatGPT“ drücken – der Browser öffnet die Anmeldung bei OpenAI.</li>
      <li>Mit deinem ChatGPT-Konto anmelden und erlauben, dass Evel • Rote Fäden dein Abo nutzt.</li>
      <li>Zurück hier sind die Modelle schon geladen – unter „Modelle je Aufgabe“ auswählen.</li></ol>
    <p class="small muted" style="margin:6px 0 0">Nur für ChatGPT Plus und Pro. Kein API-Schlüssel, keine Zusatzkosten bei OpenAI;
      es zählt das Kontingent deines Abos. Die Anmeldung bleibt auf deinem Rechner.</p></div>`;
  }
  if (preset.id === "custom") {
    steps = ["Adresse deines Gateways eintragen (endet meist auf /v1).", "Schlüssel nur eintragen, wenn dein Gateway einen verlangt.",
      "„Speichern &amp; prüfen“ drücken.", "„Modelle laden“ – danach unter „Modelle je Aufgabe“ auswählen."];
  } else if (!preset.needs_key) {
    steps = [`Programm installieren und starten: ${link}`, "Mindestens ein Modell herunterladen bzw. laden.",
      "Adresse ist vorausgefüllt – nur ändern, wenn du einen anderen Port nutzt. Dann „Speichern &amp; prüfen“.",
      "„Modelle laden“ – danach unter „Modelle je Aufgabe“ auswählen."];
  } else {
    steps = ["Beim Anbieter ein Konto anlegen oder anmelden (meist Guthaben/Zahlungsmittel nötig).",
      `API-Schlüssel erstellen: ${link} – er wird oft nur einmal angezeigt, also gleich kopieren.`,
      "Schlüssel unten einfügen und „Speichern &amp; prüfen“ drücken.", "„Modelle laden“ – danach unter „Modelle je Aufgabe“ auswählen."];
  }
  return `<div class="guide"><b>So geht’s – ${esc(preset.name)}</b><p class="small" style="margin:4px 0">${esc(preset.info)}</p>
    <ol class="small">${steps.map((s) => `<li>${s}</li>`).join("")}</ol>
    <p class="small muted" style="margin:6px 0 0">Kosten entstehen direkt beim Anbieter je nach Nutzung. Der Schlüssel bleibt auf deinem Rechner.</p></div>`;
}

SUB["anbieter-edit"] = async (el) => {
  const st = S.settings;
  const p = S.editId ? st.providers.find((x) => x.id === S.editId) : null;
  if (S.editId && !p) { S.sub = "anbieter"; return render(); }
  const preset = st.presets.find((x) => x.id === (p ? p.preset : S.newPreset)) || st.presets[st.presets.length - 1];
  const models = (p && p.models) || [];
  el.innerHTML = `<div class="row"><button class="ghost" id="back">← Zurück</button>
      <h2 style="margin:0">${p ? esc(p.name) : "Neu: " + esc(preset.name)}</h2>${p ? statusChip(p.status) : ""}</div>
    ${guideHtml(preset)}
    <div class="card form stack">
      <div class="field"><label>Anzeigename</label><input id="pe-name" value="${esc(p ? p.name : preset.name)}"></div>
      ${preset.oauth ? (p ? chatgptStatusHtml(p) : "") : `<div class="field"><label>Adresse (Base-URL)</label><input id="pe-url" value="${esc(p ? p.base_url : preset.base_url)}" placeholder="https://…/v1"></div>
      <div class="field"><label>API-Schlüssel ${preset.needs_key ? "" : "(optional)"}</label>
        <div class="row" style="flex-wrap:nowrap"><input id="pe-key" type="password" autocomplete="off"
          placeholder="${p && p.api_key_gesetzt ? "gespeichert: " + esc(p.api_key_maskiert) + " – leer lassen zum Behalten" : "hier einfügen"}">
          <button class="ghost" id="pe-show" type="button">👁</button></div></div>`}
      ${p && p.last_error ? `<div class="err small">${esc(p.last_error)}</div>` : ""}
      <div class="row spread"><div class="row">${p ? `<button class="danger" id="pe-arch">Ins Archiv</button>` : ""}
        ${p && p.chatgpt && p.chatgpt.angemeldet ? `<button class="ghost" id="pe-cgout">Abmelden</button>` : ""}</div>
        <div class="row">${preset.oauth && (!p || !p.chatgpt.plan) ? `<button class="chatgpt-btn" id="pe-cglogin">Continue with ChatGPT</button>` : ""}
        ${preset.oauth && !p ? "" : `<button class="primary" id="pe-save">${p ? "Speichern" : "Speichern & prüfen"}</button>`}
        ${p ? `<button class="ki" id="pe-verify">Verbindung prüfen</button><button class="ghost" id="pe-models">Modelle laden</button>` : ""}</div></div>
    </div>
    ${p ? `<div class="card stack"><div class="row spread"><h3 style="margin:0">Modelle (${models.length})</h3>
        <span class="small muted">${p.models_geladen ? "geladen " + esc(p.models_geladen) : ""}</span></div>
      ${models.length ? `<input id="pe-filter" placeholder="Modelle filtern …"><div class="models" id="pe-list">${models.map((m) => `<div>${esc(m)}</div>`).join("")}</div>`
        : '<div class="muted small">Noch keine Modelle – „Modelle laden“ drücken.</div>'}
      <div class="row" style="flex-wrap:nowrap"><input id="pe-manual" placeholder="Modell von Hand ergänzen (nur falls es in der Liste fehlt)">
        <button class="ghost" id="pe-add-model">Hinzufügen</button></div></div>` : ""}`;
  $("#back").onclick = () => { S.sub = p ? "anbieter" : "anbieter-neu"; render(); };
  if ($("#pe-show")) $("#pe-show").onclick = () => { const k = $("#pe-key"); k.type = k.type === "password" ? "text" : "password"; };
  if ($("#pe-cglogin")) $("#pe-cglogin").onclick = (e) => guard(async () => {
    let id = p && p.id;
    if (!id) {
      const r = await api("/api/settings/providers", { method: "POST", body: { name: $("#pe-name").value, preset: preset.id } });
      id = S.editId = r.id;
      S.settings = await api("/api/settings");
    }
    await chatgptLogin(id, e.target);
  });
  if ($("#pe-cgout")) $("#pe-cgout").onclick = () => confirm("Von ChatGPT abmelden? Die Anmeldung wird bei OpenAI widerrufen.") && guard(() => chatgptLogout(p.id));
  if ($("#pe-save")) $("#pe-save").onclick = () => guard(async () => {
    const body = { name: $("#pe-name").value };
    if ($("#pe-url")) Object.assign(body, { base_url: $("#pe-url").value, api_key: $("#pe-key").value });
    if (p) {
      await api(`/api/settings/providers/${p.id}`, { method: "PUT", body }); toast("Gespeichert.", "ok"); render();
    } else {
      const r = await api("/api/settings/providers", { method: "POST", body: { ...body, preset: preset.id } });
      S.editId = r.id;
      if (await verifyProvider(r.id)) await loadModels(r.id);
    }
  });
  if (p) {
    $("#pe-verify").onclick = (e) => verifyProvider(p.id, e.target);
    $("#pe-models").onclick = (e) => loadModels(p.id, e.target);
    $("#pe-arch").onclick = () => confirm(`„${p.name}“ ins Archiv verschieben? (Wiederherstellbar)`) && guard(async () => {
      await api(`/api/settings/providers/${p.id}/archivieren`, { method: "POST", body: {} }); S.sub = "anbieter"; render();
    });
    $("#pe-add-model").onclick = () => guard(async () => {
      await api(`/api/settings/providers/${p.id}`, { method: "PUT", body: { manuelles_modell: $("#pe-manual").value } }); render();
    });
    if ($("#pe-filter")) $("#pe-filter").oninput = (e) => {
      const q = e.target.value.toLowerCase();
      $("#pe-list").querySelectorAll("div").forEach((d) => d.classList.toggle("hidden", !d.textContent.toLowerCase().includes(q)));
    };
  }
};

SUB.aufgaben = async (el) => {
  const st = S.settings;
  const usable = st.providers.filter((p) => (p.models || []).length);
  const lists = usable.map((p) => `<datalist id="dl-${p.id}">${p.models.map((m) => `<option value="${esc(m)}">`).join("")}</datalist>`).join("");
  const slot = (task, i, entry) => `<div class="slot" data-task="${task.id}" data-i="${i}"><span class="nr">${i + 1}</span>
    <select class="s-prov"><option value="">— Anbieter —</option>${usable.map((p) => `<option value="${p.id}" ${entry && entry.provider === p.id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
    <input class="s-model" placeholder="Modell wählen oder tippen" value="${esc(entry ? entry.model : "")}" ${entry ? `list="dl-${entry.provider}"` : ""}></div>`;
  el.innerHTML = `<h2>Modelle je Aufgabe</h2>
    <p class="muted">Pro Aufgabe bis zu drei Modelle – auch von verschiedenen Anbietern. Die 1. Wahl wird genutzt; fällt sie aus
      (Fehler, Limit, offline), springt automatisch die 2., dann die 3. ein. Aufgaben ohne eigene Auswahl nutzen „Standard“.</p>
    ${usable.length ? "" : `<div class="banner"><span>Noch kein Anbieter mit geladenen Modellen.</span><button class="primary" id="to-prov">Anbieter einrichten</button></div>`}
    ${usable.length ? `<div class="row spread card"><span class="small">Keine Lust auf Einzelauswahl? Die Standard-Auswahl in alle Aufgaben kopieren.</span>
      <button class="primary" id="copy-all">Standard für alle übernehmen</button></div>` : ""}
    ${lists}
    ${st.tasks.map((t) => `<div class="card"><div class="row spread"><div><h3 style="margin:0 0 2px">${esc(t.label)}</h3>
        <div class="small muted">${esc(t.info)}</div></div><div class="row"><span class="small muted" id="saved-${t.id}"></span>
        ${t.id === "standard" ? "" : `<button class="ghost" data-copy="${t.id}">Standard übernehmen</button>`}
        <button class="ki" data-test="${t.id}">Testen</button></div></div>
      <div style="margin-top:10px">${[0, 1, 2].map((i) => slot(t, i, t.kette[i])).join("")}</div>
      <div class="row expert" style="margin-top:8px"><label class="small" style="margin:0">Temperatur (Kreativität, 0–2)</label>
        <input class="t-temp" data-task="${t.id}" type="number" min="0" max="2" step="0.1" style="max-width:120px"
          value="${t.werte && t.werte.temperatur != null ? t.werte.temperatur : ""}" placeholder="automatisch">
        <span class="small muted">leer = Standard der Aufgabe (meist 0,8; Bewerter und Richter immer 0)</span></div></div>`).join("")}`;
  if ($("#to-prov")) $("#to-prov").onclick = () => { S.sub = "anbieter"; render(); };
  const save = (taskId) => guard(async () => {
    const kette = [...el.querySelectorAll(`.slot[data-task="${taskId}"]`)].map((s) => ({
      provider: $(".s-prov", s).value, model: $(".s-model", s).value }));
    await api(`/api/settings/tasks/${taskId}`, { method: "PUT", body: { kette } });
    $(`#saved-${taskId}`).textContent = "✓ gespeichert";
  });
  const standardChain = () => [...el.querySelectorAll('.slot[data-task="standard"]')].map((s) => ({
    provider: $(".s-prov", s).value, model: $(".s-model", s).value })).filter((e) => e.provider && e.model.trim());
  const copyStandard = async (taskIds) => {
    const kette = standardChain();
    if (!kette.length) { toast("Erst bei „Standard“ mindestens ein Modell auswählen.", "bad"); return; }
    for (const id of taskIds) await api(`/api/settings/tasks/${id}`, { method: "PUT", body: { kette } });
    toast(taskIds.length > 1 ? "Standard in alle Aufgaben übernommen." : "Standard übernommen.", "ok");
    render();
  };
  el.querySelectorAll("[data-copy]").forEach((b) => (b.onclick = () => guard(() => copyStandard([b.dataset.copy]))));
  if ($("#copy-all")) $("#copy-all").onclick = () => guard(() =>
    copyStandard(st.tasks.map((t) => t.id).filter((id) => id !== "standard")));
  el.querySelectorAll(".slot").forEach((s) => {
    $(".s-prov", s).onchange = (e) => { const m = $(".s-model", s); m.setAttribute("list", `dl-${e.target.value}`); m.value = ""; m.focus(); };
    $(".s-model", s).onchange = () => save(s.dataset.task);
  });
  el.querySelectorAll(".t-temp").forEach((i) => (i.onchange = () => guard(async () => {
    await api(`/api/settings/tasks/${i.dataset.task}/werte`, { method: "PUT", body: { temperatur: i.value } });
    $(`#saved-${i.dataset.task}`).textContent = "✓ gespeichert";
  })));
  el.querySelectorAll("[data-test]").forEach((b) => (b.onclick = () => guard(async () => {
    b.disabled = true; b.textContent = "teste …";
    const r = await api(`/api/settings/tasks/${b.dataset.test}/test`, { method: "POST", body: {} });
    b.disabled = false; b.textContent = "Testen";
    toast(r.ok ? `✓ Antwort von ${r.modell}` : `Test fehlgeschlagen: ${r.fehler}`, r.ok ? "ok" : "bad");
  })));
};

function previewHtml() {
  return `<div class="pv-head">Evel<span style="color:var(--accent)"> • </span>Rote Fäden</div>
  <div class="pv-body"><div class="row"><button class="primary">Primär</button><button class="ghost">Zweitrangig</button>
    <button class="ki">KI anwerfen</button><button class="danger">Löschen</button></div>
    <div class="card"><h3>Karte</h3><div>Normaler Text <span class="muted">und gedämpfter Text</span>.</div>
      <div class="row" style="margin-top:8px"><span class="chip st-fertig">erfolg</span><span class="chip st-offen">warnung</span>
      <span class="chip st-fehler">fehler</span><span class="chip ki">KI</span><span class="chip gap">Lücke</span></div></div>
    <input placeholder="Eingabefeld"><div class="op"><span class="k">+ neu</span> <b>Ort</b> „Kesh“</div>
    <div class="toast ok">Gespeichert.</div></div>`;
}

SUB.darstellung = async (el) => {
  const theme = S.settings.theme;
  const card = (id, name, vars) => `<div class="theme-card ${theme.active === id ? "active" : ""}" data-theme="${id}"><b>${name}</b>
    <div class="swatches">${["bg", "head", "panel", "accent", "ki", "text"].map((k) => `<span style="background:${vars[k]}"></span>`).join("")}</div>
    ${theme.active === id ? '<span class="small muted">aktiv</span>' : ""}</div>`;
  const eigen = { ...THEMES.hell.vars, ...(theme.eigen || {}) };
  el.innerHTML = `<h2>Darstellung</h2>
    <div class="themes">${Object.entries(THEMES).map(([id, t]) => card(id, t.name, t.vars)).join("")}
      ${card("eigen", "＋ Eigenes Theme", eigen)}</div>
    <div class="card stack ${theme.active === "eigen" || S.editTheme ? "" : "hidden"}" id="th-edit">
      <div class="row spread"><h3 style="margin:0">Eigenes Theme</h3><div class="row"><span class="small muted">Ausgangspunkt</span>
        <select id="th-base">${Object.entries(THEMES).map(([id, t]) => `<option value="${id}">${t.name}</option>`).join("")}</select>
        <button class="ghost" id="th-load">übernehmen</button></div></div>
      <div class="color-grid">${THEME_VARS.map(([k, label]) => `<label class="color-row"><input type="color" data-var="${k}" value="${eigen[k]}"><span>${label}</span></label>`).join("")}</div>
      <h3 style="margin:8px 0 0">Vorschau</h3><div class="preview" id="th-preview">${previewHtml()}</div>
      <div class="row spread"><span class="small muted">Änderungen siehst du sofort in der Vorschau.</span>
        <button class="primary" id="th-save">Eigenes Theme verwenden</button></div></div>`;
  const pv = $("#th-preview");
  const current = () => Object.fromEntries([...el.querySelectorAll("[data-var]")].map((i) => [i.dataset.var, i.value]));
  setVars(pv, current());
  el.querySelectorAll("[data-var]").forEach((i) => (i.oninput = () => setVars(pv, current())));
  el.querySelectorAll("[data-theme]").forEach((c) => (c.onclick = () => guard(async () => {
    if (c.dataset.theme === "eigen") { S.editTheme = true; $("#th-edit").classList.remove("hidden"); $("#th-edit").scrollIntoView({ behavior: "smooth" }); return; }
    S.editTheme = false;
    const t = await api("/api/settings/theme", { method: "PUT", body: { active: c.dataset.theme, eigen: theme.eigen } });
    applyTheme(t); render();
  })));
  $("#th-load").onclick = () => {
    const vars = THEMES[$("#th-base").value].vars;
    el.querySelectorAll("[data-var]").forEach((i) => (i.value = vars[i.dataset.var]));
    setVars(pv, current());
  };
  $("#th-save").onclick = () => guard(async () => {
    const t = await api("/api/settings/theme", { method: "PUT", body: { active: "eigen", eigen: current() } });
    applyTheme(t); toast("Eigenes Theme aktiv.", "ok"); render();
  });
};

SUB.welt = async (el) => {
  if (!S.world) { el.innerHTML = '<div class="card empty">Erst eine Welt anlegen.</div>'; return; }
  const o = await api(W("/overview"));
  el.innerHTML = `<h2>Diese Welt: ${esc(o.meta.name || S.world)}</h2><div class="card stack">
    <label class="row" style="margin:0;color:var(--text);text-transform:none;letter-spacing:0;font-size:14px;font-weight:400">
      <input type="checkbox" id="s-auto" style="width:auto" ${o.meta.einstellungen.auto_uebernehmen === "1" ? "checked" : ""}>
      KI-Vorschläge automatisch übernehmen (außer bei Rückfragen der KI)</label>
    <p class="muted small">Laut OFFENE_PUNKTE.md Nr. 7: keine regelmäßige Freigabe, die KI fragt nur gezielt nach.</p></div>
    <div class="card stack"><div class="field"><label>Standard-Länge einer Folge (Wörter)</label>
      <div class="row" style="flex-wrap:nowrap"><input id="s-words" type="number" min="500" max="20000" step="500" value="${esc(o.meta.einstellungen.folge_woerter)}" style="max-width:160px">
      <span class="small muted" id="s-words-min"></span><button class="ghost" id="s-words-save">Speichern</button></div></div>
      <p class="muted small">OFFENE_PUNKTE.md Nr. 6: Hörbuchfolgen ungefähr 60 Minuten (≈ 8000 Wörter bei ruhigem Vorlesetempo).</p></div>
    <div class="card stack"><div class="field"><label>Standard-Genre der Welt</label><div class="row" style="flex-wrap:nowrap">
      <select id="s-genre"><option value="">keins – Planer wählt passend</option></select><button class="ghost" id="s-genre-save">Speichern</button></div></div>
      <p class="muted small">Gilt, wenn weder Folge noch Strang ein Genre vorgeben. Genres und ihre Regeln: Welt → Genres.</p></div>
    <div class="card stack"><h3 style="margin:0">Überraschung</h3>
      <div class="field"><label>Wie weit darf die Geschichte vom Erwartbaren abweichen?</label><select id="s-abw">
        ${ABW.map(([v, l]) => `<option value="${v}" ${String(v) === o.meta.einstellungen.abweichung ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      <p class="small muted">Gilt, wenn Folge, Geschichte (Strang) und Genre nichts anderes sagen. Ab „Wendung“ darf der Erzähler den Hörer
        in die Irre führen – fair und auflösbar, nie gegen den Kanon.</p>
      <div class="expert stack">
        <div class="row"><div class="field"><label>Szenarien je Folge</label><select id="s-szen">${[1, 2, 3].map((n) =>
          `<option ${String(n) === o.meta.einstellungen.szenarien ? "selected" : ""}>${n}</option>`).join("")}</select></div>
          <div class="field"><label>Wer wählt?</label><select id="s-wahl"><option value="automatisch">der Bewerter (automatisch)</option>
            <option value="ich" ${o.meta.einstellungen.szenario_wahl === "ich" ? "selected" : ""}>ich selbst</option></select></div>
          <div class="field"><label>Mindest-Kanonpassung (0–10)</label><input id="s-mink" type="number" min="0" max="10" step="1" value="${esc(o.meta.einstellungen.min_kanon)}" style="max-width:90px"></div>
          <div class="field"><label>Ziel-Überraschung (0–10)</label><input id="s-ziel" type="number" min="0" max="10" step="0.5" value="${esc(o.meta.einstellungen.ziel_ueberraschung)}" placeholder="aus Stufe" style="max-width:100px"></div></div>
        <p class="small muted">Bei mehr als einem Szenario: Ein Agent schreibt auf, was der Hörer erwartet (ohne Geheimnisse), der Planer liefert
          Szenarien mit verschiedenen Stufen, der Bewerter misst Kanonpassung und Überraschung. Gewählt wird das Szenario mit ausreichend
          Kanonpassung, dessen Überraschung am nächsten am Ziel liegt (Ziel leer = aus der Stufe: 2 / 4 / 6,5 / 8,5).</p>
        <div class="field"><label>Kontext für die KI</label><select id="s-kon"><option value="voll">voll – ganzer Kanon in jedem Aufruf</option>
          <option value="kaskade" ${o.meta.einstellungen.kontext_modus === "kaskade" ? "selected" : ""}>Kaskade – Thema → Beteiligte → Szene</option></select></div>
        <p class="small muted">Kaskade: erst wählt die KI aus einem kompakten Überblick Thema und Beteiligte, danach bekommen Planer, Autor, Prüfer und
          Archivar nur deren Datensätze. Ob das besser ist, zeigt der Prüfstand (mit Ballast, einmal voll, einmal Kaskade).</p></div>
      <div class="row"><button class="ghost" id="s-abw-save">Speichern</button></div></div>
    <div class="card stack"><h3 style="margin:0">Stil-Abgleich</h3>
      <div class="field"><label>Wenn eine Folge deutlich vom Fingerabdruck der Stimme abweicht …</label><div class="row" style="flex-wrap:nowrap">
        <select id="s-stil"><option value="stark">… wartet sie auf meine Freigabe</option>
          <option value="nie" ${o.meta.einstellungen.stil_anhalten === "nie" ? "selected" : ""}>… nur anzeigen, nicht anhalten</option></select>
        <button class="ghost" id="s-stil-save">Speichern</button></div></div>
      <p class="small muted">Jede Folge wird per Code mit dem Stil-Fingerabdruck ihrer Stimme verglichen (Satzbau, Rhythmus, Dialog, Erzählzeit,
        Perspektive, Satzzeichen, kleine Wörter). Das Ergebnis steht an der Folge unter „Stil-Abgleich“ und im KI-Lauf.</p></div>`;
  $("#s-stil-save").onclick = () => guard(async () => {
    await api(W("/settings"), { method: "POST", body: { stil_anhalten: $("#s-stil").value } }); toast("Gespeichert.", "ok");
  });
  api(W("/rows/genres")).then((g) => {
    $("#s-genre").innerHTML += g.rows.map((x) => `<option value="${x.id}" ${String(x.id) === o.meta.einstellungen.standard_genre ? "selected" : ""}>${esc(x.name)}</option>`).join("");
  });
  $("#s-abw-save").onclick = () => guard(async () => {
    const body = { abweichung: $("#s-abw").value };
    if (S.expert) Object.assign(body, { szenarien: $("#s-szen").value, szenario_wahl: $("#s-wahl").value, min_kanon: $("#s-mink").value,
      ziel_ueberraschung: $("#s-ziel").value, kontext_modus: $("#s-kon").value });
    await api(W("/settings"), { method: "POST", body }); toast("Gespeichert.", "ok");
  });
  $("#s-genre-save").onclick = () => guard(async () => {
    await api(W("/settings"), { method: "POST", body: { standard_genre: $("#s-genre").value } }); toast("Gespeichert.", "ok");
  });
  const wmin = () => { $("#s-words-min").textContent = `≈ ${Math.round(Number($("#s-words").value) / 135)} Minuten`; };
  $("#s-words").oninput = wmin; wmin();
  $("#s-words-save").onclick = () => guard(async () => {
    await api(W("/settings"), { method: "POST", body: { folge_woerter: Number($("#s-words").value) } }); toast("Gespeichert.", "ok");
  });
  $("#s-auto").onchange = (e) => guard(async () => {
    await api(W("/settings"), { method: "POST", body: { auto_uebernehmen: e.target.checked } }); toast("Gespeichert.", "ok");
  });
  await worldExtras(el, o);
};

async function worldExtras(el, o) {
  const set = o.meta.einstellungen;
  const [n, v] = await Promise.all([api(W("/news")), api("/api/audio/stimmen")]);
  const box = document.createElement("div");
  box.className = "stack";
  box.style.marginTop = "14px";
  box.innerHTML = `<div class="card stack"><h3 style="margin:0">Täglicher Lauf</h3>
      <p class="small muted">Zur eingestellten Uhrzeit: Nachrichten abrufen → als Impulse einarbeiten → nächste Folge erzeugen.
        Läuft nur, solange Story World geöffnet ist; ein verpasster Lauf wird am selben Tag nachgeholt. Für den Betrieb ohne
        offene Oberfläche: <code>python3 -m story_world taeglich ${esc(S.world)}</code> per Zeitplan (siehe BETRIEB.md).</p>
      <label class="row" style="margin:0;color:var(--text);text-transform:none;letter-spacing:0;font-size:14px;font-weight:400">
        <input type="checkbox" id="a-on" style="width:auto" ${set.auto_folge === "1" ? "checked" : ""}> Jeden Tag automatisch eine Folge</label>
      <div class="row"><div class="field"><label>Uhrzeit</label><input id="a-time" type="time" value="${esc(set.auto_uhrzeit)}"></div>
        <div class="field"><label>Nachrichten pro Tag</label><input id="a-news" type="number" min="0" max="10" value="${esc(set.nachrichten_pro_tag)}" style="max-width:110px"></div>
        <button class="ghost" id="a-save">Speichern</button><button class="ki" id="a-now">Jetzt einmal ausführen</button></div>
      <div class="small muted">Letzter Lauf: ${esc(o.meta.auto_letzter_lauf || "noch nie")}</div></div>
    <div class="card stack"><h3 style="margin:0">Nachrichtenquellen (RSS/Atom)</h3>
      ${n.quellen.length ? `<table>${n.quellen.map((q) => `<tr><td><b>${esc(q.name)}</b><div class="small muted">${esc(q.url)}</div>
        ${q.last_error ? `<div class="err small">${esc(q.last_error)}</div>` : ""}</td><td class="small muted">${esc(q.last_fetch || "")}</td>
        <td><button class="ghost" data-toggle="${q.id}">${q.active ? "deaktivieren" : "aktivieren"}</button></td></tr>`).join("")}</table>`
        : '<div class="muted small">Noch keine Quelle. Beispiel: der RSS-Feed einer Nachrichtenseite oder eines Wissenschaftsmagazins.</div>'}
      <div class="row" style="flex-wrap:nowrap"><input id="n-name" placeholder="Name" style="max-width:180px"><input id="n-url" placeholder="https://…/feed.xml">
        <button class="primary" id="n-add">Hinzufügen</button></div>
      <div class="row"><button class="ghost" id="n-fetch">Jetzt abrufen</button><span class="small muted" id="n-res"></span></div>
      ${n.meldungen.length ? `<details><summary class="muted">Letzte Meldungen (${n.meldungen.length})</summary><table>${n.meldungen.map((m) =>
        `<tr><td class="small">${esc(m.title)}</td><td class="small muted">${esc(m.quelle || "")}</td><td>${m.impulse_id ? '<span class="chip st-fertig">Impuls</span>' : ""}</td></tr>`).join("")}</table></details>` : ""}</div>
    <div class="card stack"><h3 style="margin:0">Hörbuch-Stimmen</h3>
      ${v.verfuegbar ? `<div class="row"><div class="field"><label>Erzähler-Stimme</label><select id="h-voice"><option value="">automatisch (erste deutsche)</option>
        ${v.deutsch.map((name) => `<option ${name === set.erzaehler_stimme ? "selected" : ""}>${esc(name)}</option>`).join("")}</select></div>
        <div class="field"><label>Sprechtempo (Wörter/Minute)</label><input id="h-rate" type="number" min="80" max="260" value="${esc(set.sprechtempo)}" style="max-width:110px"></div>
        <button class="ghost" id="h-save">Speichern</button></div>
        <p class="small muted">${v.deutsch.length} deutsche Systemstimmen gefunden. Figuren bekommen ihre Stimme über das Feld „Stimme (Hörbuch)“ – sonst reihum.
          Weitere Stimmen: macOS-Systemeinstellungen → Bedienungshilfen → Gesprochene Inhalte → Systemstimme → Stimmen verwalten.
          Aussprache fremder Namen: Welt → Aussprache-Lexikon.</p>`
        : '<p class="small muted">Vertonung nutzt den macOS-Befehl „say“ – auf diesem System nicht vorhanden. Der JSON-Export je Folge funktioniert trotzdem.</p>'}</div>`;
  el.appendChild(box);
  const save = (body) => guard(async () => { await api(W("/settings"), { method: "POST", body }); toast("Gespeichert.", "ok"); });
  $("#a-save").onclick = () => save({ auto_folge: $("#a-on").checked, auto_uhrzeit: $("#a-time").value,
    nachrichten_pro_tag: Number($("#a-news").value) });
  $("#a-on").onchange = () => save({ auto_folge: $("#a-on").checked });
  $("#a-now").onclick = () => guard(async () => {
    await api(W("/daily/run"), { method: "POST", body: {} }); toast("Täglicher Lauf gestartet."); pollJobs();
  });
  $("#n-add").onclick = () => guard(async () => {
    await api(W("/news/sources"), { method: "POST", body: { name: $("#n-name").value, url: $("#n-url").value } }); render();
  });
  $("#n-fetch").onclick = () => guard(async () => {
    $("#n-res").textContent = "rufe ab …";
    const r = await api(W("/news/abrufen"), { method: "POST", body: {} });
    $("#n-res").textContent = `${r.neu} neue Meldungen` + (r.fehler.length ? ` · Fehler: ${r.fehler.join("; ")}` : "");
  });
  box.querySelectorAll("[data-toggle]").forEach((b) => (b.onclick = () => guard(async () => {
    await api(W(`/news/sources/${b.dataset.toggle}/umschalten`), { method: "POST", body: {} }); render();
  })));
  if ($("#h-save")) $("#h-save").onclick = () => save({ erzaehler_stimme: $("#h-voice").value, sprechtempo: Number($("#h-rate").value) });
}

SUB.schnittstellen = async (el) => {
  el.innerHTML = `<h2>Schnittstellen</h2><div class="card stack"><h3>MCP – für KI-Clients</h3>
    <p class="small">Claude Desktop, Claude Code und andere MCP-fähige KIs können die Welt lesen, Impulse und Nachrichten einspielen
      und Vorschläge einreichen. Eintrag für <code>claude_desktop_config.json</code> → <code>mcpServers</code>:</p>
    <pre class="code">"story-world": {
  "command": "python3",
  "args": ["&lt;Projektordner&gt;/story_world_mcp.py"]
}</pre>
    <p class="small muted">Für Claude Code: <code>mcp.example.json</code> im Projektordner in <code>.mcp.json</code> umbenennen.</p></div>
    <div class="card stack"><h3>HTTP-API – für Skripte auf diesem Rechner</h3>
    <pre class="code">curl -X POST http://127.0.0.1:8765/api/w/&lt;welt&gt;/impulses -H 'X-Story-World: 1' \\
  -H 'Content-Type: application/json' \\
  -d '{"title": "Schlagzeile", "content": "…", "kind": "nachricht", "ki_sofort": true}'</pre></div>`;
};

SUB.sicherung = async (el) => {
  const ex = await api("/api/exporte");
  const sizeTxt = (b) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`);
  el.innerHTML = `<h2>Export &amp; Umzug</h2><div class="card stack">
    <p class="small muted">Für einen anderen Rechner. <b>Welt</b>: Kanon, Folgen, Nachvollzug und jede Stimme, die die Welt nutzt
      (Steckbrief, Regler, Hinweise, Probe, Maßstab). Bei Stimmen „wie ein Mensch“ gehen statt der ganzen Texte nur Stilanker und
      Maßstab-Auszug mit; eingelesene Texte, die schon im Kanon stecken, ohne Inhalt. <b>Autor</b>: Erzählprofile, eigene Texte
      vollständig, alle Stimmen. <b>Alles</b>: Autor plus alle Welten.<br>
      Beim Import prüft Story World die Profil-ID: Ist der Mensch auf dem Rechner bekannt, sind seine Texte sichtbar – sonst liegen sie
      verborgen und werden trotzdem genutzt. Erst den Autor importieren, dann die Welten. Exporte enthalten Backstage-Geheimnisse.</p>
    <div class="row spread">${S.world ? `<span>Welt „${esc(S.world)}“</span><span class="row"><label class="small row" style="gap:6px"><input type="checkbox" id="x-audio-w" style="width:auto"> mit Hörbüchern</label>
      <button class="ghost" data-export="welt">Welt exportieren</button></span>` : '<span class="muted small">Keine Welt gewählt.</span>'}</div>
    <div class="row spread"><span>Autor (Profile, Texte, Stimmen)</span><button class="ghost" data-export="autor">Autor exportieren</button></div>
    <div class="row spread"><span>Alles</span><span class="row"><label class="small row" style="gap:6px"><input type="checkbox" id="x-audio-a" style="width:auto"> mit Hörbüchern</label>
      <button class="ghost" data-export="alles">Alles exportieren</button></span></div>
    <div class="row spread" style="border-top:1px solid var(--line);padding-top:12px"><span>Importieren <span class="small muted">(Export-Datei .zip)</span></span>
      <span class="row"><input type="file" id="x-file" accept=".zip" style="width:auto"><button class="primary" id="x-import">Importieren</button></span></div>
    <div id="x-report"></div>
    <details ${ex.exporte.length ? "open" : ""}><summary class="small">Exporte in ${esc(ex.ordner)} (${ex.exporte.length})</summary>
      ${ex.exporte.length ? `<table>${ex.exporte.map((x) => `<tr><td class="small">${esc(x.datei)}</td><td class="small muted">${esc(x.zeit)}</td>
        <td class="small muted">${sizeTxt(x.groesse)}</td><td><a class="small" href="/api/exporte/${encodeURIComponent(x.datei)}">Herunterladen</a></td></tr>`).join("")}</table>` : '<div class="small muted">Noch keine Exporte.</div>'}</details></div>
    <div id="s-sicherung"></div>`;
  el.querySelectorAll("[data-export]").forEach((b) => (b.onclick = () => guard(async () => {
    const typ = b.dataset.export;
    b.disabled = true; const label = b.textContent; b.textContent = "Exportiere …";
    try {
      const r = await api("/api/export", { method: "POST", body: { typ, welt: S.world,
        audio: typ === "welt" ? $("#x-audio-w").checked : typ === "alles" ? $("#x-audio-a").checked : false } });
      toast(`Export fertig: ${r.datei}`, "ok");
      const a = document.createElement("a"); a.href = `/api/exporte/${encodeURIComponent(r.datei)}`; a.click();
    } finally { b.disabled = false; b.textContent = label; render(); }
  })));
  $("#x-import").onclick = () => guard(async () => {
    const f = $("#x-file").files[0];
    if (!f) throw new Error("Bitte eine Export-Datei wählen.");
    $("#x-import").disabled = true; $("#x-import").textContent = "Importiere …";
    try {
      const res = await fetch("/api/import", { method: "POST", headers: { "X-Story-World": "1", "Content-Type": "application/zip" }, body: f });
      const r = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(r.fehler || `Fehler ${res.status}`);
      const lines = [];
      if (r.autor) lines.push(`Autor: ${r.autor.profile_neu.length} neue Profile${r.autor.profile_vorhanden.length ? `, ${r.autor.profile_vorhanden.length} vorhanden` : ""}, ${r.autor.texte_neu} Texte,
        Stimmen ${Object.entries(r.autor.stimmen).map(([k, n]) => `${n} ${k}`).join(", ") || "–"}${r.autor.freigeschaltet ? `, ${r.autor.freigeschaltet} vorher Verborgenes jetzt sichtbar` : ""}`);
      for (const w of r.welten) lines.push(`Welt „${w.name || w.slug}“ → ${w.slug}: Stimmen ${Object.entries(w.stimmen).map(([k, n]) => `${n} ${k}`).join(", ") || "–"}${w.verborgen ? `, ${w.verborgen} Text-Abschnitte verborgen (anderer Autor)` : ""}${w.audio ? `, ${w.audio} Audiodateien` : ""}`);
      $("#x-report").innerHTML = `<div class="note small">${lines.map(esc).join("<br>")}</div>`;
      toast("Import fertig.", "ok");
      if (r.welten.length) { await loadWorlds(r.welten[0].slug); }
    } finally { $("#x-import").disabled = false; $("#x-import").textContent = "Importieren"; }
  });
  const inner = $("#s-sicherung");
  if (!S.world) return;
  inner.innerHTML = `<h2 style="margin-top:22px">Sicherung</h2><div class="card stack">
    <p class="muted small">Legt eine konsistente Kopie der aktuellen Welt unter welten/backups/ an. Vor jeder Schemaänderung passiert das automatisch.
      Sicherungen enthalten Backstage-Geheimnisse – nicht weitergeben.</p>
    <div class="row"><button class="ghost" id="s-backup">Sicherung jetzt anlegen</button><span id="s-bres" class="small muted"></span></div></div>`;
  $("#s-backup").onclick = () => guard(async () => {
    const r = await api(W("/backup"), { method: "POST", body: {} }); $("#s-bres").textContent = r.datei; toast("Sicherung angelegt.", "ok"); render();
  });
  const { sicherungen } = await api("/api/backups");
  const box = document.createElement("div");
  box.className = "card stack";
  box.style.marginTop = "14px";
  el = inner;
  box.innerHTML = `<h3 style="margin:0">Wiederherstellen</h3>
    <p class="small muted">Eine Sicherung wird als <b>neue</b> Welt wiederhergestellt – deine aktuelle Welt und die Sicherung bleiben unverändert.</p>
    ${sicherungen.length ? `<table>${sicherungen.map((b) => `<tr><td class="small">${esc(b.datei)}</td><td class="small muted">${esc(b.zeit)}</td>
      <td class="small muted">${Math.round(b.groesse / 1024)} KB</td><td><button class="ghost" data-restore="${esc(b.datei)}">Als neue Welt öffnen</button></td></tr>`).join("")}</table>`
      : '<div class="muted small">Noch keine Sicherungen.</div>'}`;
  el.appendChild(box);
  box.querySelectorAll("[data-restore]").forEach((b) => (b.onclick = () => guard(async () => {
    const r = await api("/api/backups/wiederherstellen", { method: "POST", body: { datei: b.dataset.restore } });
    store("sw-world", r.slug); await loadWorlds(r.slug); toast("Als neue Welt wiederhergestellt.", "ok"); render();
  })));
};

// ------------------------------------------------------------ Programm-Update

const UPD = { info: null, report: null };

SUB.update = async (el) => {
  const st = await api("/api/update/status");
  const info = UPD.info, rep = UPD.report;
  const notes = (txt) => (txt ? `<div class="update-notes">${esc(txt)}</div>` : "");
  let result = "";
  if (rep || st.wartet_auf_neustart) {
    result = `<div class="card stack"><b>Update ${esc(rep ? rep.nach : "")} ist installiert.</b>
      ${rep ? `<div class="small">${rep.geaendert} Dateien geändert, ${rep.neu} neu, ${rep.entfallen} entfallen.
        ${rep.sicherung ? `Die alten Fassungen liegen in <code>${esc(rep.sicherung)}</code>.` : ""}</div>` : ""}
      <div class="small muted">Wirksam nach dem Neustart. Deine Welten werden beim ersten Öffnen automatisch angepasst – vorher wird jeweils eine Sicherung angelegt.</div>
      ${st.neustart_automatisch ? '<div class="row"><button class="primary" id="u-restart">Jetzt neu starten</button></div>'
        : '<div class="note small">Bitte das Story-World-Fenster schließen und „Story World starten.bat“ erneut doppelklicken.</div>'}</div>`;
  } else if (info && info.neuer) {
    result = `<div class="card stack"><div class="row spread"><b>Neue Version ${esc(info.neueste)}</b>
      <span class="small muted">${esc((info.veroeffentlicht || "").slice(0, 10))}</span></div>
      ${notes(info.notizen) || '<div class="small muted">Keine Beschreibung zum Release.</div>'}
      ${st.entwickler ? '<div class="note small">Dieser Ordner ist ein Git-Entwicklerstand – hier bitte <code>git pull</code> verwenden.</div>'
        : `<div class="row"><button class="primary" id="u-install" ${st.jobs_laufen ? "disabled" : ""}>Jetzt installieren</button>
          ${st.jobs_laufen ? '<span class="small muted">Erst laufende KI-Aufträge abwarten.</span>' : ""}</div>`}</div>`;
  } else if (info) {
    result = `<div class="card small">Du hast die neueste Version${info.neueste ? ` (${esc(info.neueste)})` : ""}. Geprüft: ${esc(info.geprueft)}</div>`;
  }
  el.innerHTML = `<h2>Update</h2><div class="card stack">
    <div class="row spread"><span>Installierte Version <b>${esc(st.version)}</b></span>
      <button class="ghost" id="u-check">Nach Updates suchen</button></div>
    <p class="small muted">Lädt neue Versionen von Codeberg. Ersetzt werden nur Programmdateien – Welten, Einstellungen, Profile, Stimmen,
      Texte und Exporte bleiben unberührt. Alte Programmdateien kommen nach <code>_old/</code>, nichts wird gelöscht.</p>
    <label class="small row" style="gap:6px;text-transform:none;letter-spacing:0;font-weight:400"><input type="checkbox" id="u-auto" style="width:auto" ${st.automatisch ? "checked" : ""}>
      Beim Start automatisch nachsehen (höchstens einmal am Tag)</label></div>
    <div id="u-result" class="stack" style="margin-top:14px">${result}</div>`;
  $("#u-auto").onchange = (e) => guard(async () => { await api("/api/update/einstellungen", { method: "PUT", body: { automatisch: e.target.checked } }); });
  $("#u-check").onclick = () => guard(async () => {
    const b = $("#u-check"); b.disabled = true; b.textContent = "Suche …";
    try { UPD.info = await api("/api/update/pruefen", { method: "POST", body: {} }); } finally { b.disabled = false; b.textContent = "Nach Updates suchen"; }
    render();
  });
  const inst = $("#u-install");
  if (inst) inst.onclick = () => guard(async () => {
    inst.disabled = true; inst.textContent = "Lade und installiere …";
    try { UPD.report = await api("/api/update/installieren", { method: "POST", body: {} }); toast("Update installiert.", "ok"); }
    finally { inst.disabled = false; inst.textContent = "Jetzt installieren"; }
    render();
  });
  const rs = $("#u-restart");
  if (rs) rs.onclick = () => guard(async () => {
    rs.disabled = true; rs.textContent = "Starte neu …";
    await api("/api/update/neustart", { method: "POST", body: {} });
    await waitForRestart(st.version);
  });
};

async function waitForRestart(oldVersion) {
  const until = Date.now() + 90000;
  await new Promise((r) => setTimeout(r, 1500));
  while (Date.now() < until) {
    try {
      const res = await fetch("/api/update/status", { headers: { "X-Story-World": "1" } });
      if (res.ok) { const s = await res.json(); if (s.version !== oldVersion) { location.reload(); return; } }
    } catch (e) { /* Server startet gerade neu */ }
    await new Promise((r) => setTimeout(r, 1000));
  }
  toast("Neustart dauert ungewöhnlich lange – bitte Story World von Hand neu starten.", "bad");
}

async function showUpdateBanner() {
  const st = await api("/api/update/status").catch(() => null);
  const box = $("#update-banner");
  if (!st) return;
  const parts = [];
  if (st.reparatur) {
    const r = st.reparatur;
    parts.push(r.fehler ? `<div><b>Ein Update wurde unterbrochen.</b> <span class="small">${esc(r.fehler)}</span></div>`
      : `<div><b>Ein Update wurde unterbrochen</b> (z. B. Stromausfall). Der vorherige Stand ${esc(r.von)} ist wiederhergestellt –
        du kannst das Update unter Einstellungen → Update erneut starten.
        <div class="small muted">${r.wiederhergestellt} Dateien zurückgeholt, ${r.beiseitegelegt} beiseitegelegt in <code>${esc(r.sicherung)}</code>.</div></div>`);
  }
  if (st.neu) {
    const secs = st.neu.abschnitte.map((a) => `<div style="margin-top:6px"><b>${esc(a.titel)}</b><div class="update-notes">${esc(a.text)}</div></div>`).join("");
    parts.push(`<div><b>Update installiert: ${esc(st.neu.von)} → ${esc(st.neu.nach)}</b>
      ${secs || (st.neu.notizen ? `<div class="update-notes">${esc(st.neu.notizen)}</div>` : "")}
      ${st.neu.sicherung ? `<div class="small muted">Alte Programmdateien: <code>${esc(st.neu.sicherung)}</code></div>` : ""}</div>`);
  }
  if (st.migrationen.length) {
    parts.push(`<div class="small"><b>Datenbanken angepasst:</b> ${st.migrationen.map((m) => `${esc(m.datei)} (Schema ${m.von} → ${m.nach}${m.sicherung
      ? `, Sicherung ${esc(m.sicherung.split(/[\\/]/).pop())}` : ""})`).join(", ")}. Deine Inhalte bleiben erhalten; die Sicherungen liegen in welten/backups/.</div>`);
  }
  if (parts.length) {
    box.innerHTML = `<div class="banner"><div class="stack">${parts.join("")}</div><button class="ghost" id="ub-ok">Verstanden</button></div>`;
    box.classList.remove("hidden");
    $("#ub-ok").onclick = () => guard(async () => { await api("/api/update/gesehen", { method: "POST", body: {} }); box.classList.add("hidden"); box.innerHTML = ""; });
  } else if (st.verfuegbar && !sessionStorage.getItem("sw-upd-hinweis")) {
    try { sessionStorage.setItem("sw-upd-hinweis", "1"); } catch (e) {}
    box.innerHTML = `<div class="banner"><span>Neue Version <b>${esc(st.verfuegbar.neueste)}</b> verfügbar.</span>
      <span class="row"><button class="primary" id="ub-go">Ansehen</button><button class="ghost" id="ub-later">Später</button></span></div>`;
    box.classList.remove("hidden");
    $("#ub-go").onclick = () => { box.classList.add("hidden"); UPD.info = { ...st.verfuegbar, neuer: true }; openSettings("update"); };
    $("#ub-later").onclick = () => box.classList.add("hidden");
  }
}

// ------------------------------------------------------------ KI-Jobs

let pollTimer = null;
function pollJobs() { S.jobsRunning = true; if (!pollTimer) pollTimer = setTimeout(checkJobs, 1000); }
async function checkJobs() {
  pollTimer = null;
  const { jobs } = await api("/api/jobs").catch(() => ({ jobs: [] }));
  const running = jobs.filter((j) => j.status === "laeuft");
  const ind = $("#jobs-indicator");
  ind.innerHTML = running.map((j) => `<span title="${esc(j.phase || "")}">${esc(j.ziel)} · ${j.progress || 0}%</span>
    <span class="mini-bar"><span style="width:${Math.max(j.progress || 0, 4)}%"></span></span>`).join(" ");
  ind.classList.toggle("hidden", !running.length);
  ind.onclick = () => go("laeufe", running.length === 1 && running[0].run_id ? running[0].run_id : null);
  const badge = $("#badge-runs");
  badge.textContent = running.length; badge.classList.toggle("hidden", !running.length);
  let seen = [];
  try { seen = JSON.parse(sessionStorage.getItem("sw-jobs-seen") || "[]"); } catch (e) {}
  jobs.filter((j) => j.status !== "laeuft" && !seen.includes(j.id)).forEach((j) => {
    seen.push(j.id);
    if (S.jobsRunning) toast(j.status === "fertig" ? `KI fertig (${j.ziel}): ${j.meldung}` : `KI-Fehler (${j.ziel}): ${j.meldung}`, j.status === "fertig" ? "ok" : "bad");
  });
  try { sessionStorage.setItem("sw-jobs-seen", JSON.stringify(seen.slice(-50))); } catch (e) {}
  const wasRunning = S.jobsRunning;
  S.jobsRunning = running.length > 0;
  if (wasRunning && !S.jobsRunning) render();
  if (S.jobsRunning) pollJobs();
}

// ------------------------------------------------------------ Start

(async () => {
  await guard(async () => {
    S.cfg = await api("/api/config");
    S.settings = await api("/api/settings");
    applyTheme(S.settings.theme);
    await loadWorlds();
  });
  $("#btn-user").onclick = () => (S.user ? openPerson(S.user.id) : guard(chooseUser));
  showUser();
  render();
  checkJobs();
  showUpdateBanner();
  guard(chooseUser);  // beim Start: Wer bedient gerade?
})();

// ------------------------------------------------------------ TTS-Server (Einstellungen) und Vertonung je Folge

const TTS_STATUS = { ok: "verbunden", fehler: "Fehler", ungeprueft: "nicht geprüft" };
const GENDER = { female: "w", male: "m", w: "w", m: "m" };
const voiceLabel = (v) => `${v.name}${GENDER[v.geschlecht] ? ` (${GENDER[v.geschlecht]})` : ""}`;

function ttsServerForm(s, typen, preset) {
  preset = preset || {};
  const isNew = !s;
  const custom = !preset.id || preset.id === "custom";
  s = s || { typ: preset.typ || "openai", name: custom ? "" : preset.name, base_url: preset.base_url || "", modell: preset.modell || "",
    sprache: preset.sprache || "", max_zeichen: preset.max_zeichen || 400, timeout: 300 };
  const needsKey = preset.needs_key || s.api_key_gesetzt;
  const keyField = `<div class="field"><label>API-Schlüssel ${s.api_key_gesetzt ? `(gesetzt: ${esc(s.api_key_maskiert)})` : preset.needs_key ? "" : "(optional)"}</label>
    <input data-f="api_key" type="password" autocomplete="off" placeholder="${s.api_key_gesetzt ? "leer = behalten" : preset.needs_key ? "hier einfügen" : ""}"></div>`;
  const typField = `<div class="field"><label>Art</label><select data-f="typ">${typen.map((t) => `<option value="${t.id}" ${t.id === s.typ ? "selected" : ""}>${esc(t.name)}</option>`).join("")}</select></div>`;
  const dlId = `tm-${s.id || "neu"}`;
  const dl = (s.modelle || []).length ? `<datalist id="${esc(dlId)}">${s.modelle.map((m) => `<option value="${esc(m)}">`).join("")}</datalist>` : "";
  return `${isNew ? `<input type="hidden" data-f="preset" value="${esc(preset.id || "custom")}">` : ""}<div class="row">
      <div class="field"><label>Name</label><input data-f="name" value="${esc(s.name || "")}" placeholder="z. B. Phonon 40M"></div>
      ${custom ? typField : ""}
      <div class="field" style="flex:2"><label>Adresse</label><input data-f="base_url" value="${esc(s.base_url || "")}" placeholder="http://192.168.1.50:8012"></div>
      ${needsKey ? keyField : ""}</div>
    <div class="row expert">
      ${custom ? "" : typField}
      <div class="field"><label>Modell (leer = vom Server)</label><input data-f="modell" value="${esc(s.modell || "")}" placeholder="tts-1" ${dl ? `list="${esc(dlId)}"` : ""}>${dl}</div>
      <div class="field"><label>Sprache (leer = je Stimme)</label><input data-f="sprache" value="${esc(s.sprache || "")}" placeholder="de" style="max-width:90px"></div>
      <div class="field"><label>Max. Zeichen je Anfrage</label><input data-f="max_zeichen" type="number" min="50" max="5000" value="${esc(s.max_zeichen || 400)}" style="max-width:110px"></div>
      <div class="field"><label>Zeitlimit (s)</label><input data-f="timeout" type="number" min="10" max="3600" value="${esc(s.timeout || 300)}" style="max-width:100px"></div>
      ${needsKey ? "" : keyField}</div>`;
}

function ttsGuide(p) {
  const link = p.key_url ? `<a href="${esc(p.key_url)}" target="_blank" rel="noopener">${esc(p.key_url)}</a>` : "";
  const steps = p.needs_key
    ? ["Beim Anbieter ein Konto anlegen oder anmelden.",
      `API-Schlüssel erstellen: ${link} – er wird oft nur einmal angezeigt, also gleich kopieren.`,
      p.typ === "azure" ? "Region in der Adresse anpassen (steht in der Azure-Ressource unter „Schlüssel und Endpunkt“)." : "",
      "Schlüssel unten einfügen und „Hinzufügen und prüfen“ drücken – die Stimmen werden geladen.",
      "Danach in der Folge unter „Vertonung über TTS-Server“ die Stimmen besetzen."]
    : p.id === "custom"
      ? ["Adresse deines Servers eintragen (ohne /v1).", "„Hinzufügen und prüfen“ – die Stimmen werden vom Server geladen."]
      : [`Programm installieren und starten: ${link}`, "Adresse ist vorausgefüllt – nur ändern, wenn der Server auf einem anderen Rechner oder Port läuft.",
        "„Hinzufügen und prüfen“ – die Stimmen werden geladen."];
  return `<div class="guide"><b>So geht’s – ${esc(p.name)}</b><p class="small" style="margin:4px 0">${esc(p.info)}</p>
    <ol class="small">${steps.filter(Boolean).map((x) => `<li>${x}</li>`).join("")}</ol>
    ${p.cloud ? `<p class="small muted" style="margin:6px 0 0">☁ Der Text der Folgen geht zum Vertonen an ${esc(p.name)}. Kosten entstehen dort je nach Zeichen. Der Schlüssel bleibt auf deinem Rechner.</p>` : ""}</div>`;
}
const readTtsForm = (root) => Object.fromEntries([...root.querySelectorAll("[data-f]")].map((i) => [i.dataset.f, i.value]).filter(([k, v]) => k !== "api_key" || v));

SUB.tts = async (el) => {
  const t = await api("/api/tts");
  const presetOf = (s) => t.presets.find((p) => p.id === (s.preset || "custom")) || {};
  const cards = t.server.map((s) => `<div class="card stack" data-srv="${s.id}">
    <div class="row spread"><div><b>${esc(s.name)}</b> <span class="muted small">${esc(s.preset_name && s.preset !== "custom" ? s.preset_name : s.typ_name)}</span>
      ${s.cloud ? '<span class="chip" title="Der Text geht zum Vertonen an diesen Anbieter">☁ Cloud</span>' : ""}</div>${statusChip(s.status)}</div>
    <div class="small muted">${esc(s.base_url)}${s.modell ? ` · Modell ${esc(s.modell)}` : ""}${s.sprache || s.sprache_erkannt ? ` · Sprache ${esc(s.sprache || s.sprache_erkannt)}${s.sprache ? "" : " (vom Server)"}` : ""} · max. ${esc(s.max_zeichen)} Zeichen je Anfrage${s.geprueft_am ? ` · geprüft ${esc(s.geprueft_am)}` : ""}</div>
    ${s.last_error ? `<div class="err small">${esc(s.last_error)}</div>` : ""}
    <div class="row"><button class="ki" data-tverify="${s.id}">Prüfen &amp; Stimmen laden</button><button class="ghost" data-tedit="${s.id}">Bearbeiten</button>
      <button class="ghost" data-tarch="${s.id}">Archivieren</button></div>
    <div class="hidden stack" data-teditbox="${s.id}">${ttsServerForm(s, t.typen, presetOf(s))}<div class="row"><button class="primary" data-tsave="${s.id}">Speichern</button></div></div>
    ${s.stimmen_anzahl ? `<details><summary class="muted">${s.stimmen_anzahl} Stimmen – Hörprobe per ▶</summary>
      <div class="row small" style="margin:8px 0"><input data-tprobe-text placeholder="Probetext (leer = Standardsatz)"></div>
      <table>${s.stimmen.map((v) => `<tr><td>${esc(v.name)}</td><td class="small muted">${esc(v.sprache || "")}</td><td class="small muted">${esc(v.geschlecht || "")}</td>
        <td><button class="ghost" data-tplay="${esc(v.id)}">▶</button></td></tr>`).join("")}</table></details>` : ""}</div>`).join("");
  const pre = S.ttsPreset ? t.presets.find((p) => p.id === S.ttsPreset) : null;
  const newCard = pre
    ? `<div class="card stack" id="t-new"><div class="row spread"><h3 style="margin:0">Neu: ${esc(pre.name)}</h3><button class="ghost" id="t-back">← andere Auswahl</button></div>
        ${ttsGuide(pre)}${ttsServerForm(null, t.typen, pre)}
        ${pre.id === "custom" ? `<p class="small muted">${t.typen.map((x) => `<b>${esc(x.name)}:</b> ${esc(x.info)}`).join("<br>")}</p>` : ""}
        <div class="row"><button class="primary" id="t-add">Hinzufügen und prüfen</button></div></div>`
    : `<div class="card stack" id="t-new"><h3 style="margin:0">TTS-Anbieter hinzufügen</h3>
        <p class="small muted">Wähle einen Anbieter. Adresse und Einstellungen sind vorbereitet – bei Cloud-Anbietern brauchst du nur deinen Schlüssel.</p>
        <div class="provider-grid">${t.presets.map((p) => `<button class="preset" data-tpreset="${p.id}"><b>${esc(p.name)}</b><span class="small muted">${esc(p.info)}</span>
          <div class="small" style="margin-top:6px">${p.needs_key ? "🔑 Schlüssel nötig" : "Kein Schlüssel nötig"} · ${p.cloud ? "☁ Text geht an den Anbieter" : "🏠 bleibt bei dir"}</div></button>`).join("")}</div></div>`;
  el.innerHTML = `<div class="row spread"><h2>TTS-Server</h2></div>
    <p class="small muted">Eigene Sprach-Server für die Vertonung. Stimmen werden vom Server geladen; Besetzung und Modus (Hörspiel/Hörbuch)
      wählst du je Folge. Text wird in Stücke bis „max. Zeichen“ zerlegt und zu einer WAV-Datei zusammengefügt.
      Das Vorlesen im Browser und die macOS-Vertonung bleiben unverändert.</p>
    <div class="provider-grid">${cards || '<div class="muted small">Noch kein TTS-Server eingerichtet.</div>'}</div>
    ${newCard}
    ${t.archiv.length ? `<details><summary class="muted">Archiv (${t.archiv.length}) – entfernte Server, wiederherstellbar</summary>
      ${t.archiv.map((s) => `<div class="row spread card" style="margin-top:8px"><span>${esc(s.name)} <span class="muted small">${esc(s.base_url)} · archiviert ${esc(s.archiviert_am || "")}</span></span>
        <button class="ghost" data-trestore="${s.id}">Wiederherstellen</button></div>`).join("")}</details>` : ""}`;
  el.querySelectorAll("[data-tpreset]").forEach((b) => (b.onclick = () => { S.ttsPreset = b.dataset.tpreset; render(); }));
  if ($("#t-back")) $("#t-back").onclick = () => { S.ttsPreset = null; render(); };
  if ($("#t-add")) $("#t-add").onclick = () => guard(async () => {
    const r = await api("/api/tts/server", { method: "POST", body: readTtsForm($("#t-new")) });
    S.ttsPreset = null;
    const v = await api(`/api/tts/server/${r.id}/pruefen`, { method: "POST", body: {} });
    toast(v.ok ? `Verbunden – ${v.stimmen} Stimmen geladen.` : `${v.fehler} – „Bearbeiten“ zum Korrigieren.`, v.ok ? "ok" : "bad"); render();
  });
  el.querySelectorAll("[data-tverify]").forEach((b) => (b.onclick = () => guard(async () => {
    b.disabled = true; b.textContent = "prüfe …";
    const v = await api(`/api/tts/server/${b.dataset.tverify}/pruefen`, { method: "POST", body: {} });
    toast(v.ok ? `Verbunden – ${v.stimmen} Stimmen geladen.` : v.fehler, v.ok ? "ok" : "bad"); render();
  })));
  el.querySelectorAll("[data-tedit]").forEach((b) => (b.onclick = () => $(`[data-teditbox="${b.dataset.tedit}"]`).classList.toggle("hidden")));
  el.querySelectorAll("[data-tsave]").forEach((b) => (b.onclick = () => guard(async () => {
    await api(`/api/tts/server/${b.dataset.tsave}`, { method: "PUT", body: readTtsForm($(`[data-teditbox="${b.dataset.tsave}"]`)) });
    toast("Gespeichert.", "ok"); render();
  })));
  el.querySelectorAll("[data-tarch]").forEach((b) => (b.onclick = () => guard(async () => {
    await api(`/api/tts/server/${b.dataset.tarch}/archivieren`, { method: "POST", body: {} }); render();
  })));
  el.querySelectorAll("[data-trestore]").forEach((b) => (b.onclick = () => guard(async () => {
    await api(`/api/tts/server/${b.dataset.trestore}/wiederherstellen`, { method: "POST", body: {} }); render();
  })));
  el.querySelectorAll("[data-tplay]").forEach((b) => (b.onclick = () => {
    const card = b.closest("[data-srv]");
    const text = ($("[data-tprobe-text]", card) || {}).value || "";
    b.textContent = "…";
    const a = new Audio(`/api/tts/server/${card.dataset.srv}/probe?stimme=${encodeURIComponent(b.dataset.tplay)}&text=${encodeURIComponent(text)}`);
    a.onplaying = () => (b.textContent = "▶");
    a.onerror = () => { b.textContent = "▶"; toast("Hörprobe fehlgeschlagen – Server prüfen.", "bad"); };
    a.play().catch(() => {});
  }));
};

// Stimmen gruppiert nach Server und Sprache; Deutsch (bzw. die Sprache der gewählten Stimme) zuerst.
function voiceOptions(t, selected, emptyLabel) {
  const selLang = (() => { for (const s of t.server) for (const v of s.stimmen || []) if (`${s.id}|${v.id}` === selected) return v.sprache; return null; })();
  const first = selLang || "de";
  const groups = t.server.filter((s) => (s.stimmen || []).length).flatMap((s) => {
    const byLang = {};
    s.stimmen.forEach((v) => { const l = v.sprache || s.sprache || s.sprache_erkannt || ""; (byLang[l] = byLang[l] || []).push(v); });
    return Object.keys(byLang).sort((a, b) => (b === first) - (a === first) || a.localeCompare(b)).map((l) =>
      `<optgroup label="${esc(s.name)}${l ? ` · ${esc(l)}` : ""}">${byLang[l].map((v) => {
        const ref = `${s.id}|${v.id}`;
        return `<option value="${esc(ref)}" ${ref === selected ? "selected" : ""}>${esc(voiceLabel(v))}</option>`;
      }).join("")}</optgroup>`);
  }).join("");
  return `${emptyLabel !== null ? `<option value="">${esc(emptyLabel)}</option>` : ""}${groups}`;
}

async function ttsCard(id) {
  const box = $("#rd-tts");
  if (!box) return;
  const [t, st] = await Promise.all([api("/api/tts"), api(W(`/episodes/${id}/tts`))]);
  if (!t.server.length) {
    box.innerHTML = `<div class="card row spread"><span class="small muted">Vertonung über eigene TTS-Server: noch kein Server eingerichtet.</span>
      <button class="ghost" id="tts-setup">TTS-Server einrichten</button></div>`;
    $("#tts-setup").onclick = () => openSettings("tts");
    return;
  }
  const ready = t.server.some((s) => (s.stimmen || []).length);
  const names = Object.keys(st.sprecher);
  const autoName = (n) => st.sprecher[n] && st.sprecher[n].stimme ? `automatisch (${st.sprecher[n].stimme_name || st.sprecher[n].stimme})` : "automatisch";
  const narratorRef = st.besetzung["Erzähler"] || "";
  const ttsExt = (st.datei || "").endsWith(".mp3") ? "mp3" : "wav";
  box.innerHTML = `<div class="card stack"><div class="row spread"><h3 style="margin:0">Vertonung über TTS-Server</h3>
      <div class="row"><label class="small muted" style="margin:0">Modus</label><select id="tts-mode">${Object.entries(st.modi).map(([k, l]) =>
        `<option value="${k}" ${k === st.modus ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></div></div>
    ${ready ? "" : '<div class="small err">Noch keine Stimmen geladen – Einstellungen → TTS-Server → „Prüfen &amp; Stimmen laden“.</div>'}
    ${st.modus === "hoerbuch"
      ? `<div class="row"><div class="field" style="flex:1"><label>Sprecher:in für die ganze Folge</label>
          <select id="tts-single">${voiceOptions(t, st.einstellung.stimme || narratorRef, narratorRef ? "wie Erzähler-Stimme" : "— bitte wählen —")}</select></div></div>`
      : `<table class="small">${names.map((n) => {
          const isNarr = n === "Erzähler";
          return `<tr><td><b>${esc(n)}</b></td><td><select data-cast="${esc(n)}">${voiceOptions(t, st.besetzung[n] || "", isNarr ? "— bitte wählen —" : autoName(n))}</select></td>
            <td class="muted">${st.sprecher[n].quelle === "automatisch" ? "reihum vom Server der Erzähler-Stimme" : ""}</td></tr>`; }).join("")}</table>
        <div class="small muted">Die Besetzung gilt für alle Folgen dieser Welt; Figuren ohne Wahl bekommen reihum eine freie Stimme derselben Sprache.</div>`}
    ${st.fehlt.length ? `<div class="small err">Ohne Stimme: ${esc(st.fehlt.join(", "))}</div>` : ""}
    <div class="row">${st.datei ? `<audio controls preload="none" src="${W(`/episodes/${id}/tts.${ttsExt}`)}" style="height:36px"></audio>
        <a class="small" href="${W(`/episodes/${id}/tts.${ttsExt}?download=1`)}">${ttsExt.toUpperCase()} herunterladen</a>` : ""}
      <button class="ki" id="tts-render" ${st.fehlt.length ? "disabled" : ""}>${st.datei ? "Neu vertonen" : "🎙 Mit TTS-Server vertonen"}</button>
      ${st.erstellt ? `<span class="small muted">zuletzt ${esc(st.erstellt)} · ${esc(st.datei)}</span>` : ""}</div></div>`;
  const save = (body) => guard(async () => { await api(W(`/episodes/${id}/tts`), { method: "PUT", body }); ttsCard(id); });
  $("#tts-mode").onchange = (e) => save({ modus: e.target.value });
  if ($("#tts-single")) $("#tts-single").onchange = (e) => save({ stimme: e.target.value });
  box.querySelectorAll("[data-cast]").forEach((sel) => (sel.onchange = () => save({ besetzung: { [sel.dataset.cast]: sel.value } })));
  $("#tts-render").onclick = () => guard(async () => {
    await api(W(`/episodes/${id}/tts/vertonen`), { method: "POST", body: {} });
    toast("Vertonung über TTS-Server läuft – Fortschritt oben rechts."); pollJobs();
  });
}

// ------------------------------------------------------------ Tabellen: Sortieren (Klick auf Spaltenkopf) & Filtern

const TBL = {};          // Zustand je Tabelle (Ansicht + Spaltenköpfe): Sortierspalte, Richtung, Filtertext
let tblFocus = null;     // Filterfeld, das beim Neuzeichnen den Fokus behalten soll

function tblCompare(a, b, col, dir) {
  const ta = (a.cells[col] ? a.cells[col].textContent : "").trim(), tb = (b.cells[col] ? b.cells[col].textContent : "").trim();
  if (!ta || !tb) return ta ? -1 : tb ? 1 : 0;  // Leere immer ans Ende
  const na = Number(ta.replace(",", ".")), nb = Number(tb.replace(",", "."));
  const r = !isNaN(na) && !isNaN(nb) ? na - nb : ta.localeCompare(tb, "de", { numeric: true, sensitivity: "base" });
  return r * dir;
}

function enhanceTable(t) {
  const head = t.rows[0];
  t.dataset.enh = "1";
  if (!head || !head.cells.length || [...head.cells].some((c) => c.tagName !== "TH") || t.querySelector("td[colspan]")) return;
  const rows = [...t.rows].slice(1);
  if (rows.length < 2) return;
  const key = `${S.view}|${S.entity}|${[...head.cells].map((c) => c.textContent.trim()).join("|")}`;
  const st = (TBL[key] = TBL[key] || { col: -1, dir: 1, q: "" });
  rows.forEach((r, i) => (r.dataset.ord = i));
  const body = head.parentNode;
  let info = null;
  const apply = () => {
    const order = [...rows].sort(st.col >= 0 ? (a, b) => tblCompare(a, b, st.col, st.dir) : (a, b) => a.dataset.ord - b.dataset.ord);
    order.forEach((r) => body.appendChild(r));
    const q = st.q.trim().toLowerCase();
    let shown = 0;
    rows.forEach((r) => { const hit = !q || r.textContent.toLowerCase().includes(q); r.style.display = hit ? "" : "none"; shown += hit ? 1 : 0; });
    [...head.cells].forEach((c, i) => { c.classList.toggle("sort-asc", i === st.col && st.dir === 1); c.classList.toggle("sort-desc", i === st.col && st.dir === -1); });
    if (info) info.textContent = q ? `${shown} von ${rows.length}` : "";
  };
  [...head.cells].forEach((c, i) => {
    if (!c.textContent.trim()) return;
    c.classList.add("sortable");
    c.title = "Klicken: sortieren (auf-, absteigend, aus)";
    c.onclick = () => { if (st.col !== i) { st.col = i; st.dir = 1; } else if (st.dir === 1) st.dir = -1; else st.col = -1; apply(); };
  });
  if (rows.length >= 5 || st.q || t.classList.contains("liste")) {  // Bereichslisten immer, sonst ab 5 Zeilen
    const bar = document.createElement("div");
    bar.className = "tfilter";
    bar.innerHTML = `<input type="search" placeholder="Filtern …" value="${esc(st.q)}"><span class="small muted"></span>`;
    t.parentNode.insertBefore(bar, t);
    info = bar.querySelector("span");
    const inp = bar.querySelector("input");
    inp.oninput = () => { st.q = inp.value; apply(); };
    inp.onfocus = () => (tblFocus = key);
    inp.onblur = () => { if (document.contains(inp)) tblFocus = null; };
    if (tblFocus === key) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
  }
  if (st.col >= 0 || st.q) apply();
}

let tblFrame = null;
new MutationObserver(() => {
  if (tblFrame) return;
  tblFrame = requestAnimationFrame(() => { tblFrame = null; document.querySelectorAll("#view table:not([data-enh])").forEach(enhanceTable); });
}).observe($("#view"), { childList: true, subtree: true });

// ------------------------------------------------------------ Beziehungsnetz (Figuren, Familie & Beziehungen)
// Familien (über Familien-Beziehungen verbunden) liegen jeweils in einem eigenen Kreis; alle übrigen Beziehungen
// verbinden die Bubbles quer. Pfeil = Leserichtung „A ist … von B“. Klick auf Bubble öffnet die Figur, Klick auf eine
// Linie die Beziehung. Ziehen verschiebt Bubbles bzw. die Ansicht, Mausrad zoomt.

const NETZ_BEREICHE = new Set(["characters", "character_relations"]);
const FAMILIE = new Set(["elternteil", "kind", "partner", "geschwister", "grosselternteil", "enkel", "verwandt"]);
const VOLK_FARBEN = ["#4e79a7", "#e8862a", "#59a14f", "#b07aa1", "#3f9f9a", "#c9a227", "#e0607e", "#9c755f", "#6b6ecf", "#7f8c2d"];
const NETZ = { opt: { familie: true, andere: true, gebrochen: true, einzeln: true }, view: null, nodes: null };
const netzAn = () => load(`sw-netz-${S.entity}`) === "1";
const netzSetzen = (on) => store(`sw-netz-${S.entity}`, on ? "1" : "0");

function netzLayout(nodes, edges) {
  const byId = new Map(nodes.map((d) => [d.id, d]));
  // Familiengruppen: Zusammenhangskomponenten über Familien-Kanten
  const parent = new Map(nodes.map((d) => [d.id, d.id]));
  const find = (x) => (parent.get(x) === x ? x : (parent.set(x, find(parent.get(x))), parent.get(x)));
  edges.filter((e) => e.familie && !e.gebrochen).forEach((e) => parent.set(find(e.von), find(e.zu)));
  const groups = new Map();
  nodes.forEach((d) => { const g = find(d.id); if (!groups.has(g)) groups.set(g, []); groups.get(g).push(d); });
  const list = [...groups.values()].sort((a, b) => b.length - a.length || a[0].label.localeCompare(b[0].label, "de"));
  list.forEach((members, gi) => {
    const ang = gi * 2.39996, rad = 170 * Math.sqrt(gi), cx = Math.cos(ang) * rad, cy = Math.sin(ang) * rad;
    members.forEach((d, i) => {
      const a = (i / members.length) * Math.PI * 2, r = members.length > 1 ? 50 * Math.sqrt(members.length) : 0;
      d.x = cx + Math.cos(a) * r; d.y = cy + Math.sin(a) * r; d.vx = d.vy = 0; d.g = gi;
    });
  });
  const R = 40;
  for (let it = 0; it < 350; it++) {
    const cool = 1 - it / 400;
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      let dx = b.x - a.x, dy = b.y - a.y, d2 = dx * dx + dy * dy || 0.01;
      const f = (a.g === b.g ? 26000 : 18000) / d2, d = Math.sqrt(d2);
      dx /= d; dy /= d; a.vx -= dx * f; a.vy -= dy * f; b.vx += dx * f; b.vy += dy * f;
    }
    edges.forEach((e) => {
      const a = byId.get(e.von), b = byId.get(e.zu);
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const len = e.familie ? 175 : 280, k = e.familie ? 0.05 : 0.012, f = (d - len) * k;
      a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
    });
    list.forEach((m) => {
      if (m.length < 2) return;
      const cx = m.reduce((s, d) => s + d.x, 0) / m.length, cy = m.reduce((s, d) => s + d.y, 0) / m.length;
      m.forEach((d) => { d.vx += (cx - d.x) * 0.02; d.vy += (cy - d.y) * 0.02; });
    });
    nodes.forEach((d) => {
      d.vx -= d.x * 0.004; d.vy -= d.y * 0.004;
      const sp = Math.hypot(d.vx, d.vy), max = 30 * cool + 2;
      if (sp > max) { d.vx *= max / sp; d.vy *= max / sp; }
      d.x += d.vx; d.y += d.vy; d.vx *= 0.55; d.vy *= 0.55;
    });
    netzKollision(nodes, 2 * R + 70);  // Platz für Beschriftungen zwischen den Bubbles
  }
  // Kreise (Familien und Einzelne) dürfen sich nicht überlappen
  const circ = () => list.map((m) => {
    const cx = m.reduce((s, d) => s + d.x, 0) / m.length, cy = m.reduce((s, d) => s + d.y, 0) / m.length;
    return { m, cx, cy, r: Math.max(...m.map((d) => Math.hypot(d.x - cx, d.y - cy))) + R + (m.length > 1 ? 22 : 8) };
  });
  for (let it = 0; it < 80; it++) {
    const cs = circ();
    let moved = false;
    for (let i = 0; i < cs.length; i++) for (let j = i + 1; j < cs.length; j++) {
      const a = cs[i], b = cs[j];
      let dx = b.cx - a.cx, dy = b.cy - a.cy, d = Math.hypot(dx, dy) || 0.01;
      const over = a.r + b.r + 40 - d;
      if (over <= 0) continue;
      moved = true; dx /= d; dy /= d;
      const wa = b.m.length / (a.m.length + b.m.length), wb = 1 - wa;
      a.m.forEach((n) => { n.x -= dx * over * wa; n.y -= dy * over * wa; });
      b.m.forEach((n) => { n.x += dx * over * wb; n.y += dy * over * wb; });
      a.cx -= dx * over * wa; a.cy -= dy * over * wa; b.cx += dx * over * wb; b.cy += dy * over * wb;
    }
    if (!moved) break;
  }
  return list;
}

function netzKollision(nodes, min) {
  for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
    const a = nodes[i], b = nodes[j];
    let dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy);
    if (d >= min) continue;
    if (d < 0.01) { dx = 1; dy = 0; d = 1; }
    const push = (min - d) / 2;
    a.x -= (dx / d) * push; a.y -= (dy / d) * push; b.x += (dx / d) * push; b.y += (dy / d) * push;
  }
}

function familienName(members) {
  const count = {};
  members.forEach((d) => { if (d.nachname) count[d.nachname] = (count[d.nachname] || 0) + 1; });
  const best = Object.entries(count).sort((a, b) => b[1] - a[1])[0];
  return best ? `Familie ${best[0]}` : "Familie";
}

async function netzView(main) {
  const [{ rows: figuren }, { rows: bez }, volk] = await Promise.all([api(W("/rows/characters")), api(W("/rows/character_relations")),
    api(W("/rows/peoples"))]);
  const farbe = {};
  volk.rows.forEach((v, i) => (farbe[v.id] = VOLK_FARBEN[i % VOLK_FARBEN.length]));
  const label = S.cfg.entities[S.entity].label;
  main.innerHTML = `<div class="row spread"><h2>${esc(label)} <span class="muted small">· Netz</span></h2><div class="row">
      <button class="ghost" id="n-liste">☰ Liste</button><button class="primary" id="n-new">+ Beziehung</button></div></div>
    <div class="netz-bar small">
      <label><input type="checkbox" data-o="familie" ${NETZ.opt.familie ? "checked" : ""}> Familie</label>
      <label><input type="checkbox" data-o="andere" ${NETZ.opt.andere ? "checked" : ""}> weitere Beziehungen</label>
      <label><input type="checkbox" data-o="gebrochen" ${NETZ.opt.gebrochen ? "checked" : ""}> gebrochene</label>
      <label><input type="checkbox" data-o="einzeln" ${NETZ.opt.einzeln ? "checked" : ""}> Figuren ohne Verbindung</label>
      <input type="search" id="n-such" placeholder="Figur hervorheben …" style="max-width:200px">
      <button class="ghost small" id="n-fit">Einpassen</button></div>
    <div class="netz-wrap" id="n-wrap"><svg id="n-svg" class="netz"><defs>
      <marker id="n-pfeil" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="n-pfeil"/></marker>
      </defs><g id="n-root"></g></svg></div>
    <div class="netz-legende small">${volk.rows.map((v) => `<span><i style="border-color:${farbe[v.id]}"></i>${esc(v.name)}</span>`).join("")}
      <span><i class="n-ohne"></i>ohne Volk</span><span class="n-l fam"></span>Familie<span class="n-l rel"></span>Beziehung<span class="n-l bruch"></span>gebrochen
      <span class="muted">· Pfeil: „A ist … von B“ · Ziehen verschiebt · Mausrad zoomt · Klick öffnet</span></div>`;
  $("#n-liste").onclick = () => { netzSetzen(false); S.netzFokus = null; render(); };
  $("#n-new").onclick = () => editDialog("character_relations", null);
  main.querySelectorAll("[data-o]").forEach((c) => (c.onchange = () => { NETZ.opt[c.dataset.o] = c.checked; zeichnen(true); }));

  const svg = $("#n-svg"), root = $("#n-root");
  let nodes = [], edges = [], groups = [], view = NETZ.view || { x: 0, y: 0, k: 1 }, fokus = S.netzFokus, such = "";

  function aufbauen() {
    const id2 = new Map(figuren.map((f) => [f.id, f]));
    edges = bez.filter((b) => id2.has(b.character_id) && id2.has(b.other_id)).map((b) => ({
      id: b.id, von: b.character_id, zu: b.other_id, art: b.kind, familie: FAMILIE.has(b.kind), gebrochen: b.ended_world_time != null,
      grund: b.reason || "", seit: b.since_world_time, bruch: b.ended_world_time, bruchGrund: b.break_reason || "" }))
      .filter((e) => (e.gebrochen ? NETZ.opt.gebrochen : true) && (e.familie ? NETZ.opt.familie : NETZ.opt.andere));
    const verbunden = new Set(edges.flatMap((e) => [e.von, e.zu]));
    nodes = figuren.filter((f) => NETZ.opt.einzeln || verbunden.has(f.id) || f.id === fokus).map((f) => ({
      id: f.id, vorname: f.first_name || (!f.last_name ? f.name : ""), nachname: f.last_name || "", label: personName(f),
      rolle: f.role || "", volk: f.people_id__name || "", farbe: f.people_id ? farbe[f.people_id] : null, geschlecht: f.gender || "" }));
    const ids = new Set(nodes.map((d) => d.id));
    edges = edges.filter((e) => ids.has(e.von) && ids.has(e.zu));
    groups = netzLayout(nodes, edges);
  }

  const R = 40, byId = () => new Map(nodes.map((d) => [d.id, d]));
  const cut = (t, n = 13) => (t.length > n ? t.slice(0, n - 1) + "…" : t);
  function zeichnen(neu) {
    if (neu) aufbauen();
    const m = byId(), out = [];
    groups.filter((g) => g.length > 1).forEach((g) => {
      const cx = g.reduce((s, d) => s + d.x, 0) / g.length, cy = g.reduce((s, d) => s + d.y, 0) / g.length;
      const r = Math.max(...g.map((d) => Math.hypot(d.x - cx, d.y - cy))) + R + 22;
      out.push(`<g class="n-fam"><circle cx="${cx}" cy="${cy}" r="${r}"/><text x="${cx}" y="${cy - r + 16}" text-anchor="middle">${esc(familienName(g))}</text></g>`);
    });
    const paar = {};
    edges.forEach((e) => {
      const a = m.get(e.von), b = m.get(e.zu), key = [e.von, e.zu].sort().join("-"), n = (paar[key] = (paar[key] || 0) + 1) - 1;
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1, ux = dx / d, uy = dy / d;
      const off = n * 18 * (n % 2 ? 1 : -1), nx = -uy * off, ny = ux * off;
      const x1 = a.x + ux * R + nx, y1 = a.y + uy * R + ny, x2 = b.x - ux * (R + 3) + nx, y2 = b.y - uy * (R + 3) + ny;
      const tip = `${a.label} ist ${REL_LABEL[e.art] || e.art} von ${b.label}` + (e.grund ? `\nGrund: ${e.grund}` : "")
        + (e.seit != null ? `\nSeit: ${e.seit}` : "") + (e.gebrochen ? `\nGebrochen seit ${e.bruch}${e.bruchGrund ? `: ${e.bruchGrund}` : ""}` : "");
      out.push(`<g class="n-e ${e.familie ? "fam" : "rel"} ${e.gebrochen ? "bruch" : ""}" data-e="${e.id}" data-a="${e.von}" data-b="${e.zu}"><title>${esc(tip)}</title>
        <line class="hit" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/><line class="ln" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" marker-end="url(#n-pfeil)"/>
        <text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 4}" text-anchor="middle">${esc(REL_LABEL[e.art] || e.art)}${e.gebrochen ? " ✕" : ""}</text></g>`);
    });
    nodes.forEach((d) => {
      const tip = `${d.label}${d.rolle ? ` – ${d.rolle}` : ""}${d.volk ? `\nVolk: ${d.volk}` : ""}${d.geschlecht ? `\n${d.geschlecht}` : ""}`;
      const style = d.farbe ? `style="--vf:${d.farbe}"` : "";
      out.push(`<g class="n-n ${d.id === fokus ? "fokus" : ""}" data-n="${d.id}" transform="translate(${d.x},${d.y})" ${style}><title>${esc(tip)}</title>
        <circle r="${R}"/><text y="${d.nachname ? -3 : 4}" text-anchor="middle" class="vn">${esc(cut(d.vorname))}</text>
        ${d.nachname ? `<text y="13" text-anchor="middle" class="nn">${esc(cut(d.nachname))}</text>` : ""}</g>`);
    });
    root.innerHTML = out.join("") || "";
    if (!nodes.length) root.innerHTML = `<text x="0" y="0" text-anchor="middle" class="n-leer">Noch keine Figuren${figuren.length ? " mit diesen Filtern" : ""}.</text>`;
    markieren();
    setView();
  }

  const setView = () => root.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);
  function einpassen() {
    const w = svg.clientWidth || 800, h = svg.clientHeight || 600;
    if (!nodes.length) { view = { x: w / 2, y: h / 2, k: 1 }; return setView(); }
    const pad = 90, xs = nodes.map((d) => d.x), ys = nodes.map((d) => d.y);
    const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
    const k = Math.min(1.4, w / (x1 - x0), h / (y1 - y0));
    view = { k, x: w / 2 - ((x0 + x1) / 2) * k, y: h / 2 - ((y0 + y1) / 2) * k };
    const f = fokus && byId().get(fokus);
    if (f) { view.k = Math.max(k, 0.9); view.x = w / 2 - f.x * view.k; view.y = h / 2 - f.y * view.k; }
    setView();
  }
  function markieren(hover) {
    const q = such.trim().toLowerCase();
    const treffer = new Set(nodes.filter((d) => q && d.label.toLowerCase().includes(q)).map((d) => d.id));
    const aktiv = hover != null ? new Set([hover]) : treffer.size ? treffer : fokus && byId().has(fokus) ? new Set([fokus]) : null;
    svg.classList.toggle("dim", !!aktiv);
    if (!aktiv) { root.querySelectorAll(".hi").forEach((x) => x.classList.remove("hi")); return; }
    const nb = new Set(aktiv);
    root.querySelectorAll(".n-e").forEach((g) => {
      const on = aktiv.has(+g.dataset.a) || aktiv.has(+g.dataset.b);
      g.classList.toggle("hi", on);
      if (on) { nb.add(+g.dataset.a); nb.add(+g.dataset.b); }
    });
    root.querySelectorAll(".n-n").forEach((g) => g.classList.toggle("hi", nb.has(+g.dataset.n)));
  }

  // Ziehen, Zoomen, Klicken
  let drag = null;
  const pt = (ev) => { const r = svg.getBoundingClientRect(); return { x: ev.clientX - r.left, y: ev.clientY - r.top }; };
  svg.onpointerdown = (ev) => {
    const n = ev.target.closest(".n-n"), e = ev.target.closest(".n-e"), p = pt(ev);
    drag = { node: n ? byId().get(+n.dataset.n) : null, edge: e ? +e.dataset.e : null, sx: p.x, sy: p.y, vx: view.x, vy: view.y, moved: false };
    svg.setPointerCapture(ev.pointerId);
  };
  svg.onpointermove = (ev) => {
    if (!drag) {
      const n = ev.target.closest && ev.target.closest(".n-n");
      if (!such.trim()) markieren(n ? +n.dataset.n : null);
      return;
    }
    const p = pt(ev), dx = p.x - drag.sx, dy = p.y - drag.sy;
    if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
    if (!drag.moved) return;
    if (drag.node) {
      drag.node.x += dx / view.k; drag.node.y += dy / view.k; drag.sx = p.x; drag.sy = p.y;
      zeichnen(false);
    } else { view.x = drag.vx + dx; view.y = drag.vy + dy; setView(); }
  };
  svg.onpointerup = () => {
    const d = drag; drag = null;
    NETZ.view = { ...view };
    if (!d || d.moved) return;
    if (d.node) openItem("characters", d.node.id);
    else if (d.edge) editDialog("character_relations", d.edge);
  };
  svg.onpointerleave = () => { if (!drag && !such.trim()) markieren(null); };
  svg.onwheel = (ev) => {
    ev.preventDefault();
    const p = pt(ev), k = Math.min(3, Math.max(0.15, view.k * (ev.deltaY < 0 ? 1.12 : 1 / 1.12)));
    view.x = p.x - ((p.x - view.x) / view.k) * k; view.y = p.y - ((p.y - view.y) / view.k) * k; view.k = k;
    NETZ.view = { ...view }; setView();
  };
  $("#n-such").oninput = (ev) => { such = ev.target.value; markieren(); };
  $("#n-fit").onclick = () => { fokus = S.netzFokus = null; einpassen(); NETZ.view = { ...view }; zeichnen(false); };
  zeichnen(true);
  if (!NETZ.view || fokus) einpassen();
  NETZ.view = { ...view };
}
