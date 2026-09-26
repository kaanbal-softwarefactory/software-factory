/* Kaanbal Agent Console v1 — chat con flujos, sistema real, memoria,
   Agent Studio (skills/roles/automejora) y tabla master de clips.
   Reutilizable: solo necesita el backend de contexto (observe/memory/chat). */
(() => {
  const TOKEN = new URLSearchParams(location.search).get("token") || "";
  const api = (p) => `${p}${p.includes("?") ? "&" : "?"}token=${encodeURIComponent(TOKEN)}`;
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const jget = async (p) => (await fetch(api(p))).json();
  const jpost = async (p, b) => (await fetch(api(p), { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) })).json();

  /* ── config persistente del agente ── */
  const CFG_KEY = "kaanbal.agent.cfg";
  const cfg = Object.assign({
    workflow: "general", role: "orquestador", cons: 7, modo: "asistido", grupo: false,
    scopes: { infra: true, actividad: true, apps: true, logs: true, codigo: false, datos: false, uidom: false },
  }, JSON.parse(localStorage.getItem(CFG_KEY) || "{}"));
  const saveCfg = () => localStorage.setItem(CFG_KEY, JSON.stringify(cfg));

  /* ── Acuaponsito flotante (framework compartido) ── */
  const bot = new window.AcuaBot({
    v1: $("#bot-v1"), v2: $("#bot-v2"), svg: $("#bot-svg"),
    bubble: $("#acuabot-bubble"), bubbleText: $("#acuabot-text"),
    root: $("#acuabot"), api,
  });
  bot.draggable($("#acuabot-stage"), () => bot.speak("Aquí ando 🌱 — pregúntame en la pestaña Agente."));

  /* ── navegación por pestañas ── */
  $$(".rail-btn").forEach((b) => b.addEventListener("click", () => {
    $$(".rail-btn").forEach((x) => x.classList.remove("active"));
    $$(".tab").forEach((t) => t.classList.remove("active"));
    b.classList.add("active");
    $(`#tab-${b.dataset.tab}`).classList.add("active");
    if (b.dataset.tab === "sistema") refreshSystem();
    if (b.dataset.tab === "memoria") refreshMemory();
  }));
  $("#btn-back").href = `/?token=${encodeURIComponent(TOKEN)}`;

  /* ── estado global: célula, proveedor ── */
  let hasProvider = false;
  async function loadState() {
    try {
      const st = await jget("/api/state");
      $("#chip-cell").textContent = `célula: ${st.hostname || "—"}`;
      $("#chip-ctx").textContent = `contexto: ${st.phase === "done" ? "operativo" : "instalador"}`;
      hasProvider = (st.ai_providers || []).length > 0;
      $("#chip-provider").textContent = hasProvider
        ? `🤖 ${st.ai_providers[0].provider} · ${st.ai_providers[0].model}`
        : "sin proveedor — configúralo en el instalador";
      bot.awake(hasProvider);
      bot.setState(hasProvider ? "idle" : "sleep");
    } catch {}
  }

  /* ── AGENTE: chat ── */
  let WORKFLOWS = {}, ROLES = {};
  const thread = $("#thread");
  function addMsg(kind, text) {
    const div = document.createElement("div");
    div.className = `msg ${kind}`;
    div.innerHTML = `<div class="msg-body"></div>`;
    div.querySelector(".msg-body").textContent = text;
    thread.appendChild(div);
    thread.scrollTop = thread.scrollHeight;
    return div;
  }
  async function askAgent(text, workflowOverride) {
    if (!hasProvider) {
      addMsg("agent", "Aún estoy dormido 💤 — conecta un proveedor de IA en el instalador (paso Agente IA) y vuelve.");
      return null;
    }
    addMsg("user", text);
    const thinking = addMsg("agent thinking", "pensando…");
    bot.setState("think");
    try {
      const res = await jpost("/api/ai/chat", {
        messages: history.concat([{ role: "user", content: text }]).slice(-12),
        workflow: workflowOverride || cfg.workflow, role: cfg.role,
        conservadurismo: cfg.cons, modo: cfg.modo,
        scopes: cfg.scopes, grupo: cfg.grupo,
      });
      thinking.remove();
      if (res.error) {
        addMsg("agent", `⚠ ${res.message || res.error}`);
        bot.setState("warn");
        return null;
      }
      history.push({ role: "user", content: text }, { role: "assistant", content: res.say });
      addMsg("agent", res.say);
      bot.applyLLM({ state: res.state, clip: res.clip });   // el agente decide el clip
      return res;
    } catch (e) {
      thinking.remove();
      addMsg("agent", "⚠ Error de conexión con el backend.");
      return null;
    }
  }
  const history = [];
  $("#chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("#chat-text").value.trim();
    if (!text) return;
    $("#chat-text").value = "";
    askAgent(text);
  });
  $$(".quick .btn").forEach((b) => b.addEventListener("click", () => askAgent(b.dataset.q)));

  /* config del chat */
  function renderAgentConfig() {
    const wf = $("#cfg-workflow"), rl = $("#cfg-role");
    wf.innerHTML = Object.entries(WORKFLOWS)
      .map(([id, w]) => `<option value="${id}" ${id === cfg.workflow ? "selected" : ""}>${w.icon} ${w.name}</option>`).join("");
    rl.innerHTML = Object.entries(ROLES)
      .map(([id, r]) => `<option value="${id}" ${id === cfg.role ? "selected" : ""}>${r.icon} ${r.name}</option>`).join("");
    const consWrap = () => $("#cfg-cons-wrap").classList.toggle("hidden", cfg.workflow !== "ciencia");
    wf.addEventListener("change", () => { cfg.workflow = wf.value; saveCfg(); consWrap(); });
    rl.addEventListener("change", () => { cfg.role = rl.value; saveCfg(); renderRoles(); });
    $("#cfg-cons").value = cfg.cons;
    $("#cons-val").textContent = cfg.cons;
    $("#cfg-cons").addEventListener("input", (e) => {
      cfg.cons = +e.target.value; $("#cons-val").textContent = cfg.cons; saveCfg();
    });
    consWrap();
    $("#chip-mode").textContent = `modo: ${cfg.modo}`;
  }

  /* ── SISTEMA: mapa real ── */
  async function refreshSystem() {
    try {
      const s = await jget("/api/observe");
      const node = s.nodes[0] || {};
      $("#sys-cards").innerHTML = `
        <div class="glass-soft stat-card ${node.ready ? "stat-ok" : "stat-warn"}">
          <small>nodo</small><b>${node.name || "—"}</b><span>${node.ready ? "Ready ✓" : "no listo"} · ${node.version || ""}</span></div>
        <div class="glass-soft stat-card stat-ok"><small>pods</small><b>${s.totals.running}/${s.totals.pods}</b><span>Running</span></div>
        <div class="glass-soft stat-card"><small>namespaces</small><b>${s.totals.namespaces}</b><span>ambientes activos</span></div>
        <div class="glass-soft stat-card"><small>capacidad</small><b>${node.cpu || "?"} CPU</b><span>${node.memory || ""}</span></div>`;
      drawMap(s);
    } catch {}
  }
  function drawMap(s) {
    const svg = $("#sys-map");
    const W = 900, H = 460, cx = 150, cy = H / 2;
    const nss = Object.entries(s.namespaces);
    let out = `
      <defs><linearGradient id="mg" x1="0" y1="0" x2="1" y2="1">
        <stop stop-color="#22d3ee"/><stop offset="1" stop-color="#4ade80"/></linearGradient></defs>
      <path d="M${cx} ${cy - 52} l45 26 v52 l-45 26 -45 -26 v-52 Z" fill="rgba(34,211,238,.07)"
        stroke="url(#mg)" stroke-width="2"/>
      <text x="${cx}" y="${cy - 2}" text-anchor="middle" class="map-ns-label">${(s.nodes[0] || {}).name || "célula"}</text>
      <text x="${cx}" y="${cy + 16}" text-anchor="middle" class="map-node-label">k3s · ${s.totals.pods} pods</text>`;
    const colX = 420, colGap = Math.min(86, (H - 60) / Math.max(nss.length, 1));
    nss.forEach(([ns, pods], i) => {
      const y = 46 + i * colGap + colGap / 2;
      out += `<path d="M${cx + 50} ${cy} C ${cx + 160} ${cy}, ${colX - 130} ${y}, ${colX - 12} ${y}"
        fill="none" stroke="rgba(103,232,249,.22)" stroke-width="1.5"/>`;
      out += `<text x="${colX}" y="${y - 14}" class="map-ns-label">${ns} <tspan class="map-node-label">(${pods.length})</tspan></text>`;
      pods.slice(0, 14).forEach((p, j) => {
        const px = colX + 8 + j * 26, py = y + 4;
        const color = p.phase === "Running" ? (p.restarts > 3 ? "#fbbf24" : "#4ade80")
                    : p.phase === "Succeeded" ? "#64748b" : "#fb7185";
        out += `<circle cx="${px}" cy="${py}" r="7" fill="${color}" opacity=".85">
          <title>${p.name} · ${p.phase} · restarts ${p.restarts}</title></circle>`;
      });
    });
    svg.innerHTML = out;
  }
  $("#btn-sys-refresh").addEventListener("click", refreshSystem);
  setInterval(() => { if ($("#tab-sistema").classList.contains("active")) refreshSystem(); }, 12000);

  /* ── MEMORIA ── */
  const ICONS = { step: "🧩", phase: "🚦", handoff: "🔑", log: "📝", chat: "💬",
    nota: "📌", "clip-registrado": "🎬", accion: "⚡" };
  async function refreshMemory() {
    try {
      const m = await jget("/api/memory?limit=150");
      $("#mem-count").textContent = m.events.length + (m.events.length >= 150 ? "+" : "");
      $("#mem-file").textContent = m.file;
      const tl = $("#timeline");
      tl.innerHTML = m.events.slice().reverse().map((e) => {
        const what = e.step ? `${e.step} → ${e.status || ""} ${e.detail || ""}` :
          e.kind === "chat" ? `[${e.workflow}] «${e.user}» → «${e.agent}»` :
          e.line || e.text || e.phase || e.clip_id || JSON.stringify(
            Object.fromEntries(Object.entries(e).filter(([k]) => !["ts", "iso", "source", "kind"].includes(k)))).slice(0, 110);
        return `<div class="tl-item"><span class="tl-time">${(e.iso || "").slice(5)}</span>
          <span class="tl-ico">${ICONS[e.kind] || "·"}</span>
          <span class="tl-text"><span class="mono">${e.source}</span> ${what}</span></div>`;
      }).join("");
    } catch {}
  }
  $("#note-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = $("#note-text").value.trim();
    if (!text) return;
    $("#note-text").value = "";
    await jpost("/api/memory", { kind: "nota", text });
    refreshMemory();
    bot.speak("Anotado en mi memoria 📌");
  });

  /* ── ESTUDIO: roles + automejora ── */
  function renderRoles() {
    $("#roles-grid").innerHTML = Object.entries(ROLES).map(([id, r]) =>
      `<div class="role-card ${id === cfg.role ? "active" : ""}" data-role="${id}" title="${r.desc}">
        <span>${r.icon}</span><b>${r.name}</b></div>`).join("");
    $$("#roles-grid .role-card").forEach((c) => c.addEventListener("click", () => {
      cfg.role = c.dataset.role; saveCfg(); renderRoles();
      $("#cfg-role").value = cfg.role;
      bot.speak(`Rol activo: ${ROLES[cfg.role].name} ${ROLES[cfg.role].icon}`);
    }));
  }
  $("#modo-grupo").checked = cfg.grupo;
  $("#modo-grupo").addEventListener("change", (e) => { cfg.grupo = e.target.checked; saveCfg(); });

  /* tablero de automejora (persistente) */
  const BOARD_KEY = "kaanbal.agent.board";
  let board = JSON.parse(localStorage.getItem(BOARD_KEY) || '{"propuestas":[],"analisis":[],"dev":[]}');
  const COLS = ["propuestas", "analisis", "dev"];
  function renderBoard() {
    COLS.forEach((col) => {
      const body = $(`.board-col[data-col="${col}"] .col-body`);
      body.innerHTML = board[col].map((f, i) => {
        const next = COLS[COLS.indexOf(col) + 1];
        return `<div class="ficha">${f.replace(/</g, "&lt;")}
          <div class="ficha-actions">
            ${next ? `<button class="btn btn-ghost btn-xs" data-mv="${col}:${i}:${next}">avanzar →</button>` : ""}
            <button class="btn btn-ghost btn-xs" data-del="${col}:${i}">✕</button>
          </div></div>`;
      }).join("") || '<span class="opt" style="font-size:11.5px">vacío</span>';
    });
    localStorage.setItem(BOARD_KEY, JSON.stringify(board));
    $$("[data-mv]").forEach((b) => b.addEventListener("click", () => {
      const [from, i, to] = b.dataset.mv.split(":");
      board[to].push(board[from].splice(+i, 1)[0]); renderBoard();
    }));
    $$("[data-del]").forEach((b) => b.addEventListener("click", () => {
      const [col, i] = b.dataset.del.split(":");
      board[col].splice(+i, 1); renderBoard();
    }));
  }
  $("#btn-idea").addEventListener("click", async () => {
    const idea = $("#idea-text").value.trim();
    const msg = $("#msg-idea");
    if (!idea) { msg.className = "val-msg bad"; msg.textContent = "Escribe tu idea primero"; return; }
    msg.className = "val-msg wait"; msg.textContent = "El agente está armando la ficha…";
    const res = await askAgent(`Registra esta mejora: ${idea}`, "mejora");
    if (res?.say) {
      board.propuestas.unshift(res.say);
      renderBoard();
      $("#idea-text").value = "";
      msg.className = "val-msg ok"; msg.textContent = "✓ Ficha creada en Propuestas";
      await jpost("/api/memory", { kind: "accion", text: `mejora registrada: ${idea.slice(0, 90)}` });
    } else { msg.className = "val-msg bad"; msg.textContent = "No se pudo crear la ficha"; }
  });

  /* ── CLIPS: tabla master ── */
  async function renderClips() {
    await bot.load();
    const cat = bot.catalog || { clips: [], states: {}, wishlist: [] };
    $("#clip-table tbody").innerHTML = cat.clips.map((c) =>
      `<tr data-clip="${c.id}"><td class="mono">${c.id}</td>
       <td><span class="state-pill">${c.state}</span></td>
       <td>${c.energy || "—"}</td><td>${c.title || ""}</td></tr>`).join("");
    $$("#clip-table tbody tr").forEach((tr) => tr.addEventListener("click", () => {
      bot.playClip(bot.byId[tr.dataset.clip]);
      bot.speak(bot.byId[tr.dataset.clip].description || tr.dataset.clip, { stay: 6000 });
    }));
    $("#wishlist").innerHTML = (cat.wishlist || []).map((w) =>
      `<span class="wish-chip" title="${w.prompt_hint}">pendiente: ${w.state}</span>`).join("");
    const sel = $("#clip-state");
    sel.innerHTML = Object.keys(cat.states || {}).map((s) => `<option>${s}</option>`).join("");
  }
  $("#btn-clip-ai").addEventListener("click", async () => {
    const file = $("#clip-file").value.trim();
    const state = $("#clip-state").value;
    const msg = $("#msg-clip");
    if (!file) { msg.className = "val-msg bad"; msg.textContent = "Pon el nombre del archivo primero"; return; }
    msg.className = "val-msg wait"; msg.textContent = "✨ El agente propone…";
    const res = await askAgent(
      `Voy a registrar un clip nuevo del catálogo: archivo "${file}", estado "${state}". ` +
      `Propón en tu "say" SOLO dos líneas: "TITULO: <título corto>" y "DESC: <descripción de cuándo usarlo, 1-2 frases>".`);
    if (res?.say) {
      const t = res.say.match(/TITULO:\s*(.+)/i)?.[1]?.trim();
      const d = res.say.match(/DESC:\s*(.+)/is)?.[1]?.trim();
      if (t && !$("#clip-title").value) $("#clip-title").value = t;
      if (d) $("#clip-desc").value = d;
      if (!$("#clip-id").value) $("#clip-id").value = `${state}__${file.replace(/\.mp4$/i, "").replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;
      msg.className = "val-msg ok"; msg.textContent = "✓ Propuesta lista — edítala si quieres y guarda";
    } else { msg.className = "val-msg bad"; msg.textContent = "Sin propuesta (¿proveedor conectado?)"; }
  });
  $("#btn-clip-save").addEventListener("click", async () => {
    const msg = $("#msg-clip");
    const body = {
      file: $("#clip-file").value.trim(), state: $("#clip-state").value,
      id: $("#clip-id").value.trim(), title: $("#clip-title").value.trim(),
      description: $("#clip-desc").value.trim(),
    };
    if (!body.file || !body.id) { msg.className = "val-msg bad"; msg.textContent = "Archivo e ID son obligatorios"; return; }
    const res = await jpost("/api/catalog/clip", body);
    if (res.clip) {
      msg.className = "val-msg ok"; msg.textContent = "✓ Guardado en la tabla master";
      renderClips();
      bot.speak(`¡Clip nuevo en mi repertorio! ${body.id} 🎬`);
    } else { msg.className = "val-msg bad"; msg.textContent = `✕ ${res.error || "error"}`; }
  });

  /* ── ACCESOS ── */
  const SCOPES_DEF = [
    ["infra", "📡", "Infraestructura", "nodos, pods, ambientes, fases del cluster"],
    ["actividad", "🧠", "Actividad / memoria", "bitácora JSONL de todo lo que pasa"],
    ["apps", "📦", "Apps desplegadas", "catálogo, estados, dominios y vínculos"],
    ["logs", "📜", "Logs", "bitácoras de despliegue y ejecución"],
    ["codigo", "⌨️", "Código", "repositorios y cambios (próxima fase)"],
    ["datos", "📊", "Datos", "bases y datasets de tus apps (próxima fase)"],
    ["uidom", "🖱️", "UI / DOM", "actuar sobre botones y formularios (próxima fase)"],
  ];
  const MODES = [
    ["asistido", "🟢 Asistido", "solo propone — nunca toca nada"],
    ["dev", "🔧 Dev", "podrá aplicar cambios en ambiente dev"],
    ["staging", "🟡 Staging", "cambios con tu aprobación previa"],
    ["prod", "🔴 Producción", "solo con aprobación explícita + auditoría"],
  ];
  function renderAccess() {
    $("#scopes-list").innerHTML = SCOPES_DEF.map(([id, ico, name, desc]) =>
      `<label class="scope-row"><span class="ico">${ico}</span>
        <span class="info"><b>${name}</b><small>${desc}</small></span>
        <input type="checkbox" data-scope="${id}" ${cfg.scopes[id] ? "checked" : ""}></label>`).join("");
    $$("[data-scope]").forEach((c) => c.addEventListener("change", () => {
      cfg.scopes[c.dataset.scope] = c.checked; saveCfg();
    }));
    $("#modes-list").innerHTML = MODES.map(([id, name, desc]) =>
      `<div class="scope-row mode-row ${cfg.modo === id ? "active" : ""}" data-mode="${id}">
        <span class="info"><b>${name}</b><small>${desc}</small></span></div>`).join("");
    $$("[data-mode]").forEach((r) => r.addEventListener("click", () => {
      cfg.modo = r.dataset.mode; saveCfg(); renderAccess();
      $("#chip-mode").textContent = `modo: ${cfg.modo}`;
      bot.speak(`Modo de operación: ${cfg.modo} 🛡️`);
    }));
  }

  /* ── arranque ── */
  (async function boot() {
    await bot.load();
    const agentCfg = await jget("/api/agent/config").catch(() => ({ workflows: {}, roles: {} }));
    WORKFLOWS = agentCfg.workflows || {}; ROLES = agentCfg.roles || {};
    renderAgentConfig(); renderRoles(); renderBoard(); renderAccess(); renderClips();
    await loadState();
    refreshMemory();
    refreshSystem();
    await jpost("/api/memory", { kind: "accion", text: "consola del agente abierta" }).catch(() => {});
  })();
})();
