/* Acuaponsito Panel — gate (admin/login/wake) → app (chat/acciones/auto/ajustes)
   El estado del bot lo dicta el SERVIDOR vía WebSocket: todos los embeds
   sincronizados. El panel manda por HTTP y escucha por WS. */
(() => {
  const Q = new URLSearchParams(location.search);
  const TOKEN = Q.get("token") || "";
  const api = (p) => `${p}${p.includes("?") ? "&" : "?"}token=${encodeURIComponent(TOKEN)}`;
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  let SESSION = localStorage.getItem("acua.session") || "";
  let ME = null, BOOT = null, WS = null, channel = "dm";
  const H = { "Content-Type": "application/json" };
  const hs = () => ({ ...H, "X-Session": SESSION });
  const jget = async (p) => { const r = await fetch(api(p), { headers: hs() }); return { s: r.status, j: await r.json() }; };
  const jpost = async (p, b) => { const r = await fetch(api(p), { method: "POST", headers: hs(), body: JSON.stringify(b) }); return { s: r.status, j: await r.json() }; };
  const toParent = (msg) => { try { parent.postMessage({ acua: true, ...msg }, "*"); } catch {} };

  /* ── bot en el header (framework AcuaBot, estado servidor-céntrico) ── */
  const bot = new window.AcuaBot({
    v1: $("#pv1"), v2: $("#pv2"), svg: $("#bot-svg"),
    bubble: $("#bubble"), bubbleText: $("#bubble-text"), root: $("#stage"), api,
  });
  const STATE_NAMES = { sleep: "dormido", rest: "descansando", idle: "atento", greet: "saludando",
    listen: "escuchando", think: "pensando", work: "trabajando", speak: "hablando",
    wake: "despertando", celebrate: "celebrando", warn: "alerta", error: "error" };
  function setBotState(state, clip) {
    if (clip && bot.byId?.[clip]) bot.playClip(bot.byId[clip]);
    else bot.setState(state);
    $("#state-dot").className = `dot s-${state}`;
    $("#state-name").textContent = STATE_NAMES[state] || state;
    toParent({ kind: "state", state });
  }

  /* ── ventana (postMessage al embed padre) ── */
  let full = false;
  $("#btn-size").addEventListener("click", () => { full = !full; toParent({ kind: "size", mode: full ? "full" : "medium" }); });
  $("#btn-close").addEventListener("click", () => toParent({ kind: "close" }));

  /* ── gate ── */
  const gates = { admin: $("#gate-admin"), login: $("#gate-login"), forgot: $("#gate-forgot"),
    reset: $("#gate-reset"), wake: $("#gate-wake") };
  function showGate(which) {
    $("#gate").classList.remove("hidden"); $("#main").classList.add("hidden");
    Object.entries(gates).forEach(([k, el]) => (el.style.display = k === which ? "" : "none"));
  }
  function paintSysPill() {
    const st = BOOT?.system_status;
    if (!st) return;
    const pill = $("#sys-pill");
    pill.className = `sys-pill sp-${st.code}`;
    pill.textContent = st.code === "activo" ? "🟢 " + st.label : "🟡 " + st.label;
  }
  async function enterApp() {
    $("#gate").classList.add("hidden"); $("#main").classList.remove("hidden");
    connectWS(); loadChat(); loadActs(); fillConfig(); renderUsers();
    if (ME.role !== "admin") $$(".admin-only").forEach((e) => (e.style.display = "none"));
  }
  $("#ga-go").addEventListener("click", async () => {
    const { s, j } = await jpost("/api/setup-admin", {
      username: $("#ga-user").value.trim(), email: $("#ga-email").value.trim(), password: $("#ga-pass").value });
    if (j.session) {
      SESSION = j.session; localStorage.setItem("acua.session", SESSION); ME = j;
      BOOT.needs_admin = false; BOOT.system_status = { code: "activo", label: "Sistema iniciado" };
      paintSysPill(); route();
    } else { $("#ga-msg").className = "gmsg bad"; $("#ga-msg").textContent = j.error || s; }
  });
  $("#gl-go").addEventListener("click", async () => {
    const { s, j } = await jpost("/api/login", { identifier: $("#gl-user").value.trim(), password: $("#gl-pass").value });
    if (j.session) { SESSION = j.session; localStorage.setItem("acua.session", SESSION); ME = j; route(); }
    else { $("#gl-msg").className = "gmsg bad"; $("#gl-msg").textContent = "credenciales inválidas"; }
  });
  $("#gl-forgot-link").addEventListener("click", () => showGate("forgot"));
  $("#gf-back-link").addEventListener("click", () => showGate("login"));
  $("#gf-go").addEventListener("click", async () => {
    const m = $("#gf-msg"); m.className = "gmsg wait"; m.textContent = "enviando…";
    const { j } = await jpost("/api/forgot-password", { identifier: $("#gf-identifier").value.trim() });
    m.className = `gmsg ${j.mail_sent ? "ok" : "wait"}`; m.textContent = j.message;
  });
  $("#gr-go").addEventListener("click", async () => {
    const m = $("#gr-msg");
    const pw = $("#gr-pass").value;
    if (pw.length < 6) { m.className = "gmsg bad"; m.textContent = "mínimo 6 caracteres"; return; }
    const { j } = await jpost("/api/reset-password", { token: Q.get("reset"), password: pw });
    if (j.session) {
      SESSION = j.session; localStorage.setItem("acua.session", SESSION); ME = j;
      history.replaceState(null, "", location.pathname + "?token=" + encodeURIComponent(TOKEN));
      route();
    } else { m.className = "gmsg bad"; m.textContent = j.error || "no se pudo restablecer"; }
  });
  $("#gw-go").addEventListener("click", async () => {
    const m = $("#gw-msg"); m.className = "gmsg wait"; m.textContent = "validando…";
    const { j } = await jpost("/api/provider", { provider: $("#gw-provider").value, api_key: $("#gw-key").value.trim() });
    m.className = `gmsg ${j.valid ? "ok" : "bad"}`; m.textContent = j.message;
    if (j.valid) { BOOT.agent.has_provider = true; setTimeout(enterApp, 900); }
  });

  async function route() {
    paintSysPill();
    if (Q.get("reset")) return showGate("reset");
    if (BOOT.needs_admin) return showGate("admin");
    if (!SESSION) return showGate("login");
    const me = await jget("/api/me");
    if (me.s !== 200) { SESSION = ""; localStorage.removeItem("acua.session"); return showGate("login"); }
    ME = me.j;
    if (!BOOT.agent.has_provider) return showGate("wake");
    enterApp();
  }

  /* ── WebSocket: chat, presencia, estado, aprobaciones ── */
  function connectWS() {
    if (WS) try { WS.close(); } catch {}
    const proto = location.protocol === "https:" ? "wss" : "ws";
    WS = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(TOKEN)}&session=${encodeURIComponent(SESSION)}`);
    WS.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "bot_state") setBotState(ev.state, ev.clip);
      if (ev.type === "presence") $("#presence").innerHTML = ev.users.map((u) => `<span>${u}</span>`).join("");
      if (ev.type === "chat") { if (ev.channel === realChannel()) addMsg(ev); if (ev.from === "bot" && ev.channel !== realChannel()) toParent({ kind: "unread" }); }
      if (ev.type === "approval") { upsertAct(ev.item); }
      if (ev.type === "config") { $("#agent-name").textContent = ev.agent.name; }
    };
    WS.onclose = () => setTimeout(connectWS, 3000);
  }

  /* ── chat ── */
  const realChannel = () => (channel === "dm" ? `dm:${ME.user}` : "team");
  function addMsg(m) {
    const div = document.createElement("div");
    div.className = `m ${m.from === "bot" ? "bot" : m.from === "system" ? "system" : m.user === ME.user ? "user" : "bot"}`;
    div.innerHTML = `<div class="m-b">${m.from !== "system" && m.user !== ME.user ? `<span class="m-u">${m.user}</span>` : ""}<span></span></div>`;
    div.querySelector("span:last-child").textContent = m.text;
    $("#msgs").appendChild(div);
    $("#msgs").scrollTop = $("#msgs").scrollHeight;
  }
  async function loadChat() {
    $("#msgs").innerHTML = "";
    const { j } = await jget(`/api/chat/history?channel=${encodeURIComponent(realChannel())}`);
    (j.messages || []).forEach(addMsg);
    if (!j.messages?.length && channel === "dm")
      addMsg({ from: "bot", user: BOOT.agent.name, text: `¡Hola ${ME.user}! 🌱 Soy ${BOOT.agent.name}. Pregúntame sobre tu sistema, pídeme diagnósticos o cuéntame tus objetivos — estoy para guiarte.` });
  }
  $$(".ch").forEach((b) => b.addEventListener("click", () => {
    $$(".ch").forEach((x) => x.classList.remove("active")); b.classList.add("active");
    channel = b.dataset.ch;
    $("#ch-hint").textContent = channel === "dm" ? "solo tú y el agente" : `todos + ${BOOT.agent.name} si lo mencionas`;
    loadChat();
  }));
  $("#chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = $("#chat-text").value.trim();
    if (!text) return;
    $("#chat-text").value = "";
    await jpost("/api/chat", { channel: realChannel(), text });
  });

  /* ── acciones / aprobaciones ── */
  const acts = {};
  function upsertAct(item) {
    acts[item.id] = item;
    renderActs();
    const pend = Object.values(acts).filter((a) => a.status === "pending").length;
    const b = $("#acts-badge");
    b.textContent = pend; b.classList.toggle("hidden", !pend);
    toParent({ kind: "approvals", pending: pend });
  }
  function renderActs() {
    const list = Object.values(acts).sort((a, b) => b.ts - a.ts);
    $("#acts-list").innerHTML = list.map((a) => `
      <div class="act"><span class="st ${a.status}">${a.status}</span>
        <div class="cmd">$ ${a.cmd.replace(/</g, "&lt;")}</div>
        <div class="why">${(a.reason || "").replace(/</g, "&lt;")} — pide: ${a.requested_by}</div>
        ${a.status === "pending" && ME.role === "admin" ? `
          <div class="act-btns"><button class="btn sm" data-ap="${a.id}">✓ Aprobar y ejecutar</button>
          <button class="btn sm no" data-rj="${a.id}">✕ Rechazar</button></div>` : ""}
        ${a.output ? `<div class="out">${a.output.replace(/</g, "&lt;")}</div>` : ""}
      </div>`).join("") || '<p class="hint">Sin acciones propuestas todavía.</p>';
    $$("[data-ap]").forEach((b) => b.addEventListener("click", () => jpost("/api/approve", { id: b.dataset.ap, decision: "approve" })));
    $$("[data-rj]").forEach((b) => b.addEventListener("click", () => jpost("/api/approve", { id: b.dataset.rj, decision: "reject" })));
  }
  async function loadActs() {
    const { j } = await jget("/api/approvals");
    (j.items || []).forEach((i) => (acts[i.id] = i));
    renderActs();
  }

  /* ── automatización + ajustes ── */
  function fillConfig() {
    const a = BOOT.agent;
    $("#agent-name").textContent = a.name;
    $("#cf-name").value = a.name; $("#cf-pers").value = a.personality; $("#cf-goal").value = a.goal || "";
    $("#cf-team").value = a.respond_in_team; $("#cf-idle").value = a.idle_minutes;
    $("#cf-rest").checked = a.rest_mode; $("#cf-auto").checked = a.auto_approve;
    $("#btn-rest").classList.toggle("on", a.rest_mode);
    $("#cf-provs").innerHTML = a.providers.map((p) => `<div class="mini-item">🤖 ${p.provider} <span class="mono">${p.model}</span></div>`).join("");
    renderSch(); renderWh();
  }
  function renderSch() {
    $("#sch-list").innerHTML = (BOOT.agent.schedules || []).map((s, i) =>
      `<div class="mini-item">⏱️ ${s.name} <span class="mono">cada ${s.every_minutes}min</span><button data-schdel="${i}">✕</button></div>`).join("");
    $$("[data-schdel]").forEach((b) => b.addEventListener("click", async () => {
      BOOT.agent.schedules.splice(+b.dataset.schdel, 1);
      await jpost("/api/config", { schedules: BOOT.agent.schedules }); renderSch();
    }));
  }
  function renderWh() {
    $("#wh-list").innerHTML = (BOOT.agent.webhooks || []).map((w, i) =>
      `<div class="mini-item">🪝 ${w.name} <span class="mono">POST /hook/${w.id}</span><button data-whdel="${i}">✕</button></div>`).join("");
    $("#wh-hint").textContent = BOOT.agent.webhooks?.length
      ? `URL: ${location.origin}/hook/<id>?token=… — cualquier sistema puede activar al agente.` : "";
    $$("[data-whdel]").forEach((b) => b.addEventListener("click", async () => {
      BOOT.agent.webhooks.splice(+b.dataset.whdel, 1);
      await jpost("/api/config", { webhooks: BOOT.agent.webhooks }); renderWh();
    }));
  }
  $("#sch-add").addEventListener("click", async () => {
    const s = { id: Math.random().toString(36).slice(2, 8), name: $("#sch-name").value.trim() || "tarea",
      every_minutes: +$("#sch-min").value || 60, prompt: $("#sch-prompt").value.trim() };
    if (!s.prompt) return;
    BOOT.agent.schedules.push(s);
    await jpost("/api/config", { schedules: BOOT.agent.schedules });
    $("#sch-name").value = $("#sch-min").value = $("#sch-prompt").value = ""; renderSch();
  });
  $("#wh-add").addEventListener("click", async () => {
    const w = { id: Math.random().toString(36).slice(2, 8), name: $("#wh-name").value.trim() || "hook",
      prompt: $("#wh-prompt").value.trim() };
    if (!w.prompt) return;
    BOOT.agent.webhooks.push(w);
    await jpost("/api/config", { webhooks: BOOT.agent.webhooks });
    $("#wh-name").value = $("#wh-prompt").value = ""; renderWh();
  });
  $("#cf-save").addEventListener("click", async () => {
    const m = $("#cf-msg");
    const { s } = await jpost("/api/config", {
      name: $("#cf-name").value.trim(), personality: $("#cf-pers").value.trim(), goal: $("#cf-goal").value.trim(),
      respond_in_team: $("#cf-team").value, idle_minutes: +$("#cf-idle").value || 8,
      rest_mode: $("#cf-rest").checked, auto_approve: $("#cf-auto").checked,
    });
    m.className = `gmsg ${s === 200 ? "ok" : "bad"}`; m.textContent = s === 200 ? "✓ guardado" : "sin permiso";
    if (s === 200) { BOOT.agent.name = $("#cf-name").value.trim(); fillConfig(); }
  });
  $("#cf-prov-add").addEventListener("click", async () => {
    const { j } = await jpost("/api/provider", { provider: $("#cf-prov").value, api_key: $("#cf-key").value.trim() });
    if (j.valid) { BOOT.agent.has_provider = true; BOOT.agent.providers.unshift({ provider: $("#cf-prov").value, model: j.default_model }); $("#cf-key").value = ""; fillConfig(); }
  });
  async function renderUsers() {
    if (ME.role !== "admin") return;
    const { s, j } = await jget("/api/users");
    if (s !== 200) return;
    $("#us-list").innerHTML = j.users.map((u) =>
      `<div class="mini-item">${u.username === ME.user ? "👤" : "•"} <b>${u.username}</b>
         ${u.email ? `<span class="mono">${u.email}</span>` : '<span class="mono">sin correo</span>'}
         <span class="mono">${u.role}</span>
         ${!u.last_login_ts ? '<span class="mono" style="color:var(--amber)">nunca entró</span>' : ""}
         <button data-userreset="${u.username}" title="restablecer contraseña">🔑</button></div>`).join("");
    $$("[data-userreset]").forEach((b) => b.addEventListener("click", async () => {
      const pw = prompt(`Nueva contraseña para "${b.dataset.userreset}" (mín. 6 caracteres):`);
      if (!pw) return;
      const r = await jpost("/api/users/reset", { username: b.dataset.userreset, password: pw });
      $("#us-msg").textContent = r.j.ok ? "✓ contraseña restablecida" : r.j.error || "error";
    }));
  }
  $("#us-add").addEventListener("click", async () => {
    const { s, j } = await jpost("/api/users", {
      username: $("#us-name").value.trim(), email: $("#us-email").value.trim(),
      password: $("#us-pass").value, role: $("#us-role").value });
    $("#us-msg").textContent = s === 201 ? "✓ persona agregada" : j.error || "error";
    if (s === 201) { $("#us-name").value = $("#us-email").value = $("#us-pass").value = ""; renderUsers(); }
  });
  $("#btn-rest").addEventListener("click", async () => {
    BOOT.agent.rest_mode = !BOOT.agent.rest_mode;
    await jpost("/api/config", { rest_mode: BOOT.agent.rest_mode });
    $("#btn-rest").classList.toggle("on", BOOT.agent.rest_mode);
  });

  /* ── tabs ── */
  $$(".tb").forEach((b) => b.addEventListener("click", () => {
    $$(".tb").forEach((x) => x.classList.remove("active")); $$(".tab-body").forEach((t) => t.classList.remove("active"));
    b.classList.add("active"); $(`#t-${b.dataset.t}`).classList.add("active");
  }));

  /* ── arranque ── */
  (async () => {
    await bot.load("/api/catalog");
    const { j } = await jget("/api/boot");
    BOOT = j;
    setBotState(j.bot.state, j.bot.clip);
    $("#agent-name").textContent = j.agent.name;
    route();
  })();
})();
