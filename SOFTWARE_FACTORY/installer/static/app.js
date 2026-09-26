/* Kaanbal Installer v2 — AcuaBot framework player + wizard + SSE
   AcuaBot es la implementación de referencia del Acuaponsito Framework
   (ver docs/acuaponsito/FRAMEWORK.md) — reutilizable en otros proyectos. */
(() => {
  const TOKEN = new URLSearchParams(location.search).get("token") || "";
  const api = (p) => `${p}${p.includes("?") ? "&" : "?"}token=${encodeURIComponent(TOKEN)}`;
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];

  /* ═══ El agente es el Acuaponsito Runtime (:4600) — el flotante es SU embed ═══ */
  const RT = `${location.protocol}//${location.hostname}:4600`;
  const rt = (p) => `${RT}${p}${p.includes("?") ? "&" : "?"}token=${encodeURIComponent(TOKEN)}`;
  (() => {
    const s = document.createElement("script");
    s.src = `${RT}/embed.js`;
    s.dataset.token = TOKEN;
    document.body.appendChild(s);
  })();
  /* el estado del personaje lo gobierna el runtime; el instalador ya no actúa clips */
  const bot = { async load() {}, setState() {}, speak() {}, applyLLM() {}, awake() {}, playClip() {} };

  /* ═══════════════ wizard ═══════════════ */
  function show(id) {
    $$(".screen").forEach((s) => s.classList.remove("active"));
    $(`#screen-${id}`).classList.add("active");
  }
  const setPhaseChip = (t) => ($("#chip-phase").textContent = t);

  /* chequeo de sistema */
  const CHECKS = [
    ["ram_gb", (v) => [v >= 4, `${v} GB RAM`, "mínimo 4 GB"]],
    ["cpus", (v) => [v >= 2, `${v} CPUs`, "mínimo 2"]],
    ["disk_free_gb", (v) => [v >= 15, `${v} GB libres`, "recomendado 20+"]],
    ["systemd", (v) => [v, "systemd activo", "requerido"]],
    ["sudo_nopasswd", (v, info) => [
      !!v || !!info.k3s_installed,
      info.privileged_installer ? "bootstrap privilegiado temporal" :
        (v ? "sudo no interactivo" : (info.k3s_installed ? "k3s ya instalado" : "faltan privilegios")),
      "inicia con sudo bash ./install.sh",
    ]],
    ["wsl", (v) => [true, v ? "WSL2 detectado" : "Linux nativo", ""]],
    ["k3s_installed", (v) => [true, v ? "k3s ya presente" : "k3s se instalará", ""]],
    ["argocd_present", (v) => [true, v ? "ArgoCD ya presente" : "ArgoCD se instalará", ""]],
  ];
  async function systemCheck() {
    try {
      const r = await fetch(api("/api/system-check"));
      if (r.status === 401) { alert("Token inválido — usa la URL completa impresa en la terminal."); return; }
      const info = await r.json();
      $("#chip-host").textContent = info.hostname || "célula";
      const grid = $("#check-grid"); grid.innerHTML = "";
      let allOk = true;
      for (const [key, fn] of CHECKS) {
        const [ok, label, hint] = fn(info[key], info);
        if (!ok) allOk = false;
        grid.insertAdjacentHTML("beforeend",
          `<div class="check"><span class="${ok ? "ok" : "bad"}">${ok ? "✓" : "✕"}</span>
           <span>${label} ${hint && !ok ? `<small>· ${hint}</small>` : ""}</span></div>`);
      }
      $("#sys-spin").classList.add("hidden");
      $("#btn-start").disabled = !allOk;
      setPhaseChip(allOk ? "sistema listo" : "revisa requisitos");
    } catch {
      $("#check-grid").innerHTML = `<div class="check"><span class="bad">✕</span><span>Sin conexión con el backend</span></div>`;
    }
  }

  /* ═══ Paso 1: el agente se configura EN SU PROPIO panel (runtime :4600) ═══ */
  const aiProviders = [];   // el paso "ia" del despliegue lee providers del runtime en el backend
  let aiAwake = false;
  async function pollRuntime() {
    try {
      const b = await (await fetch(rt("/api/boot"))).json();
      $("#rt-status").innerHTML =
        `<span class="ok">✓</span><span>${b.agent.name} en línea <small>· servicio :4600</small></span>`;
      $("#rt-guardian").innerHTML = b.needs_admin
        ? `<span class="info">—</span><span>Guardián (admin): pendiente — créalo en el panel</span>`
        : `<span class="ok">✓</span><span>Guardián creado</span>`;
      if (b.agent.has_provider) {
        const p = b.agent.providers[0] || {};
        $("#rt-provider").innerHTML =
          `<span class="ok">✓</span><span>Despierto 🌱 · ${p.provider} <small>${p.model}</small></span>`;
        if (!aiAwake) {
          aiAwake = true;
          $("#btn-ia-next").disabled = false;
          setPhaseChip("agente despierto");
          $("#msg-ai").className = "val-msg ok";
          $("#msg-ai").textContent = "✓ Tu agente está listo — te acompañará en toda la plataforma";
        }
      } else {
        $("#rt-provider").innerHTML =
          `<span class="info">—</span><span>Proveedor IA: dormido 💤 — despiértalo en el panel</span>`;
      }
    } catch {
      $("#rt-status").innerHTML =
        `<span class="bad">✕</span><span>El agente no responde en :4600 — revisa la terminal del instalador</span>`;
    }
  }
  setInterval(pollRuntime, 3000);
  $("#btn-ia-open").addEventListener("click", () => {
    window.postMessage({ acua: true, kind: "open" }, "*");
    $("#msg-ai").className = "val-msg wait";
    $("#msg-ai").textContent = "Panel abierto → crea al guardián y conéctale su proveedor";
  });

  /* modo + validaciones infra */
  let mode = "cloud";
  $$(".mode-card").forEach((card) => card.addEventListener("click", () => {
    $$(".mode-card").forEach((c) => c.classList.remove("selected"));
    card.classList.add("selected");
    mode = card.dataset.mode;
    $("#cloud-fields").style.opacity = mode === "cloud" ? "1" : ".35";
  }));
  const validated = {};
  let githubBootstrap = false;
  let githubLogin = "";
  const restoredSecrets = new Set();

  function applyCredentialStatus(status) {
    for (const key of status.secret_configured || []) restoredSecrets.add(key);
    const values = status.values || {};
    const fieldMap = {
      domain: "#f-domain", cf_account: "#f-cf-account", tunnel_token: "#f-tunnel",
      gitops_url: "#f-git-url", docker_user: "#f-dk-user",
      tailscale_id: "#f-ts-id", tailscale_dns: "#f-ts-dns",
      admin_user: "#f-admin-user",
    };
    for (const [key, selector] of Object.entries(fieldMap)) {
      if (values[key] && $(selector)) $(selector).value = values[key];
    }
    const secretFields = {
      cf_token: "#f-cf-token", gitops_token: "#f-git-token", docker_token: "#f-dk-token",
      tailscale_secret: "#f-ts-secret", admin_pass: "#f-admin-pass",
    };
    for (const [key, selector] of Object.entries(secretFields)) {
      if (restoredSecrets.has(key) && $(selector)) $(selector).placeholder = "•••• guardado en el servidor";
    }
    if (restoredSecrets.has("admin_pass")) {
      $("#st-admin").className = "cred-state ok";
      $("#st-admin").textContent = "✓ restaurado";
    }
    $("#msg-env").className = "val-msg ok";
    $("#msg-env").textContent = (status.configured || []).length
      ? `✓ ${(status.configured || []).length} variables disponibles`
      : "Sin credenciales guardadas";
  }

  async function loadCredentialStatus() {
    try {
      const res = await (await fetch(api("/api/credentials/status"))).json();
      applyCredentialStatus(res);
    } catch {}
  }

  $("#f-env-file").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    $("#msg-env").className = "val-msg wait";
    $("#msg-env").textContent = "Importando…";
    try {
      const res = await fetch(api("/api/env/import"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ env: await file.text() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "No se pudo importar");
      applyCredentialStatus(data);
    } catch (e) {
      $("#msg-env").className = "val-msg bad";
      $("#msg-env").textContent = `✕ ${e.message}`;
    }
  });
  async function validate(kind, payload, msgEl, stateEl) {
    msgEl.className = "val-msg wait"; msgEl.textContent = "Validando…";
    try {
      const r = await fetch(api("/api/validate"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, ...payload }),
      });
      const res = await r.json();
      msgEl.className = `val-msg ${res.valid ? "ok" : "bad"}`;
      msgEl.textContent = (res.valid ? "✓ " : res.needs_org ? "→ " : "✕ ") + res.message;
      validated[kind] = !!res.valid;
      if (stateEl) {
        stateEl.className = `cred-state ${res.valid ? "ok" : res.needs_org ? "wait" : "bad"}`;
        stateEl.textContent = res.valid ? "✓ conectado" : res.needs_org ? "→ elige org" : "✕ revisar";
      }
      return res;
    } catch {
      msgEl.className = "val-msg bad"; msgEl.textContent = "✕ Error de conexión";
      if (stateEl) { stateEl.className = "cred-state bad"; stateEl.textContent = "✕ sin conexión"; }
      validated[kind] = false;
      return null;
    }
  }

  function fillGitHubOrgs(namespaces, selected) {
    const sel = $("#f-git-org");
    const prev = selected || sel.value;
    sel.innerHTML = '<option value="">— elige org o cuenta personal —</option>';
    for (const ns of namespaces || []) {
      const opt = document.createElement("option");
      opt.value = ns.login;
      opt.textContent = ns.label || ns.login;
      sel.appendChild(opt);
    }
    if (prev) sel.value = prev;
    $("#gh-org-row").classList.remove("hidden");
  }

  function renderGitHubRepos(coreRepos, missing) {
    const ul = $("#gh-repos-list");
    if (!coreRepos || !coreRepos.length) {
      ul.classList.add("hidden");
      ul.innerHTML = "";
      return;
    }
    ul.classList.remove("hidden");
    ul.innerHTML = coreRepos.map((r) =>
      `<li class="${r.status === "ok" ? "ok" : "miss"}">${r.status === "ok" ? "✓" : "○"} ${r.name}</li>`
    ).join("");
    if (missing && missing.length) {
      ul.insertAdjacentHTML("beforeend",
        `<li class="hint">Al instalar → se crean: ${missing.join(", ")}</li>`);
    }
  }

  function resetGitHubValidation() {
    validated.github = false;
    githubBootstrap = false;
    githubLogin = "";
    $("#gh-org-row").classList.add("hidden");
    $("#gh-url-row").classList.add("hidden");
    $("#f-git-url").value = "";
    $("#gh-url-preview").textContent = "";
    $("#f-git-org").innerHTML = '<option value="">— elige org o cuenta personal —</option>';
    $("#st-gh").className = "cred-state";
    $("#st-gh").textContent = "";
    $("#gh-repos-list").classList.add("hidden");
    $("#gh-repos-list").innerHTML = "";
  }

  async function validateGitHub() {
    const token = $("#f-git-token").value.trim();
    if (!token) {
      $("#msg-gh").className = "val-msg bad";
      $("#msg-gh").textContent = "✕ Pega tu token primero";
      return;
    }
    const org = $("#f-git-org").value;
    const res = await validate(
      "github",
      { token, org: org || undefined },
      $("#msg-gh"),
      $("#st-gh"),
    );
    if (!res) return;
    if (res.namespaces) fillGitHubOrgs(res.namespaces, res.org || org);
    if (res.login) githubLogin = res.login;
    githubBootstrap = !!res.bootstrap_needed;
    if (res.core_repos) renderGitHubRepos(res.core_repos, res.missing_repos);
    if (res.gitops_url) {
      $("#f-git-url").value = res.gitops_url;
      $("#gh-url-preview").textContent = res.gitops_url;
      $("#gh-url-row").classList.remove("hidden");
    }
    if (res.valid && res.bootstrap_needed) {
      $("#st-gh").textContent = "✓ bootstrap";
    }
  }

  $("#f-git-token").addEventListener("input", resetGitHubValidation);
  $("#f-git-org").addEventListener("change", () => {
    if ($("#f-git-org").value) validateGitHub();
    else {
      validated.github = false;
      $("#gh-url-row").classList.add("hidden");
      $("#f-git-url").value = "";
      $("#gh-url-preview").textContent = "";
      $("#st-gh").className = "cred-state wait";
      $("#st-gh").textContent = "→ elige org";
      $("#msg-gh").className = "val-msg wait";
      $("#msg-gh").textContent = "→ Elige la org o cuenta donde vive infra-gitops";
    }
  });
  $("#btn-val-cf").addEventListener("click", () =>
    validate("cloudflare", { token: $("#f-cf-token").value, account_id: $("#f-cf-account").value }, $("#msg-cf")));
  $("#btn-val-gh").addEventListener("click", validateGitHub);
  $("#btn-val-dk").addEventListener("click", () =>
    validate("docker", { username: $("#f-dk-user").value, token: $("#f-dk-token").value }, $("#msg-dk"), $("#st-dk")));
  $("#btn-val-ts").addEventListener("click", () =>
    validate("tailscale", { client_id: $("#f-ts-id").value, client_secret: $("#f-ts-secret").value,
      dns_suffix: $("#f-ts-dns").value }, $("#msg-ts"), $("#st-ts")));

  /* despliegue: SSE + pasos + terminal */
  const term = $("#term");
  function termLine(line, level) {
    const div = document.createElement("div");
    div.className = `l-${level || "info"}`;
    div.textContent = line;
    term.appendChild(div);
    term.scrollTop = term.scrollHeight;
  }
  function applyStep(step, status, detail) {
    const li = $(`.steps li[data-step="${step}"]`);
    if (!li) return;
    li.className = status;
    if (detail) li.querySelector("small").textContent = detail;
  }
  function connectStream() {
    const es = new EventSource(api("/api/stream"));
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.kind === "log") termLine(ev.line, ev.level);
      if (ev.kind === "step") applyStep(ev.step, ev.status, ev.detail);
      if (ev.kind === "phase") {
        setPhaseChip(ev.phase === "installing" ? "desplegando…" : ev.phase === "done" ? "operativa" : ev.phase);
        if (ev.phase === "error") {
          bot.setState("error");
          bot.speak("Algo detuvo el cultivo… revisa la bitácora, corrige y reintenta. No se pierde el progreso.");
          $("#deploy-title").textContent = "Algo detuvo el cultivo — revisa la bitácora";
        }
      }
      if (ev.kind === "handoff") finish(ev);
    };
    return es;
  }
  function finish(h) {
    $("#done-node").textContent = h.node || "kaanbal";
    $("#h-url").textContent = h.argocd_url; $("#h-url").href = h.argocd_url;
    $("#btn-open-argo").href = h.argocd_url;
    $("#h-pass").textContent = h.argocd_password;
    $("#h-kube").textContent = h.kubeconfig;
    $("#f-final-user").value = h.admin_user || $("#f-admin-user").value || "admin";
    if (h.dns && h.dns.length) {
      $("#h-dns-row").style.display = "";
      $("#h-dns").textContent = h.dns.join("  ·  ");
    }
    if (h.api_url) {
      $("#h-api-row").style.display = "";
      $("#h-api").textContent = h.api_url; $("#h-api").href = h.api_url;
    }
    if (h.agent_url) {
      $("#h-agent-row").style.display = "";
      $("#h-agent").textContent = h.agent_url; $("#h-agent").href = h.agent_url;
    }

    const openBtn = $("#btn-open-argo");
    if (h.console_url) {
      $("#h-domain-row").style.display = "";
      $("#h-console").textContent = h.console_url; $("#h-console").href = h.console_url;
      // El botón principal solo lleva a la consola cuando de verdad responde:
      // ofrecer un enlace muerto es peor que mandar al panel de ArgoCD.
      const tag = $("#h-console-tag");
      if (h.console_exposure === "tailnet") {
        tag.textContent = "SOLO VPN TAILSCALE";
        openBtn.href = h.console_url;
        openBtn.textContent = "Abrir consola (por VPN) ⚡";
        bot.speak("Abre la consola desde un equipo conectado a tu VPN y confirma el acceso antes de cerrar.");
      } else if (h.console_reachable) {
        tag.textContent = "EN VIVO · HTTPS";
        openBtn.href = h.console_url;
        openBtn.textContent = "Abrir Kaanbal Console ⚡";
        bot.speak(`¡Kaanbal está EN VIVO en ${h.domain}! 🌐 Entra y despliega tu primera app.`);
      } else {
        tag.textContent = "PROPAGANDO DNS…";
        openBtn.href = h.argocd_url;
        bot.speak("Todo desplegado 🎉 — el DNS de Cloudflare tarda un par de minutos en propagar.");
      }
    } else if (h.domain) {
      bot.speak("Célula viva 🎉 — el engine no quedó publicado; revisa Repos e Imágenes en la bitácora.");
    } else {
      bot.speak("¡Tu célula está viva! 🎉 Para salir a internet, configura tu dominio en Conectividad.");
    }
    bot.setState("celebrate");
    setPhaseChip("operativa");
    setTimeout(() => show("done"), 900);
  }
  $("#btn-copy-pass").addEventListener("click", () => {
    navigator.clipboard.writeText($("#h-pass").textContent);
    $("#btn-copy-pass").textContent = "✓ copiado";
    setTimeout(() => ($("#btn-copy-pass").textContent = "copiar"), 1600);
  });
  $("#btn-finalize").addEventListener("click", async () => {
    const msg = $("#msg-finalize");
    msg.className = "val-msg wait";
    msg.textContent = "Confirmando acceso…";
    try {
      const r = await fetch(api("/api/finalize"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: $("#f-final-user").value,
          password: $("#f-final-pass").value,
          vpn_access_confirmed: $("#f-access-confirmed").checked,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "No se pudo cerrar");
      msg.className = "val-msg ok";
      msg.textContent = "✓ Token revocado. El instalador se apagará; Kaanbal sigue operativo.";
      $("#btn-finalize").disabled = true;
    } catch (e) {
      msg.className = "val-msg bad";
      msg.textContent = `✕ ${e.message}`;
    }
  });

  /* navegación */
  $("#btn-start").addEventListener("click", () => { show("ia"); pollRuntime(); });
  $("#btn-back-welcome").addEventListener("click", () => show("welcome"));
  $("#btn-ia-next").addEventListener("click", () => { show("mode"); bot.setState("listen"); });
  $("#btn-ia-skip").addEventListener("click", () => { show("mode"); });
  $("#btn-back-ia").addEventListener("click", () => show("ia"));
  $("#btn-deploy").addEventListener("click", async () => {
    const adminPass = $("#f-admin-pass").value;
    if (!restoredSecrets.has("admin_pass") && adminPass.length < 12) {
      $("#st-admin").className = "cred-state bad";
      $("#st-admin").textContent = "✕ mínimo 12";
      $("#f-admin-pass").focus();
      return;
    }
    const cfg = {
      mode,
      domain: $("#f-domain").value,
      cf_token: $("#f-cf-token").value,
      cf_account: $("#f-cf-account").value,
      tunnel_token: $("#f-tunnel").value,
      gitops_url: $("#f-git-url").value,
      gitops_token: $("#f-git-token").value,
      github_org: $("#f-git-org").value,
      github_login: githubLogin,
      github_bootstrap: githubBootstrap,
      docker_user: $("#f-dk-user").value,
      docker_token: $("#f-dk-token").value,
      tailscale_id: $("#f-ts-id").value,
      tailscale_secret: $("#f-ts-secret").value,
      tailscale_dns: $("#f-ts-dns").value,
      console_exposure: $("#f-exp-tailnet").checked ? "tailnet" : "public",
      admin_user: $("#f-admin-user").value,
      admin_pass: adminPass,
      ai_providers: aiProviders,
    };
    const button = $("#btn-deploy");
    button.disabled = true;
    button.textContent = "Validando credenciales…";
    const status = $("#install-validation-error");
    status.textContent = "";
    try {
      const r = await fetch(api("/api/install"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg),
      });
      const result = await r.json();
      if (!r.ok && r.status !== 409) {
        throw new Error((result.errors || [result.error || "No se pudo iniciar"]).join(" · "));
      }
      show("deploy");
      bot.setState("think");
      setPhaseChip("desplegando…");
      connectStream();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      button.disabled = false;
      button.textContent = "Instalar Kaanbal";
    }
  });

  /* arranque: Acuaponsito duerme hasta que el agente IA exista */
  (async function boot() {
    pollRuntime();
    await loadCredentialStatus();
    await systemCheck();
    try {
      const st = await (await fetch(api("/api/state"))).json();
      if (st.phase === "installing") {
        show("deploy"); bot.setState("think"); setPhaseChip("desplegando…");
        for (const [sid, s] of Object.entries(st.steps)) applyStep(sid, s.status, s.detail);
        connectStream();
      } else if (st.phase === "done" && st.handoff.argocd_url) {
        for (const [sid, s] of Object.entries(st.steps)) applyStep(sid, s.status, s.detail);
        finish(st.handoff); show("done");
      }
    } catch {}
  })();
})();
