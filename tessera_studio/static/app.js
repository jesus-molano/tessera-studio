// Tessera Studio SPA. No dependencies, no network beyond this loopback server.
// The CSP forbids inline style attributes, so dynamic values travel as
// `data-v="--prop:value|--prop:value"` and are applied through CSSOM.

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const app = $("#app");
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");

// Icons ----------------------------------------------------------------------
const ICONS = {
  arrow: "M5 12h14M13 6l6 6-6 6",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-3.5-3.5",
  layers: "m12 3 9 5-9 5-9-5 9-5zM3 13l9 5 9-5",
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
  scale: "M12 3v18M5 7h14M5 7l-3 7a4 4 0 0 0 6 0zM19 7l-3 7a4 4 0 0 0 6 0z",
  gauge: "M12 14l4-4M4 18a9 9 0 1 1 16 0",
  alert: "M12 9v4M12 17h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  link: "M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1",
  check: "M20 6 9 17l-5-5",
  git: "M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9",
  clock: "M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  box: "M21 8 12 3 3 8v8l9 5 9-5zM3 8l9 5 9-5M12 13v8",
  compare: "M8 3 4 7l4 4M4 7h16M16 21l4-4-4-4M20 17H4",
  inbox: "M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z",
};
const icon = (name, cls = "icon") => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICONS[name]}"/></svg>`;

// Formatting -----------------------------------------------------------------
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const nf = new Intl.NumberFormat("en");
const pct = (value) => `${Math.round(value * 100)}%`;
const short = (sha) => (sha ? String(sha).slice(0, 8) : "—");
const vars = (map) => `data-v="${esc(Object.entries(map).map(([k, v]) => `${k}:${v}`).join("|"))}"`;
const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
function ago(epochSeconds) {
  const diff = epochSeconds * 1000 - Date.now();
  const units = [["year", 31536e6], ["month", 2592e6], ["day", 864e5], ["hour", 36e5], ["minute", 6e4]];
  for (const [unit, ms] of units) if (Math.abs(diff) >= ms) return rtf.format(Math.round(diff / ms), unit);
  return "just now";
}
function highlight(text, query) {
  const source = String(text ?? "");
  if (!query) return esc(source);
  const index = source.toLowerCase().indexOf(query);
  if (index < 0) return esc(source);
  return esc(source.slice(0, index)) + `<mark>${esc(source.slice(index, index + query.length))}</mark>` + esc(source.slice(index + query.length));
}

// Data -----------------------------------------------------------------------
const state = { roots: [], projects: null, details: new Map(), decisions: new Map(), ui: new Map() };

async function api(path) {
  const response = await fetch(path, { cache: "no-store", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(response.status === 404 ? "Not found" : `Server responded ${response.status}`);
  return response.json();
}
async function loadProjects(force = false) {
  if (state.projects && !force) return state.projects;
  const data = await api("/api/projects");
  state.roots = data.roots;
  state.projects = data.projects;
  return state.projects;
}
async function loadProject(id) {
  if (!state.details.has(id)) state.details.set(id, decorate(await api(`/api/projects/${encodeURIComponent(id)}`)));
  return state.details.get(id);
}
async function loadDecision(id, task) {
  const key = `${id}/${task}`;
  if (!state.decisions.has(key)) state.decisions.set(key, await api(`/api/projects/${encodeURIComponent(id)}/decisions/${encodeURIComponent(task)}`));
  return state.decisions.get(key);
}
function ui(id) {
  if (!state.ui.has(id)) state.ui.set(id, { query: "", kinds: new Set(), inventoryKind: "all", inventoryQuery: "" });
  return state.ui.get(id);
}

// Derived lookups: stable colors per kind, entry maps, option labels.
function decorate(project) {
  // The server normalizes shapes; keep the client safe against older servers too.
  for (const e of project.catalog) {
    e.kind = typeof e.kind === "string" && e.kind ? e.kind : "unknown";
    e.source = typeof e.source === "string" ? e.source : "";
    for (const key of ["usages", "tags", "constraints"]) if (!Array.isArray(e[key])) e[key] = [];
  }
  const kinds = Object.entries(project.catalog.reduce((acc, e) => ((acc[e.kind] = (acc[e.kind] || 0) + 1), acc), {}))
    .sort((a, b) => b[1] - a[1]);
  project.kindList = kinds;
  project.kindColor = Object.fromEntries(kinds.map(([kind], i) => [kind, i < 5 ? `var(--kind-${i + 1})` : "var(--kind-other)"]));
  project.byId = new Map(project.catalog.map((e) => [e.id, e]));
  project.bySource = new Map(project.catalog.map((e) => [e.source, e]));
  project.gaps = project.catalog.filter((e) => !e.usages?.length).length;
  return project;
}
const kindColor = (project, kind) => project.kindColor?.[kind] || "var(--kind-other)";
const text = (value) => (typeof value === "string" ? value : "");
function optionInfo(project, option) {
  const value = text(option);
  if (value === "create") return { label: "create", color: "var(--opt-create)" };
  if (value === "insufficient_evidence") return { label: "insufficient evidence", color: "var(--opt-insufficient)" };
  const match = /^(reuse|modify|wrap):(.+)$/.exec(value);
  if (!match) return { label: value || "—", color: "var(--kind-other)" };
  const entry = project.byId.get(match[2]);
  return { label: `${match[1]} · ${entry?.name || match[2]}`, color: `var(--opt-${match[1]})`, entry: entry?.id };
}
function relation(value) {
  const verdict = text(value);
  if (verdict.startsWith("agree")) return { cls: "ok", label: "Agrees with provider" };
  if (verdict.startsWith("disagree")) return { cls: "warn", label: "Overrides provider" };
  return { cls: "muted", label: "No verdict" };
}
const providerOption = (d) => (d.provider_primary ? `${text(d.provider_action)}:${d.provider_primary}` : d.provider_action);
const providerName = (d) => text(d.model) || text(d.provider) || "unknown";

// Live region: route titles and result counts only, debounced.
const announcer = $("#announcer");
let announceTimer;
function announce(message) {
  clearTimeout(announceTimer);
  announceTimer = setTimeout(() => {
    announcer.textContent = "";
    requestAnimationFrame(() => (announcer.textContent = message));
  }, 350);
}

// Routing --------------------------------------------------------------------
function parseRoute() {
  let parts;
  try {
    parts = location.hash.split("?")[0].replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  } catch {
    return { view: "invalid" };
  }
  if (parts[0] !== "p" || !parts[1]) return { view: "home" };
  return { view: parts[2] || "overview", project: parts[1], item: parts[3] || null };
}
const href = (project, view = "overview", item) =>
  `#/p/${encodeURIComponent(project)}${view === "overview" && !item ? "" : `/${view}`}${item ? `/${encodeURIComponent(item)}` : ""}`;
const hashParam = (name) => new URLSearchParams(location.hash.split("?")[1] || "").get(name);

let current = { key: null };
let navToken = 0;
async function render() {
  // Every navigation takes a token; a slower, older render must not overwrite a newer route.
  const token = ++navToken;
  const route = parseRoute();
  const key = route.view === "home" || route.view === "invalid" ? route.view : `${route.project}/${route.view}`;
  // Same master-detail view: update the detail pane in place.
  if (key === current.key && (route.view === "catalog" || route.view === "decisions")) {
    current.route = route;
    if (route.view === "decisions") return selectDecision(route.item);
    const project = state.details.get(route.project);
    if (project && applyKindParam(project)) renderEntryList(true);
    return selectEntry(route.item);
  }
  let html;
  let failure = null;
  try {
    if (route.view === "invalid") throw new Error("This address is not valid");
    if (route.view === "home") html = await homeView();
    else {
      await loadProjects();
      const project = await loadProject(route.project);
      html = shell(project, route, await projectView(project, route));
    }
  } catch (error) {
    failure = error.message;
    html = errorView(error);
  }
  if (token !== navToken) return;
  const first = current.key === null;
  current = { key, route };
  swap(() => {
    if (token !== navToken) return;
    app.innerHTML = html;
    hydrate(app);
    afterRender(route, first);
  });
  const label = updateSwitcher(route);
  if (!first) announce(failure || label);
}
function swap(update) {
  if (document.startViewTransition && !reducedMotion.matches) document.startViewTransition(update);
  else update();
}

function hydrate(root) {
  for (const el of $$("[data-v]", root)) {
    for (const pair of el.dataset.v.split("|")) {
      const at = pair.indexOf(":");
      if (at > 0) el.style.setProperty(pair.slice(0, at), pair.slice(at + 1));
    }
  }
  for (const el of $$("[data-count]", root)) countUp(el, Number(el.dataset.count));
}
function countUp(el, target) {
  if (reducedMotion.matches || !Number.isFinite(target) || target === 0) return (el.textContent = nf.format(target));
  const start = performance.now();
  const duration = 700;
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    el.textContent = nf.format(Math.round(target * (1 - Math.pow(1 - t, 3))));
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
function afterRender(route, first) {
  moveIndicator(first);
  if (route.view === "catalog") { renderEntryList(); selectEntry(route.item, { initial: true }); }
  if (route.view === "decisions") selectDecision(route.item, true);
  if (route.view === "inventory") renderInventory();
  if (first) return;
  window.scrollTo({ top: 0, behavior: "instant" });
  // Move focus to the new page heading so keyboard and screen reader users start there.
  ($("h1.title", app) || app).focus({ preventScroll: true });
}
function moveIndicator(instant) {
  const active = $(".tab[aria-current='page']");
  const bar = $(".tab-indicator");
  if (!active || !bar) return;
  if (instant) bar.style.transition = "none";
  bar.style.setProperty("--x", `${active.offsetLeft}px`);
  bar.style.setProperty("--w", `${active.offsetWidth}px`);
  if (instant) requestAnimationFrame(() => (bar.style.transition = ""));
}

// Views ----------------------------------------------------------------------
async function homeView() {
  const projects = await loadProjects();
  const cards = projects.map((p, i) => {
    const total = p.kinds.reduce((sum, [, n]) => sum + n, 0) || 1;
    const top = p.kinds.slice(0, 5);
    const rest = p.kinds.slice(5).reduce((sum, [, n]) => sum + n, 0);
    const stack = [...top, ...(rest ? [["other", rest]] : [])].map(([kind, n], k) =>
      `<i title="${esc(kind)}: ${n}" ${vars({ "--f": n / total, "--c": k < 5 ? `var(--kind-${k + 1})` : "var(--kind-other)", "--i": k })}></i>`).join("");
    return `<a class="card project-card rise" href="${href(p.id)}" ${vars({ "--i": i })}>
      <div>
        <h2><span>${esc(p.name)}</span><span class="project-arrow">${icon("arrow")}</span></h2>
        <div class="project-path" title="${esc(p.repo_path || p.store)}">${esc(p.repo_path || p.id)}</div>
      </div>
      ${statusPill(p)}
      <div class="stats">
        <div class="stat"><b>${nf.format(p.entries)}</b><span>entries</span></div>
        <div class="stat"><b>${nf.format(p.files)}</b><span>files</span></div>
        <div class="stat"><b>${nf.format(p.decisions)}</b><span>decisions</span></div>
      </div>
      ${p.kinds.length ? `<div class="stack" aria-hidden="true">${stack}</div>` : ""}
      <div class="meta-row">
        <span>${icon("git")} ${esc(short(p.revision))}</span>
        <span>${icon("clock")} updated ${esc(ago(p.updated))}</span>
      </div>
    </a>`;
  }).join("");
  return `<div class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">Local stores</div>
        <h1 class="title" tabindex="-1">Tessera projects</h1>
        <p class="lede">Component and utility catalogs curated for each repository, with the reuse decisions the provider (for example Jev) and the agent made on top of them. Everything is read from this machine; nothing is uploaded.</p>
      </div>
    </div>
    ${projects.length ? `<div class="grid projects">${cards}</div>` : `<div class="card empty rise">${icon("inbox")}
      <b>No Tessera projects found</b>
      <span>Initialize one with <code>tessera.py init --repo PROJECT</code>, or start Studio with <code>--store PATH</code>.</span>
      <div class="meta-row">${state.roots.map((r) => `<span class="mono">${esc(r)}</span>`).join("")}</div></div>`}
  </div>`;
}

function statusPill(p) {
  if (!p.initialized) {
    return p.files
      ? `<span class="pill warn">Initializing · ${nf.format(p.reviewed || 0)}/${nf.format(p.files)} reviewed</span>`
      : `<span class="pill muted">Not initialized</span>`;
  }
  return p.finalized ? `<span class="pill ok">Finalized at ${esc(short(p.revision))}</span>` : `<span class="pill warn">Finalization pending</span>`;
}

function shell(project, route, body) {
  const tabs = [
    ["overview", "Overview", "gauge", null],
    ["catalog", "Catalog", "grid", project.catalog.length],
    ["inventory", "Inventory", "file", project.inventory.length],
    ["decisions", "Decisions", "scale", project.decision_list.length],
  ].map(([view, label, ic, count]) => `<a class="tab" href="${href(project.id, view)}" ${route.view === view ? 'aria-current="page"' : ""}>
      ${icon(ic)} ${label}${count !== null ? ` <span class="count">${nf.format(count)}</span>` : ""}</a>`).join("");
  return `<div class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">Project</div>
        <h1 class="title" tabindex="-1">${esc(project.name)}</h1>
        <div class="meta-row">
          ${statusPill(project)}
          ${project.repo_path ? `<span>${icon("folder")} <span class="mono">${esc(project.repo_path)}</span></span>` : ""}
          <span>${icon("clock")} reviewed ${esc(project.reviewed_on || "never")}</span>
        </div>
      </div>
    </div>
    <nav class="tabs" aria-label="Project views">${tabs}<span class="tab-indicator" aria-hidden="true"></span></nav>
    ${body}
  </div>`;
}

async function projectView(project, route) {
  if (route.view === "catalog") return catalogView(project);
  if (route.view === "inventory") return inventoryView(project);
  if (route.view === "decisions") return decisionsView(project);
  return overviewView(project);
}

function barList(rows, { format = (v) => nf.format(v), mono = false, action } = {}) {
  const max = Math.max(...rows.map((r) => r.value), 1e-9);
  return `<div class="bars">${rows.map((r, i) => {
    const inner = `<span class="label ${mono ? "mono" : ""}">${r.dot ? `<i class="kind-dot" ${vars({ "--c": r.color })}></i>` : ""}<span title="${esc(r.title || r.label)}">${esc(r.label)}</span></span>
      <span class="track"><span class="fill" ${vars({ "--w": `${(r.value / max) * 100}%`, "--c": r.color || "var(--accent)", "--i": i })}></span></span>
      <span class="value">${format(r.value)}</span>`;
    return r.href ? `<a class="bar-row" href="${r.href}">${inner}</a>` : action && r.data ? `<button class="bar-row" type="button" data-action="${action}" data-arg="${esc(r.data)}">${inner}</button>` : `<div class="bar-row">${inner}</div>`;
  }).join("")}</div>`;
}

function overviewView(project) {
  if (!project.initialized) {
    return `<div class="card empty rise">${icon("inbox")}<b>No catalog yet</b><span>Run <code>tessera.py status --repo PROJECT</code> and follow its <code>next_action</code>.</span></div>`;
  }
  const inventoryKinds = Object.entries(project.inventory.reduce((acc, f) => ((acc[f.kind] = (acc[f.kind] || 0) + 1), acc), {})).sort((a, b) => b[1] - a[1]);
  const invColor = { catalogued: "var(--accent)", supporting: "var(--code-400)", excluded: "var(--neutral-600)", protected: "var(--danger)", pending: "var(--warning)" };
  const invTotal = project.inventory.length || 1;
  const decisions = project.decision_list;
  const agree = decisions.filter((d) => relation(d.relation_to_provider).cls === "ok").length;
  const folders = Object.entries(project.catalog.reduce((acc, e) => {
    const key = e.source.split("/").slice(0, e.source.startsWith("app/") ? 2 : 1).join("/") || "(no source)";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {})).sort((a, b) => b[1] - a[1]).slice(0, 8);

  // Group tesserae by kind so the mosaic reads as a composition. The stagger
  // shrinks with the entry count so the whole mosaic settles within ~600 ms.
  let t = 0;
  const step = Math.min(4, 80 / Math.max(1, project.catalog.length));
  const tiles = project.kindList.flatMap(([kind]) => project.catalog.filter((e) => e.kind === kind).map((e) =>
    `<a class="tessera ${e.usages?.length ? "" : "gap"}" href="${href(project.id, "catalog", e.id)}" data-kind="${esc(e.kind)}"
      data-tip="${esc(e.name || e.id)}" data-tip-sub="${esc(`${e.kind} · ${e.source}`)}" aria-label="${esc(`${e.name || e.id}, ${e.kind}`)}"
      ${vars({ "--c": kindColor(project, e.kind), "--d": `${Math.round(t++ * step)}ms` })}></a>`)).join("");
  const legend = project.kindList.map(([kind, n]) =>
    `<button class="chip" type="button" data-action="mosaic-kind" data-arg="${esc(kind)}" aria-pressed="false"><i class="kind-dot" ${vars({ "--c": kindColor(project, kind) })}></i>${esc(kind)} <small>${n}</small></button>`).join("");

  return `<div class="grid cols-4">
      ${kpi(0, "Catalog entries", project.catalog.length, `${project.kindList.length} kinds`, "var(--code-400)", "grid")}
      ${kpi(1, "Inventory files", project.inventory.length, `${project.scope.length} in scope`, "var(--info)", "file")}
      ${kpi(2, "Usage gaps", project.gaps, "entries without a recorded consumer", "var(--warning)", "alert")}
      ${kpi(3, "Decisions", decisions.length, decisions.length ? `${agree} of ${decisions.length} agree with the provider` : "none yet", "var(--success)", "scale")}
    </div>
    <div class="grid cols-2 mt-16">
      <section class="card span-2 rise" ${vars({ "--i": 4 })}>
        <div class="card-head"><span class="card-title">${icon("grid")} Catalog mosaic</span><span class="hint">One tessera per entry · outlined = no recorded usage</span></div>
        <div class="mosaic" id="mosaic">${tiles}</div>
        <div class="chips mt-14">${legend}</div>
      </section>
      <section class="card rise" ${vars({ "--i": 5 })}>
        <div class="card-head"><span class="card-title">${icon("layers")} Entries by kind</span></div>
        ${barList(project.kindList.map(([kind, n]) => ({ label: kind, value: n, color: kindColor(project, kind), dot: true, href: `${href(project.id, "catalog")}?kind=${encodeURIComponent(kind)}` })))}
      </section>
      <section class="card rise" ${vars({ "--i": 6 })}>
        <div class="card-head"><span class="card-title">${icon("file")} Inventory review</span><span class="hint">${nf.format(project.inventory.length)} tracked files</span></div>
        <div class="stack">${inventoryKinds.map(([k, n], i) => `<i title="${esc(k)}: ${n}" ${vars({ "--f": n / invTotal, "--c": invColor[k] || "var(--kind-other)", "--i": i })}></i>`).join("")}</div>
        <div class="legend">${inventoryKinds.map(([k, n]) => `<span><i class="kind-dot" ${vars({ "--c": invColor[k] || "var(--kind-other)" })}></i>${esc(k)} <b>${nf.format(n)}</b></span>`).join("")}</div>
        <div class="card-head sub-head"><span class="card-title">${icon("folder")} Top folders</span></div>
        ${barList(folders.map(([f, n]) => ({ label: f, value: n, color: "var(--neutral-500)" })), { mono: true })}
      </section>
      <section class="card rise" ${vars({ "--i": 7 })}>
        <div class="card-head"><span class="card-title">${icon("scale")} Recent decisions</span><a class="hint link" href="${href(project.id, "decisions")}">View all</a></div>
        ${decisions.length ? decisions.slice(0, 4).map((d) => decisionLine(project, d)).join("") : `<p class="hint">No decisions recorded.</p>`}
      </section>
      <section class="card rise" ${vars({ "--i": 8 })}>
        <div class="card-head"><span class="card-title">${icon("check")} Coverage</span></div>
        <p class="lede m-0">${esc(project.coverage || "No coverage statement.")}</p>
        <dl class="dl mt-14">
          <dt>Reviewed revision</dt><dd class="mono">${esc(project.revision || "—")}</dd>
          <dt>Inventory revision</dt><dd class="mono">${esc(project.inventory_revision || "—")}</dd>
          <dt>Catalog snapshots</dt><dd>${nf.format(project.history)} in history</dd>
          <dt>Store</dt><dd class="mono">${esc(project.store)}</dd>
        </dl>
      </section>
    </div>`;
}

function kpi(i, label, value, foot, tone, ic) {
  return `<div class="card kpi rise" ${vars({ "--i": i, "--tone": tone })}>
    <span class="kpi-label">${icon(ic)} ${esc(label)}</span>
    <span class="kpi-value"><span aria-hidden="true" data-count="${value}">${nf.format(value)}</span><span class="sr-only">${nf.format(value)}</span></span>
    <span class="kpi-foot">${esc(foot)}</span>
  </div>`;
}

function decisionLine(project, d) {
  const rel = relation(d.relation_to_provider);
  const provider = optionInfo(project, providerOption(d));
  return `<a class="row" href="${href(project.id, "decisions", d.task_id)}">
    <div class="row-main"><div class="row-title mono">${esc(d.task_id)}</div>
      <div class="decision-flow"><span>Provider <b>${esc(provider.label)}</b></span>${icon("arrow")}<span>Agent <b>${esc(firstWord(d.agent_final_choice))}</b></span></div></div>
    <span class="pill ${rel.cls}">${rel.label}</span></a>`;
}
const firstWord = (value) => text(value).split(" (")[0] || "—";

// Catalog ----------------------------------------------------------------------
function catalogView(project) {
  const filters = ui(project.id);
  applyKindParam(project);
  const chips = project.kindList.map(([kind, n]) =>
    `<button class="chip" type="button" data-action="kind" data-arg="${esc(kind)}" aria-pressed="${filters.kinds.has(kind)}"><i class="kind-dot" ${vars({ "--c": kindColor(project, kind) })}></i>${esc(kind)} <small>${n}</small></button>`).join("");
  return `<div class="toolbar">
      <label class="search"><span class="sr-only">Search catalog</span>${icon("search")}
        <input id="entry-search" type="search" placeholder="Search name, id, tag, path or contract" value="${esc(filters.query)}" autocomplete="off" spellcheck="false"><kbd>/</kbd></label>
    </div>
    <div class="chips mb-16">${chips}</div>
    <div class="split">
      <section class="card list-panel rise"><div class="list-head"><span id="entry-count"></span><span>kind · source</span></div><nav aria-label="Catalog entries"><ul class="list" id="entry-list"></ul></nav></section>
      <section class="card detail rise" id="entry-detail" ${vars({ "--i": 1 })}></section>
    </div>`;
}

// A `?kind=` hash parameter selects exactly that kind; chips mirror the filter.
function applyKindParam(project) {
  const kind = hashParam("kind");
  if (!kind) return false;
  const filters = ui(project.id);
  filters.kinds = new Set([kind]);
  for (const chip of $$("[data-action='kind']")) chip.setAttribute("aria-pressed", String(filters.kinds.has(chip.dataset.arg)));
  return true;
}

function filteredEntries(project) {
  const { query, kinds } = ui(project.id);
  const q = query.trim().toLowerCase();
  return project.catalog.filter((e) => (!kinds.size || kinds.has(e.kind)) &&
    (!q || [e.id, e.name, e.source, e.summary, e.contract, ...(e.tags || [])].join(" ").toLowerCase().includes(q)));
}

function renderEntryList(announceCount = false) {
  const project = state.details.get(current.route.project);
  const list = $("#entry-list");
  if (!project || !list) return;
  const q = ui(project.id).query.trim().toLowerCase();
  const rows = filteredEntries(project);
  const count = `${nf.format(rows.length)} of ${nf.format(project.catalog.length)} entries`;
  $("#entry-count").textContent = count;
  if (announceCount) announce(count);
  list.innerHTML = rows.length ? rows.map((e) => `<li><a class="row" href="${href(project.id, "catalog", e.id)}" data-id="${esc(e.id)}"${e.id === current.route.item ? ' aria-current="true"' : ""}>
      <i class="kind-dot" ${vars({ "--c": kindColor(project, e.kind) })}></i>
      <div class="row-main"><div class="row-title">${highlight(e.name || e.id, q)}</div><div class="row-sub">${highlight(e.source, q)}</div></div>
      <span class="row-side">${esc(e.kind)}</span></a></li>`).join("")
    : `<li class="empty">${icon("search")}<span>No entries match these filters.</span></li>`;
  hydrate(list);
}

// `scroll` brings the detail pane into view on narrow screens after a click or tap;
// keyboard walking through the list keeps the viewport still.
function selectEntry(id, { initial = false, scroll = !initial } = {}) {
  const project = state.details.get(current.route.project);
  const pane = $("#entry-detail");
  if (!project || !pane) return;
  const entry = project.byId.get(id) || (initial && !id ? filteredEntries(project)[0] : null);
  for (const row of $$("#entry-list .row")) {
    if (row.dataset.id === entry?.id) row.setAttribute("aria-current", "true");
    else row.removeAttribute("aria-current");
  }
  if (!entry) {
    pane.innerHTML = `<div class="empty">${icon("grid")}<span>${id ? "This entry no longer exists in the catalog." : "Select an entry to inspect its contract."}</span></div>`;
    return;
  }
  const usages = entry.usages?.length
    ? `<ul class="usages">${entry.usages.map((u) => `<li><b>${esc(u.path)}</b>:${esc(u.start)}–${esc(u.end)}</li>`).join("")}</ul>`
    : `<div class="callout">${icon("alert")}<span>No recorded consumer. ${esc(entry.usage_gap || "")}</span></div>`;
  pane.innerHTML = `<div class="detail-enter">
    <div class="meta-row mt-0"><span class="pill muted"><i class="kind-dot" ${vars({ "--c": kindColor(project, entry.kind) })}></i>${esc(entry.kind)}</span><span class="mono">${esc(entry.id)}</span></div>
    <h2 class="mt-10">${esc(entry.name || entry.id)}</h2>
    <div class="meta-row"><span>${icon("file")} <span class="mono">${esc(entry.source)}</span></span></div>
    ${entry.tags?.length ? `<div class="chips mt-12">${entry.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>` : ""}
    <div class="section"><h3>Summary</h3><p>${esc(entry.summary)}</p></div>
    <div class="section"><h3>Contract</h3><div class="contract">${esc(entry.contract)}</div></div>
    <div class="section"><h3>Constraints</h3>${entry.constraints?.length ? `<ul class="constraints">${entry.constraints.map((c) => `<li>${icon("alert")}<span>${esc(c)}</span></li>`).join("")}</ul>` : `<p>None recorded.</p>`}</div>
    <div class="section"><h3>Usages ${entry.usages?.length ? `<span class="count">${entry.usages.length}</span>` : ""}</h3>${usages}</div>
  </div>`;
  hydrate(pane);
  if (scroll && innerWidth <= 900) pane.scrollIntoView({ behavior: reducedMotion.matches ? "auto" : "smooth", block: "start" });
}

// Inventory ------------------------------------------------------------------
function inventoryView(project) {
  const filters = ui(project.id);
  const kinds = Object.entries(project.inventory.reduce((acc, f) => ((acc[f.kind] = (acc[f.kind] || 0) + 1), acc), {})).sort((a, b) => b[1] - a[1]);
  const buttons = [["all", project.inventory.length], ...kinds].map(([k, n]) =>
    `<button type="button" data-action="inventory-kind" data-arg="${esc(k)}" aria-pressed="${filters.inventoryKind === k}">${esc(k)} <small class="hint">${nf.format(n)}</small></button>`).join("");
  return `<div class="toolbar">
      <div class="segmented" role="group" aria-label="Review classification">${buttons}</div>
      <label class="search"><span class="sr-only">Search inventory</span>${icon("search")}
        <input id="inventory-search" type="search" placeholder="Filter by path or reason" value="${esc(filters.inventoryQuery)}" autocomplete="off" spellcheck="false"><kbd>/</kbd></label>
    </div>
    <section class="card list-panel rise">
      <div class="list-head"><span id="inventory-count"></span><span>Tests are excluded before inspection</span></div>
      <div class="table-wrap"><table class="table"><thead><tr><th>Path</th><th>Review</th><th>Reason</th></tr></thead><tbody id="inventory-body"></tbody></table></div>
    </section>`;
}
function renderInventory(announceCount = false) {
  const project = state.details.get(current.route.project);
  const body = $("#inventory-body");
  if (!project || !body) return;
  const { inventoryKind, inventoryQuery } = ui(project.id);
  const q = inventoryQuery.trim().toLowerCase();
  const tone = { catalogued: "ok", supporting: "muted", excluded: "muted", protected: "danger", pending: "warn" };
  const rows = project.inventory.filter((f) => (inventoryKind === "all" || f.kind === inventoryKind) &&
    (!q || `${f.path} ${f.reason || ""}`.toLowerCase().includes(q)));
  const count = `${nf.format(rows.length)} of ${nf.format(project.inventory.length)} files`;
  $("#inventory-count").textContent = count;
  if (announceCount) announce(count);
  body.innerHTML = rows.map((f) => {
    const entry = project.bySource.get(f.path);
    const path = entry ? `<a class="link" href="${href(project.id, "catalog", entry.id)}">${highlight(f.path, q)}</a>` : highlight(f.path, q);
    const reason = f.kind === "catalogued" && entry ? esc(entry.name || entry.id) : highlight(f.reason === "private_path" ? "Private path (never inspected)" : f.reason || "", q);
    return `<tr><td class="path">${path}</td><td><span class="pill ${tone[f.kind] || "muted"}">${esc(f.kind)}</span></td><td class="reason">${reason}</td></tr>`;
  }).join("") || `<tr><td colspan="3"><div class="empty">${icon("search")}<span>No files match.</span></div></td></tr>`;
}

// Decisions ------------------------------------------------------------------
function decisionsView(project) {
  if (!project.decision_list.length) return `<div class="card empty rise">${icon("scale")}<b>No decisions yet</b><span>Decisions appear after <code>prepare</code> and <code>evaluate</code> runs are reviewed.</span></div>`;
  const cards = project.decision_list.map((d, i) => {
    const rel = relation(d.relation_to_provider);
    const provider = optionInfo(project, providerOption(d));
    return `<a class="card decision-card rise" href="${href(project.id, "decisions", d.task_id)}" data-task="${esc(d.task_id)}" ${vars({ "--i": i })}>
      <div class="meta-row m-0"><span class="pill ${rel.cls}">${rel.label}</span><span>${esc(d.reviewed_on || "")}</span></div>
      <h3>${esc(d.task_id)}</h3>
      <div class="decision-flow"><span>Provider <b>${esc(provider.label)}</b></span>${icon("arrow")}<span>Agent <b>${esc(firstWord(d.agent_final_choice))}</b></span></div>
    </a>`;
  }).join("");
  return `<div class="split"><div class="grid" id="decision-list">${cards}</div><section class="card detail" id="decision-detail"></section></div>`;
}

async function selectDecision(task, initial = false) {
  const project = state.details.get(current.route.project);
  const pane = $("#decision-detail");
  if (!project || !pane) return;
  const id = task || (initial ? project.decision_list[0]?.task_id : null);
  for (const card of $$("#decision-list .decision-card")) {
    if (card.dataset.task === id) card.setAttribute("aria-current", "true");
    else card.removeAttribute("aria-current");
  }
  if (!id) return;
  pane.innerHTML = skeletons();
  hydrate(pane);
  // The user may have picked another decision or left the view while loading.
  const stillCurrent = () => pane.isConnected && current.route?.view === "decisions" && current.route.project === project.id &&
    (current.route.item || project.decision_list[0]?.task_id) === id;
  let html;
  try {
    html = decisionDetail(project, await loadDecision(project.id, id));
  } catch (error) {
    html = `<div class="empty">${icon("alert")}<span>${esc(error.message)}</span></div>`;
  }
  if (!stillCurrent()) return;
  pane.innerHTML = html;
  hydrate(pane);
  if (!initial && innerWidth <= 900) pane.scrollIntoView({ behavior: reducedMotion.matches ? "auto" : "smooth", block: "start" });
}
const skeletons = () => [["60%", "28px"], ["100%", "92px"], ["100%", "180px"]]
  .map(([w, h], i) => `<div class="skeleton" ${vars({ width: w, height: h, "margin-top": i ? "16px" : "0" })}></div>`).join("");

function decisionDetail(project, d) {
  const rel = relation(d.relation_to_provider);
  const trace = d.trace || { batches: [], alternatives: [], final: [], manifest: {} };
  const provider = optionInfo(project, providerOption(d));
  const choice = text(d.agent_final_choice);
  const toRows = (pairs) => pairs.map(([option, p]) => {
    const info = optionInfo(project, option);
    return { label: info.label, title: option, value: p, color: info.color, dot: true, href: info.entry ? href(project.id, "catalog", info.entry) : null };
  });
  const batches = trace.batches.map((b, i) => {
    const info = optionInfo(project, b.choice);
    const best = b.best ? `best candidate ${optionInfo(project, b.best[0]).label} ${pct(b.best[1])}` : "";
    return `<button class="batch" type="button" data-tip="Batch ${i + 1}: ${esc(info.label)} (${pct(b.confidence || 0)})" data-tip-sub="${esc(best)}" aria-label="Batch ${i + 1}: ${esc(info.label)}"
      ${vars({ "--c": info.color, "--o": 0.35 + 0.65 * (b.confidence || 0), "--i": i })}></button>`;
  }).join("");
  const m = trace.manifest || {};
  return `<div class="detail-enter">
    <div class="meta-row mt-0"><span class="pill ${rel.cls}">${rel.label}</span><span>${icon("clock")} ${esc(d.reviewed_on || "")}</span><span>${esc(d.review_status || "")}</span></div>
    <h2 class="mono mt-10 task-title">${esc(d.task_id)}</h2>
    ${d.task ? `<div class="section"><h3>Requirement</h3><p>${esc(d.task.requirement)}</p></div>
      <div class="section"><h3>Acceptance</h3><ol class="acceptance">${(Array.isArray(d.task.acceptance) ? d.task.acceptance : []).map((a) => `<li>${esc(a)}</li>`).join("")}</ol></div>` : ""}
    <div class="section"><h3>Verdict</h3>
      <div class="verdict">
        <div class="verdict-side"><small>Provider · ${esc(providerName(d))}</small><b>${esc(provider.label)}</b></div>
        <div class="verdict-link">${icon("compare")}</div>
        <div class="verdict-side"><small>Agent final choice</small><b>${esc(firstWord(choice))}</b>${choice.includes("(") ? `<span class="mono">${esc(choice.slice(choice.indexOf("(")))}</span>` : ""}</div>
      </div>
      <p class="relation">${esc(text(d.relation_to_provider))}</p>
    </div>
    ${trace.final.length ? `<div class="section"><h3>Final round probabilities</h3>${barList(toRows(trace.final), { format: pct })}</div>` : ""}
    ${trace.batches.length ? `<div class="section"><h3>Batch choices · ${trace.batches.length} calls</h3><div class="batches">${batches}</div>
      <div class="legend"><span><i class="kind-dot" ${vars({ "--c": "var(--opt-create)" })}></i>create</span><span><i class="kind-dot" ${vars({ "--c": "var(--opt-insufficient)" })}></i>insufficient evidence</span>${["reuse", "modify", "wrap"].map((a) => `<span><i class="kind-dot" ${vars({ "--c": `var(--opt-${a})` })}></i>${a}</span>`).join("")}<span>opacity = confidence</span></div></div>` : ""}
    ${trace.alternatives.length ? `<div class="section"><h3>Strongest candidates across batches</h3>${barList(toRows(trace.alternatives), { format: pct })}</div>` : ""}
    <div class="section"><h3>Agent explanation</h3><p>${esc(d.agent_explanation || "—")}</p></div>
    <div class="section"><h3>Verification</h3><p>${esc(d.verification || "—")}</p></div>
    <div class="section"><h3>Run</h3><dl class="dl">
      <dt>Strategy</dt><dd>${esc(m.strategy || "—")} · ${esc(m.entry_count ?? "—")} entries · ${esc(m.initial_batches ?? "—")} batches · max ${esc(m.max_calls ?? "—")} calls</dd>
      <dt>Tokens</dt><dd>${nf.format(d.usage?.input_tokens || 0)} in · ${nf.format(d.usage?.output_tokens || 0)} out</dd>
      <dt>Prepared at</dt><dd class="mono">${esc(short(m.revision))} · ${esc(m.created_at || "—")}</dd>
      <dt>Implemented in</dt><dd class="mono">${esc(d.implemented_in || "—")}</dd>
    </dl></div>
  </div>`;
}

function errorView(error) {
  return `<div class="page"><div class="card empty rise">${icon("alert")}<b>${esc(error.message)}</b><span>The project may have moved or the server may have stopped.</span><a class="secondary-button" href="#/">Back to projects</a></div></div>`;
}

// Interactions ---------------------------------------------------------------
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const project = current.route?.project && state.details.get(current.route.project);
  const arg = target.dataset.arg;
  if (target.dataset.action === "kind" && project) {
    const { kinds } = ui(project.id);
    kinds.has(arg) ? kinds.delete(arg) : kinds.add(arg);
    target.setAttribute("aria-pressed", String(kinds.has(arg)));
    if (location.hash.includes("?")) history.replaceState(null, "", location.hash.split("?")[0]);
    renderEntryList(true);
  }
  if (target.dataset.action === "inventory-kind" && project) {
    ui(project.id).inventoryKind = arg;
    for (const b of $$("[data-action='inventory-kind']")) b.setAttribute("aria-pressed", String(b === target));
    renderInventory(true);
  }
  if (target.dataset.action === "mosaic-kind") {
    const pressed = target.getAttribute("aria-pressed") !== "true";
    for (const chip of $$("[data-action='mosaic-kind']")) chip.setAttribute("aria-pressed", String(chip === target && pressed));
    const mosaic = $("#mosaic");
    mosaic.classList.toggle("dim", pressed);
    for (const tile of $$(".tessera", mosaic)) tile.classList.toggle("match", pressed && tile.dataset.kind === arg);
  }
});

let searchTimer;
document.addEventListener("input", (event) => {
  const project = current.route?.project && state.details.get(current.route.project);
  if (!project) return;
  if (event.target.id === "entry-search") {
    ui(project.id).query = event.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => renderEntryList(true), 80);
  }
  if (event.target.id === "inventory-search") {
    ui(project.id).inventoryQuery = event.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => renderInventory(true), 80);
  }
});

// Tooltips for mosaic tiles and batch cells. The tooltip describes the element
// it belongs to while shown and leaves the accessibility tree when hidden.
const tooltip = $("#tooltip");
let tipOwner = null;
function showTip(el) {
  if (tipOwner && tipOwner !== el) tipOwner.removeAttribute("aria-describedby");
  tipOwner = el;
  el.setAttribute("aria-describedby", "tooltip");
  tooltip.innerHTML = `<b>${esc(el.dataset.tip)}</b>${el.dataset.tipSub ? `<span>${esc(el.dataset.tipSub)}</span>` : ""}`;
  const rect = el.getBoundingClientRect();
  tooltip.classList.add("show");
  const width = tooltip.offsetWidth;
  const left = Math.min(Math.max(8, rect.left + rect.width / 2 - width / 2), innerWidth - width - 8);
  const top = rect.top - tooltip.offsetHeight - 10 < 8 ? rect.bottom + 10 : rect.top - tooltip.offsetHeight - 10;
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}
function hideTip() {
  tooltip.classList.remove("show");
  tipOwner?.removeAttribute("aria-describedby");
  tipOwner = null;
}
document.addEventListener("pointerover", (e) => { const el = e.target.closest("[data-tip]"); el ? showTip(el) : hideTip(); });
document.addEventListener("focusin", (e) => { const el = e.target.closest("[data-tip]"); el ? showTip(el) : hideTip(); });
addEventListener("scroll", hideTip, { passive: true });

// Keyboard: "/" focuses search, Ctrl/Cmd+K opens the palette, arrows walk lists.
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && tooltip.classList.contains("show")) hideTip();
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    openPalette();
    return;
  }
  const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName);
  if (event.key === "/" && !typing && !$("#palette").open) {
    const input = $("#entry-search") || $("#inventory-search");
    if (input) { event.preventDefault(); input.focus(); input.select(); }
  }
  if ((event.key === "ArrowDown" || event.key === "ArrowUp") && current.route?.view === "catalog" &&
      (document.activeElement?.closest("#entry-list") || document.activeElement?.id === "entry-search")) {
    const rows = $$("#entry-list .row");
    if (!rows.length) return;
    event.preventDefault();
    const index = rows.findIndex((r) => r.getAttribute("aria-current") === "true");
    const next = rows[Math.max(0, Math.min(rows.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)))];
    history.replaceState(null, "", next.getAttribute("href"));
    current.route = parseRoute();
    selectEntry(next.dataset.id, { scroll: false });
    next.scrollIntoView({ block: "nearest" });
    if (document.activeElement?.id !== "entry-search") next.focus();
  }
});

// Command palette ------------------------------------------------------------
const palette = $("#palette");
const paletteInput = $("#palette-input");
const paletteList = $("#palette-list");
let paletteItems = [];
let paletteIndex = 0;

async function openPalette() {
  if (palette.open) return;
  await loadProjects().catch(() => []);
  paletteInput.value = "";
  palette.showModal();
  renderPalette();
  paletteInput.focus();
}
function paletteSource() {
  const items = [];
  const project = current.route?.project && state.details.get(current.route.project);
  if (project) {
    for (const [view, label, ic] of [["overview", "Overview", "gauge"], ["catalog", "Catalog", "grid"], ["inventory", "Inventory", "file"], ["decisions", "Decisions", "scale"]]) {
      items.push({ group: project.name, label, hint: "view", ic, href: href(project.id, view) });
    }
  }
  items.push({ group: "Projects", label: "All projects", hint: "home", ic: "layers", href: "#/" });
  for (const p of state.projects || []) items.push({ group: "Projects", label: p.name, hint: `${p.entries} entries`, ic: "box", href: href(p.id) });
  if (project) {
    for (const d of project.decision_list) items.push({ group: "Decisions", label: d.task_id, hint: firstWord(d.agent_final_choice), ic: "scale", href: href(project.id, "decisions", d.task_id) });
    for (const e of project.catalog) items.push({ group: "Catalog", label: e.name || e.id, hint: e.kind, ic: "grid", href: href(project.id, "catalog", e.id), text: `${e.id} ${e.source} ${(e.tags || []).join(" ")}` });
  }
  return items;
}
function renderPalette() {
  const q = paletteInput.value.trim().toLowerCase();
  paletteItems = paletteSource().filter((item) => !q || `${item.label} ${item.hint} ${item.text || ""}`.toLowerCase().includes(q)).slice(0, 60);
  paletteIndex = 0;
  // Options are grouped with role="group", each labelled by its visible heading.
  const groups = [];
  paletteItems.forEach((item, i) => {
    if (groups.at(-1)?.name !== item.group) groups.push({ name: item.group, items: [] });
    groups.at(-1).items.push(`<button class="palette-item" type="button" role="option" tabindex="-1" id="pi-${i}" data-index="${i}" aria-selected="${i === 0}">${icon(item.ic)}<span>${highlight(item.label, q)}</span><small>${esc(item.hint)}</small></button>`);
  });
  paletteList.innerHTML = groups.map((g, k) => `<div role="group" aria-labelledby="pg-${k}"><div class="palette-group" id="pg-${k}" role="presentation">${esc(g.name)}</div>${g.items.join("")}</div>`).join("")
    || `<div class="empty" role="presentation"><span>No matches</span></div>`;
  if (paletteItems.length) paletteInput.setAttribute("aria-activedescendant", "pi-0");
  else paletteInput.removeAttribute("aria-activedescendant");
}
function movePalette(delta) {
  if (!paletteItems.length) return;
  paletteIndex = (paletteIndex + delta + paletteItems.length) % paletteItems.length;
  for (const el of $$(".palette-item", paletteList)) el.setAttribute("aria-selected", String(Number(el.dataset.index) === paletteIndex));
  $(`#pi-${paletteIndex}`)?.scrollIntoView({ block: "nearest" });
  paletteInput.setAttribute("aria-activedescendant", `pi-${paletteIndex}`);
}
function choosePalette(index) {
  const item = paletteItems[index];
  if (!item) return;
  palette.close();
  location.hash = item.href;
}
paletteInput.addEventListener("input", renderPalette);
paletteInput.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown") { event.preventDefault(); movePalette(1); }
  if (event.key === "ArrowUp") { event.preventDefault(); movePalette(-1); }
  if (event.key === "Enter") { event.preventDefault(); choosePalette(paletteIndex); }
});
// Focus can land on an option after a pointer press; arrows keep working there.
paletteList.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  event.preventDefault();
  const focused = event.target.closest(".palette-item");
  if (focused) paletteIndex = Number(focused.dataset.index);
  movePalette(event.key === "ArrowDown" ? 1 : -1);
  $(`#pi-${paletteIndex}`)?.focus();
});
paletteList.addEventListener("click", (event) => {
  const item = event.target.closest(".palette-item");
  if (item) choosePalette(Number(item.dataset.index));
});
palette.addEventListener("click", (event) => { if (event.target === palette) palette.close(); });
$("#palette-open").addEventListener("click", openPalette);
$("#switcher").addEventListener("click", openPalette);

const VIEW_LABELS = { overview: "Overview", catalog: "Catalog", inventory: "Inventory", decisions: "Decisions" };
// Updates the switcher and document title; returns the label announced for the route.
function updateSwitcher(route) {
  const project = route.project && (state.details.get(route.project) || state.projects?.find((p) => p.id === route.project));
  $("#switcher-label").textContent = project ? project.name : "All projects";
  const view = VIEW_LABELS[route.view] || VIEW_LABELS.overview;
  document.title = project ? `${view} · ${project.name} · Tessera Studio` : "Tessera Studio";
  return project ? `${project.name}, ${view}` : "All projects";
}

$("#refresh").addEventListener("click", async () => {
  state.details.clear();
  state.decisions.clear();
  state.projects = null;
  current = { key: null };
  await render();
});

addEventListener("hashchange", render);
addEventListener("resize", () => moveIndicator(true));
render();
