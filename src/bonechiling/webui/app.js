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

const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---- connection indicator ------------------------------------------------ //
async function checkConn() {
  try {
    const h = await fetch("/health").then((r) => r.json());
    conn.textContent = TOKEN ? `connected · v${h.version}` : "no token — open via the app";
    conn.className = "conn " + (TOKEN ? "ok" : "err");
  } catch {
    conn.textContent = "backend offline";
    conn.className = "conn err";
  }
}

// ---- router -------------------------------------------------------------- //
const views = {};
function navigate(name, arg) {
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  app.innerHTML = "";
  (views[name] || views.worklist)(arg);
}
document.getElementById("nav").addEventListener("click", (e) => {
  if (e.target.dataset.view) navigate(e.target.dataset.view);
});

// ---- Worklist ------------------------------------------------------------ //
const statusPill = (s) =>
  s === "verified" ? `<span class="pill ok">verified</span>` : `<span class="pill muted">unreviewed</span>`;

views.worklist = async () => {
  app.appendChild(el(`<div>
    <div class="row" style="align-items:center">
      <h2 style="margin:0">Patient worklist</h2>
      <div style="flex:0"><button class="btn secondary" id="xlsx" style="margin:0">📊 Download Excel</button></div>
    </div>
    <div id="wl" class="card" style="margin-top:14px">Loading…</div></div>`));
  document.getElementById("xlsx").onclick = downloadExcel;
  try {
    const patients = await api("/patients");
    const wl = document.getElementById("wl");
    if (!patients.length) { wl.innerHTML = `<p class="muted">No patients yet. Use <b>Ingest</b> to analyze a folder.</p>`; return; }
    wl.innerHTML = "";
    const table = el(`<table><thead><tr><th>Patient</th><th>Films</th><th>Status</th><th>Folder</th></tr></thead><tbody></tbody></table>`);
    const tb = table.querySelector("tbody");
    patients.forEach((p) => {
      const tr = el(`<tr class="clickable"><td>${esc(p.display_name || p.name || "—")}</td><td>${p.image_count}</td><td>${statusPill(p.review_status)}</td><td class="muted">${esc(p.folder_path)}</td></tr>`);
      tr.onclick = () => navigate("patient", p.id);
      tb.appendChild(tr);
    });
    wl.appendChild(table);
  } catch (e) { document.getElementById("wl").innerHTML = `<p class="pill err">${esc(e.message)}</p>`; }
};

async function downloadExcel() {
  try {
    const r = await fetch("/export.xlsx", { headers: { "X-API-Token": TOKEN } });
    if (!r.ok) throw new Error("export failed (" + r.status + ")");
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "patient_studies.xlsx";
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) { alert(e.message); }
}

// ---- Patient detail ------------------------------------------------------ //
views.patient = async (id) => {
  app.appendChild(el(`<div><button class="btn secondary" id="back">← Worklist</button><div id="pd" style="margin-top:14px">Loading…</div></div>`));
  document.getElementById("back").onclick = () => navigate("worklist");
  try {
    const data = await api(`/patients/${id}`);
    const p = data.patient;
    const pd = document.getElementById("pd");
    pd.innerHTML = `
      <div class="card">
        <h2 style="margin-top:0">${esc(p.display_name || p.name || "Patient #" + id)} ${statusPill(p.review_status)}</h2>
        <div class="kv">
          <span class="k">Age / Sex</span><span>${esc(p.age || "?")} / ${esc(p.sex || "?")}</span>
          <span class="k">Patient ID</span><span>${esc(p.patient_id || "—")}</span>
          <span class="k">Reconciled hardware</span><span>${(data.reconciled_hardware || []).map(esc).join("<br>") || "—"}</span>
        </div>
      </div>
      <div class="card">
        <h3 style="margin-top:0">Surgeon review</h3>
        <label>Status</label>
        <select id="rstatus"><option value="unreviewed">Unreviewed</option><option value="verified">Verified</option></select>
        <label>Clinical notes</label>
        <textarea id="rnotes">${esc(p.surgeon_notes || "")}</textarea>
        <label>Override hardware (optional — overrides the AI summary in the export)</label>
        <input id="rhw" value="${esc(p.verified_hardware || "")}" placeholder="leave blank to keep AI summary" />
        <button class="btn" id="rsave">Save review</button>
        <span id="rmsg" style="margin-left:12px"></span>
      </div>
      <h3>Films (${data.images.length})</h3>
      <div class="films"></div>`;
    pd.querySelector("#rstatus").value = p.review_status || "unreviewed";
    const films = pd.querySelector(".films");
    data.images.forEach((img) => {
      const hw = safeJson(img.hardware), views_ = safeJson(img.views);
      const cc = safeJson(img.crosscheck_json), name = cc.name || {};
      const flag = name.status === "conflict" ? ` <span class="pill warn">name conflict</span>` : "";
      films.appendChild(el(`<div class="film">
        <h4>${esc(img.body_part || "—")} ${views_.length ? "(" + views_.map(esc).join(", ") + ")" : ""}</h4>
        <div class="kv">
          <span class="k">Impression</span><span>${esc(img.impression || "—")}</span>
          <span class="k">Hardware</span><span>${hw.length ? hw.map((h) => esc(h.implant || h)).join("; ") : "none"}</span>
          <span class="k">Label</span><span>${esc(name.value || "—")}${flag}</span>
          <span class="k">Engine</span><span class="muted">${esc(img.engine_used || "—")}</span>
          <span class="k">Status</span><span>${img.error ? `<span class="pill err">error</span>` : `<span class="pill ok">ok</span>`}</span>
        </div></div>`));
    });
    pd.querySelector("#rsave").onclick = async () => {
      const body = {
        review_status: pd.querySelector("#rstatus").value,
        surgeon_notes: pd.querySelector("#rnotes").value,
        verified_hardware: pd.querySelector("#rhw").value || null,
      };
      pd.querySelector("#rmsg").innerHTML = `<span class="pill muted">saving…</span>`;
      try {
        await api(`/patients/${id}/review`, { method: "POST", json: body });
        pd.querySelector("#rmsg").innerHTML = `<span class="pill ok">saved</span>`;
      } catch (e) { pd.querySelector("#rmsg").innerHTML = `<span class="pill err">${esc(e.message)}</span>`; }
    };
  } catch (e) { document.getElementById("pd").innerHTML = `<p class="pill err">${esc(e.message)}</p>`; }
};

// ---- Ingest -------------------------------------------------------------- //
views.ingest = () => {
  app.appendChild(el(`<div><h2>Ingest patient folders</h2>
    <div class="card">
      <label>Folder path(s) — one per line (each folder = one patient)</label>
      <textarea id="paths" placeholder="/path/to/patient_folder_or_batch_root"></textarea>
      <div class="hint">Drop a batch root containing many patient subfolders, or individual patient folders.</div>
      <button class="btn secondary" id="pick" style="display:none">Choose folder…</button>
      <button class="btn" id="start">Start analysis</button>
    </div>
    <div class="card" id="prog" style="display:none">
      <div class="row"><div><b id="pcount">0</b> films saved</div><div id="pstatus" class="muted">running…</div></div>
      <div class="progress-bar"><div id="pbar"></div></div>
      <div class="log" id="plog"></div>
    </div></div>`));
  document.getElementById("start").onclick = startIngest;
  // Native folder picker is available only inside the desktop shell.
  if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_folders) {
    const pick = document.getElementById("pick");
    pick.style.display = "inline-block";
    pick.onclick = async () => {
      const dirs = await window.pywebview.api.pick_folders();
      if (dirs && dirs.length) {
        const ta = document.getElementById("paths");
        ta.value = (ta.value ? ta.value + "\n" : "") + dirs.join("\n");
      }
    };
  }
};

async function startIngest() {
  const paths = document.getElementById("paths").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!paths.length) return alert("Enter at least one folder path.");
  const btn = document.getElementById("start"); btn.disabled = true;
  const prog = document.getElementById("prog"); prog.style.display = "block";
  const log = document.getElementById("plog"), pcount = document.getElementById("pcount");
  const pstatus = document.getElementById("pstatus"), pbar = document.getElementById("pbar");
  log.textContent = ""; let saved = 0, folders = 0, doneFolders = 0;
  const add = (line) => { log.textContent += line + "\n"; log.scrollTop = log.scrollHeight; };
  try {
    const { job_id } = await api("/ingest", { method: "POST", json: { paths } });
    add(`Job ${job_id} started…`);
    const ws = new WebSocket(`${location.origin.replace("http", "ws")}/ws/jobs/${job_id}?token=${encodeURIComponent(TOKEN)}`);
    ws.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (ev.kind === "folder_start") { folders++; add(`📁 ${ev.folder} — ${ev.message}`); }
      else if (ev.kind === "image_done") { add(`  ✓ ${ev.file}: ${ev.message}`); }
      else if (ev.kind === "image_skipped") { add(`  · ${ev.file}: ${ev.message}`); }
      else if (ev.kind === "folder_done") { doneFolders++; saved += ev.done; pcount.textContent = saved;
        if (folders) pbar.style.width = Math.round((doneFolders / folders) * 100) + "%"; add(`✅ ${ev.message}`); }
      else if (ev.kind === "error") { add(`⚠️ ${ev.message}`); }
      else if (ev.kind === "job_end") { pstatus.textContent = ev.status; pbar.style.width = "100%";
        btn.disabled = false; ws.close(); navRefreshHint(); }
    };
    ws.onerror = () => { add("⚠️ progress connection error"); btn.disabled = false; };
  } catch (e) { add(`⚠️ ${e.message}`); btn.disabled = false; }
}
function navRefreshHint() { const s = document.getElementById("pstatus"); if (s) s.textContent += " — see Worklist"; }

// ---- Settings ------------------------------------------------------------ //
views.settings = async () => {
  app.appendChild(el(`<div><h2>Settings</h2><div id="st" class="card">Loading…</div>
    <div id="ollama" class="card"><h3 style="margin-top:0">Local AI (Ollama)</h3><div id="olbody" class="muted">Checking…</div></div></div>`));
  loadOllama();
  try {
    const [providers, cfg] = await Promise.all([api("/providers"), api("/settings")]);
    const st = document.getElementById("st");
    st.innerHTML = `
      <div class="notice">Using a cloud provider sends X-ray images off this device. Local (Ollama) keeps everything on this PC.</div>
      <label>AI provider</label>
      <select id="prov">${providers.map((p) => `<option value="${p.key}" ${p.key === cfg.provider ? "selected" : ""}>${esc(p.label)}${p.needs_key ? (p.has_key ? " ✓ key set" : " — key needed") : ""}</option>`).join("")}</select>
      <div class="hint" id="pnote"></div>
      <label>Model (blank = recommended default)</label>
      <input id="model" value="${esc(cfg.model || "")}" placeholder="provider default" />
      <div id="keyrow">
        <label>API key <span class="muted">(stored securely in your OS credential store)</span></label>
        <input id="key" type="password" placeholder="paste key, then Test & Save" />
      </div>
      <div class="row">
        <button class="btn" id="save">Save settings</button>
        <button class="btn secondary" id="test">Test &amp; Save key</button>
      </div>
      <div id="stmsg" style="margin-top:12px"></div>`;
    const provSel = document.getElementById("prov");
    const meta = () => providers.find((p) => p.key === provSel.value);
    const refresh = () => {
      const p = meta();
      document.getElementById("pnote").textContent = p.notes || "";
      document.getElementById("keyrow").style.display = p.needs_key ? "block" : "none";
    };
    provSel.onchange = refresh; refresh();
    const msg = (html) => (document.getElementById("stmsg").innerHTML = html);
    document.getElementById("save").onclick = async () => {
      await api("/settings", { method: "POST", json: { provider: provSel.value, model: document.getElementById("model").value || null } });
      msg(`<span class="pill ok">settings saved</span>`);
    };
    document.getElementById("test").onclick = async () => {
      const body = { provider: provSel.value, model: document.getElementById("model").value || null, store: true };
      const k = document.getElementById("key").value; if (k) body.key = k;
      msg(`<span class="pill muted">testing…</span>`);
      try {
        const r = await api("/engine-test", { method: "POST", json: body });
        msg(r.ok ? `<span class="pill ok">connected${r.stored ? " · key saved" : ""}</span> <span class="muted">${esc(r.detail)}</span>`
                 : `<span class="pill err">failed</span> <span class="muted">${esc(r.detail)}</span>`);
      } catch (e) { msg(`<span class="pill err">${esc(e.message)}</span>`); }
    };
  } catch (e) { document.getElementById("st").innerHTML = `<p class="pill err">${esc(e.message)}</p>`; }
};

async function loadOllama() {
  const body = document.getElementById("olbody");
  if (!body) return;
  let s;
  try { s = await api("/ollama/status"); } catch { body.innerHTML = `<span class="pill muted">unavailable</span>`; return; }
  if (!s.binary_present) {
    body.innerHTML = `<p>Ollama is not installed. It runs the AI on this PC (private, no key needed).</p>
      <a class="btn" href="${s.install_url}" target="_blank" rel="noopener">Download Ollama</a>`;
    return;
  }
  const running = s.running ? `<span class="pill ok">running</span>` : `<span class="pill warn">installed, not running</span>`;
  const hasModel = s.has_recommended ? `<span class="pill ok">${esc(s.recommended_model)} ready</span>`
                                     : `<span class="pill warn">model not downloaded</span>`;
  const pulling = s.pull && s.pull.active;
  body.innerHTML = `<div class="kv">
      <span class="k">Status</span><span>${running}</span>
      <span class="k">Model</span><span>${hasModel}</span>
      <span class="k">Installed</span><span class="muted">${(s.models || []).map(esc).join(", ") || "none"}</span>
    </div>
    ${s.has_recommended ? "" : `<button class="btn" id="olpull" ${pulling ? "disabled" : ""}>Download recommended model (${esc(s.recommended_model)})</button>`}
    ${pulling || (s.pull && s.pull.line) ? `<div class="log" id="olprog">${esc((s.pull && s.pull.line) || "")}</div>` : ""}`;
  const pull = document.getElementById("olpull");
  if (pull) pull.onclick = async () => { try { await api("/ollama/pull", { method: "POST", json: {} }); } catch (e) { alert(e.message); } setTimeout(loadOllama, 500); };
  if (pulling) setTimeout(loadOllama, 1500);  // poll while a pull is in progress
}

function safeJson(s) { try { return JSON.parse(s) || []; } catch { return []; } }

// ---- boot ---------------------------------------------------------------- //
checkConn();
navigate("worklist");
