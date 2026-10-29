"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (id) => `<svg><use href="#i-${id}"/></svg>`;

const KIND_LABEL = {
  browser: "Browser", ai: "AI tool", chat: "Chat and calls", work: "Work and everyday", media: "Games and media",
  dev: "Developer tool", other: "Other app", hardware: "Driver or hardware", windows: "Part of Windows",
};
const CLOSE_LABEL = { safe: "Safe to close", care: "Close with care", keep: "Don't close", critical: "Windows needs it" };

const state = {
  view: "processes", data: null, kind: null, close: null, query: "", sort: { key: "name", dir: 1 },
  expanded: new Set(), collapsed: new Set(), sel: null,
  startup: null, services: null, svcFilter: "running", busy: false,
};

async function api(path, body) {
  const opts = { headers: { "X-PPV-Token": window.PPV_TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`The app's background part didn't answer (${res.status}).`);
  return res.json();
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 4200);
}

const fmtMem = (b) => {
  const mb = b / 1048576;
  if (mb < 1024) return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`;
  return `${(mb / 1024).toFixed(1)} GB`;
};
const fmtCpu = (v) => (v <= 0 ? "0%" : v < 0.1 ? "0.1%" : `${v.toFixed(1)}%`);
const cpuHeat = (v) => (v < 0.5 ? 0 : v < 5 ? 1 : v < 20 ? 2 : 3);
const memHeat = (b) => {
  const f = b / (state.data?.summary.mem_total || 1);
  return f < 0.01 ? 0 : f < 0.04 ? 1 : f < 0.12 ? 2 : 3;
};
const letter = (t) => ((t || "?").match(/[A-Za-z0-9]/) || ["?"])[0].toUpperCase();
const tile = (o) => `<span class="tile">${o.icon ? `<img src="/icon/${esc(o.icon)}.png" alt="">` : esc(letter(o.title))}</span>`;
const pill = (close) => `<span class="pill ${close}">${close === "critical" ? icon("lock") : ""}${CLOSE_LABEL[close]}</span>`;

function walk(nodes, fn, depth = 0) {
  for (const n of nodes) {
    fn(n, depth);
    walk(n.children || [], fn, depth + 1);
  }
}

// ------------------------------------------------------------------ processes

function matches(g, q) {
  if (!q) return { hit: true, viaPart: false };
  const own = [g.title, g.what, g.exe, KIND_LABEL[g.kind], CLOSE_LABEL[g.close]].join(" ").toLowerCase().includes(q);
  let viaPart = false;
  walk(g.parts, (n) => {
    if (!viaPart && partText(n).includes(q)) viaPart = true;
  });
  return { hit: own || viaPart, viaPart: viaPart && !own };
}

function sortGroups(list) {
  const { key, dir } = state.sort;
  return list.sort((a, b) => {
    if (key === "name") return dir * a.title.localeCompare(b.title, undefined, { sensitivity: "base" });
    return dir * (b[key] - a[key]) || a.title.localeCompare(b.title);
  });
}

function groupRow(g, open) {
  const sub = esc(g.what) + (g.count > 1 ? ` · ${g.count} parts` : "");
  const flag = g.unusual.length ? `<span class="flag" title="Worth a look">${icon("alert")}Unusual</span>` : "";
  const sel = state.sel?.type === "group" && state.sel.id === g.id ? " sel" : "";
  return `<div class="row k-${g.kind}${sel}" data-group="${esc(g.id)}" tabindex="0">
    <div class="nm"><button class="chev${g.count > 1 ? "" : " none"}${open ? " open" : ""}" aria-label="Show parts">${icon("chev")}</button>${tile(g)}
      <div class="txt"><div class="t"><span class="tt">${esc(g.title)}</span>${raw(g.exe)}${flag}</div><div class="s">${sub}</div></div></div>
    <div class="cell h${cpuHeat(g.cpu)}">${fmtCpu(g.cpu)}</div>
    <div class="cell h${memHeat(g.mem)}">${fmtMem(g.mem)}</div>
    <div class="cell lft">${pill(g.close)}</div>
  </div>`;
}

function partText(n) {
  return [n.title, n.name, n.what, String(n.pid), (n.services || []).map((s) => `${s.title} ${s.display}`).join(" ")].join(" ").toLowerCase();
}
const raw = (name) => (name ? `<span class="raw">${esc(name)}</span>` : "");

function partRows(g, onlyMatches) {
  let html = "";
  walk(g.parts, (n, depth) => {
    if (onlyMatches && !partText(n).includes(state.query)) return;
    const sel = state.sel?.type === "part" && state.sel.pid === n.pid ? " sel" : "";
    const flag = n.unusual.length ? `<span class="flag">${icon("alert")}Unusual</span>` : "";
    html += `<div class="row part k-${n.kind}${sel}" data-pid="${n.pid}" data-group="${esc(g.id)}" tabindex="0">
      <div class="nm" style="padding-left:${38 + depth * 22}px">${tile(n)}
        <div class="txt"><div class="t"><span class="tt">${esc(n.title)}</span>${raw(n.name)}${flag}</div><div class="s">${esc(n.what)}</div></div></div>
      <div class="cell h${cpuHeat(n.cpu)}">${fmtCpu(n.cpu)}</div>
      <div class="cell h${memHeat(n.mem)}">${fmtMem(n.mem)}</div>
      <div class="cell lft"></div>
    </div>`;
  });
  return html;
}

function renderProcesses() {
  const d = state.data;
  if (!d) return;
  const s = d.summary;
  $("#cpuTotal").textContent = `${Math.round(s.cpu)}%`;
  $("#memTotal").textContent = `${Math.round(s.mem_pct)}%`;
  $("#memTotal").parentElement.title = `${fmtMem(s.mem_used)} of ${fmtMem(s.mem_total)} in use`;
  document.querySelectorAll("#procTable .th[data-sort]").forEach((th) => th.classList.toggle("sorted", th.dataset.sort === state.sort.key));

  const notice = $("#adminNotice");
  notice.hidden = s.admin || !s.hidden;
  $("#adminText").textContent = `Windows is hiding the details of ${s.hidden} processes. Restart as admin to see what they are.`;
  $("#checking").textContent = s.checking ? `Checking signatures and icons for ${s.checking} files…` : "";

  const q = state.query;
  const base = d.groups.map((g) => ({ g, m: matches(g, q) })).filter((x) => x.m.hit);
  const closeOk = (g) => !state.close || g.close === state.close;
  const kindOk = (g) => !state.kind || g.kind === state.kind;
  const visible = base.filter((x) => closeOk(x.g));
  const counts = {};
  visible.forEach(({ g }) => (counts[g.kind] = (counts[g.kind] || 0) + 1));
  const closeCounts = {};
  base.filter((x) => kindOk(x.g)).forEach(({ g }) => (closeCounts[g.close] = (closeCounts[g.close] || 0) + 1));

  $("#chips").innerHTML = `<button class="chip all${state.kind ? "" : " on"}" data-kind="">All apps <b>${visible.length}</b></button>` +
    d.kinds.filter((k) => counts[k.id]).map((k) =>
      `<button class="chip k-${k.id}${state.kind === k.id ? " on" : ""}" data-kind="${k.id}">${esc(k.label)} <b>${counts[k.id]}</b></button>`).join("");
  $("#closeChips").innerHTML = `<span class="chip-label">If you close it</span>` +
    ["safe", "care", "keep", "critical"].filter((c) => closeCounts[c] || state.close === c).map((c) =>
      `<button class="chip c-${c}${state.close === c ? " on" : ""}" data-close="${c}">${c === "critical" ? icon("lock") : ""}${CLOSE_LABEL[c]} <b>${closeCounts[c] || 0}</b></button>`).join("");

  let html = "";
  for (const k of d.kinds) {
    if (state.kind && state.kind !== k.id) continue;
    const list = sortGroups(visible.filter((x) => x.g.kind === k.id).map((x) => x.g));
    if (!list.length) continue;
    const closed = state.collapsed.has(k.id) && !q;
    html += `<div class="section k-${k.id}${closed ? " closed" : ""}" data-section="${k.id}">${icon("chev")}<span class="dot"></span>${esc(k.label)} <span class="count">(${list.length})</span></div>`;
    if (closed) continue;
    for (const g of list) {
      const viaPart = visible.find((x) => x.g === g).m.viaPart;
      const open = state.expanded.has(g.id) || viaPart;
      html += groupRow(g, open);
      if (open && g.count > 1) html += partRows(g, viaPart && !state.expanded.has(g.id));
    }
  }
  $("#rows").innerHTML = html || `<div class="empty">${q ? `Nothing matches “${esc(q)}”.` : "Nothing matches these filters."}</div>`;
  updateButtons();
  if (state.sel && (state.sel.type === "group" || state.sel.type === "part")) renderDetails(false);
}

function findGroup(id) {
  return state.data?.groups.find((g) => g.id === id);
}
function findPart(pid) {
  for (const g of state.data?.groups || []) {
    let found = null;
    walk(g.parts, (n) => { if (n.pid === pid) found = n; });
    if (found) return { g, n: found };
  }
  return null;
}
function subtreePids(n) {
  const out = [];
  walk([n], (x) => out.push(x.pid));
  return out;
}

function selection() {
  const s = state.sel;
  if (!s) return null;
  if (s.type === "group") {
    const g = findGroup(s.id);
    return g && { title: g.title, pids: g.pids, close: g.close, note: g.note, path: g.path, count: g.count, kind: g.kind };
  }
  if (s.type === "part") {
    const f = findPart(s.pid);
    if (!f) return null;
    const pids = subtreePids(f.n);
    const close = f.n.pid === f.g.parts[0]?.pid ? f.g.close : (["critical", "keep"].includes(f.g.close) ? f.g.close : "care");
    return { title: f.n.title, pids, close, note: f.g.note, path: f.n.path, count: pids.length, kind: f.n.kind };
  }
  return null;
}

function updateButtons() {
  const sel = state.view === "processes" ? selection() : null;
  $("#endBtn").disabled = !sel;
  $("#openLocBtn").disabled = !sel?.path;
}

// ------------------------------------------------------------------ details panel

function sigText(o) {
  switch (o.signature) {
    case "Valid": return `<span class="sig-ok">Signed by ${esc(o.signer || "a trusted publisher")}</span>`;
    case "NotSigned": return `<span class="sig-no">Not signed. Common for small tools; it doesn't prove anything either way.</span>`;
    case "HashMismatch": return `<span class="sig-no">Signed, but the file was changed after signing.</span>`;
    case "NotTrusted": case "UnknownError": return `<span class="sig-no">Signed${o.signer ? ` by ${esc(o.signer)}` : ""}, but Windows doesn't trust the signature.</span>`;
    case "Checking": return "Checking…";
    case null: case undefined: return "Unknown (Windows hides the file)";
    default: return esc(o.signature);
  }
}

function factRows(rows) {
  return `<dl class="facts">${rows.filter(([, v]) => v).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
}

function headBlock(o, kindLabel) {
  return `<div class="d-head k-${o.kind}">${tile(o)}<div><h2>${esc(o.title)}</h2><span class="d-kind">${esc(kindLabel || KIND_LABEL[o.kind] || "")}</span></div>
    <button class="d-close" data-act="close-details" aria-label="Close details">${icon("x")}</button></div>`;
}

function pathFact(o) {
  if (!o.path) return null;
  return `${esc(o.folder || "")}<div class="mono">${esc(o.path)}</div>`;
}

function notesBlock(notes) {
  if (!notes.length) return "";
  return `<div class="d-note"><b>Worth a look</b>${notes.map((n) => `<div>${esc(n)}</div>`).join("")}<div style="opacity:.8">This is information to check, not a verdict.</div></div>`;
}

function renderDetails(scrollTop = true) {
  const box = $("#details");
  const s = state.sel;
  let html = "";
  if (s?.type === "group") {
    const g = findGroup(s.id);
    if (!g) return closeDetails();
    let tree = "";
    if (g.count > 1) {
      walk(g.parts, (n, depth) => {
        tree += `<div data-pid="${n.pid}"><span style="padding-left:${depth * 14}px">${esc(n.title)}</span><span>${fmtMem(n.mem)}</span></div>`;
      });
    }
    html = headBlock(g) + `<p class="d-what">${esc(g.what)}</p>` + notesBlock(g.unusual) +
      `<div class="d-block"><span class="d-label">If you close it</span><div>${pill(g.close)}</div><div>${esc(g.note)}</div></div>` +
      `<div class="d-block"><span class="d-label">Facts</span>${factRows([
        ["Started by", esc(g.started_by)],
        ["Made by", esc(g.company || g.signer || "Not stated in the file")],
        ["Signature", sigText(g)],
        ["Lives in", pathFact(g) || (g.hidden ? "Hidden by Windows" : "")],
        ["Name from", esc(g.source)],
        ["Using now", `${fmtCpu(g.cpu)} CPU · ${fmtMem(g.mem)} memory`],
        ["Parts", g.count > 1 ? `${g.count} processes` : `1 process (PID ${g.pids[0]})`],
      ])}</div>` +
      (tree ? `<div class="d-block"><span class="d-label">Its parts</span><div class="ptree">${tree}</div></div>` : "") +
      actionsBlock(g.path, g.exe, g.close);
  } else if (s?.type === "part") {
    const f = findPart(s.pid);
    if (!f) return closeDetails();
    const n = f.n;
    html = headBlock(n) + `<p class="d-what">${esc(n.what)}</p>` + notesBlock(n.unusual) +
      `<div class="d-block"><span class="d-label">Facts</span>${factRows([
        ["Part of", esc(f.g.title)],
        ["File", `<span class="mono">${esc(n.name)}</span>`],
        ["Process ID", String(n.pid)],
        ["Signature", sigText(n)],
        ["Lives in", pathFact(n) || "Hidden by Windows"],
        ["Name from", esc(n.source)],
        ["Using now", `${fmtCpu(n.cpu)} CPU · ${fmtMem(n.mem)} memory`],
      ])}</div>` +
      ((n.services || []).length ? `<div class="d-block"><span class="d-label">Windows helpers inside</span><div class="svc-list">${n.services.map((v) =>
        `<div><b>${esc(v.title)}</b><span>${esc(v.what)}</span><span class="raw">${esc(v.display)}</span></div>`).join("")}</div></div>` : "") +
      `<div class="d-block"><span class="d-label">Started with</span><div class="cmd mono" id="cmdline">Loading…</div></div>` +
      actionsBlock(n.path, n.name, null);
    if (scrollTop || !state.cmdFor || state.cmdFor !== n.pid) loadCmd(n.pid);
  } else if (s?.type === "startup") {
    const e = state.startup?.items.find((x) => x.id === s.id);
    if (!e) return closeDetails();
    html = headBlock(e) + `<p class="d-what">${esc(e.what)}</p>` +
      `<div class="d-block"><span class="d-label">Facts</span>${factRows([
        ["Status", e.enabled ? "Turned on: starts when you sign in" : "Turned off: won't start by itself"],
        ["Running now", e.running ? "Yes" : "No"],
        ["Starts for", esc(e.who)],
        ["Added in", esc(e.where)],
        ["Made by", esc(e.company || e.signer || "Not stated in the file")],
        ["Signature", e.exists ? sigText(e) : "File not found"],
        ["Lives in", pathFact(e)],
      ])}</div>` +
      `<div class="d-block"><span class="d-label">Start command</span><div class="cmd mono">${esc(e.command)}</div></div>` +
      `<div class="d-actions">${e.exists ? `<button class="btn" data-act="open-loc" data-path="${esc(e.path)}">${icon("folder")}Open file location</button>` : ""}
        <button class="btn" data-act="web" data-q="${esc(e.title)}">${icon("web")}Search the web</button>
        <button class="btn" data-act="startup-settings">${icon("settings")}Turn on or off</button></div>`;
  } else if (s?.type === "service") {
    const v = state.services?.items.find((x) => x.id === s.id);
    if (!v) return closeDetails();
    const o = { ...v, kind: v.windows ? "windows" : "other" };
    html = headBlock(o, v.windows ? "Part of Windows" : "From another company") +
      `<p class="d-what">${esc(v.what)}</p>` +
      (v.description && v.plain ? `<div class="d-block"><span class="d-label">Windows' own description</span><div class="s" style="white-space:normal">${esc(v.description)}</div></div>` : "") +
      `<div class="d-block"><span class="d-label">Facts</span>${factRows([
        ["Windows calls it", esc(v.display)],
        ["Status", esc(v.state)],
        ["Starts", esc(v.start)],
        ["Made by", esc(v.made_by)],
        ["Runs inside", v.runs_in ? `${esc(v.runs_in)} (PID ${v.pid})` : (v.pid ? `PID ${v.pid}` : "Not running")],
        ["Service name", `<span class="mono">${esc(v.name)}</span>`],
        ["Program", pathFact(v)],
      ])}</div>` +
      `<div class="d-actions">${v.path ? `<button class="btn" data-act="open-loc" data-path="${esc(v.path)}">${icon("folder")}Open file location</button>` : ""}
        <button class="btn" data-act="web" data-q="${esc(v.title + " Windows service")}">${icon("web")}Search the web</button></div>`;
  } else {
    return closeDetails();
  }
  const keepScroll = box.scrollTop;
  const cmd = $("#cmdline")?.textContent;
  box.innerHTML = html;
  box.hidden = false;
  if (cmd && $("#cmdline") && cmd !== "Loading…") $("#cmdline").textContent = cmd;
  box.scrollTop = scrollTop ? 0 : keepScroll;
}

function actionsBlock(path, exe, close) {
  return `<div class="d-actions">
    <button class="btn danger" data-act="end">${icon("x")}End task</button>
    ${path ? `<button class="btn" data-act="open-loc" data-path="${esc(path)}">${icon("folder")}Open file location</button>` : ""}
    <button class="btn" data-act="web" data-q="${esc(exe)} process">${icon("web")}Search the web</button></div>`;
}

async function loadCmd(pid) {
  state.cmdFor = pid;
  try {
    const r = await api(`/api/process/${pid}`);
    const el = $("#cmdline");
    if (el && state.sel?.pid === pid) el.textContent = r.cmdline || "Windows doesn't show this one's start command.";
  } catch (e) { /* panel shows Loading… until next refresh */ }
}

function closeDetails() {
  state.sel = null;
  $("#details").hidden = true;
  document.querySelectorAll(".row.sel").forEach((r) => r.classList.remove("sel"));
  updateButtons();
}

function select(sel) {
  state.sel = sel;
  document.querySelectorAll(".row.sel").forEach((r) => r.classList.remove("sel"));
  const q = sel.type === "part" ? `.row[data-pid="${sel.pid}"]` : sel.type === "group" ? `.row[data-group="${CSS.escape(sel.id)}"]:not(.part)` : `.row[data-id="${CSS.escape(sel.id)}"]`;
  document.querySelector(q)?.classList.add("sel");
  renderDetails(true);
  updateButtons();
}

// ------------------------------------------------------------------ end task

function modal(title, bodyHtml, actions) {
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = bodyHtml;
  $("#modalActions").innerHTML = actions.map((a, i) => `<button class="btn ${a.cls || ""}" data-i="${i}">${a.label}</button>`).join("");
  $("#modal").hidden = false;
  $("#modalActions").onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    $("#modal").hidden = true;
    actions[+b.dataset.i].run?.();
  };
  $("#modalActions button:last-child").focus();
}

function confirmEnd() {
  const sel = selection();
  if (!sel) return;
  const parts = sel.count > 1 ? `<p>${sel.count} processes will close.</p>` : "";
  if (sel.close === "critical") {
    modal(`Windows needs ${sel.title}`, `<p>${esc(sel.note)}</p>`, [{ label: "OK", cls: "primary" }]);
    return;
  }
  const lead = sel.close === "keep" ? `<p><b>This is part of Windows or a device.</b></p>` : "";
  modal(`End ${sel.title}?`, `${lead}<p>${esc(sel.note)}</p>${parts}`, [
    { label: "Cancel" },
    { label: sel.close === "keep" ? "End anyway" : "End task", cls: "danger solid", run: () => doEnd(sel) },
  ]);
}

async function doEnd(sel) {
  try {
    const r = await api("/api/end", { pids: sel.pids });
    if (r.failed.length) {
      const why = [...new Set(r.failed.map((f) => f.reason))].join(" ");
      toast(r.ended ? `Ended ${r.ended} of ${sel.pids.length} parts of ${sel.title}. ${why}` : `${sel.title} wasn't ended. ${why}`);
    } else {
      toast(`Ended ${sel.title}`);
    }
    closeDetails();
    await refresh(true);
  } catch (e) {
    toast(e.message);
  }
}

// ------------------------------------------------------------------ startup + services

async function loadStartup() {
  $("#startupRows").innerHTML = `<div class="empty">Reading startup apps…</div>`;
  try {
    state.startup = await api("/api/startup");
    renderStartup();
    if (state.startup.checking) setTimeout(() => state.view === "startup" && api("/api/startup").then((r) => { state.startup = r; renderStartup(); }), 4000);
  } catch (e) {
    $("#startupRows").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

function renderStartup() {
  const q = state.query;
  const items = (state.startup?.items || []).filter((e) => !q || [e.title, e.what, e.name, e.command].join(" ").toLowerCase().includes(q));
  $("#startupRows").innerHTML = items.map((e) => `<div class="row startup k-${e.kind}${state.sel?.id === e.id ? " sel" : ""}" data-id="${esc(e.id)}" data-type="startup" tabindex="0" style="grid-template-columns:minmax(0,1fr) 110px 110px 150px">
      <div class="nm"><span class="chev none"></span>${tile(e)}<div class="txt"><div class="t"><span class="tt">${esc(e.title)}</span>${raw(e.file)}</div><div class="s">${esc(e.what)}</div></div></div>
      <div class="cell lft"><span class="pill ${e.enabled ? "safe" : "neutral"}">${e.enabled ? "On" : "Off"}</span></div>
      <div class="cell lft">${e.running ? "Yes" : "No"}</div>
      <div class="cell lft">${esc(e.who)}</div></div>`).join("") || `<div class="empty">${q ? `Nothing matches “${esc(q)}”.` : "No startup apps found."}</div>`;
}

async function loadServices(quiet) {
  if (!quiet) $("#svcRows").innerHTML = `<div class="empty">Reading services…</div>`;
  try {
    state.services = await api("/api/services");
    renderServices();
    if (state.sel?.type === "service") renderDetails(false);
  } catch (e) {
    $("#svcRows").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

function renderServices() {
  const all = state.services?.items || [];
  const q = state.query;
  const filters = { running: (v) => v.state === "Running", all: () => true, third: (v) => !v.windows };
  const labels = { running: "Running", all: "All", third: "Not part of Windows" };
  const searched = all.filter((v) => !q || [v.title, v.name, v.display, v.what, v.made_by, v.runs_in].join(" ").toLowerCase().includes(q));
  $("#svcChips").innerHTML = Object.keys(filters).map((k) =>
    `<button class="chip ${k === "third" ? "k-other" : "all"}${state.svcFilter === k ? " on" : ""}" data-svc="${k}">${labels[k]} <b>${searched.filter(filters[k]).length}</b></button>`).join("");
  const items = searched.filter(filters[state.svcFilter]);
  $("#svcRows").innerHTML = items.map((v) => `<div class="row k-${v.windows ? "windows" : "other"}${state.sel?.id === v.id ? " sel" : ""}" data-id="${esc(v.id)}" data-type="service" tabindex="0" style="grid-template-columns:minmax(0,1fr) 100px 150px 190px">
      <div class="nm"><span class="chev none"></span>${tile({ title: v.title })}<div class="txt"><div class="t"><span class="tt">${esc(v.title)}</span>${raw(v.name)}</div><div class="s">${esc(v.what)}</div></div></div>
      <div class="cell lft"><span class="pill ${v.state === "Running" ? "safe" : "neutral"}">${esc(v.state)}</span></div>
      <div class="cell lft">${esc(v.start)}</div>
      <div class="cell lft" style="overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${v.runs_in ? esc(v.runs_in) : "—"}</div></div>`).join("") ||
    `<div class="empty">${q ? `Nothing matches “${esc(q)}”.` : "No services to show."}</div>`;
}

// ------------------------------------------------------------------ wiring

async function refresh(force) {
  if (state.busy && !force) return;
  state.busy = true;
  try {
    state.data = await api("/api/processes");
    renderProcesses();
  } catch (e) {
    $("#rows").innerHTML = `<div class="empty">${esc(e.message)} Close and reopen the app.</div>`;
  } finally {
    state.busy = false;
  }
}

function setView(v) {
  state.view = v;
  closeDetails();
  document.querySelectorAll(".rail-btn[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  document.querySelectorAll(".view").forEach((s) => (s.hidden = s.id !== `view-${v}`));
  if (v === "startup") loadStartup();
  if (v === "services") loadServices();
  if (v === "processes") refresh(true);
}

function isDark() {
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}
function paintThemeIcon() {
  $("#themeBtn use").setAttribute("href", isDark() ? "#i-sun" : "#i-moon");
}

document.addEventListener("click", (e) => {
  const t = e.target;
  const act = t.closest("[data-act]");
  if (act) {
    const a = act.dataset.act;
    if (a === "close-details") closeDetails();
    if (a === "end") confirmEnd();
    if (a === "open-loc") api("/api/open-location", { path: act.dataset.path }).then((r) => !r.ok && toast(r.reason)).catch((err) => toast(err.message));
    if (a === "web") api("/api/search-web", { q: act.dataset.q }).then(() => toast("Opened a web search in your browser"));
    if (a === "startup-settings") api("/api/open-startup-settings", {});
    return;
  }
  const ptree = t.closest(".ptree [data-pid]");
  if (ptree) return select({ type: "part", pid: +ptree.dataset.pid });

  const chip = t.closest("[data-kind]");
  if (chip) {
    state.kind = chip.dataset.kind && state.kind !== chip.dataset.kind ? chip.dataset.kind : null;
    return renderProcesses();
  }
  const closeChip = t.closest("[data-close]");
  if (closeChip) {
    state.close = state.close === closeChip.dataset.close ? null : closeChip.dataset.close;
    return renderProcesses();
  }
  const svc = t.closest("[data-svc]");
  if (svc) { state.svcFilter = svc.dataset.svc; return renderServices(); }

  const sec = t.closest("[data-section]");
  if (sec) {
    const id = sec.dataset.section;
    state.collapsed.has(id) ? state.collapsed.delete(id) : state.collapsed.add(id);
    return renderProcesses();
  }
  const sortBtn = t.closest(".th[data-sort]");
  if (sortBtn) {
    const key = sortBtn.dataset.sort;
    state.sort = state.sort.key === key ? { key, dir: -state.sort.dir } : { key, dir: 1 };
    return renderProcesses();
  }
  const chev = t.closest(".chev:not(.none)");
  if (chev) {
    const id = chev.closest(".row").dataset.group;
    state.expanded.has(id) ? state.expanded.delete(id) : state.expanded.add(id);
    return renderProcesses();
  }
  const row = t.closest(".row");
  if (row) {
    if (row.dataset.pid) return select({ type: "part", pid: +row.dataset.pid });
    if (row.dataset.group) return select({ type: "group", id: row.dataset.group });
    if (row.dataset.type) return select({ type: row.dataset.type, id: row.dataset.id });
  }
});

document.addEventListener("dblclick", (e) => {
  const row = e.target.closest(".row[data-group]:not(.part)");
  if (!row || e.target.closest(".chev")) return;
  const id = row.dataset.group;
  state.expanded.has(id) ? state.expanded.delete(id) : state.expanded.add(id);
  renderProcesses();
});

document.addEventListener("keydown", (e) => {
  if (!$("#modal").hidden) {
    if (e.key === "Escape") $("#modal").hidden = true;
    return;
  }
  if (e.key === "Escape" && state.sel) closeDetails();
  const row = e.target.closest?.(".row");
  if (row && e.key === "Enter") row.click();
  if (row && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
    e.preventDefault();
    const next = e.key === "ArrowDown" ? row.nextElementSibling : row.previousElementSibling;
    const target = next?.classList.contains("row") ? next : (e.key === "ArrowDown" ? next?.nextElementSibling : next?.previousElementSibling);
    if (target?.classList.contains("row")) { target.focus(); target.click(); }
  }
  if (e.key === "Delete" && state.view === "processes" && selection() && e.target.tagName !== "INPUT") confirmEnd();
});

$("#search").addEventListener("input", (e) => {
  state.query = e.target.value.trim().toLowerCase();
  if (state.view === "processes") renderProcesses();
  if (state.view === "startup") renderStartup();
  if (state.view === "services") renderServices();
});
document.querySelectorAll(".rail-btn[data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
$("#railToggle").addEventListener("click", () => $(".app").classList.toggle("wide-rail"));
$("#themeBtn").addEventListener("click", () => {
  const next = isDark() ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("ppv-theme", next); } catch (err) { /* not saved, still applied */ }
  paintThemeIcon();
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paintThemeIcon);
$("#endBtn").addEventListener("click", confirmEnd);
$("#openLocBtn").addEventListener("click", () => {
  const sel = selection();
  if (sel?.path) api("/api/open-location", { path: sel.path }).then((r) => !r.ok && toast(r.reason));
});
$("#elevateBtn").addEventListener("click", async () => {
  try {
    const r = await api("/api/elevate", {});
    toast(r.ok ? "Opening as admin. This window will close." : r.reason);
  } catch (e) { toast(e.message); }
});
$("#startupRefresh").addEventListener("click", loadStartup);
$("#startupSettings").addEventListener("click", () => api("/api/open-startup-settings", {}));

paintThemeIcon();
refresh(true);
setInterval(() => {
  if (document.hidden || !$("#modal").hidden) return;
  if (state.view === "processes") refresh();
}, 2000);
setInterval(() => {
  if (!document.hidden && state.view === "services") loadServices(true);
}, 10000);
