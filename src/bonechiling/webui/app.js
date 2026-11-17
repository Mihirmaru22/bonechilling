// BoneChilling SPA — vanilla JS, no build step. Talks to the local FastAPI
// backend. The per-launch token arrives as ?token= (injected by the desktop
// shell); we keep it in memory and send it on every request.

const params = new URLSearchParams(location.search);
let TOKEN = params.get("token") || sessionStorage.getItem("bc_token") || "";
if (TOKEN) sessionStorage.setItem("bc_token", TOKEN);

const app = document.getElementById("app");
const conn = document.getElementById("conn");
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---- API client ---------------------------------------------------------- //
async function api(path, opts = {}) {
  const headers = { "X-API-Token": TOKEN, ...(opts.headers || {}) };
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
  }
  const r = await fetch(path, { ...opts, headers });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch {}
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.status === 204 ? null : r.json();
}

// ---- helpers ------------------------------------------------------------- //
const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const $ = (sel, root = document) => root.querySelector(sel);
const pad2 = (n) => String(n).padStart(2, "0");

function safeJson(s, fallback = []) {
  if (s && typeof s === "object") return s;
  try { const v = JSON.parse(s); return v ?? fallback; } catch { return fallback; }
}

// Inline stroke icons so the app works fully offline.
const ICONS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  download: '<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/>',
  arrow: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
  back: '<path d="M19 12H5"/><path d="m11 6-6 6 6 6"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6C3.8 8.4 2 12 2 12s3.5 7 10 7a9.6 9.6 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  open: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 11v5M9.5 13.5 12 11l2.5 2.5"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  prev: '<path d="m15 6-6 6 6 6"/>',
};
const icon = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ""}</svg>`;

function toast(msg, kind = "") {
  const t = el(`<div class="toast ${kind}" role="status">${esc(msg)}</div>`);
  document.getElementById("toasts").appendChild(t);
  setTimeout(() => t.remove(), 3800);
}

const statusBadge = (s) =>
  s === "verified" ? `<span class="badge ok">Verified</span>` : `<span class="badge warn">Awaiting review</span>`;

const errorBlock = (msg) => `<div class="empty err"><div class="big">Couldn’t load this</div><p>${esc(msg)}</p></div>`;

function pageHead({ title, subtitle = "", actions = "" }) {
  return `<header class="page-head"><div><h1>${title}</h1>${subtitle ? `<p>${subtitle}</p>` : ""}</div>
    ${actions ? `<div class="actions">${actions}</div>` : ""}</header>`;
}

// Numbers tick up once on arrival (tabular figures keep the width steady).
function countUp(node, to) {
  if (REDUCED || to < 2) { node.textContent = to; return; }
  const t0 = performance.now(), dur = 520;
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    node.textContent = Math.round(to * e);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

const filmSrc = (id, size = 640) => `/images/${id}/view?size=${size}&token=${encodeURIComponent(TOKEN)}`;

// Full-screen film viewer: the lightbox. Arrows move between films, Esc closes.
function openViewer(list, start, onReveal) {
  let i = start;
  const prev = document.activeElement;
  const v = el(`<div class="viewer" role="dialog" aria-modal="true" aria-label="Film viewer">
    <div class="viewer-bar"><span class="viewer-cap" id="vCap"></span>
      <button class="btn secondary sm" id="vReveal">${icon("open")} Show in folder</button>
      <button class="vbtn" id="vClose" aria-label="Close">${icon("close")}</button></div>
    <div class="viewer-stage"><button class="vbtn vnav" id="vPrev" aria-label="Previous film">${icon("prev")}</button>
      <img id="vImg" alt="" /><button class="vbtn vnav" id="vNext" aria-label="Next film">${icon("chevron")}</button></div>
  </div>`);
  const img = v.querySelector("#vImg");
  const show = () => {
    const f = list[i];
    img.src = filmSrc(f.id, 2000); img.alt = `X-ray: ${f.title}`;
    img.onerror = () => { img.alt = "Image file not found on this PC"; };
    v.querySelector("#vCap").innerHTML = `<b>${esc(f.title)}</b> <span class="mono">${esc(f.file)}</span> <span class="muted">${i + 1} / ${list.length}</span>`;
    v.querySelector("#vPrev").style.visibility = v.querySelector("#vNext").style.visibility = list.length > 1 ? "" : "hidden";
  };
  const close = () => { v.remove(); document.removeEventListener("keydown", key); prev && prev.focus && prev.focus(); };
  const step = (d) => { i = (i + d + list.length) % list.length; show(); };
  const key = (e) => { if (e.key === "Escape") close(); if (e.key === "ArrowRight") step(1); if (e.key === "ArrowLeft") step(-1); };
  v.querySelector("#vClose").onclick = close;
  v.querySelector("#vPrev").onclick = () => step(-1);
  v.querySelector("#vNext").onclick = () => step(1);
  v.querySelector("#vReveal").onclick = () => onReveal(list[i].id);
  v.addEventListener("click", (e) => { if (e.target.classList.contains("viewer-stage")) close(); });
  img.onclick = () => img.classList.toggle("zoom");
  document.addEventListener("keydown", key);
  document.body.appendChild(v);
  show();
  v.querySelector("#vClose").focus();
}

// Confirmation dialog (keyboard: Esc cancels, Enter confirms).
function confirmDialog({ title, body, confirm = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    const prev = document.activeElement;
    const m = el(`<div class="modal-back" role="presentation"><div class="modal" role="alertdialog" aria-modal="true" aria-labelledby="mTitle">
      <h3 id="mTitle">${title}</h3><div class="modal-body">${body}</div>
      <div class="btn-row"><button class="btn secondary" data-a="no">Cancel</button><button class="btn ${danger ? "danger" : ""}" data-a="yes">${confirm}</button></div>
    </div></div>`);
    const done = (v) => { m.remove(); document.removeEventListener("keydown", key); prev && prev.focus && prev.focus(); resolve(v); };
    const key = (e) => { if (e.key === "Escape") done(false); };
    m.addEventListener("click", (e) => { const a = e.target.closest("[data-a]"); if (a) done(a.dataset.a === "yes"); else if (e.target === m) done(false); });
    document.addEventListener("keydown", key);
    document.body.appendChild(m);
    m.querySelector('[data-a="no"]').focus();
  });
}

// Stream a job's events; calls onEvent for each and onEnd(status) once.
function watchJob(jobId, { onEvent = () => {}, onEnd = () => {} } = {}) {
  const ws = new WebSocket(`${location.origin.replace("http", "ws")}/ws/jobs/${jobId}?token=${encodeURIComponent(TOKEN)}`);
  let ended = false;
  ws.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.kind === "job_end") { ended = true; ws.close(); onEnd(ev.status); } else onEvent(ev);
  };
  ws.onclose = () => { if (!ended) { ended = true; onEnd("disconnected"); } };
  return ws;
}

// ---- connection indicator ------------------------------------------------ //
async function checkConn() {
  const text = conn.querySelector(".conn-text");
  try {
    const h = await fetch("/health").then((r) => r.json());
    text.textContent = TOKEN ? `Connected · v${h.version}` : "No token — open via the app";
    conn.className = "conn " + (TOKEN ? "ok" : "err");
  } catch {
    text.textContent = "Backend offline";
    conn.className = "conn err";
  }
}

// ---- router (continuous transitions between views) ----------------------- //
const views = {};
let ingestRunning = false;
async function render(name, arg) {
  const navName = name === "patient" ? "worklist" : name;
  document.querySelectorAll("#nav button").forEach((b) => {
    const on = b.dataset.view === navName;
    b.classList.toggle("active", on);
    if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  app.innerHTML = "";
  window.scrollTo(0, 0);
  await (views[name] || views.worklist)(arg);
}
function navigate(name, arg) {
  if (document.startViewTransition && !REDUCED) {
    document.startViewTransition(() => render(name, arg));
  } else {
    render(name, arg).then(() => app.firstElementChild && app.firstElementChild.classList.add("view-enter"));
  }
}
document.getElementById("nav").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-view]");
  if (b) navigate(b.dataset.view);
});

// ---- Worklist ------------------------------------------------------------ //
const wlState = { q: "", filter: "all" };

views.worklist = async () => {
  app.appendChild(el(`<div>
    ${pageHead({
      title: "Worklist",
      subtitle: "Every analyzed patient folder. Open a patient to check what the AI read from each film, then sign it off.",
      actions: `<button class="btn secondary" id="xlsx">${icon("download")} Export to Excel</button>
                <button class="btn" id="goIngest">Analyze new folders ${icon("arrow")}</button>`,
    })}
    <div id="wlbody"><div class="loading">Loading patients…</div></div>
  </div>`));
  $("#xlsx").onclick = downloadExcel;
  $("#goIngest").onclick = () => navigate("ingest");

  let patients;
  try { patients = await api("/patients"); }
  catch (e) { $("#wlbody").innerHTML = errorBlock(e.message); return; }

  const total = patients.length;
  const films = patients.reduce((n, p) => n + (p.image_count || 0), 0);
  const verified = patients.filter((p) => p.review_status === "verified").length;
  const pending = total - verified;
  const pct = total ? Math.round((verified / total) * 100) : 0;
  const body = $("#wlbody");

  if (!total) {
    body.innerHTML = `<div class="empty"><div class="big">The lightbox is empty.</div>
      <p>Point BoneChilling at a folder of X-ray images. Each sub-folder is treated as one patient and every film in it is read automatically.</p>
      <button class="btn" id="emptyGo">Analyze your first folder ${icon("arrow")}</button></div>`;
    $("#emptyGo").onclick = () => navigate("ingest");
    return;
  }

  body.innerHTML = `
    <section class="facts-strip" aria-label="Summary">
      <div class="fact"><div class="val" data-n="${total}">0</div><div class="lbl">Patients</div></div>
      <div class="fact"><div class="val" data-n="${films}">0</div><div class="lbl">Films read</div></div>
      <div class="fact"><div class="val" data-n="${verified}">0</div><div class="lbl">Signed off · ${pct}%</div><div class="bar"><div id="vbar"></div></div></div>
      <div class="fact ${pending ? "warn" : ""}"><div class="val" data-n="${pending}">0</div><div class="lbl">Awaiting review</div></div>
    </section>
    <div class="toolbar">
      <div class="tabs" id="tabs" role="tablist">
        <button data-f="all" role="tab">All<span class="n">${total}</span></button>
        <button data-f="unreviewed" role="tab">Awaiting review<span class="n">${pending}</span></button>
        <button data-f="verified" role="tab">Verified<span class="n">${verified}</span></button>
      </div>
      <div class="search">${icon("search")}<input id="q" aria-label="Search patients" placeholder="Search name, patient ID or folder" value="${esc(wlState.q)}" /></div>
    </div>
    <div class="index" id="wl"></div>`;
  document.querySelectorAll(".fact .val").forEach((n) => countUp(n, +n.dataset.n));
  requestAnimationFrame(() => ($("#vbar").style.width = pct + "%"));

  const draw = () => {
    document.querySelectorAll("#tabs button").forEach((b) => {
      const on = b.dataset.f === wlState.filter;
      b.classList.toggle("on", on); b.setAttribute("aria-selected", on);
    });
    const q = wlState.q.toLowerCase();
    const rows = patients.filter((p) => {
      const st = p.review_status === "verified" ? "verified" : "unreviewed";
      if (wlState.filter !== "all" && st !== wlState.filter) return false;
      if (!q) return true;
      return [p.display_name, p.name, p.patient_id, p.folder_path].some((v) => String(v || "").toLowerCase().includes(q));
    });
    const wl = $("#wl");
    if (!rows.length) { wl.innerHTML = `<div class="placeholder">No patients match this search or filter.</div>`; return; }
    wl.innerHTML = `<div class="index-head" aria-hidden="true"><span>Patient</span><span class="hide-md">Age / Sex</span><span class="hide-md">Patient ID</span><span>Films</span><span>Status</span><span></span></div>`;
    rows.forEach((p) => {
      const name = p.display_name || p.name || "Unnamed patient";
      const row = el(`<button class="index-row" aria-label="Open ${esc(name)}">
        <span><div class="nm">${esc(name)}</div><div class="sub">${esc(p.folder_path)}</div></span>
        <span class="cell-mono hide-md hide-sm">${esc(p.age || "—")} / ${esc(p.sex || "—")}</span>
        <span class="cell-mono hide-md hide-sm">${esc(p.patient_id || "—")}</span>
        <span class="cell-num hide-sm">${p.image_count}</span>
        <span>${statusBadge(p.review_status)}</span>
        <span class="go">${icon("arrow")}</span>
      </button>`);
      row.onclick = () => navigate("patient", p.id);
      wl.appendChild(row);
    });
  };
  $("#q").oninput = (e) => { wlState.q = e.target.value; draw(); };
  $("#tabs").onclick = (e) => { const b = e.target.closest("button"); if (b) { wlState.filter = b.dataset.f; draw(); } };
  draw();
};

async function downloadExcel() {
  try {
    const r = await fetch("/export.xlsx", { headers: { "X-API-Token": TOKEN } });
    if (!r.ok) throw new Error("Export failed (" + r.status + ")");
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "patient_studies.xlsx";
    a.click();
    URL.revokeObjectURL(a.href);
    toast("Excel export downloaded", "ok");
  } catch (e) { toast(e.message, "err"); }
}

// ---- Patient detail ------------------------------------------------------ //
function lateralityMarker(lat) {
  const l = String(lat || "").trim().toLowerCase();
  if (l.startsWith("l")) return `<span class="marker" title="Left">L</span>`;
  if (l.startsWith("r")) return `<span class="marker" title="Right">R</span>`;
  if (l.startsWith("b")) return `<span class="marker none" title="Bilateral">L·R</span>`;
  return `<span class="marker none" title="Side not detected">?</span>`;
}

views.patient = async (id) => {
  app.appendChild(el(`<div id="pd"><div class="loading">Loading patient…</div></div>`));
  const pd = $("#pd");
  let data;
  try { data = await api(`/patients/${id}`); }
  catch (e) { pd.innerHTML = errorBlock(e.message); return; }

  const p = data.patient;
  const name = p.display_name || p.name || "Patient #" + id;
  const imgs = data.images || [];
  const errors = imgs.filter((i) => i.error).length;
  const conflicts = imgs.filter((i) => (safeJson(i.crosscheck_json, {}).name || {}).status === "conflict").length;
  const hw = data.reconciled_hardware || [];

  pd.innerHTML = `
    <nav class="crumbs" aria-label="Breadcrumb"><a id="crumbWl" tabindex="0">Worklist</a>${icon("chevron")}<span>${esc(name)}</span></nav>
    <header class="patient-head">
      <div>
        <h1>${esc(name)}</h1>
        <div class="film-label">
          <span>ID <b>${esc(p.patient_id || "—")}</b></span>
          <span>AGE <b>${esc(p.age || "—")}</b></span>
          <span>SEX <b>${esc(p.sex || "—")}</b></span>
          <span>FILMS <b>${pad2(imgs.length)}</b></span>
          <span id="heroBadge">${statusBadge(p.review_status)}</span>${errors ? `<span class="badge err">${errors} failed</span>` : ""}
        </div>
        <div class="folder-row"><span class="folder">${esc(p.folder_path || "")}</span>
          <button class="btn secondary sm" id="openFolder">${icon("open")} Open folder</button></div>
    </header>

    <div id="reStrip" class="re-strip" style="display:none" aria-live="polite">
      <div class="re-top"><b id="reTitle">Re-analyzing…</b><span class="muted" id="reMsg"></span><button class="btn secondary sm" id="reCancel">Cancel</button></div>
      <div class="progress"><div id="reBar"></div></div>
    </div>

    ${conflicts ? `<div class="alert" role="alert">${icon("alert")}<div><b>Check the patient name.</b> The name printed on the film label disagrees with other sources on ${conflicts} film${conflicts > 1 ? "s" : ""}. Confirm identity before signing off.</div></div>` : ""}

    <div class="two-col">
      <section>
        <div class="section-title"><h2>Hardware</h2><span class="muted">Reconciled across all films</span></div>
        <ul class="hw-strip">${hw.length
          ? hw.map((h) => `<li>${esc(h)}</li>`).join("")
          : `<li class="none">No implants or hardware detected</li>`}</ul>
        <div class="section-title"><h2>Films<span class="count">${pad2(imgs.length)}</span></h2><span class="muted">What the AI read from each image</span></div>
        <div class="films" id="films"></div>
      </section>
      <aside class="side">
        <div class="panel">
          <div class="panel-head"><div><h3>Surgeon sign-off</h3><p>This is what goes into the Excel export</p></div></div>
          <div class="panel-body">
            <label for="rstatus">Review status</label>
            <select id="rstatus"><option value="unreviewed">Awaiting review</option><option value="verified">Verified</option></select>
            <label for="rnotes">Clinical notes <span class="opt">(optional)</span></label>
            <textarea id="rnotes" placeholder="Observations, follow-up, corrections…">${esc(p.surgeon_notes || "")}</textarea>
            <label for="rhw">Override hardware <span class="opt">(optional)</span></label>
            <input id="rhw" value="${esc(p.verified_hardware || "")}" placeholder="Leave blank to keep the AI summary" />
            <div class="hint">If filled, this replaces the AI hardware summary in the export.</div>
            <div class="btn-row"><button class="btn" id="rsave">${icon("check")} Save sign-off</button></div>
          </div>
        </div>
        <div class="panel">
          <div class="panel-head"><div><h3>Correct this data</h3><p>If a film failed or was read wrongly</p></div></div>
          <div class="panel-body">
            <div class="fix-list">
              ${errors ? `<button class="fix" id="fxFailed"><b>Retry failed films <span class="badge err">${errors}</span></b><small>Read the ${errors} film${errors > 1 ? "s" : ""} that failed again, with the current AI settings.</small></button>` : ""}
              <button class="fix" id="fxAll"><b>Re-analyze all films</b><small>Discard these results and read every film in the folder again.</small></button>
              <button class="fix danger" id="fxRemove"><b>Remove patient</b><small>Delete this patient and all results from BoneChilling.</small></button>
            </div>
            <p class="hint">Your image files are never changed or deleted. To fix one film, use the actions under that film.</p>
          </div>
        </div>
      </aside>
    </div>`;

  const crumb = $("#crumbWl");
  crumb.onclick = () => navigate("worklist");
  crumb.onkeydown = (e) => { if (e.key === "Enter") navigate("worklist"); };
  $("#rstatus").value = p.review_status || "unreviewed";

  const films = $("#films");
  if (!imgs.length) films.innerHTML = `<div class="placeholder">No films stored for this patient.</div>`;
  imgs.forEach((img, i) => {
    const hwItems = safeJson(img.hardware);
    const vws = safeJson(img.views);
    const findings = safeJson(img.visible_findings);
    const nm = safeJson(img.crosscheck_json, {}).name || {};
    const conflict = nm.status === "conflict";
    const fileName = String(img.file_path || "").split(/[\\/]/).pop();
    const cls = img.error ? "has-error" : conflict ? "has-warn" : "";
    const status = img.error ? `<span class="badge err">Error</span>` : conflict ? `<span class="badge warn">Name conflict</span>` : `<span class="badge ok">Read OK</span>`;
    films.appendChild(el(`<article class="film ${cls}" style="--i:${i}">
      <div class="film-top">
        <button class="film-img" data-idx="${i}" aria-label="View X-ray full screen">
          <img loading="lazy" src="${filmSrc(img.id)}" alt="X-ray: ${esc(img.body_part || "film")}" onerror="this.parentNode.classList.add('missing');this.remove()" />
          <span class="missing-msg">Image file not found on this PC</span>
          ${lateralityMarker(img.laterality)}
        </button>
        <div class="film-cap">
          <h4>${esc(img.body_part || "Unknown body part")}</h4>
          <div class="views">${vws.length ? vws.map((v) => `<span class="chip">${esc(v)}</span>`).join("") : "No view detected"}</div>
        </div>
        <span class="film-status" aria-hidden="true"></span>
      </div>
      ${img.error ? `<div class="film-sec film-err">${icon("alert")} ${esc(img.error)}</div>` : ""}
      <div class="film-sec"><div class="k"><span>Impression</span>${status}</div><div>${esc(img.impression || "—")}</div></div>
      ${Array.isArray(findings) && findings.length ? `<div class="film-sec"><div class="k">Visible findings</div><ul>${findings.map((f) => `<li>${esc(typeof f === "string" ? f : f.finding || JSON.stringify(f))}</li>`).join("")}</ul></div>` : ""}
      <div class="film-sec"><div class="k">Hardware</div>${hwItems.length ? `<ul>${hwItems.map((h) => `<li>${esc(h.implant || h)}</li>`).join("")}</ul>` : `<span class="muted">None</span>`}</div>
      <div class="film-sec"><div class="k">Film label</div><div class="mono">${esc(nm.value || "—")}${img.study_date ? ` <span class="muted">· ${esc(img.study_date)}</span>` : ""}</div></div>
      <div class="film-foot"><span title="${esc(img.file_path || "")}">${esc(fileName || "film " + pad2(i + 1))}</span><span>${esc(img.engine_used || "")}</span></div>
      <div class="film-actions">
        <button class="act" data-act="reveal" data-id="${img.id}">Show file</button>
        <button class="act" data-act="redo" data-id="${img.id}">${img.error ? "Retry" : "Re-analyze"}</button>
        <button class="act danger" data-act="remove" data-id="${img.id}" data-name="${esc(fileName)}">Remove</button>
      </div>
    </article>`));
  });
  films.classList.add("clip-in");   // signature: films clip onto the lightbox

  // ---- corrections -------------------------------------------------------- //
  const busy = (on) => pd.querySelectorAll(".fix, .act").forEach((b) => (b.disabled = on));
  async function reanalyze(body, label) {
    let r;
    busy(true);
    try { r = await api(`/patients/${id}/reanalyze`, { method: "POST", json: body }); }
    catch (e) { busy(false); toast(e.message.replace(/^\d+: /, ""), "err"); return; }
    const strip = $("#reStrip"), bar = $("#reBar"), msgEl = $("#reMsg");
    strip.style.display = "block"; $("#reTitle").textContent = label;
    let done = 0, failed = 0; const total = r.films_queued || 1;
    msgEl.textContent = `0 of ${r.films_queued} films`;
    $("#reCancel").onclick = () => api(`/jobs/${r.job_id}/cancel`, { method: "POST" }).catch(() => {});
    watchJob(r.job_id, {
      onEvent(ev) {
        if (!strip.isConnected) return;
        if (ev.kind === "queued") msgEl.textContent = ev.message;
        if (ev.kind === "image_done" || ev.kind === "image_failed") {
          done++; if (ev.kind === "image_failed") failed++;
          msgEl.textContent = `${done} of ${r.films_queued} films${failed ? ` · ${failed} failed` : ""}`;
          bar.style.width = Math.min(100, Math.round((done / total) * 100)) + "%";
        }
        if (ev.kind === "error") msgEl.textContent = ev.message;
      },
      onEnd(status) {
        if (status === "completed") toast(failed ? `Finished with ${failed} failed film${failed > 1 ? "s" : ""}` : "Re-analysis complete", failed ? "err" : "ok");
        else if (status === "cancelled") toast("Re-analysis cancelled. Films not yet read can be retried.", "");
        else toast("Re-analysis stopped: " + status, "err");
        if (document.getElementById("pd")) render("patient", id);
      },
    });
  }
  const fxF = $("#fxFailed");
  if (fxF) fxF.onclick = () => reanalyze({ scope: "failed" }, "Retrying failed films");
  $("#fxAll").onclick = async () => {
    if (await confirmDialog({ title: "Re-analyze all films?", confirm: "Re-analyze all",
      body: `<p>The current results for all ${imgs.length} films will be discarded and every film in the folder read again with the current AI settings.</p><p class="muted">Your sign-off is reset to “Awaiting review”. Notes are kept.</p>` }))
      reanalyze({ scope: "all" }, "Re-analyzing all films");
  };
  $("#fxRemove").onclick = async () => {
    if (!(await confirmDialog({ title: `Remove ${esc(name)}?`, confirm: "Remove patient", danger: true,
      body: `<p>This deletes the patient, all ${imgs.length} film results and the sign-off notes from BoneChilling. It can’t be undone.</p><p class="muted">The image files in <span class="mono">${esc(p.folder_path || "")}</span> are not touched; you can ingest the folder again later.</p>` }))) return;
    try { await api(`/patients/${id}`, { method: "DELETE" }); toast(`${name} removed`, "ok"); navigate("worklist"); }
    catch (e) { toast(e.message, "err"); }
  };
  const viewList = imgs.map((im) => ({ id: im.id, title: [im.laterality, im.body_part].filter(Boolean).join(" ") || "Film",
    file: String(im.file_path || "").split(/[\\/]/).pop() }));
  const reveal = (imgId) => api(`/images/${imgId}/reveal`, { method: "POST" })
    .then(() => toast("Opened in your file manager", "ok")).catch((e) => toast(e.message.replace(/^\d+: /, ""), "err"));
  $("#openFolder").onclick = () => api(`/patients/${id}/open-folder`, { method: "POST" })
    .then(() => toast("Folder opened", "ok")).catch((e) => toast(e.message.replace(/^\d+: /, ""), "err"));
  films.onclick = async (e) => {
    const fi = e.target.closest(".film-img");
    if (fi && !fi.classList.contains("missing")) return openViewer(viewList, +fi.dataset.idx, reveal);
    const b = e.target.closest(".act"); if (!b) return;
    const imgId = +b.dataset.id;
    if (b.dataset.act === "reveal") return reveal(imgId);
    if (b.dataset.act === "redo") return reanalyze({ scope: "image", image_id: imgId }, "Re-analyzing film");
    if (!(await confirmDialog({ title: "Remove this film?", confirm: "Remove film", danger: true,
      body: `<p>The result for <span class="mono">${b.dataset.name}</span> is deleted from BoneChilling. The image file stays on disk.</p><p class="muted">If you ingest this folder again, the film will be read again.</p>` }))) return;
    try { await api(`/images/${imgId}`, { method: "DELETE" }); toast("Film removed", "ok"); render("patient", id); }
    catch (err) { toast(err.message, "err"); }
  };

  $("#rsave").onclick = async () => {
    const btn = $("#rsave");
    const body = {
      review_status: $("#rstatus").value,
      surgeon_notes: $("#rnotes").value,
      verified_hardware: $("#rhw").value || null,
    };
    btn.disabled = true;
    try {
      await api(`/patients/${id}/review`, { method: "POST", json: body });
      $("#heroBadge").innerHTML = statusBadge(body.review_status);
      toast("Sign-off saved", "ok");
    } catch (e) { toast(e.message, "err"); }
    btn.disabled = false;
  };
};

// ---- Ingest -------------------------------------------------------------- //
function steps(active) {
  const s = [["Select folders", "Choose what to analyze"], ["Analyze", "The AI reads each film"], ["Review", "Sign off in the worklist"]];
  return `<div class="steps">${s.map(([t, sub], i) => {
    const st = i < active ? "done" : i === active ? "active" : "";
    return `<div class="step ${st}"><span class="n">${i < active ? "✓ done" : pad2(i + 1)}</span><b>${t}</b><small>${sub}</small></div>`;
  }).join("")}</div>`;
}

views.ingest = () => {
  app.appendChild(el(`<div>
    ${pageHead({ title: "Analyze folders", subtitle: "Add patient folders and BoneChilling reads every film (body part, views, implants and label details), then adds each patient to your worklist." })}
    <div id="steps">${steps(0)}</div>
    <div class="two-col" style="margin-top:0">
      <section>
        <div class="panel" id="selectCard">
          <div class="panel-head"><div><h3>Choose folders</h3><p>One path per line. Each folder is one patient.</p></div></div>
          <div class="panel-body">
            <label for="paths">Folder paths</label>
            <textarea id="paths" class="mono" placeholder="C:\\Xrays\\2026-11-batch"></textarea>
            <div class="hint">Paste a batch folder that contains many patient sub-folders, or individual patient folders.</div>
            <div class="btn-row">
              <button class="btn secondary" id="pick" style="display:none">${icon("folder")} Browse…</button>
              <button class="btn" id="start">Start analysis ${icon("arrow")}</button>
            </div>
          </div>
        </div>
        <div class="panel" id="prog" style="display:none">
          <div class="panel-head"><div><h3>Analysis</h3><p id="pstatus">Starting…</p></div><div class="mi-row"><span id="pbadge" class="badge info">Running</span><button class="btn secondary sm" id="pcancel">Cancel</button></div></div>
          <div class="panel-body">
            <div class="counters">
              <div><div class="v" id="sFolders">0</div><div class="k">Folders</div></div>
              <div><div class="v" id="sSaved">0</div><div class="k">Films saved</div></div>
              <div><div class="v" id="sSkipped">0</div><div class="k">Skipped</div></div>
              <div><div class="v" id="sErrors">0</div><div class="k">Errors</div></div>
            </div>
            <div class="progress"><div id="pbar"></div></div>
            <div class="label" style="margin-top:0">Activity log</div>
            <div class="log" id="plog" role="log"></div>
            <div class="btn-row" id="doneRow" style="display:none">
              <button class="btn" id="toWl">Review in worklist ${icon("arrow")}</button>
              <button class="btn secondary" id="again">Analyze more folders</button>
            </div>
          </div>
        </div>
      </section>
      <aside class="side">
        <div class="panel">
          <div class="panel-head"><div><h3>How folders are read</h3><p>Expected layout</p></div></div>
          <div class="panel-body">
            <div class="tree">Batch folder/
├── Patient A/
│   ├── knee_ap.jpg
│   └── knee_lat.jpg
└── Patient B/
    └── scan001.dcm</div>
            <ul class="tips" style="margin-top:14px">
              <li>${icon("check")}<span>JPG, PNG and DICOM (.dcm) films are supported.</span></li>
              <li>${icon("check")}<span>Re-running a folder is safe: films already read are skipped.</span></li>
              <li>${icon("check")}<span>Photos that aren’t X-ray films are filtered out automatically.</span></li>
            </ul>
          </div>
        </div>
      </aside>
    </div>
  </div>`));
  $("#start").onclick = startIngest;
  // Native folder picker is available only inside the desktop shell.
  if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_folders) {
    const pick = $("#pick");
    pick.style.display = "inline-flex";
    pick.onclick = async () => {
      const dirs = await window.pywebview.api.pick_folders();
      if (dirs && dirs.length) {
        const ta = $("#paths");
        ta.value = (ta.value ? ta.value + "\n" : "") + dirs.join("\n");
      }
    };
  }
};

async function startIngest() {
  const paths = $("#paths").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!paths.length) { toast("Enter at least one folder path.", "err"); $("#paths").focus(); return; }
  const btn = $("#start"); btn.disabled = true;
  $("#steps").innerHTML = steps(1);
  $("#prog").style.display = "block";
  $("#doneRow").style.display = "none";
  const log = $("#plog"), pbar = $("#pbar"), pstatus = $("#pstatus"), pbadge = $("#pbadge");
  log.innerHTML = "";
  const c = { folders: 0, done: 0, saved: 0, skipped: 0, errors: 0 };
  const paint = () => {
    $("#sFolders").textContent = c.folders ? `${c.done}/${c.folders}` : "0";
    $("#sSaved").textContent = c.saved; $("#sSkipped").textContent = c.skipped; $("#sErrors").textContent = c.errors;
  };
  const add = (line, cls = "") => {
    const d = document.createElement("div"); if (cls) d.className = cls; d.textContent = line;
    log.appendChild(d); log.scrollTop = log.scrollHeight;
  };
  const finish = (status) => {
    ingestRunning = false; btn.disabled = false;
    pbar.style.width = "100%";
    const ok = status === "completed";
    $("#pcancel").style.display = "none";
    const label = { completed: c.errors ? "Completed with errors" : "Completed", cancelled: "Cancelled", failed: "Failed" }[status] || status;
    pbadge.className = "badge " + (ok && !c.errors ? "ok" : status === "cancelled" ? "muted" : ok ? "warn" : "err"); pbadge.textContent = label;
    const filmsTxt = `${c.saved} film${c.saved === 1 ? "" : "s"} saved across ${c.done} folder${c.done === 1 ? "" : "s"}`;
    pstatus.textContent =
      status === "cancelled" ? `Cancelled. ${filmsTxt}; everything read so far is kept. Run it again to continue where it stopped.`
      : status === "failed" ? "The analysis couldn’t start. See the log for the reason."
      : c.errors ? `Finished: ${filmsTxt}. ${c.errors} problem${c.errors > 1 ? "s" : ""}: failed films are retried automatically when you run the folder again, or use “Retry failed films” on the patient page.`
      : `Finished: ${filmsTxt}.`;
    $("#steps").innerHTML = steps(ok ? 2 : 1);
    $("#doneRow").style.display = "flex";
    $("#toWl").onclick = () => navigate("worklist");
    $("#again").onclick = () => navigate("ingest");
    toast(ok ? "Analysis complete" : "Analysis ended: " + status, ok ? "ok" : "err");
  };
  try {
    ingestRunning = true;
    const { job_id } = await api("/ingest", { method: "POST", json: { paths } });
    pstatus.textContent = "Reading films…";
    const pc = $("#pcancel"); pc.style.display = ""; pc.disabled = false;
    pc.onclick = async () => { pc.disabled = true; pstatus.textContent = "Cancelling after the current film…"; try { await api(`/jobs/${job_id}/cancel`, { method: "POST" }); } catch {} };
    add(`Job ${job_id} started`);
    const ws = new WebSocket(`${location.origin.replace("http", "ws")}/ws/jobs/${job_id}?token=${encodeURIComponent(TOKEN)}`);
    ws.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (!log.isConnected) {  // user navigated away; job keeps running server-side
        if (ev.kind === "job_end") { ws.close(); ingestRunning = false; toast("Analysis finished. See Worklist", "ok"); }
        return;
      }
      if (ev.kind === "folder_start") { c.folders++; pstatus.textContent = `Working on ${ev.folder}…`; add(`▸ ${ev.folder}: ${ev.message}`, "l-dir"); }
      else if (ev.kind === "image_done") { add(`  ✓ ${ev.file}: ${ev.message}`, "l-ok"); }
      else if (ev.kind === "image_failed") { c.errors++; add(`  ✗ ${ev.file}: ${ev.message}`, "l-err"); }
      else if (ev.kind === "image_retry") { add(`  ↻ ${ev.file}: ${ev.message}`, "l-skip"); }
      else if (ev.kind === "queued") { pstatus.textContent = ev.message; add(ev.message, "l-skip"); }
      else if (ev.kind === "image_skipped") { c.skipped++; add(`  · ${ev.file}: ${ev.message}`, "l-skip"); }
      else if (ev.kind === "folder_done") {
        c.done++; c.saved += ev.done || 0;
        if (c.folders) pbar.style.width = Math.round((c.done / c.folders) * 100) + "%";
        add(`✔ ${ev.message}`, "l-ok");
      }
      else if (ev.kind === "error") { c.errors++; add(`⚠ ${ev.message}`, "l-err"); }
      else if (ev.kind === "job_end") { ws.close(); finish(ev.status); }
      paint();
    };
    ws.onerror = () => { add("⚠ Lost connection to progress stream", "l-err"); ingestRunning = false; btn.disabled = false; };
  } catch (e) { add(`⚠ ${e.message}`, "l-err"); ingestRunning = false; btn.disabled = false; pbadge.className = "badge err"; pbadge.textContent = "Failed"; pstatus.textContent = e.message; }
}

// ---- Settings ------------------------------------------------------------ //
views.settings = async () => {
  app.appendChild(el(`<div>
    ${pageHead({ title: "Settings", subtitle: "Choose which AI reads your films. A local model keeps everything on this PC; a cloud provider can be faster but needs an API key." })}
    <section class="set-section">
      <div class="no">01</div>
      <div class="desc"><h3>AI engine</h3><p>The provider and model used for every new analysis. Films already read are not affected.</p></div>
      <div id="st"><div class="loading">Loading…</div></div>
    </section>
    <section class="set-section">
      <div class="no">02</div>
      <div class="desc"><h3>Local AI (Ollama)</h3><p>Runs the model on this computer: private, offline, no API key. Recommended for patient data.</p></div>
      <div id="olbody"><div class="loading">Checking…</div></div>
    </section>
    <section class="set-section">
      <div class="no">03</div>
      <div class="desc"><h3>Privacy &amp; safety</h3><p>How your data and keys are handled.</p></div>
      <ul class="tips">
        <li>${icon("check")}<span>Results are stored in a local database on this PC.</span></li>
        <li>${icon("check")}<span>API keys are kept in your operating system’s secure credential store, never in plain files.</span></li>
        <li>${icon("check")}<span>The app reports objective facts only and does not make diagnoses.</span></li>
      </ul>
    </section>
  </div>`));
  loadOllama();
  try {
    const [providers, cfg] = await Promise.all([api("/providers"), api("/settings")]);
    const st = $("#st");
    st.innerHTML = `
      <label for="prov">Provider</label>
      <select id="prov">${providers.map((p) => `<option value="${p.key}" ${p.key === cfg.provider ? "selected" : ""}>${esc(p.label)}${p.needs_key ? (p.has_key ? " (key saved)" : " (key needed)") : ""}</option>`).join("")}</select>
      <div class="note">${icon("info")}<div id="pnote"></div></div>
      <div id="keyrow">
        <label for="key">API key <span class="opt">(stored in your OS credential store)</span></label>
        <div class="key-field">
          <input id="key" type="password" placeholder="Paste key, then Test connection" autocomplete="off" spellcheck="false" />
          <button class="eye" id="keyEye" type="button" aria-label="Show key" aria-pressed="false">${icon("eye")}</button>
        </div>
        <div class="hint" id="keyhint"></div>
      </div>
      <label for="model">Vision model</label>
      <select id="model"><option>Loading models…</option></select>
      <div id="customRow" style="display:none">
        <label for="modelCustom">Exact model name</label>
        <input id="modelCustom" class="mono" list="modelKnown" autocomplete="off" spellcheck="false" placeholder="e.g. qwen2.5vl:7b" />
        <datalist id="modelKnown"></datalist>
      </div>
      <div id="savedWarn"></div>
      <div id="modelInfo" class="model-info"></div>
      <div class="btn-row">
        <button class="btn" id="save">${icon("check")} Save settings</button>
        <button class="btn secondary" id="test">${icon("key")} Test connection &amp; save key</button>
      </div>
      <div id="stmsg" class="status-msg" aria-live="polite"></div>`;
    const provSel = $("#prov"), modelSel = $("#model"), custom = $("#modelCustom");
    const meta = () => providers.find((p) => p.key === provSel.value);
    const CUSTOM = "__custom__";
    let options = [], verified = false, defaultModel = "", pollTimer = null;
    let wanted = cfg.provider === provSel.value ? (cfg.model || "") : "";

    const currentModel = () => (modelSel.value === CUSTOM ? custom.value.trim() : modelSel.value) || null;
    const statusBadgeFor = (o) => ({
      installed: `<span class="badge ok">Installed</span>`,
      download: `<span class="badge muted">Not downloaded</span>`,
      available: `<span class="badge ok">Available on your account</span>`,
      suggested: `<span class="badge muted">Not verified yet</span>`,
    }[o.status] || "");

    function renderInfo() {
      const box = $("#modelInfo");
      const id = currentModel();
      $("#customRow").style.display = modelSel.value === CUSTOM ? "block" : "none";
      if (!id) { box.innerHTML = `<span class="muted">Uses the provider default (<span class="mono">${esc(defaultModel)}</span>).</span>`; return; }
      const o = options.find((x) => x.id === id);
      if (o) {
        const dl = provSel.value === "ollama" && o.status === "download";
        const life = o.lifecycle === "deprecated" || o.lifecycle === "retired"
          ? `<div class="note warn" style="margin-top:6px">${icon("alert")}<div>This model ${o.lifecycle === "deprecated" ? "is being retired by the provider" : "has been retired"}.${o.replacement ? ` <button class="linkbtn" data-switch="${esc(o.replacement)}">Switch to ${esc(o.replacement)}</button>` : ""}</div></div>` : "";
        box.innerHTML = `<div class="mi-row"><span class="mono mi-id">${esc(o.id)}</span>${statusBadgeFor(o)}${o.size ? `<span class="muted">~${esc(o.size)} download</span>` : ""}</div>
          ${o.note ? `<div class="muted">${esc(o.note)}</div>` : ""}${life}
          ${dl ? `<div class="btn-row" style="margin-top:10px"><button class="btn secondary" id="pullSel">${icon("download")} Download ${esc(o.id)}</button><span class="muted" id="pullMsg">Needed before this model can read films.</span></div>` : ""}`;
        const pb = $("#pullSel"); if (pb) pb.onclick = () => pullModel(o.id);
        box.querySelectorAll("[data-switch]").forEach((b) => (b.onclick = () => switchTo(b.dataset.switch)));
        return;
      }
      // typed name that isn't in any list: warn, don't block
      const near = options.filter((x) => x.id.replace(/[^a-z0-9]/gi, "").toLowerCase() === id.replace(/[^a-z0-9]/gi, "").toLowerCase());
      const warn = near.length
        ? `Did you mean <button class="linkbtn" id="useNear">${esc(near[0].id)}</button>? A small spelling difference stops the model from running.`
        : provSel.value === "ollama"
          ? "This name isn’t in the list or installed on this PC. Check the exact tag on ollama.com/library, then download it."
          : verified ? "This model isn’t in the list your provider returned for your key. Check the exact ID." : "Can’t verify this name until a key is saved. Use Test connection to check it.";
      box.innerHTML = `<div class="note warn" style="margin-top:0">${icon("alert")}<div>${warn}</div></div>
        ${provSel.value === "ollama" ? `<div class="btn-row" style="margin-top:10px"><button class="btn secondary" id="pullSel">${icon("download")} Download ${esc(id)}</button><span class="muted" id="pullMsg"></span></div>` : ""}`;
      const u = $("#useNear"); if (u) u.onclick = () => { modelSel.value = near[0].id; renderInfo(); };
      const pb = $("#pullSel"); if (pb) pb.onclick = () => pullModel(id);
    }

    function switchTo(id) {
      if (options.some((o) => o.id === id)) modelSel.value = id; else { modelSel.value = CUSTOM; custom.value = id; }
      renderInfo(); toast(`Selected ${id}. Save settings to use it.`, "");
    }
    function renderSaved(sv) {
      const box = $("#savedWarn");
      if (!sv || !["missing", "deprecated", "retired"].includes(sv.state) || provSel.value !== cfg.provider) { box.innerHTML = ""; return; }
      box.innerHTML = `<div class="note ${sv.state === "deprecated" ? "warn" : "err"}">${icon("alert")}<div><b>Your saved model needs attention.</b> ${esc(sv.message || "")}
        ${sv.replacement ? ` <button class="linkbtn" id="useRep">Use ${esc(sv.replacement)}</button>` : " Pick another model below."}</div></div>`;
      const u = $("#useRep"); if (u) u.onclick = () => switchTo(sv.replacement);
    }
    async function loadModels() {
      modelSel.innerHTML = `<option>Loading models…</option>`; modelSel.disabled = true;
      let r;
      try { r = await api(`/models?provider=${encodeURIComponent(provSel.value)}`); }
      catch { r = { options: [], default: meta().default_model, verified: false }; }
      options = r.options || []; verified = !!r.verified; defaultModel = r.default || "";
      renderSaved(r.saved);
      const groups = [];
      for (const o of options) { let g = groups.find((x) => x.name === o.group); if (!g) groups.push(g = { name: o.group, items: [] }); g.items.push(o); }
      const mark = { installed: " ✓ installed", download: "", available: "", suggested: "" };
      modelSel.innerHTML = `<option value="">Provider default (${esc(defaultModel)})</option>` +
        groups.map((g) => `<optgroup label="${esc(g.name)}">${g.items.map((o) =>
          `<option value="${esc(o.id)}">${esc(o.label === o.id ? o.id : `${o.label} · ${o.id}`)}${o.size ? ` · ~${esc(o.size)}` : ""}${mark[o.status] || ""}${o.lifecycle === "deprecated" ? " · retiring" : o.lifecycle === "retired" ? " · retired" : ""}</option>`).join("")}</optgroup>`).join("") +
        `<option value="${CUSTOM}">Other model (type the exact name)…</option>`;
      $("#modelKnown").innerHTML = options.map((o) => `<option value="${esc(o.id)}"></option>`).join("");
      if (wanted && options.some((o) => o.id === wanted)) modelSel.value = wanted;
      else if (wanted) { modelSel.value = CUSTOM; custom.value = wanted; }
      else modelSel.value = "";
      modelSel.disabled = false;
      renderInfo();
    }

    async function pullModel(id) {
      const pm = $("#pullMsg"), pb = $("#pullSel");
      if (pb) pb.disabled = true;
      try { await api("/ollama/pull", { method: "POST", json: { model: id } }); }
      catch (e) { if (pm) pm.textContent = e.message; if (pb) pb.disabled = false; return; }
      clearInterval(pollTimer);
      pollTimer = setInterval(async () => {
        let s; try { s = await api("/ollama/status"); } catch { return; }
        const p = s.pull || {};
        const m = $("#pullMsg");
        if (!m) { clearInterval(pollTimer); return; }
        m.textContent = p.line || "Downloading…";
        if (!p.active) {
          clearInterval(pollTimer);
          if (p.error) { m.textContent = "Download failed: " + p.error + ". Check the model name."; const b = $("#pullSel"); if (b) b.disabled = false; }
          else { toast(`${id} downloaded`, "ok"); wanted = id; loadModels(); loadOllama(); }
        }
      }, 1200);
    }

    // Saved key: shown masked in the field; the eye fetches and reveals it.
    const keyIn = $("#key"), eye = $("#keyEye");
    let keyDirty = false, keyShown = false, savedMasked = "";
    keyIn.oninput = () => { keyDirty = true; };
    keyIn.onfocus = () => { if (!keyDirty && savedMasked && !keyShown) keyIn.select(); };
    const setEye = (shown) => { keyShown = shown; keyIn.type = shown ? "text" : "password";
      eye.innerHTML = icon(shown ? "eyeOff" : "eye"); eye.setAttribute("aria-pressed", shown); eye.setAttribute("aria-label", shown ? "Hide key" : "Show key"); };
    eye.onclick = async () => {
      if (keyShown) { setEye(false); if (!keyDirty && savedMasked) keyIn.value = savedMasked; return; }
      if (!keyDirty && savedMasked) {
        try { const r = await api(`/api-keys/${provSel.value}?reveal=true`); keyIn.value = r.key || ""; }
        catch (e) { toast(e.message, "err"); return; }
      }
      setEye(true);
    };
    async function loadKey() {
      const p = meta(); keyDirty = false; savedMasked = ""; setEye(false); keyIn.value = "";
      if (!p.needs_key) return;
      try {
        const r = await api(`/api-keys/${p.key}`);
        if (r.has_key) { savedMasked = r.masked; keyIn.value = r.masked; }
        $("#keyhint").innerHTML = r.has_key
          ? `Key saved in your OS credential store. Paste over it to replace it, or <button class="linkbtn" id="keyDel">remove it</button>.`
          : "Save a key to see the exact models your account can use.";
        const del = $("#keyDel");
        if (del) del.onclick = async () => {
          if (!(await confirmDialog({ title: "Remove saved key?", confirm: "Remove key", danger: true,
            body: `<p>The ${esc(p.label)} key is deleted from your OS credential store. Analyses with this provider stop until a new key is saved.</p>` }))) return;
          await api(`/api-keys/${p.key}`, { method: "DELETE" }); p.has_key = false; toast("Key removed", "ok"); refresh();
        };
      } catch { /* leave empty */ }
    }
    const refresh = () => {
      const p = meta();
      $("#pnote").textContent = p.notes || (p.needs_key ? "Cloud provider. Requires an API key." : "Runs locally. No API key required.");
      $("#keyrow").style.display = p.needs_key ? "block" : "none";
      loadKey();
      loadModels();
    };
    provSel.onchange = () => { wanted = provSel.value === cfg.provider ? (cfg.model || "") : ""; refresh(); };
    modelSel.onchange = () => { if (modelSel.value === CUSTOM) { custom.value = ""; renderInfo(); custom.focus(); } else renderInfo(); };
    custom.oninput = renderInfo;
    refresh();
    const msg = (html) => ($("#stmsg").innerHTML = html);
    $("#save").onclick = async () => {
      if (modelSel.value === CUSTOM && !custom.value.trim()) { toast("Type the model name, or pick one from the list.", "err"); custom.focus(); return; }
      try {
        await api("/settings", { method: "POST", json: { provider: provSel.value, model: currentModel() } });
        cfg.provider = provSel.value; cfg.model = currentModel() || "";
        msg(""); toast("Settings saved", "ok");
      } catch (e) { msg(`<span class="badge err">Error</span> ${esc(e.message)}`); }
    };
    $("#test").onclick = async () => {
      const body = { provider: provSel.value, model: currentModel(), store: true };
      const k = keyDirty ? keyIn.value.trim() : ""; if (k) body.key = k;
      msg(`<span class="badge info">Testing…</span>`);
      try {
        const r = await api("/engine-test", { method: "POST", json: body });
        msg(r.ok ? `<span class="badge ok">Connected${r.stored ? " · key saved" : ""}</span> <span>${esc(r.detail)}</span>`
                 : `<span class="badge err">Failed</span> <span>${esc(r.detail)}</span>`);
        if (r.ok && r.stored) { const p = meta(); if (p) p.has_key = true; wanted = currentModel() || ""; refresh(); }
      } catch (e) { msg(`<span class="badge err">Error</span> ${esc(e.message)}`); }
    };
  } catch (e) { $("#st").innerHTML = errorBlock(e.message); }
};

async function loadOllama() {
  const body = $("#olbody");
  if (!body) return;
  let s;
  try { s = await api("/ollama/status"); } catch { body.innerHTML = `<span class="badge muted">Status unavailable</span>`; return; }
  if (!s.binary_present) {
    body.innerHTML = `<div class="note warn" style="margin-top:0">${icon("alert")}<div><b>Ollama is not installed.</b> Install it to run the AI privately on this PC with no API key.</div></div>
      <div class="btn-row"><a class="btn" href="${esc(s.install_url)}" target="_blank" rel="noopener">${icon("download")} Download Ollama</a></div>`;
    return;
  }
  const running = s.running ? `<span class="badge ok">Running</span>` : `<span class="badge warn">Installed, not running</span>`;
  const hasModel = s.has_recommended ? `<span class="badge ok">${esc(s.recommended_model)} ready</span>`
                                     : `<span class="badge warn">${esc(s.recommended_model)} not downloaded</span>`;
  const pulling = s.pull && s.pull.active;
  body.innerHTML = `<div class="kv">
      <span class="k">Service</span><span>${running}</span>
      <span class="k">Recommended</span><span>${hasModel}</span>
      <span class="k">Installed</span><span class="mono">${(s.models || []).map(esc).join(", ") || `<span class="muted">None</span>`}</span>
    </div>
    ${s.has_recommended ? "" : `<div class="btn-row"><button class="btn" id="olpull" ${pulling ? "disabled" : ""}>${icon("download")} Download ${esc(s.recommended_model)}</button></div>`}
    ${pulling || (s.pull && s.pull.line) ? `<div class="log" style="margin-top:14px">${esc((s.pull && s.pull.line) || "")}</div>` : ""}`;
  const pull = $("#olpull");
  if (pull) pull.onclick = async () => { try { await api("/ollama/pull", { method: "POST", json: {} }); } catch (e) { toast(e.message, "err"); } setTimeout(loadOllama, 500); };
  if (pulling) setTimeout(loadOllama, 1500);  // poll while a pull is in progress
}

// ---- boot ---------------------------------------------------------------- //
checkConn();
render("worklist");
