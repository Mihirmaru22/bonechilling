// BoneChilling SPA — vanilla JS, no build step. Talks to the local FastAPI
// backend. The per-launch token arrives as ?token= (injected by the desktop
// shell); we keep it in memory and send it on every request.

const params = new URLSearchParams(location.search);
let TOKEN = params.get("token") || sessionStorage.getItem("bc_token") || "";
if (TOKEN) sessionStorage.setItem("bc_token", TOKEN);

const app = document.getElementById("app");
const conn = document.getElementById("conn");

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

function safeJson(s, fallback = []) {
  if (s && typeof s === "object") return s;
  try { const v = JSON.parse(s); return v ?? fallback; } catch { return fallback; }
}

// Inline icon set (Feather-style strokes) so the app works fully offline.
const ICONS = {
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  film: '<rect x="2" y="2" width="20" height="20" rx="2.2"/><path d="M7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  checkCircle: '<path d="M22 11.1V12a10 10 0 1 1-5.9-9.1"/><path d="M22 4 12 14l-3-3"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  back: '<path d="m15 18-6-6 6-6"/>',
  folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  play: '<path d="m5 3 14 9-14 9V3z"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  tool: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9l-3.8 3.8z"/>',
  clipboard: '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/>',
  tag: '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8z"/><path d="M7 7h.01"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
  server: '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><path d="M6 6h.01M6 18h.01"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  key: '<path d="m21 2-2 2m-7.6 7.6a5.5 5.5 0 1 1-7.8 7.8 5.5 5.5 0 0 1 7.8-7.8zm0 0L15.5 7.5m0 0 3 3L22 7l-3-3m-3.5 3.5L19 4"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
};
const icon = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ""}</svg>`;
document.querySelectorAll("[data-icon]").forEach((n) => (n.innerHTML = icon(n.dataset.icon)));

function avatar(name, cls = "") {
  const words = String(name || "?").trim().split(/\s+/).filter(Boolean);
  const initials = ((words[0] || "?")[0] + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase();
  return `<div class="avatar ${cls}">${esc(initials)}</div>`;
}

function toast(msg, kind = "") {
  const t = el(`<div class="toast ${kind}">${esc(msg)}</div>`);
  document.getElementById("toasts").appendChild(t);
  setTimeout(() => t.remove(), 3800);
}

const statusBadge = (s) =>
  s === "verified" ? `<span class="badge ok">Verified</span>` : `<span class="badge warn">Awaiting review</span>`;

const errorBlock = (msg) => `<div class="empty"><div class="ico" style="background:var(--err-soft);color:var(--err)">${icon("alert")}</div>
  <h3>Something went wrong</h3><p>${esc(msg)}</p></div>`;

function pageHead({ title, subtitle = "", crumbs = "", actions = "" }) {
  return `<div class="page-head"><div>${crumbs}<h1>${title}</h1>${subtitle ? `<p>${subtitle}</p>` : ""}</div>
    ${actions ? `<div class="actions">${actions}</div>` : ""}</div>`;
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

// ---- router -------------------------------------------------------------- //
const views = {};
let ingestRunning = false;
function navigate(name, arg) {
  const navName = name === "patient" ? "worklist" : name;
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === navName));
  app.innerHTML = "";
  window.scrollTo(0, 0);
  (views[name] || views.worklist)(arg);
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
      title: "Patient worklist",
      subtitle: "Every analyzed patient folder appears here. Open a patient to check the AI's findings and mark them as verified.",
      actions: `<button class="btn secondary" id="xlsx">${icon("download")} Export to Excel</button>
                <button class="btn" id="goIngest">${icon("upload")} Analyze new folders</button>`,
    })}
    <div id="stats" class="stats"></div>
    <div class="card" id="wlcard"><div class="loading">Loading patients…</div></div>
  </div>`));
  $("#xlsx").onclick = downloadExcel;
  $("#goIngest").onclick = () => navigate("ingest");

  let patients;
  try { patients = await api("/patients"); }
  catch (e) { $("#wlcard").innerHTML = errorBlock(e.message); return; }

  const total = patients.length;
  const films = patients.reduce((n, p) => n + (p.image_count || 0), 0);
  const verified = patients.filter((p) => p.review_status === "verified").length;
  const pending = total - verified;
  const pct = total ? Math.round((verified / total) * 100) : 0;
  $("#stats").innerHTML = [
    ["tone-blue", "users", total, "Patients"],
    ["tone-purple", "film", films, "Films analyzed"],
    ["tone-green", "checkCircle", verified, "Verified by surgeon"],
    ["tone-amber", "clock", pending, "Awaiting review"],
  ].map(([tone, ic, v, l]) => `<div class="stat ${tone}"><div class="ico">${icon(ic)}</div><div><div class="val">${v}</div><div class="lbl">${l}</div></div></div>`).join("");

  const card = $("#wlcard");
  if (!total) {
    card.innerHTML = `<div class="empty"><div class="ico">${icon("folder")}</div>
      <h3>No patients yet</h3>
      <p>Point BoneChilling at a folder of X-ray images. Each sub-folder is treated as one patient and analyzed automatically.</p>
      <button class="btn" id="emptyGo">${icon("upload")} Analyze your first folder</button></div>`;
    $("#emptyGo").onclick = () => navigate("ingest");
    return;
  }

  card.innerHTML = `
    <div class="card-head">
      <div><h3>${icon("clipboard")} Review progress</h3><p>${verified} of ${total} patients verified</p></div>
      <div class="review-progress" style="min-width:240px;flex:0 1 360px"><div class="progress ok"><div style="width:${pct}%"></div></div><b>${pct}%</b></div>
    </div>
    <div class="toolbar">
      <div class="search">${icon("search")}<input id="q" placeholder="Search by name, patient ID or folder…" value="${esc(wlState.q)}" /></div>
      <div class="seg" id="seg">
        <button data-f="all">All<span class="n">${total}</span></button>
        <button data-f="unreviewed">Awaiting review<span class="n">${pending}</span></button>
        <button data-f="verified">Verified<span class="n">${verified}</span></button>
      </div>
    </div>
    <div class="card-body flush" id="wl"></div>`;

  const render = () => {
    document.querySelectorAll("#seg button").forEach((b) => b.classList.toggle("on", b.dataset.f === wlState.filter));
    const q = wlState.q.toLowerCase();
    const rows = patients.filter((p) => {
      const st = p.review_status === "verified" ? "verified" : "unreviewed";
      if (wlState.filter !== "all" && st !== wlState.filter) return false;
      if (!q) return true;
      return [p.display_name, p.name, p.patient_id, p.folder_path].some((v) => String(v || "").toLowerCase().includes(q));
    });
    const wl = $("#wl");
    if (!rows.length) { wl.innerHTML = `<div class="placeholder">No patients match this search or filter.</div>`; return; }
    const table = el(`<table><thead><tr>
      <th>Patient</th><th class="hide-sm">Age / Sex</th><th class="hide-sm">Patient ID</th><th class="num">Films</th><th>Status</th><th></th>
    </tr></thead><tbody></tbody></table>`);
    const tb = table.querySelector("tbody");
    rows.forEach((p) => {
      const name = p.display_name || p.name || "Unnamed patient";
      const tr = el(`<tr class="clickable">
        <td><div class="person">${avatar(name)}<div class="meta"><div class="nm">${esc(name)}</div><div class="sub mono">${esc(p.folder_path)}</div></div></div></td>
        <td class="hide-sm">${esc(p.age || "—")} / ${esc(p.sex || "—")}</td>
        <td class="hide-sm mono">${esc(p.patient_id || "—")}</td>
        <td class="num">${p.image_count}</td>
        <td>${statusBadge(p.review_status)}</td>
        <td class="num"><span class="chev">${icon("chevron")}</span></td>
      </tr>`);
      tr.onclick = () => navigate("patient", p.id);
      tb.appendChild(tr);
    });
    wl.innerHTML = "";
    wl.appendChild(table);
  };
  $("#q").oninput = (e) => { wlState.q = e.target.value; render(); };
  $("#seg").onclick = (e) => { const b = e.target.closest("button"); if (b) { wlState.filter = b.dataset.f; render(); } };
  render();
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
    <div class="crumbs"><a id="crumbWl">Worklist</a>${icon("chevron")}<span>${esc(name)}</span></div>
    <div class="card">
      <div class="patient-hero">
        ${avatar(name, "lg")}
        <div style="flex:1;min-width:0">
          <h1>${esc(name)} <span id="heroBadge">${statusBadge(p.review_status)}</span></h1>
          <div class="folder">${esc(p.folder_path || "")}</div>
        </div>
        <button class="btn secondary" id="back">${icon("back")} Back to worklist</button>
      </div>
      <div class="facts">
        <div><div class="k">Age</div><div class="v">${esc(p.age || "—")}</div></div>
        <div><div class="k">Sex</div><div class="v">${esc(p.sex || "—")}</div></div>
        <div><div class="k">Patient ID</div><div class="v mono">${esc(p.patient_id || "—")}</div></div>
        <div><div class="k">Films</div><div class="v">${imgs.length}${errors ? ` <span class="badge err">${errors} failed</span>` : ""}</div></div>
      </div>
    </div>

    ${conflicts ? `<div class="callout warn" style="margin:0 0 18px">${icon("alert")}<div><b>Check the patient name.</b> The name read from the film label disagrees with other sources on ${conflicts} film${conflicts > 1 ? "s" : ""}. Confirm identity before verifying.</div></div>` : ""}

    <div class="two-col">
      <div>
        <div class="section-title"><h2>Films (${imgs.length})</h2><span class="muted" style="font-size:13px">AI-extracted facts per image</span></div>
        <div class="films" id="films"></div>
      </div>
      <div class="side">
        <div class="card">
          <div class="card-head"><div><h3>${icon("tool")} Hardware summary</h3><p>Reconciled across all films</p></div></div>
          <div class="card-body">${hw.length
            ? `<ul class="hw-list">${hw.map((h) => `<li>${icon("tool")}<span>${esc(h)}</span></li>`).join("")}</ul>`
            : `<p class="muted" style="margin:0">No implants or hardware detected.</p>`}</div>
        </div>
        <div class="card">
          <div class="card-head"><div><h3>${icon("checkCircle")} Surgeon review</h3><p>Your sign-off is what goes into the export</p></div></div>
          <div class="card-body">
            <label for="rstatus">Review status</label>
            <select id="rstatus"><option value="unreviewed">Awaiting review</option><option value="verified">Verified</option></select>
            <label for="rnotes">Clinical notes <span class="opt">(optional)</span></label>
            <textarea id="rnotes" placeholder="Observations, follow-up, corrections…">${esc(p.surgeon_notes || "")}</textarea>
            <label for="rhw">Override hardware <span class="opt">(optional)</span></label>
            <input id="rhw" value="${esc(p.verified_hardware || "")}" placeholder="Leave blank to keep the AI summary" />
            <div class="hint">If filled, this replaces the AI hardware summary in the Excel export.</div>
            <div class="btn-row"><button class="btn" id="rsave">${icon("check")} Save review</button></div>
          </div>
        </div>
      </div>
    </div>`;

  $("#back").onclick = $("#crumbWl").onclick = () => navigate("worklist");
  $("#rstatus").value = p.review_status || "unreviewed";

  const films = $("#films");
  if (!imgs.length) films.innerHTML = `<div class="card"><div class="placeholder">No films stored for this patient.</div></div>`;
  imgs.forEach((img, i) => {
    const hwItems = safeJson(img.hardware);
    const vws = safeJson(img.views);
    const findings = safeJson(img.visible_findings);
    const cc = safeJson(img.crosscheck_json, {});
    const nm = cc.name || {};
    const conflict = nm.status === "conflict";
    const fileName = String(img.file_path || "").split(/[\\/]/).pop();
    const cls = img.error ? "has-error" : conflict ? "has-warn" : "";
    const statusB = img.error ? `<span class="badge err">Error</span>` : conflict ? `<span class="badge warn">Name conflict</span>` : `<span class="badge ok">OK</span>`;
    const parts = [img.laterality, img.body_part].filter(Boolean).join(" ") || "Unknown body part";
    films.appendChild(el(`<div class="film ${cls}">
      <div class="film-head">
        <div><h4>${esc(parts)}</h4>
          <div class="views">${vws.length ? vws.map((v) => `<span class="chip">${esc(v)}</span>`).join("") : `<span class="muted" style="font-size:12px">No view detected</span>`}</div>
        </div>${statusB}
      </div>
      ${img.error ? `<div class="film-sec film-err">${icon("alert")} ${esc(img.error)}</div>` : ""}
      <div class="film-sec"><div class="k">${icon("eye")} Impression</div><div>${esc(img.impression || "—")}</div></div>
      ${Array.isArray(findings) && findings.length ? `<div class="film-sec"><div class="k">${icon("clipboard")} Visible findings</div><ul>${findings.map((f) => `<li>${esc(typeof f === "string" ? f : f.finding || JSON.stringify(f))}</li>`).join("")}</ul></div>` : ""}
      <div class="film-sec"><div class="k">${icon("tool")} Hardware</div>${hwItems.length ? `<ul>${hwItems.map((h) => `<li>${esc(h.implant || h)}</li>`).join("")}</ul>` : `<span class="muted">None</span>`}</div>
      <div class="film-sec"><div class="k">${icon("tag")} Film label</div><div>${esc(nm.value || "—")}${img.study_date ? ` <span class="muted">· ${esc(img.study_date)}</span>` : ""}</div></div>
      <div class="film-foot"><span class="mono" title="${esc(img.file_path || "")}">${esc(fileName || "Film " + (i + 1))}</span><span>${esc(img.engine_used || "")}</span></div>
    </div>`));
  });

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
      toast("Review saved", "ok");
    } catch (e) { toast(e.message, "err"); }
    btn.disabled = false;
  };
};

// ---- Ingest -------------------------------------------------------------- //
function stepper(active) {
  const steps = [["Select folders", "Choose what to analyze"], ["Analyze", "AI reads each film"], ["Review", "Verify in the worklist"]];
  return `<div class="stepper">${steps.map(([t, s], i) => {
    const st = i < active ? "done" : i === active ? "active" : "";
    return `<div class="step ${st}"><div class="n">${i < active ? icon("check") : i + 1}</div><div><b>${t}</b><small>${s}</small></div></div>`;
  }).join("")}</div>`;
}

views.ingest = () => {
  app.appendChild(el(`<div>
    ${pageHead({ title: "Analyze X-ray folders", subtitle: "Add patient folders and BoneChilling will read every film — body part, views, implants and label details — then add them to your worklist." })}
    <div id="stepper">${stepper(0)}</div>
    <div class="two-col">
      <div>
        <div class="card" id="selectCard">
          <div class="card-head"><div><h3>${icon("folder")} Step 1 · Choose folders</h3><p>One path per line. Each folder is one patient.</p></div></div>
          <div class="card-body">
            <label for="paths">Folder paths</label>
            <textarea id="paths" class="mono" placeholder="C:\\Xrays\\2026-11-batch"></textarea>
            <div class="hint">You can paste a batch folder that contains many patient sub-folders, or individual patient folders.</div>
            <div class="btn-row">
              <button class="btn secondary" id="pick" style="display:none">${icon("folder")} Browse…</button>
              <button class="btn" id="start">${icon("play")} Start analysis</button>
            </div>
          </div>
        </div>
        <div class="card" id="prog" style="display:none">
          <div class="card-head"><div><h3>${icon("cpu")} Step 2 · Analysis in progress</h3><p id="pstatus">Starting…</p></div><span id="pbadge" class="badge info">Running</span></div>
          <div class="card-body">
            <div class="mini-stats">
              <div><div class="v" id="sFolders">0</div><div class="k">Folders</div></div>
              <div><div class="v" id="sSaved">0</div><div class="k">Films saved</div></div>
              <div><div class="v" id="sSkipped">0</div><div class="k">Skipped</div></div>
              <div><div class="v" id="sErrors">0</div><div class="k">Errors</div></div>
            </div>
            <div class="progress"><div id="pbar"></div></div>
            <div class="label" style="margin-top:0">Activity log</div>
            <div class="log" id="plog"></div>
            <div class="btn-row" id="doneRow" style="display:none">
              <button class="btn" id="toWl">${icon("users")} Review results in worklist</button>
              <button class="btn secondary" id="again">Analyze more folders</button>
            </div>
          </div>
        </div>
      </div>
      <div class="side">
        <div class="card">
          <div class="card-head"><div><h3>${icon("info")} How folders are read</h3><p>Expected layout</p></div></div>
          <div class="card-body">
            <div class="tree">Batch folder/
├── Patient A/
│   ├── knee_ap.jpg
│   └── knee_lat.jpg
└── Patient B/
    └── scan001.dcm</div>
            <ul class="tips" style="margin-top:12px">
              <li>${icon("check")}<span>JPG, PNG and DICOM (.dcm) films are supported.</span></li>
              <li>${icon("check")}<span>Re-running a folder is safe — already analyzed films are skipped.</span></li>
              <li>${icon("check")}<span>Photos that aren't X-ray films are filtered out automatically.</span></li>
            </ul>
          </div>
        </div>
      </div>
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
  $("#stepper").innerHTML = stepper(1);
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
    pstatus.textContent = ok ? `Finished — ${c.saved} film${c.saved === 1 ? "" : "s"} saved across ${c.done} folder${c.done === 1 ? "" : "s"}.` : `Job ${status}.`;
    $("#stepper").innerHTML = stepper(ok ? 2 : 1);
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
        if (ev.kind === "job_end") { ws.close(); ingestRunning = false; toast("Analysis finished — see Worklist", "ok"); }
        return;
      }
      if (ev.kind === "folder_start") { c.folders++; pstatus.textContent = `Working on ${ev.folder}…`; add(`📁 ${ev.folder} — ${ev.message}`, "l-dir"); }
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
    <div class="card"><div class="card-body">
      <section class="set-section">
        <div class="desc"><h3>${icon("server")} AI engine</h3><p>The provider and model used for every new analysis. Changing this does not affect films already analyzed.</p></div>
        <div id="st"><div class="loading">Loading…</div></div>
      </section>
      <section class="set-section">
        <div class="desc"><h3>${icon("cpu")} Local AI (Ollama)</h3><p>Ollama runs the model on this computer — private, offline, no API key. Recommended for patient data.</p></div>
        <div id="olbody"><div class="loading">Checking…</div></div>
      </section>
      <section class="set-section">
        <div class="desc"><h3>${icon("shield")} Privacy &amp; safety</h3><p>How your data and keys are handled.</p></div>
        <ul class="tips">
          <li>${icon("check")}<span>Results are stored in a local database on this PC.</span></li>
          <li>${icon("check")}<span>API keys are kept in your operating system's secure credential store, never in plain files.</span></li>
          <li>${icon("check")}<span>The app reports objective facts only and does not make diagnoses.</span></li>
        </ul>
      </section>
    </div></div>
  </div>`));
  loadOllama();
  try {
    const [providers, cfg] = await Promise.all([api("/providers"), api("/settings")]);
    const st = $("#st");
    st.innerHTML = `
      <div class="field-row">
        <div>
          <label for="prov">Provider</label>
          <select id="prov">${providers.map((p) => `<option value="${p.key}" ${p.key === cfg.provider ? "selected" : ""}>${esc(p.label)}${p.needs_key ? (p.has_key ? " — key saved" : " — key needed") : ""}</option>`).join("")}</select>
        </div>
        <div>
          <label for="model">Model <span class="opt">(pick or type)</span></label>
          <input id="model" list="modellist" value="${esc(cfg.model || "")}" placeholder="Provider default" autocomplete="off" />
          <datalist id="modellist"></datalist>
        </div>
      </div>
      <div class="callout" id="pnoteBox">${icon("info")}<div id="pnote"></div></div>
      <div id="keyrow">
        <label for="key">${"API key"} <span class="opt">(stored in your OS credential store)</span></label>
        <input id="key" type="password" placeholder="Paste key, then click Test &amp; save key" />
        <div class="hint" id="keyhint"></div>
      </div>
      <div class="btn-row">
        <button class="btn" id="save">${icon("check")} Save settings</button>
        <button class="btn secondary" id="test">${icon("key")} Test connection &amp; save key</button>
      </div>
      <div id="stmsg" class="status-msg"></div>`;
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
      $("#pnote").textContent = p.notes || (p.needs_key ? "Cloud provider — requires an API key." : "Runs locally — no API key required.");
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
    body.innerHTML = `<div class="callout warn">${icon("alert")}<div><b>Ollama is not installed.</b> Install it to run the AI privately on this PC with no API key.</div></div>
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
      <span class="k">Installed</span><span>${(s.models || []).map((m) => `<span class="chip">${esc(m)}</span>`).join(" ") || `<span class="muted">None</span>`}</span>
    </div>
    ${s.has_recommended ? "" : `<div class="btn-row"><button class="btn" id="olpull" ${pulling ? "disabled" : ""}>${icon("download")} Download ${esc(s.recommended_model)}</button></div>`}
    ${pulling || (s.pull && s.pull.line) ? `<div class="log" style="margin-top:14px">${esc((s.pull && s.pull.line) || "")}</div>` : ""}`;
  const pull = $("#olpull");
  if (pull) pull.onclick = async () => { try { await api("/ollama/pull", { method: "POST", json: {} }); } catch (e) { toast(e.message, "err"); } setTimeout(loadOllama, 500); };
  if (pulling) setTimeout(loadOllama, 1500);  // poll while a pull is in progress
}

// ---- boot ---------------------------------------------------------------- //
checkConn();
navigate("worklist");
