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
          <span>FILMS <b>${pad2(imgs.length)}</b>${errors ? ` <span class="badge err">${errors} failed</span>` : ""}</span>
        </div>
        <div class="patient-meta"><span id="heroBadge">${statusBadge(p.review_status)}</span><span class="folder">${esc(p.folder_path || "")}</span></div>
      </div>
      <button class="btn secondary back" id="back">${icon("back")} Worklist</button>
    </header>

    ${conflicts ? `<div class="alert" role="alert">${icon("alert")}<div><b>Check the patient name.</b> The name printed on the film label disagrees with other sources on ${conflicts} film${conflicts > 1 ? "s" : ""}. Confirm identity before signing off.</div></div>` : ""}

    <div class="two-col">
      <section>
        <div class="section-title"><h2>Films<span class="count">${pad2(imgs.length)}</span></h2><span class="muted" style="font-size:13px">What the AI read from each image</span></div>
        <div class="films" id="films"></div>
      </section>
      <aside class="side">
        <div class="panel">
          <div class="panel-head"><div><h3>Hardware</h3><p>Reconciled across all films</p></div></div>
          <div class="panel-body">${hw.length
            ? `<ol class="hw-list">${hw.map((h) => `<li><span>${esc(h)}</span></li>`).join("")}</ol>`
            : `<p class="muted" style="margin:0">No implants or hardware detected.</p>`}</div>
        </div>
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
      </aside>
    </div>`;

  $("#back").onclick = () => navigate("worklist");
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
        <span class="clip" aria-hidden="true"></span>
        ${lateralityMarker(img.laterality)}
        <h4>${esc(img.body_part || "Unknown body part")}</h4>
        <div class="views">${vws.length ? vws.map((v) => `<span class="chip">${esc(v)}</span>`).join("") : "No view detected"}</div>
        <span class="film-status" aria-hidden="true"></span>
      </div>
      ${img.error ? `<div class="film-sec film-err">${icon("alert")} ${esc(img.error)}</div>` : ""}
      <div class="film-sec"><div class="k"><span>Impression</span>${status}</div><div>${esc(img.impression || "—")}</div></div>
      ${Array.isArray(findings) && findings.length ? `<div class="film-sec"><div class="k">Visible findings</div><ul>${findings.map((f) => `<li>${esc(typeof f === "string" ? f : f.finding || JSON.stringify(f))}</li>`).join("")}</ul></div>` : ""}
      <div class="film-sec"><div class="k">Hardware</div>${hwItems.length ? `<ul>${hwItems.map((h) => `<li>${esc(h.implant || h)}</li>`).join("")}</ul>` : `<span class="muted">None</span>`}</div>
      <div class="film-sec"><div class="k">Film label</div><div class="mono">${esc(nm.value || "—")}${img.study_date ? ` <span class="muted">· ${esc(img.study_date)}</span>` : ""}</div></div>
      <div class="film-foot"><span title="${esc(img.file_path || "")}">${esc(fileName || "film " + pad2(i + 1))}</span><span>${esc(img.engine_used || "")}</span></div>
    </article>`));
  });
  films.classList.add("clip-in");   // signature: films clip onto the lightbox

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
          <div class="panel-head"><div><h3>Analysis</h3><p id="pstatus">Starting…</p></div><span id="pbadge" class="badge info">Running</span></div>
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
    pbadge.className = "badge " + (ok ? "ok" : "err"); pbadge.textContent = ok ? "Completed" : status;
    pstatus.textContent = ok ? `Finished: ${c.saved} film${c.saved === 1 ? "" : "s"} saved across ${c.done} folder${c.done === 1 ? "" : "s"}.` : `Job ${status}.`;
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
      <div class="field-row">
        <div>
          <label for="prov">Provider</label>
          <select id="prov">${providers.map((p) => `<option value="${p.key}" ${p.key === cfg.provider ? "selected" : ""}>${esc(p.label)}${p.needs_key ? (p.has_key ? " (key saved)" : " (key needed)") : ""}</option>`).join("")}</select>
        </div>
        <div>
          <label for="model">Model <span class="opt">(pick or type)</span></label>
          <input id="model" list="modellist" value="${esc(cfg.model || "")}" placeholder="Provider default" autocomplete="off" />
          <datalist id="modellist"></datalist>
        </div>
      </div>
      <div class="note">${icon("info")}<div id="pnote"></div></div>
      <div id="keyrow">
        <label for="key">API key <span class="opt">(stored in your OS credential store)</span></label>
        <input id="key" type="password" placeholder="Paste key, then Test connection" />
        <div class="hint" id="keyhint"></div>
      </div>
      <div class="btn-row">
        <button class="btn" id="save">${icon("check")} Save settings</button>
        <button class="btn secondary" id="test">${icon("key")} Test connection &amp; save key</button>
      </div>
      <div id="stmsg" class="status-msg" aria-live="polite"></div>`;
    const provSel = $("#prov");
    const meta = () => providers.find((p) => p.key === provSel.value);
    async function loadModels() {
      const dl = $("#modellist"), model = $("#model");
      dl.innerHTML = "";
      try {
        const r = await api(`/models?provider=${encodeURIComponent(provSel.value)}`);
        for (const m of r.models || []) dl.appendChild(el(`<option value="${esc(m)}"></option>`));
        model.placeholder = r.default ? `${r.default} (default)` : "Provider default";
      } catch { /* leave free-text */ }
    }
    const refresh = () => {
      const p = meta();
      $("#pnote").textContent = p.notes || (p.needs_key ? "Cloud provider. Requires an API key." : "Runs locally. No API key required.");
      $("#keyrow").style.display = p.needs_key ? "block" : "none";
      $("#keyhint").textContent = p.has_key ? "A key is already saved. Paste a new one only to replace it." : "";
      loadModels();
    };
    provSel.onchange = refresh; refresh();
    const msg = (html) => ($("#stmsg").innerHTML = html);
    $("#save").onclick = async () => {
      try {
        await api("/settings", { method: "POST", json: { provider: provSel.value, model: $("#model").value || null } });
        msg(""); toast("Settings saved", "ok");
      } catch (e) { msg(`<span class="badge err">Error</span> ${esc(e.message)}`); }
    };
    $("#test").onclick = async () => {
      const body = { provider: provSel.value, model: $("#model").value || null, store: true };
      const k = $("#key").value; if (k) body.key = k;
      msg(`<span class="badge info">Testing…</span>`);
      try {
        const r = await api("/engine-test", { method: "POST", json: body });
        msg(r.ok ? `<span class="badge ok">Connected${r.stored ? " · key saved" : ""}</span> <span>${esc(r.detail)}</span>`
                 : `<span class="badge err">Failed</span> <span>${esc(r.detail)}</span>`);
        if (r.ok && r.stored) { $("#key").value = ""; const p = meta(); if (p) p.has_key = true; refresh(); }
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
